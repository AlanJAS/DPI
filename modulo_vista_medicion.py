"""Componentes de medición de DPI."""

import math
from modulo_calculo_medicion import anchos_puntos, anios_por_punto, dist_punto_segmento
import numpy as np
from modulo_modelo_medicion import ModeloMedicion, PuntoMedicion, HistorialMedicion, TipoMarca
from PyQt6.QtWidgets import QWidget, QDialog, QGraphicsView, QGraphicsScene, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QDoubleSpinBox, QComboBox, QToolTip, QGraphicsEllipseItem, QDialogButtonBox
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from modulo_pith import ajustar_circulo_minimos_cuadrados
from constantes import MM_POR_PULGADA, PIXELES_POR_MM_DEFECTO, MAX_PASOS_HISTORIAL, TOLERANCIA_CLICK_PUNTO, TOLERANCIA_CLICK_SEGMENTO, INTERVALO_MARCADOR_DECADA, INTERVALO_MARCADOR_CINCUENTENA, INTERVALO_MARCADOR_CENTENA, COLOR_PUNTO_ACTIVO, COLOR_LINEA_ACTIVA, COLOR_SALTO, COLOR_GUIA, COLOR_CALIBRACION, COLOR_PUNTO_INACTIVO, COLOR_EWLW, TIPOS_ANOMALIA
from modulo_marcas_medicion import _es_amarillo, _es_espacio, _es_ewlw, _es_quiebre_ini, _es_salto_real
from modulo_marcas_medicion import ModoMedicion


class VistaSplitView(QGraphicsView):
    """Vista de solo lectura con zoom/pan independiente."""

    def __init__(self, escena: QGraphicsScene, parent=None):
        super().__init__(escena, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        # Permitir mover la imagen arrastrando con el mouse (mano).
        # Sin esto la ventana auxiliar solo soportaba zoom (wheel) pero no
        # paneo, lo que hacía la herramienta poco útil.
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Estilo de scrollbars (igual que la vista principal)
        self.setStyleSheet(
            "QScrollBar:horizontal{background:#3b3b3b; height:10px;}"
            "QScrollBar::handle:horizontal{background:#5a5a5a;"
            " border-radius:4px; min-width:20px;}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{"
            " width:0px; background:none;}"
            "QScrollBar:vertical{background:#3b3b3b; width:10px;}"
            "QScrollBar::handle:vertical{background:#5a5a5a;"
            " border-radius:4px; min-height:20px;}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{"
            " height:0px; background:none;}"
            "QGraphicsView{border:2px solid #FF8C00; border-radius:2px;}"
        )
        # Cache de viewport: evita repintar la imagen completa en cada
        # movimiento o cambio menor — mejora notablemente la fluidez de pan
        # y zoom con imágenes grandes.
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        event.accept()



class PanelSplit(QWidget):
    """Panel de vista dividida con selector de imagen y vista de solo lectura.

    Permite ver la misma imagen en otra posición/zoom, o bien una imagen
    diferente de otra pestaña abierta.
    """

    def __init__(self, escena_propia: QGraphicsScene, pestana: "PestanaImagen"):
        super().__init__()
        self._pestana = pestana
        self._escena_propia = escena_propia

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Barra de selección ──
        barra = QHBoxLayout()
        barra.setContentsMargins(4, 2, 4, 2)

        lbl = QLabel("◫")
        lbl.setStyleSheet("color:#FF8C00; font-size:14px; font-weight:bold; background:transparent;")
        barra.addWidget(lbl)

        self.combo_fuente = QComboBox()
        self.combo_fuente.setToolTip("Selecciona qué imagen mostrar en este panel")
        self.combo_fuente.setMinimumWidth(140)
        self.combo_fuente.setStyleSheet(
            "QComboBox{background:#3b3b3b; color:white; border:1px solid #FF8C00; "
            "border-radius:3px; padding:2px 6px;}"
            "QComboBox QAbstractItemView{background:#3b3b3b; color:white; "
            "selection-background-color:#FF8C00;}"
        )
        self.combo_fuente.currentIndexChanged.connect(self._cambiar_fuente)
        barra.addWidget(self.combo_fuente, 1)

        # Botón sincronizar zoom/posición con la vista principal
        btn_sync = QPushButton("⟲")
        btn_sync.setFixedSize(26, 26)
        btn_sync.setToolTip("Sincronizar zoom y posición con la vista principal")
        btn_sync.setStyleSheet(
            "QPushButton{background:#555; color:white; border-radius:3px; font-size:14px;}"
            "QPushButton:hover{background:#FF8C00;}")
        btn_sync.clicked.connect(self._sincronizar_con_principal)
        barra.addWidget(btn_sync)

        layout.addLayout(barra)

        # ── Vista ──
        # El estilo (borde naranja + scrollbars) ya está aplicado por
        # VistaSplitView en su __init__, no hace falta aplicarlo aquí.
        self.vista = VistaSplitView(escena_propia, self)
        layout.addWidget(self.vista)

    def refrescar_combo(self):
        """Actualiza la lista de imágenes disponibles."""
        self.combo_fuente.blockSignals(True)
        seleccion_actual = self.combo_fuente.currentData()
        self.combo_fuente.clear()

        # Opción 1: misma imagen
        self.combo_fuente.addItem("📷 Misma imagen", userData="__self__")

        # Opciones 2+: otras pestañas abiertas
        try:
            ventana = self._pestana._ventana_padre
            tabs = getattr(ventana, '_tabs_imagenes', None)
            if tabs is not None:
                for i in range(tabs.count()):
                    widget = tabs.widget(i)
                    if widget is not self._pestana and widget is not None:
                        nombre = tabs.tabText(i)
                        self.combo_fuente.addItem(f"📷 {nombre}", userData=id(widget))
        except Exception:
            pass

        # Restaurar selección
        if seleccion_actual is not None:
            for i in range(self.combo_fuente.count()):
                if self.combo_fuente.itemData(i) == seleccion_actual:
                    self.combo_fuente.setCurrentIndex(i)
                    break

        self.combo_fuente.blockSignals(False)

    def _cambiar_fuente(self, idx):
        """Cambia la escena de la vista según la selección del combo."""
        data = self.combo_fuente.itemData(idx)
        if data == "__self__" or data is None:
            self.vista.setScene(self._escena_propia)
            return

        # Buscar la pestaña por id
        try:
            ventana = self._pestana._ventana_padre
            tabs = getattr(ventana, '_tabs_imagenes', None)
            if tabs is not None:
                for i in range(tabs.count()):
                    widget = tabs.widget(i)
                    if id(widget) == data:
                        self.vista.setScene(widget.escena)
                        # Ajustar zoom para ver toda la imagen
                        self.vista.fitInView(
                            widget.escena.sceneRect(),
                            Qt.AspectRatioMode.KeepAspectRatio)
                        return
        except Exception:
            pass

    def _sincronizar_con_principal(self):
        """Copia zoom y posición de la vista principal."""
        self.vista.setTransform(self._pestana.vista.transform())
        center = self._pestana.vista.mapToScene(
            self._pestana.vista.viewport().rect().center())
        self.vista.centerOn(center)



class DialogoCalibracionRegla(QDialog):
    """Diálogo para preguntar la distancia antes de trazar la regla."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrar Escala (Regla)")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Ingresa la distancia física que vas a trazar en la imagen:"))

        fila = QHBoxLayout()
        self.spin_val = QDoubleSpinBox()
        self.spin_val.setRange(0.01, 10000.0)
        self.spin_val.setValue(1.0)
        self.spin_val.setDecimals(2)
        self.spin_val.setSingleStep(0.1)
        fila.addWidget(self.spin_val)

        self.combo_unidad = QComboBox()
        self.combo_unidad.addItems(["cm", "mm"])
        fila.addWidget(self.combo_unidad)

        layout.addLayout(fila)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def obtener_mm(self) -> float:
        val = self.spin_val.value()
        if self.combo_unidad.currentText() == "cm":
            return val * 10.0  # Convertir a mm
        return val



class VistaInteractiva(QGraphicsView):
    """
    Vista de imagen con herramientas de marcado de anillos.

    Modos disponibles (constantes MODO_*):
      1 ANADIR    — clic para añadir punto de anillo
      2 CALIBRAR  — clic en dos puntos para calibrar escala
      3 MOVER     — arrastrar puntos o hacer pan de la imagen
      4 SALTO     — añade un salto (discontinuidad del camino)
      5 INSERTAR  — inserta un punto en un segmento existente
      6 BORRAR    — elimina un punto con clic
      7 AUTODETECT — marca médula y corteza para auto-detección
    """

    mediciones_actualizadas = pyqtSignal(list)
    progreso_modificado = pyqtSignal()

    def __init__(self, escena: QGraphicsScene, pestana_padre: "PestanaImagen"):
        super().__init__(escena, pestana_padre)
        self._pestana = pestana_padre

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)

        # Estilo de scrollbars — el global de estilos.py solo cubre la
        # vertical, dejando la horizontal con el default del sistema (blanco
        # en algunos temas de Linux). Acá la estilamos local para que se vea
        # consistente con el resto de la UI.
        self.setStyleSheet(
            "QScrollBar:horizontal{background:#3b3b3b; height:10px;}"
            "QScrollBar::handle:horizontal{background:#5a5a5a;"
            " border-radius:4px; min-width:20px;}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{"
            " width:0px; background:none;}"
            "QScrollBar:vertical{background:#3b3b3b; width:10px;}"
            "QScrollBar::handle:vertical{background:#5a5a5a;"
            " border-radius:4px; min-height:20px;}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{"
            " height:0px; background:none;}"
        )

        # Estado de medición
        self.modelo_medicion = pestana_padre.modelo_sesion.activo if hasattr(pestana_padre, "modelo_sesion") else ModeloMedicion()
        self.puntos_calibracion: list[tuple[float, float]] = []
        # Items visuales de calibración (puntos, línea, texto) — se limpian
        # al cancelar/aceptar/reiniciar la calibración.
        self._items_calibracion: list = []
        self._pixeles_por_mm: float = PIXELES_POR_MM_DEFECTO

        # Elementos gráficos activos
        self._items_puntos: list = []
        self._items_lineas: list = []
        self._items_textos: list = []
        self.items_caminos_inactivos: dict = {}

        # Estado de interacción
        self.modo_actual: ModoMedicion = ModoMedicion.MEDIR
        # Anomalías: {anio: tipo_str}
        self.anomalias: dict[int, str] = {}
        self._items_anomalias: list = []   # QGraphicsItems de marcas visuales
        self._punto_arrastrado_idx: int | None = None
        self._is_panning: bool = False
        self._last_pan_pos = None
        self._linea_guia = None
        self._item_hover_prev = None
        # Estado del modo Medir/Salto: punto de anclaje seleccionado
        self._idx_anclado: int | None = None   # índice del punto de partida
        self._item_anclado = None               # resaltado visual del ancla

        # Historial de deshacer
        self._historial = HistorialMedicion(self.modelo_medicion, MAX_PASOS_HISTORIAL)

        # Auto-detección: almacena los dos puntos (médula, corteza)
        self._puntos_autodetect: list[tuple[float, float]] = []
        self._items_autodetect: list = []   # marcadores visuales temporales
        # Imagen OpenCV cacheada para no releerla en cada detección
        self._imagen_bgr: np.ndarray | None = None

        # Estimación de médula: puntos del arco marcados por el usuario
        self._puntos_pith: list[tuple[float, float]] = []
        self._items_pith: list = []   # marcadores visuales temporales
        self._item_circulo_pith = None  # círculo ajustado visualizado
        self._items_pith_extras: list = []  # línea, centro, texto de preview
        self._item_pith_mouse_preview = None  # arco preview siguiendo el mouse

        # Espacio intra-anillo: selección de dos puntos existentes
        self._puntos_espacio: list[tuple[float, float]] = []
        self._items_espacio: list = []
        self._idx_espacio_inicio: int | None = None  # flag: None = esperando clic 1
        self._espacio_p1: tuple[float,float] = (0.0, 0.0)
        self._espacio_seg1: int = 0

        # Pens y brushes — cosméticos (grosor en px pantalla, invariante al zoom)
        self._pen_punto       = QPen()
        self._brush_punto     = QBrush(QColor(COLOR_PUNTO_ACTIVO))
        self._pen_linea       = QPen()
        self._pen_salto       = QPen()
        self._pen_guia        = QPen(QColor(COLOR_GUIA))
        self._pen_guia.setStyle(Qt.PenStyle.DashLine)
        self._pen_guia.setCosmetic(True)
        self._pen_guia.setWidthF(1.0)
        self._pen_calibracion = QPen()
        self._pen_ewlw        = QPen()
        self._actualizar_pens()   # inicializa colores y grosores

        # HUD overlay para mostrar resultado de "anillos al centro".
        # Es un QLabel hijo del VIEWPORT (no de la escena), así NO se mueve
        # cuando el usuario hace pan/zoom. Solución al problema de que el
        # texto quedaba en el centro estimado de la médula que muchas veces
        # cae FUERA de la muestra visible (justo el caso típico — la médula
        # no está en la muestra, por eso la estamos estimando).
        from PyQt6.QtWidgets import QLabel
        self._hud_pith = QLabel(self.viewport())
        self._hud_pith.setStyleSheet(
            "QLabel { background-color: rgba(0,0,0,220); color: #FF8C00; "
            "padding: 6px 12px; border-radius: 4px; font-size: 13px; "
            "font-weight: bold; font-family: Arial; "
            "border: 1px solid rgba(255,140,0,150); }"
        )
        self._hud_pith.setVisible(False)
        self._hud_pith.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # ── Herramienta de selección múltiple ──
        # Permite al usuario seleccionar varios anillos a la vez (clic
        # alterna selección por punto) y aplicarles una acción común:
        # borrarlos todos, convertirlos a salto o convertirlos a quiebre.
        self._puntos_seleccionados: set[int] = set()
        self._items_seleccion: list = []  # marcadores visuales (círculos amarillos)

        # Cache de los datos de caminos inactivos. Necesario para poder
        # re-renderizar en cambios de zoom (los labels y ticks dependen
        # de la escala). Antes los labels viejos quedaban con el tamaño
        # de un zoom anterior y se veían enormes después de acercar.
        self._caminos_inactivos_data: dict = {}

        # Estado para selección por arrastre (rectángulo).
        # Cuando el usuario hace clic+drag en ModoMedicion.SELECCIONAR sobre un
        # área vacía, dibujamos un rectángulo de selección. Al soltar,
        # todos los anillos dentro del rectángulo se agregan a la selección.
        self._sel_drag_iniciado: bool = False
        self._sel_drag_start: tuple[float, float] = (0.0, 0.0)
        self._sel_drag_rect_item = None
        self._sel_click_idx_candidato: int | None = None  # punto sobre el que se hizo click
        self._sel_click_pos: tuple[float, float] = (0.0, 0.0)

        # Panel flotante (HUD) con los botones de acción. Se muestra solo
        # en ModoMedicion.SELECCIONAR. Lo construimos perezosamente la primera vez
        # que se entra al modo (para no impactar la inicialización).
        self._panel_seleccion: 'QFrame | None' = None
        self._lbl_seleccion_count: 'QLabel | None' = None
        self._btn_borrar_sel = None
        self._btn_salto_sel = None
        self._btn_quiebre_sel = None
        self._btn_limpiar_sel = None

        self.cambiar_modo(ModoMedicion.MEDIR)

    # -------------------------------------------------------------------------
    # Historial
    # -------------------------------------------------------------------------

    @property
    def coordenadas_anillos(self):
        return self.modelo_medicion.coordenadas

    @property
    def es_salto(self):
        return self.modelo_medicion.marcas

    def guardar_en_historial(self):
        self._historial.guardar()

    def limpiar_historial(self):
        self._historial.limpiar()

    def deshacer_ultimo(self):
        if self._historial.deshacer():
            self._actualizar_tras_historial()

    def rehacer_ultimo(self):
        if self._historial.rehacer():
            self._actualizar_tras_historial()

    def _actualizar_tras_historial(self):
        self._limpiar_anclado()
        if self._linea_guia:
            self.scene().removeItem(self._linea_guia)
            self._linea_guia = None
        self.recalcular_todas_las_distancias()
        self.progreso_modificado.emit()

    # -------------------------------------------------------------------------
    # Modos
    # -------------------------------------------------------------------------

    def cambiar_modo(self, nuevo_modo: ModoMedicion):
        modo_anterior = self.modo_actual  # capturar antes de asignar
        self.modo_actual = nuevo_modo
        # Limpiar ancla visual al salir del modo Medir/Salto
        if nuevo_modo not in (ModoMedicion.MEDIR, ModoMedicion.SALTO):
            self._limpiar_anclado()
        # Al entrar a ModoMedicion.ESPACIO limpiar la línea guía de Medir
        # pero NO borrar el ancla — así al volver a Medir se reanuda
        if nuevo_modo == ModoMedicion.ESPACIO:
            if self._linea_guia:
                self.scene().removeItem(self._linea_guia)
                self._linea_guia = None
        # Limpiar selección espacio al salir del modo
        if nuevo_modo != ModoMedicion.ESPACIO:
            self._idx_espacio_inicio = None
            self._limpiar_espacio()
        # Limpiar items visuales del modo PITH al salir de ese modo.
        # Bug previo: si el usuario activaba "Anillos al centro" y luego
        # cambiaba a otra herramienta (Mover, Borrar, etc.), los círculos
        # naranjas, líneas y texto del análisis quedaban dibujados en la
        # imagen indefinidamente. Solo se limpiaban con Enter (confirmar) o
        # Esc — pero cualquier otro modo de salida los dejaba huérfanos.
        # Usamos modo_anterior (capturado antes de asignar) porque
        # self.modo_actual ya fue actualizado a nuevo_modo arriba.
        if (modo_anterior == ModoMedicion.PITH and nuevo_modo != ModoMedicion.PITH
                and hasattr(self, "_limpiar_items_pith")):
            self._limpiar_items_pith()
        # NOTA: NO limpiamos items de calibración al cambiar de modo.
        # Las marcas persisten como recordatorio visual de que la imagen
        # fue calibrada. Solo se borran cuando el usuario inicia una nueva
        # calibración (iniciar_calibracion las limpia al inicio) o cancela
        # el diálogo de mm.
        # ── Manejo del panel de la herramienta de selección ──
        # Al entrar: mostrar panel + resetear estado de drag.
        # Al salir: limpiar selección, drag activo y panel.
        if nuevo_modo == ModoMedicion.SELECCIONAR:
            self._sel_drag_iniciado = False
            self._sel_click_idx_candidato = None
            self._mostrar_panel_seleccion(True)
        elif modo_anterior == ModoMedicion.SELECCIONAR:
            # Si quedó un rectángulo de drag en la escena, removerlo
            if self._sel_drag_rect_item is not None:
                try:
                    self.scene().removeItem(self._sel_drag_rect_item)
                except Exception:
                    pass
                self._sel_drag_rect_item = None
            self._sel_drag_iniciado = False
            self._sel_click_idx_candidato = None
            self._limpiar_seleccion_completa()
            self._mostrar_panel_seleccion(False)

        if nuevo_modo not in (ModoMedicion.MEDIR, ModoMedicion.SALTO) and self._linea_guia:
            self.scene().removeItem(self._linea_guia)
            self._linea_guia = None
        if nuevo_modo not in (ModoMedicion.MEDIR, ModoMedicion.SALTO) and self._linea_guia:
            self.scene().removeItem(self._linea_guia)
            self._linea_guia = None
        cursores = {
            ModoMedicion.MEDIR:       Qt.CursorShape.CrossCursor,
            ModoMedicion.CALIBRAR:    Qt.CursorShape.CrossCursor,
            ModoMedicion.SALTO:       Qt.CursorShape.CrossCursor,
            ModoMedicion.MOVER:       Qt.CursorShape.OpenHandCursor,
            ModoMedicion.INSERTAR:    Qt.CursorShape.ArrowCursor,
            ModoMedicion.BORRAR:      Qt.CursorShape.ArrowCursor,
            ModoMedicion.AUTODETECT:  Qt.CursorShape.CrossCursor,
            ModoMedicion.ANOMALIA:    Qt.CursorShape.PointingHandCursor,
            ModoMedicion.PITH:        Qt.CursorShape.CrossCursor,
            ModoMedicion.ESPACIO:     Qt.CursorShape.CrossCursor,
            ModoMedicion.EWLW:        Qt.CursorShape.CrossCursor,
            ModoMedicion.SELECCIONAR: Qt.CursorShape.PointingHandCursor,
        }
        self.setCursor(cursores.get(nuevo_modo, Qt.CursorShape.ArrowCursor))

    def _limpiar_items_calibracion(self):
        """Elimina puntos / línea / texto de una calibración previa."""
        for item in self._items_calibracion:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
        self._items_calibracion.clear()
        self.puntos_calibracion = []

    def iniciar_calibracion(self, objetivo_mm: float | None = None):
        """Inicia el modo de calibración por regla.

        Flujo:
          1. Si había marcas de calibración anteriores, se borran (nueva
             calibración reemplaza la anterior).
          2. Click 1 → marca punto inicial
          3. Click 2 → marca punto final + dibuja línea con distancia en px,
             luego pregunta los mm (QInputDialog)
          4. Si OK: aplica calibración. Las marcas SE MANTIENEN como
             recordatorio visual de que la imagen está calibrada (etiqueta
             cambia a "✓ Calibrada: X px = Y mm").
          5. Si Cancel: se borran las marcas (no hubo calibración).
        """
        # Limpiar marcas de calibración anteriores (puntos, línea, texto)
        # para evitar que se acumulen en la imagen tras múltiples usos.
        # Las marcas de la calibración previa se reemplazan por las nuevas.
        self._limpiar_items_calibracion()

        self.cambiar_modo(ModoMedicion.CALIBRAR)
        self._objetivo_calibracion_mm = objetivo_mm
        # Forzar foco en la vista para que el primer click se registre
        # directamente como mousePressEvent en la vista.
        self.setFocus()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    # -------------------------------------------------------------------------
    # ── Propiedad pixeles_por_mm ──────────────────────────────────────────

    @property
    def pixeles_por_mm(self) -> float:
        return self._pixeles_por_mm

    @pixeles_por_mm.setter
    def pixeles_por_mm(self, valor: float):
        self._pixeles_por_mm = valor
        self._actualizar_pens()

    def _actualizar_pens(self):
        """
        Recalcula el grosor de los pens en función de los DPI actuales.
        Los pens son COSMÉTICOS: su grosor se expresa en píxeles de pantalla,
        invariante al zoom, pero proporcional a la resolución de la imagen.

        Lógica:
          - A 2400 DPI (defecto, ~94 px/mm) queremos líneas de 2 px → grosor base.
          - A menor DPI (imagen más gruesa por px) escalamos proporcionalmente.
          - Mínimo 1.5 px, máximo 5 px para evitar extremos.
        """
        dpi = self._pixeles_por_mm * MM_POR_PULGADA
        # Grosor base calibrado para 2400 DPI
        factor = dpi / 2400.0
        grosor_linea  = max(1.5, min(5.0, 2.0 * factor))
        grosor_tick   = max(1.5, min(5.0, 2.0 * factor))
        grosor_calib  = max(2.0, min(6.0, 3.0 * factor))

        def _make(color, grosor, estilo=Qt.PenStyle.SolidLine) -> QPen:
            p = QPen(QColor(color))
            p.setCosmetic(True)
            p.setWidthF(grosor)
            p.setStyle(estilo)
            return p

        self._pen_punto       = _make(COLOR_PUNTO_ACTIVO, grosor_tick)
        self._brush_punto     = QBrush(QColor(COLOR_PUNTO_ACTIVO))
        self._pen_linea       = _make(COLOR_LINEA_ACTIVA, grosor_linea)
        self._pen_salto       = _make(COLOR_SALTO, grosor_linea, Qt.PenStyle.DashLine)
        self._pen_ewlw        = _make(COLOR_EWLW, grosor_tick)
        self._pen_calibracion = _make(COLOR_CALIBRACION, grosor_calib)

    # ── Utilidades de dibujo proporcionales al zoom ───────────────────────


    def _escala_vista(self) -> float:
        """
        Devuelve cuántas unidades de escena equivalen a 1 píxel de pantalla.
        Usado para que las líneas perpendiculares mantengan largo visual constante.
        """
        t = self.transform()
        # El factor de escala horizontal de la transformación afín
        escala_px_por_escena = t.m11()   # >1 = zoom in, <1 = zoom out
        return 1.0 / escala_px_por_escena if escala_px_por_escena != 0 else 1.0

    def _perp_tick(
        self,
        coords: list[tuple[float, float]],
        idx: int,
        largo_px_pantalla: float = 22.0,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """
        Calcula los dos extremos de la línea perpendicular al radio en el
        punto coords[idx].

        La dirección del radio se estima a partir de los vecinos:
          - Punto interior: promedio de los vectores anterior y posterior.
          - Extremo: vector hacia el único vecino.

        largo_px_pantalla: largo visual en píxeles de pantalla (independiente del zoom).
        """
        n = len(coords)
        x, y = coords[idx]

        # Vector tangente al radio
        if n == 1:
            tx, ty = 1.0, 0.0      # sin vecinos: horizontal por defecto
        elif idx == 0:
            nx, ny = coords[1]
            tx, ty = nx - x, ny - y
        elif idx == n - 1:
            px, py = coords[idx - 1]
            tx, ty = x - px, y - py
        else:
            px, py = coords[idx - 1]
            nx, ny = coords[idx + 1]
            tx, ty = nx - px, ny - py

        # Normalizar
        mag = math.hypot(tx, ty)
        if mag < 1e-9:
            tx, ty = 1.0, 0.0
        else:
            tx, ty = tx / mag, ty / mag

        # Perpendicular (rotar 90°)
        perp_x, perp_y = -ty, tx

        # Escalar al largo deseado en píxeles de pantalla
        mitad = largo_px_pantalla * 0.5 * self._escala_vista()
        return (
            (x + perp_x * mitad, y + perp_y * mitad),
            (x - perp_x * mitad, y - perp_y * mitad),
        )

    # -------------------------------------------------------------------------
    # Dibujo
    # -------------------------------------------------------------------------

    def _grosor_tick_zoom(self) -> float:
        """Calcula el ancho del tick perpendicular según el nivel de zoom.

        Principio: los límites de anillo se muestran SIEMPRE (no se filtran).
        Lo que se adapta con el zoom es su grosor: muy fino al alejar para
        evitar el "muro rojo" cuando hay miles de anillos juntos en pocos
        píxeles, normal al acercar para mejor visibilidad.

        El ancho del pen se interpreta en píxeles de PANTALLA porque los
        pens son cosmetic.
        """
        escala = self._escala_vista()
        if escala < 0.3:    # muy acercado
            return 3.0
        elif escala < 1.5:  # acercado
            return 2.5
        elif escala < 3.5:  # medio
            return 1.8
        elif escala < 7.0:  # alejado
            return 1.2
        else:               # muy alejado
            return 0.8

    def redibujar_todo(self):
        """Elimina todos los elementos gráficos y los reconstruye desde el estado."""
        for item in self._items_puntos + self._items_lineas + self._items_textos:
            self.scene().removeItem(item)
        self._items_puntos.clear()
        self._items_lineas.clear()
        self._items_textos.clear()

        # Ajustar grosor de los pens de tick según zoom actual.
        # Esto se hace ANTES del loop para que todos los ticks usen el
        # ancho correcto. Los pens son atributos persistentes; modificar
        # su ancho aquí afecta todo lo que se dibuje en esta pasada.
        grosor_actual = self._grosor_tick_zoom()
        self._pen_punto.setWidthF(grosor_actual)
        self._pen_salto.setWidthF(grosor_actual)
        self._pen_ewlw.setWidthF(grosor_actual)
        # Para el camino activo usamos los mismos pens (con el ancho ya ajustado).
        # Los nombres con sufijo "_zoom" son alias semánticos para claridad.
        self._pen_punto_zoom = self._pen_punto
        self._pen_salto_zoom = self._pen_salto
        self._pen_ewlw_zoom = self._pen_ewlw

        # Tracker para filtro de overlap: bbox del último label dibujado.
        # Se compara con cada nuevo candidato para evitar superposiciones.
        self._ultimo_bbox_label_activo = None

        try:
            anio_medula = self._pestana.spin_medula.value()
            anio_corteza = self._pestana.spin_corteza.value()
            medula_a_corteza = self._pestana.combo_dir.currentIndex() == 0
        except Exception:
            # La vista puede redibujar antes de que los widgets de la pestaña
            # estén completamente inicializados; usamos valores neutros como fallback.
            anio_medula, anio_corteza, medula_a_corteza = 0, 0, True

        anios, cierres = anios_por_punto(self.modelo_medicion.captura(),
            self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)
        for i, coord in enumerate(self.coordenadas_anillos):
            val = self.es_salto[i] if i > 0 else False
            es_amar = _es_amarillo(val)
            es_corte = _es_salto_real(val)
            anio = anios[i]

            # Línea de conexión: ew_lw usa azul (cuenta como distancia)
            if i > 0:
                pen = self._pen_linea if _es_ewlw(val) else (
                    self._pen_salto if es_amar else self._pen_linea)
                prev = self.coordenadas_anillos[i - 1]
                linea_conexion = self.scene().addLine(prev[0], prev[1], coord[0], coord[1], pen)
                # zValue=1 para que la línea quede DEBAJO de los ticks (zValue=2).
                # El usuario quiere los límites siempre prominentes.
                linea_conexion.setZValue(1)
                self._items_lineas.append(linea_conexion)

            # Tick perpendicular
            # Color: naranja si es ew_lw, amarillo si es espacio/salto o inicio quiebre,
            # rojo en cualquier otro caso (límite normal de anillo).
            # IMPORTANTE: TODOS los límites se muestran SIEMPRE. Lo que se
            # adapta con el zoom es el ANCHO del tick (más fino al alejar),
            # no su existencia. Esto evita el "muro rojo" al alejar pero
            # mantiene visible cada límite — fundamental para no perder
            # información en series largas.
            val_sale = self.es_salto[i + 1] if i + 1 < len(self.es_salto) else False
            if _es_ewlw(val):
                pen_tick = self._pen_ewlw_zoom
            elif es_amar or _es_espacio(val_sale):
                pen_tick = self._pen_salto_zoom
            else:
                pen_tick = self._pen_punto_zoom
            p1_t, p2_t = self._perp_tick(self.coordenadas_anillos, i)
            p = self.scene().addLine(p1_t[0], p1_t[1], p2_t[0], p2_t[1], pen_tick)
            # zValue=2 → ticks ON TOP de la línea de conexión (zValue=1).
            # Los límites son lo más importante y deben ser visibles aun
            # cuando se cruzan con la línea azul.
            p.setZValue(2)
            if _es_ewlw(val):
                etiqueta = "EW/LW"
            elif _es_espacio(val):
                etiqueta = "Espacio"
            elif _es_quiebre_ini(val):
                etiqueta = "Quiebre"
            elif es_corte:
                etiqueta = "Salto"
            else:
                etiqueta = str(anio)
            p.setToolTip(etiqueta)
            p.anio_texto = etiqueta
            self._items_puntos.append(p)

            # Etiquetas de año — densidad adaptativa según zoom.
            # _escala_vista() = 1/m11: PEQUEÑO = zoom acercado, GRANDE = alejado.
            # Acercado (escala < 0.3) → cada año individual
            # Medio    (0.3–1.5)      → cada 5 años
            # Alejado  (> 1.5)        → solo décadas
            # En todos los casos el font-size se ajusta para ser siempre legible.
            if i in cierres:
                escala = self._escala_vista()
                mostrar = self._filtro_densidad_anio(anio, escala)

                if mostrar:
                    # Colocar la etiqueta sobre el segmento AZUL que cierra
                    # el anillo actual: punto i-1 → punto i.
                    coord_inicio = self.coordenadas_anillos[i - 1]
                    coord_sig = coord

                    # Filtro de OVERLAP: si el label estimado se solapa con
                    # el último aceptado, lo saltamos. El usuario lo dijo
                    # claro: nunca dos números encima — preferible que
                    # desaparezcan intercaladamente a que se ilegibles.
                    bbox_nuevo = self._estimar_bbox_label_pantalla(
                        str(anio), coord_sig, coord_inicio)
                    if (self._ultimo_bbox_label_activo is None
                            or not self._labels_se_solapan(
                                self._ultimo_bbox_label_activo, bbox_nuevo)):
                        if anio % INTERVALO_MARCADOR_DECADA == 0:
                            self._items_textos.append(
                                self._crear_marcador_decada(anio, coord_inicio, coord_sig)
                            )
                        else:
                            self._items_textos.append(
                                self._crear_etiqueta_anio(str(anio), "#cccccc",
                                                           coord_inicio, coord_sig)
                            )
                        self._ultimo_bbox_label_activo = bbox_nuevo

        self._dibujar_anomalias()

    def _anio_en_indice(self, idx: int) -> int | None:
        """Devuelve el año calendario del punto en coordenadas_anillos[idx], o None."""
        try:
            anio_medula = self._pestana.spin_medula.value()
            anio_corteza = self._pestana.spin_corteza.value()
            medula_a_corteza = self._pestana.combo_dir.currentIndex() == 0
        except Exception:
            return None
        anios, _ = anios_por_punto(self.modelo_medicion.captura(),
            self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)
        return anios[idx] if 0 <= idx < len(anios) else None

    def _dibujar_anomalias(self):
        """Dibuja marcas de color sobre los ticks de anillos con anomalía registrada."""
        for item in self._items_anomalias:
            self.scene().removeItem(item)
        self._items_anomalias.clear()

        if not self.anomalias or not self.coordenadas_anillos:
            return

        # Construir mapa anio→indice
        anio_a_idx = {}
        try:
            anio_medula = self._pestana.spin_medula.value()
            anio_corteza = self._pestana.spin_corteza.value()
            medula_a_corteza = self._pestana.combo_dir.currentIndex() == 0
        except Exception:
            return

        anillos_validos = 0
        for i, coord in enumerate(self.coordenadas_anillos):
            val = self.es_salto[i] if i > 0 else False
            val_sale_a = self.es_salto[i + 1] if i + 1 < len(self.es_salto) else False
            if (i > 0
                    and not _es_amarillo(val)
                    and not _es_ewlw(val)
                    and not _es_espacio(val_sale_a)):
                anillos_validos += 1
            if medula_a_corteza:
                anio = (anio_medula + anillos_validos - 1) if i > 0 else (anio_medula - 1)
            else:
                anio = (anio_corteza - anillos_validos + 1) if i > 0 else anio_corteza
            anio_a_idx[anio] = i

        escala = self._escala_vista()
        for anio, tipo in self.anomalias.items():
            idx = anio_a_idx.get(anio)
            if idx is None:
                continue
            coord = self.coordenadas_anillos[idx]
            color = TIPOS_ANOMALIA.get(tipo, ("", "", "#CC0000"))[2]
            etiqueta_tipo = TIPOS_ANOMALIA.get(tipo, ("", tipo, ""))[1]

            # 1) Línea perpendicular LARGA y GRUESA, con borde oscuro detrás
            #    para que contraste sobre la madera a cualquier zoom. El largo
            #    es en píxeles de pantalla (constante con el zoom) y el ancho
            #    es cosmético (constante en pantalla).
            p1, p2 = self._perp_tick(self.coordenadas_anillos, idx,
                                     largo_px_pantalla=48.0)
            pen_borde = QPen(QColor("#000000"))
            pen_borde.setCosmetic(True); pen_borde.setWidthF(8.0)
            item_borde = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen_borde)
            item_borde.setZValue(9)
            item_borde.setToolTip(f"{anio}: {etiqueta_tipo}")
            self._items_anomalias.append(item_borde)

            pen = QPen(QColor(color))
            pen.setCosmetic(True); pen.setWidthF(4.0)
            item = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen)
            item.setZValue(11)
            item.setToolTip(f"{anio}: {etiqueta_tipo}")
            self._items_anomalias.append(item)

            # 2) Marcador circular relleno sobre el punto del anillo, con
            #    borde blanco para destacar. Radio constante en pantalla
            #    (≈9 px) usando la escala vista→pantalla.
            r = 9.0 * escala
            cx, cy = coord
            pen_circ = QPen(QColor("#ffffff"))
            pen_circ.setCosmetic(True); pen_circ.setWidthF(2.5)
            brush = QBrush(QColor(color))
            circ = self.scene().addEllipse(
                cx - r, cy - r, 2 * r, 2 * r, pen_circ, brush)
            circ.setZValue(12)
            circ.setToolTip(f"{anio}: {etiqueta_tipo}")
            self._items_anomalias.append(circ)

    def _crear_marcador_decada(
        self,
        anio: int,
        coord_actual: tuple,
        coord_anterior: tuple,
    ):
        if anio % INTERVALO_MARCADOR_CENTENA == 0:
            texto, color = f"••• {anio}", "#FFD700"
        elif anio % INTERVALO_MARCADOR_CINCUENTENA == 0:
            texto, color = f"•• {anio}", "#5cb85c"
        else:
            texto, color = f"• {anio}", "#ffffff"

        return self._crear_etiqueta_anio(texto, color, coord_actual, coord_anterior)

    def _filtro_densidad_anio(self, anio: int, escala: float) -> bool:
        """Decide si mostrar la etiqueta de un año según el nivel de zoom.

        5 niveles de zoom para evitar recargar la imagen cuando se aleja:
          - Muy acercado (escala < 0.3): cada año
          - Acercado    (0.3 ≤ escala < 1.5): cada 5
          - Medio       (1.5 ≤ escala < 3.5): cada 10
          - Alejado     (3.5 ≤ escala < 7.0): cada 50
          - Muy alejado (escala ≥ 7.0): cada 100

        Acéptese también años 0 y negativos (Schulman) usando módulo positivo.
        """
        a = abs(anio)
        if escala < 0.3:
            return True
        elif escala < 1.5:
            return a % 5 == 0
        elif escala < 3.5:
            return a % 10 == 0
        elif escala < 7.0:
            return a % 50 == 0
        else:
            return a % 100 == 0

    def _estimar_bbox_label_pantalla(
        self,
        texto: str,
        coord_actual: tuple,
        coord_anterior: tuple,
        offset_perpendicular_px: float = 8.0,
    ) -> tuple:
        """Estima la bounding box del label en píxeles de PANTALLA sin
        dibujarlo. Devuelve (cx, cy, ancho, alto) en píxeles relativos al
        origen de la escena dividido por la escala — sirve para chequeos
        de overlap entre labels consecutivos.

        Usa QFontMetrics para medir el ANCHO REAL del texto (antes el
        cálculo simple `chars * 8 + 6` era demasiado conservador para
        fuente Arial Bold y subestimaba los labels — sobre todo cuando el
        zoom era alto y el `fs_pantalla` efectivo superaba los 14 px,
        causando la superposición visible que reportó el usuario).
        """
        from PyQt6.QtGui import QFont, QFontMetrics

        escala = self._escala_vista()

        # Font-size en escena (igual cálculo que _crear_etiqueta_anio).
        # El piso de 8 evita texto microscópico, pero implica que cuando
        # hay mucho zoom-in (escala chica) el render en PANTALLA es más
        # grande que 14 px → labels más anchos de lo esperado.
        fs_escena = max(8, int(14 * escala))
        # Tamaño efectivo en pantalla del font:
        #   fs_escena = font-size en unidades de escena
        #   m11 = 1/escala → pantalla = escena * m11 = escena / escala
        fs_pantalla = fs_escena / escala if escala > 1e-9 else fs_escena

        # Medir el ancho real del texto con QFontMetrics
        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(max(8, int(round(fs_pantalla))))
        fm = QFontMetrics(font)
        ancho_texto_px = fm.horizontalAdvance(texto)
        alto_texto_px = fm.height()

        # Padding HTML (1px arriba/abajo, 3px izq/der) + documentMargin
        # del QGraphicsTextItem (default 4 px cada lado).
        ancho_px = ancho_texto_px + 6 + 8  # HTML pad horizontal + doc margin
        alto_px = alto_texto_px + 2 + 8     # HTML pad vertical + doc margin

        # Punto medio del segmento en escena
        mid_x = (coord_actual[0] + coord_anterior[0]) / 2
        mid_y = (coord_actual[1] + coord_anterior[1]) / 2

        # Offset perpendicular dinámico (misma fórmula que _crear_etiqueta_anio)
        if offset_perpendicular_px > 0:
            seg_dx = coord_actual[0] - coord_anterior[0]
            seg_dy = coord_actual[1] - coord_anterior[1]
            seg_norm = math.hypot(seg_dx, seg_dy)
            if seg_norm > 1e-6:
                perp_dx = seg_dy / seg_norm
                perp_dy = -seg_dx / seg_norm
                extension_perp_px = (
                    abs(perp_dx) * ancho_px / 2.0
                    + abs(perp_dy) * alto_px / 2.0
                )
                offset_total_px = extension_perp_px + offset_perpendicular_px
                offset_escena = offset_total_px * escala
                mid_x += perp_dx * offset_escena
                mid_y += perp_dy * offset_escena

        # Posición en pantalla (proxy: solo las DIFERENCIAS entre labels
        # son relevantes para el test de overlap)
        cx_pantalla = mid_x / escala if escala > 1e-9 else mid_x
        cy_pantalla = mid_y / escala if escala > 1e-9 else mid_y
        return (cx_pantalla, cy_pantalla, ancho_px, alto_px)

    def _labels_se_solapan(self, bbox_a: tuple, bbox_b: tuple,
                            margen_px: float = 2.0) -> bool:
        """True si dos bboxes (cx, cy, ancho, alto) en pantalla se tocan
        con menos de `margen_px` de espacio entre ellas. Test AABB.
        """
        cx_a, cy_a, w_a, h_a = bbox_a
        cx_b, cy_b, w_b, h_b = bbox_b
        dx = abs(cx_a - cx_b)
        dy = abs(cy_a - cy_b)
        sep_x_min = (w_a + w_b) / 2 + margen_px
        sep_y_min = (h_a + h_b) / 2 + margen_px
        return dx < sep_x_min and dy < sep_y_min

    def _crear_etiqueta_anio(
        self,
        texto: str,
        color: str,
        coord_actual: tuple,
        coord_anterior: tuple,
        offset_perpendicular_px: float = 8.0,
        bg_color: str = "rgba(0,0,0,0.60)",
    ):
        """
        Crea una etiqueta de texto cuyo tamaño en pantalla es siempre ~14 px,
        independientemente del nivel de zoom.

        OFFSET PERPENDICULAR DINÁMICO:
        El parámetro `offset_perpendicular_px` es solo el MARGEN extra
        respecto al borde más cercano del label. El offset real se calcula
        como: extensión_perpendicular_del_label + margen.

        Por qué:
          - Si el segmento es horizontal, la perpendicular es vertical;
            el label se desplaza hacia arriba y la dimensión relevante
            es su ALTURA → el offset = altura/2 + margen.
          - Si el segmento es vertical, la perpendicular es horizontal;
            el label se desplaza lateralmente y la dimensión relevante
            es su ANCHO → el offset = ancho/2 + margen. Esto es crítico
            porque sin ello los números ("1888", "1887"...) tapaban la
            línea azul vertical.
          - En diagonales, la extensión se compone de ambas dimensiones
            según el seno/coseno del ángulo del segmento.

        Geometría: para una caja UPRIGHT de tamaño W×H, su extensión en
        la dirección del vector perpendicular unitario (perp_dx, perp_dy)
        es:  |perp_dx| · W/2  +  |perp_dy| · H/2
        """
        # Tamaño objetivo en píxeles de pantalla
        PX_OBJETIVO = 14
        fs = max(8, int(PX_OBJETIVO * self._escala_vista()))

        item = self.scene().addText("")
        item.setHtml(
            f"<div style='background-color:{bg_color}; color:{color}; "
            f"padding:1px 3px; border-radius:3px; font-weight:bold; "
            f"font-family:Arial; font-size:{fs}px; white-space:nowrap;'>{texto}</div>"
        )
        rect = item.boundingRect()
        mid_x = (coord_actual[0] + coord_anterior[0]) / 2
        mid_y = (coord_actual[1] + coord_anterior[1]) / 2

        if offset_perpendicular_px > 0:
            seg_dx = coord_actual[0] - coord_anterior[0]
            seg_dy = coord_actual[1] - coord_anterior[1]
            seg_norm = math.hypot(seg_dx, seg_dy)
            if seg_norm > 1e-6:
                # Perpendicular CW al segmento (en Qt y crece hacia abajo,
                # CW pone la etiqueta "arriba" para segmentos horizontales
                # de izq a der)
                perp_dx = seg_dy / seg_norm
                perp_dy = -seg_dx / seg_norm

                # Tamaño del label en píxeles de PANTALLA.
                # El bounding rect está en escena; dividimos por escala
                # para convertir a píxeles de pantalla (porque el font
                # se calculó como 14 * escala).
                escala = self._escala_vista()
                rect_w_px = rect.width() / escala if escala > 0 else rect.width()
                rect_h_px = rect.height() / escala if escala > 0 else rect.height()

                # Extensión del label en la dirección perpendicular
                # al segmento (geometría AABB proyectada sobre un eje).
                extension_perp_px = (
                    abs(perp_dx) * rect_w_px / 2.0
                    + abs(perp_dy) * rect_h_px / 2.0
                )

                # Offset total = extensión necesaria + margen libre.
                # Así garantizamos que el borde del label queda a
                # `offset_perpendicular_px` de la línea, sin importar
                # la orientación del segmento.
                offset_total_px = extension_perp_px + offset_perpendicular_px
                offset_escena = offset_total_px * escala

                mid_x += perp_dx * offset_escena
                mid_y += perp_dy * offset_escena

        item.setPos(mid_x - rect.width() / 2, mid_y - rect.height() / 2)
        return item

    # -------------------------------------------------------------------------
    # Cálculos
    # -------------------------------------------------------------------------

    def recalcular_todas_las_distancias(self):
        """
        Calcula el ancho de cada anillo.

        Estructura de es_salto:
          False    → segmento normal (cuenta, cierra anillo)
          True     → salto (no cuenta, cierra anillo previo, inicia nuevo)
          "espacio"→ quiebre intra-anillo (no cuenta, no cierra)
          "ew_lw"  → límite EW/LW (cuenta, NO cierra — el anillo continúa)

        Un anillo se cierra cuando se encuentra un segmento con val=False
        (el límite del anillo) o al final del camino.
        Los segmentos ew_lw se acumulan junto con los False del mismo anillo.
        """
        distancias = anchos_puntos(self.modelo_medicion.captura(), self.pixeles_por_mm)
        self.mediciones_actualizadas.emit(distancias)

    _dist_punto_segmento = staticmethod(dist_punto_segmento)

    def _tolerancia_punto(self) -> float:
        return TOLERANCIA_CLICK_PUNTO / self.transform().m11()

    def _tolerancia_segmento(self) -> float:
        return TOLERANCIA_CLICK_SEGMENTO / self.transform().m11()

    def _indice_punto_mas_cercano(self, x: float, y: float) -> int | None:
        tol = self._tolerancia_punto()
        mejor_idx, mejor_d = None, float("inf")
        for i, (px, py) in enumerate(self.coordenadas_anillos):
            d = math.hypot(px - x, py - y)
            if d < tol and d < mejor_d:
                mejor_d, mejor_idx = d, i
        return mejor_idx

    # =========================================================================
    # Selección múltiple — métodos
    # =========================================================================

    def _construir_panel_seleccion(self):
        """Construye perezosamente el panel HUD para la herramienta de
        selección. Hijo del viewport (no de la escena), así NO se mueve
        cuando el usuario hace pan/zoom.

        El panel solo MUESTRA información (contador + hint). Las acciones
        se ejecutan con los botones que ya existen en la barra de
        herramientas (✕ Borrar, 🔀 Salto, ⊘ Quiebre): cuando se hace clic
        en cualquiera de esos botones estando en MODO_SELECCIONAR con
        selecciones activas, se aplica la acción en bulk a la selección
        en vez de cambiar de modo (ver `DPIInteractiva.set_modo`)."""
        from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

        self._panel_seleccion = QFrame(self.viewport())
        self._panel_seleccion.setStyleSheet(
            "QFrame { background-color: rgba(20,20,20,235); "
            "border: 1px solid rgba(255,235,59,180); border-radius: 6px; }"
        )

        lay = QHBoxLayout(self._panel_seleccion)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        # Contador + estado
        self._lbl_seleccion_count = QLabel("🎯 Clic / arrastrá un área para seleccionar")
        self._lbl_seleccion_count.setStyleSheet(
            "color: #FFEB3B; font-weight: bold; font-size: 12px;"
        )
        lay.addWidget(self._lbl_seleccion_count)

        # Separador visual
        sep = QLabel("│")
        sep.setStyleSheet("color: #555; font-size: 14px;")
        lay.addWidget(sep)

        # Hint: las acciones se ejecutan con los botones existentes
        self._lbl_seleccion_hint = QLabel(
            "Aplicar con la barra: <b style='color:#e74c3c;'>✕ Borrar</b>"
            "  ·  <b style='color:#f39c12;'>🔀 Salto</b>"
            "  ·  <b style='color:#9b59b6;'>⊘ Quiebre</b>"
        )
        self._lbl_seleccion_hint.setStyleSheet("color: #cccccc; font-size: 11px;")
        lay.addWidget(self._lbl_seleccion_hint)

        # Mantener referencias compatibles con el código existente, pero
        # ahora ninguna apunta a botones (que fueron eliminados del panel).
        self._btn_borrar_sel = None
        self._btn_salto_sel = None
        self._btn_quiebre_sel = None
        self._btn_limpiar_sel = None

        self._panel_seleccion.adjustSize()
        self._panel_seleccion.setVisible(False)

    def _posicionar_panel_seleccion(self):
        """Coloca el panel en la parte superior central del viewport.
        Llamar después de mostrar el panel o cuando cambia el tamaño del view."""
        if self._panel_seleccion is None:
            return
        self._panel_seleccion.adjustSize()
        vp_w = self.viewport().width()
        panel_w = self._panel_seleccion.width()
        x = max(8, (vp_w - panel_w) // 2)
        y = 8  # 8 px desde el borde superior del viewport
        self._panel_seleccion.move(x, y)

    def _mostrar_panel_seleccion(self, visible: bool):
        if self._panel_seleccion is None:
            self._construir_panel_seleccion()
        if visible:
            self._actualizar_panel_seleccion()
            self._posicionar_panel_seleccion()
            self._panel_seleccion.setVisible(True)
            self._panel_seleccion.raise_()
        else:
            self._panel_seleccion.setVisible(False)

    def _actualizar_panel_seleccion(self):
        """Actualiza solo el contador del panel. Los botones de acción ya
        no están en el panel: están en la barra principal."""
        if self._panel_seleccion is None:
            return
        n = len(self._puntos_seleccionados)
        if n == 0:
            self._lbl_seleccion_count.setText(
                "🎯 Clic / arrastrá un área para seleccionar")
        elif n == 1:
            self._lbl_seleccion_count.setText("🎯 1 seleccionado")
        else:
            self._lbl_seleccion_count.setText(f"🎯 {n} seleccionados")
        self._posicionar_panel_seleccion()

    def _dibujar_marcadores_seleccion(self):
        """Dibuja un círculo amarillo brillante alrededor de cada anillo
        seleccionado. Se redibuja completo cada vez para simplificar."""
        # Limpiar marcadores previos
        for item in self._items_seleccion:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
        self._items_seleccion.clear()

        if not self._puntos_seleccionados:
            return

        # Radio del círculo de selección en píxeles de PANTALLA constantes
        r_px = 11.0
        r = r_px * self._escala_vista()

        pen = QPen(QColor("#FFEB3B"))  # amarillo brillante
        pen.setCosmetic(True)
        pen.setWidthF(3.0)
        brush = QBrush(Qt.BrushStyle.NoBrush)

        for idx in self._puntos_seleccionados:
            if 0 <= idx < len(self.coordenadas_anillos):
                x, y = self.coordenadas_anillos[idx]
                e = self.scene().addEllipse(
                    x - r, y - r, 2 * r, 2 * r, pen, brush)
                e.setZValue(950)  # arriba de casi todo
                self._items_seleccion.append(e)

    def _toggle_seleccion_punto(self, idx: int):
        """Alterna la selección de un punto: si estaba seleccionado lo
        deselecciona, si no lo agrega a la selección."""
        if idx in self._puntos_seleccionados:
            self._puntos_seleccionados.discard(idx)
        else:
            self._puntos_seleccionados.add(idx)
        self._dibujar_marcadores_seleccion()
        self._actualizar_panel_seleccion()

    def _limpiar_seleccion_completa(self):
        """Vacía la selección y oculta sus marcadores."""
        self._puntos_seleccionados.clear()
        self._dibujar_marcadores_seleccion()
        self._actualizar_panel_seleccion()

    # ── Acciones sobre la selección ──

    def _ejecutar_borrar_seleccionados(self):
        """Borra todos los anillos seleccionados, en cualquier posición
        (inicio, medio, fin). Procesa los índices en orden DESCENDENTE
        para que los índices más altos no se invaliden al hacer pop()
        de los más bajos."""
        if not self._puntos_seleccionados:
            return
        self.guardar_en_historial()
        # Orden descendente: borrar de atrás hacia adelante para no
        # desplazar los índices que aún no procesamos
        indices = sorted(self._puntos_seleccionados, reverse=True)
        n_borrados = 0
        for i in indices:
            if 0 <= i < len(self.coordenadas_anillos):
                self.modelo_medicion.borrar(i)
                n_borrados += 1
        self._puntos_seleccionados.clear()
        self._dibujar_marcadores_seleccion()
        self.recalcular_todas_las_distancias()
        self._actualizar_panel_seleccion()
        self.progreso_modificado.emit()

    def _ejecutar_convertir_a_salto(self):
        """Marca los anillos seleccionados como SALTOS (es_salto = True).
        Esto convierte sus segmentos en discontinuidades (amarillas)."""
        if not self._puntos_seleccionados:
            return
        self.guardar_en_historial()
        for i in self._puntos_seleccionados:
            if 0 <= i < len(self.es_salto):
                self.modelo_medicion.marcar(i, TipoMarca.SALTO)
        self._puntos_seleccionados.clear()
        self._dibujar_marcadores_seleccion()
        self.recalcular_todas_las_distancias()
        self._actualizar_panel_seleccion()
        self.progreso_modificado.emit()

    def _ejecutar_convertir_a_quiebre(self):
        """Marca los anillos seleccionados como QUIEBRES (es_salto = "espacio").
        Convierte el segmento previo en un quiebre intra-anillo, que no
        cuenta como anillo en la cronología."""
        if not self._puntos_seleccionados:
            return
        self.guardar_en_historial()
        for i in self._puntos_seleccionados:
            if 0 <= i < len(self.es_salto):
                self.modelo_medicion.marcar(i, TipoMarca.ESPACIO)
        self._puntos_seleccionados.clear()
        self._dibujar_marcadores_seleccion()
        self.recalcular_todas_las_distancias()
        self._actualizar_panel_seleccion()
        self.progreso_modificado.emit()

    # =========================================================================
    # Eventos de ratón
    # =========================================================================

    def wheelEvent(self, event):
        """
        Zoom con rueda del mouse o touchpad.

        - Mouse wheel: cada "click" envía angleDelta=±120, factor 1.25 / 0.8
          como antes.
        - Touchpad: envía MUCHOS eventos con deltas pequeños (típicamente
          pixelDelta es no-null). Aplicamos un factor proporcional MUY
          pequeño por evento para que el zoom acumulado sea suave en vez
          de exagerado.

        Además debouncing del `redibujar_todo`: en gestos de touchpad llegan
        decenas de eventos por segundo, no tiene sentido redibujar todo
        en cada uno. Esperamos 80 ms de quietud antes de redibujar.
        """
        # Botón central presionado durante el scroll → ignorar zoom (es paneo)
        if event.buttons() & Qt.MouseButton.MiddleButton:
            return

        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()

        if not pixel_delta.isNull():
            # Touchpad de alta resolución: delta en píxeles
            delta_y = pixel_delta.y()
            if delta_y == 0:
                return
            # 200 px ≈ doble zoom. Suave pero responsive.
            factor = 1.0 + (delta_y / 200.0)
        elif not angle_delta.isNull():
            # Rueda de mouse: angleDelta en 1/8 de grado; 120 = un "click"
            delta_y = angle_delta.y()
            if delta_y == 0:
                return
            # Mantener comportamiento clásico: 1.25 por click, escalado
            # proporcionalmente a la magnitud del delta
            factor = 1.25 ** (delta_y / 120.0)
        else:
            return

        # Limitar el factor por evento para evitar saltos enormes
        factor = max(0.5, min(2.0, factor))

        self.scale(factor, factor)

        # Debounce: en vez de redibujar_todo() en cada evento de touchpad,
        # esperamos a que el usuario "termine" de hacer zoom (80 ms de
        # quietud) y entonces redibujamos una vez. Esto evita la "recarga"
        # constante que mencionaba el usuario.
        #
        # IMPORTANTE: el timer se dispara si hay camino activo O si hay
        # caminos inactivos. Antes solo se chequeaba coordenadas_anillos,
        # entonces al terminar un radio (que vacía la lista activa) los
        # caminos guardados se quedaban "congelados" al último zoom desde
        # el cual fueron renderizados.
        if self.coordenadas_anillos or self._caminos_inactivos_data:
            if not hasattr(self, '_zoom_debounce_timer'):
                from PyQt6.QtCore import QTimer
                self._zoom_debounce_timer = QTimer(self)
                self._zoom_debounce_timer.setSingleShot(True)
                self._zoom_debounce_timer.timeout.connect(self._redibujar_post_zoom)
            self._zoom_debounce_timer.start(80)

    def _redibujar_post_zoom(self):
        """Redibuja después del zoom (llamado por el debounce timer)."""
        if self.coordenadas_anillos:
            self.redibujar_todo()
        # Reescalar marcadores de selección si los hay (su radio se
        # calcula con _escala_vista() para mantener tamaño constante
        # en pantalla — al cambiar el zoom hay que regenerarlos).
        if self._puntos_seleccionados:
            self._dibujar_marcadores_seleccion()
        # Re-renderizar caminos inactivos para que labels y ticks usen
        # la escala nueva. Sin esto, los labels viejos quedan con el
        # tamaño de un zoom anterior (lo cual hace aparecer un "100"
        # enorme tras alejar/acercar).
        if self._caminos_inactivos_data:
            self.cargar_caminos_inactivos(self._caminos_inactivos_data)

    def event(self, ev):
        """Intercepta el evento `ShortcutOverride` para que las teclas
        Delete/Backspace en MODO_SELECCIONAR las maneje keyPressEvent (bulk
        borrar selección) en vez del QShortcut global (que cambiaría a
        MODO_BORRAR).

        Qt envía ShortcutOverride al widget con foco ANTES de disparar
        QShortcut. Si el widget acepta el evento, el shortcut se inhibe
        y la tecla llega a keyPressEvent. Si no lo acepta, el shortcut
        toma precedencia.
        """
        if ev.type() == QEvent.Type.ShortcutOverride:
            if self.modo_actual == ModoMedicion.SELECCIONAR:
                if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    ev.accept()
                    return True
        return super().event(ev)

    def mousePressEvent(self, event):
        pos = self.mapToScene(event.pos())
        x, y = pos.x(), pos.y()
        boton = event.button()
        if boton == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if boton == Qt.MouseButton.RightButton:
            self._salto_rapido(x, y)
            return
        if boton != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if self.modo_actual == ModoMedicion.MOVER:
            self._iniciar_mover(x, y, event)
            return
        acciones = {
            ModoMedicion.INSERTAR: self._insertar_en_segmento,
            ModoMedicion.BORRAR: self._borrar_punto_cercano,
            ModoMedicion.SELECCIONAR: self._iniciar_seleccion_mouse,
            ModoMedicion.CALIBRAR: self._paso_calibracion,
            ModoMedicion.MEDIR: self._paso_medir,
            ModoMedicion.SALTO: self._paso_medir,
            ModoMedicion.AUTODETECT: self._paso_autodetect,
            ModoMedicion.ANOMALIA: self._paso_anomalia,
            ModoMedicion.PITH: self._paso_pith,
            ModoMedicion.ESPACIO: self._paso_espacio,
            ModoMedicion.EWLW: self._paso_ewlw,
        }
        accion = acciones.get(self.modo_actual)
        if accion is None:
            return super().mousePressEvent(event)
        accion(x, y)

    def _salto_rapido(self, x, y):
        if self.modo_actual in (ModoMedicion.MEDIR, ModoMedicion.SALTO, ModoMedicion.INSERTAR,
                                ModoMedicion.BORRAR, ModoMedicion.ANOMALIA):
            modo_previo = self.modo_actual
            self.modo_actual = ModoMedicion.SALTO
            self._paso_medir(x, y)
            # _paso_medir ya restaura ModoMedicion.MEDIR tras un salto;
            # si el modo previo era especial (anomalía, etc.) lo respetamos
            if modo_previo not in (ModoMedicion.MEDIR, ModoMedicion.SALTO):
                self.modo_actual = modo_previo
                try:
                    self._pestana._botones_modo[modo_previo].setChecked(True)
                except Exception:
                    pass

    def _iniciar_seleccion_mouse(self, x, y):
        # En ModoMedicion.SELECCIONAR hay dos comportamientos según dónde se
        # haga clic:
        #   - Sobre un anillo (a tolerancia): se guarda como candidato
        #     a toggle, que se ejecutará al soltar (mouseRelease) si
        #     no hubo arrastre.
        #   - Sobre área vacía: se inicia un rectángulo de selección
        #     que se completará al soltar. Todos los anillos dentro
        #     del rectángulo se agregan a la selección.
        # Esto permite seleccionar varios anillos rápidamente
        # arrastrando un área (request del usuario).
        idx = self._indice_punto_mas_cercano(x, y)
        self._sel_click_pos = (x, y)
        if idx is not None:
            # Posible toggle de un punto — lo decidiremos en release
            self._sel_click_idx_candidato = idx
            self._sel_drag_iniciado = False
            self._sel_drag_start = (x, y)
        else:
            # Click en área vacía → iniciar drag rectangle
            self._sel_click_idx_candidato = None
            self._sel_drag_iniciado = True
            self._sel_drag_start = (x, y)
            # Si había un rectángulo previo (caso raro), removerlo
            if self._sel_drag_rect_item is not None:
                try:
                    self.scene().removeItem(self._sel_drag_rect_item)
                except Exception:
                    pass
                self._sel_drag_rect_item = None

    def _paso_anomalia(self, x: float, y: float):
        """
        Clic en MODO_ANOMALIA: asigna el tipo activo (seleccionado en la barra)
        al anillo más cercano. Si el anillo ya tiene ese mismo tipo, lo quita (toggle).
        """
        idx = self._indice_punto_mas_cercano(x, y)
        if idx is None or idx == 0:
            return
        anio = self._anio_en_indice(idx)
        if anio is None:
            return

        # Obtener tipo activo desde el combo de la pestaña
        try:
            tipo_activo = self._pestana.combo_tipo_anomalia.currentData()
        except Exception:
            return
        if not tipo_activo:
            return

        tipo_actual = self.anomalias.get(anio)
        if tipo_actual == tipo_activo:
            # Toggle: quitar si ya tiene el mismo tipo
            self.anomalias.pop(anio, None)
        else:
            # Asignar (sobreescribe si tenía otro tipo)
            self.anomalias[anio] = tipo_activo

        self._dibujar_anomalias()
        try:
            self._pestana._anomalias_modificadas()
        except Exception:
            pass

    def _paso_pith(self, x: float, y: float):
        """
        Modo interactivo de estimación de anillos al centro.
        Flujo guiado en 3 pasos:
          Clic 1: Extremo izquierdo del arco interno visible.
          Clic 2: Extremo derecho del arco → se dibuja guía entre ambos.
          Clic 3: Punto central del arco (la curvatura) → ajuste de círculo.
          Clics 4+: Puntos adicionales para refinar el ajuste.
        Enter confirma; Esc cancela.
        """
        pen_punto = QPen(QColor("#FF8C00"))
        pen_punto.setCosmetic(True)
        pen_punto.setWidthF(3.0)
        brush_punto = QBrush(QColor("#FF8C00"))

        self._puntos_pith.append((x, y))
        n = len(self._puntos_pith)

        # Marcador visual del punto
        r = 8 * self._escala_vista()
        marker = self.scene().addEllipse(x - r, y - r, 2*r, 2*r,
                                          pen_punto, brush_punto)
        self._items_pith.append(marker)

        # ── Paso 1: primer extremo ──
        if n == 1:
            try:
                self._pestana.label_estado.setText(
                    "🎯 Paso 2/3: Haz clic en el otro EXTREMO del arco.")
            except Exception:
                pass
            return

        # ── Paso 2: segundo extremo → dibujar guía ──
        if n == 2:
            p1, p2 = self._puntos_pith
            # Línea guía entre los dos extremos
            pen_guia = QPen(QColor("#FFD700"))
            pen_guia.setCosmetic(True)
            pen_guia.setWidthF(1.5)
            pen_guia.setStyle(Qt.PenStyle.DashDotLine)
            linea_guia = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen_guia)
            self._items_pith_extras.append(linea_guia)

            # Punto medio (referencia visual)
            mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
            r_mid = 5 * self._escala_vista()
            pen_mid = QPen(QColor("#FFD700"))
            pen_mid.setCosmetic(True)
            pen_mid.setWidthF(2.0)
            mid_marker = self.scene().addEllipse(
                mx-r_mid, my-r_mid, 2*r_mid, 2*r_mid,
                pen_mid, QBrush(Qt.BrushStyle.NoBrush))
            self._items_pith_extras.append(mid_marker)

            # NOTA: el círculo guía amarillo que mostraba un preview tras
            # el 2° clic fue removido a petición del usuario ("el círculo
            # no ayuda en nada"). Después del 2° clic solo se mantiene la
            # línea entre los dos puntos como referencia visual. El círculo
            # real (calculado por mínimos cuadrados a través de los 3 puntos)
            # se dibuja después del 3° clic en _actualizar_circulo_pith.

            try:
                self._pestana.label_estado.setText(
                    "🎯 Paso 3/3: Haz clic en un 3er punto sobre el MISMO "
                    "anillo visible (formando un arco claro con los otros 2).")
            except Exception:
                pass
            return

        # ── Paso 3+: ajustar círculo ──
        self._limpiar_preview_pith_mouse()  # limpiar preview del mouse
        self._actualizar_circulo_pith()
        try:
            self._pestana.label_estado.setText(
                f"🎯 Círculo ajustado con {n} puntos. "
                "Enter para confirmar · clic para agregar más puntos · Esc para cancelar.")
        except Exception:
            pass

    def _preview_pith_mouse(self, x: float, y: float):
        """Dibuja un arco preview cuando hay 2 puntos y el mouse se mueve.

        Estilo: línea más gruesa, color amarillo brillante, opacidad alta
        para que sea visible sobre la textura de la madera (la versión
        anterior usaba opacidad 0.5 + naranja, que se confundía con los
        anillos).
        """
        if len(self._puntos_pith) != 2:
            return
        # Limpiar preview anterior
        self._limpiar_preview_pith_mouse()

        puntos_temp = list(self._puntos_pith) + [(x, y)]
        resultado = ajustar_circulo_minimos_cuadrados(puntos_temp)
        if resultado is None:
            return

        cx, cy, radio = resultado
        # Evitar dibujar círculos absurdamente grandes (cuando el mouse
        # cae casi en línea con p1-p2, el radio tiende a infinito).
        # Tamaño máximo razonable: 10x la distancia entre p1 y p2.
        p1, p2 = self._puntos_pith
        d12 = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        if radio > d12 * 10:
            return

        pen_preview = QPen(QColor("#FFD700"))   # amarillo brillante
        pen_preview.setCosmetic(True)
        pen_preview.setWidthF(2.5)
        pen_preview.setStyle(Qt.PenStyle.DashLine)

        item = self.scene().addEllipse(
            cx - radio, cy - radio, 2*radio, 2*radio,
            pen_preview, QBrush(Qt.BrushStyle.NoBrush))
        item.setOpacity(0.85)
        # Z-value alto: garantiza visibilidad sobre la imagen
        item.setZValue(1000)
        self._item_pith_mouse_preview = item

    def _limpiar_preview_pith_mouse(self):
        """Elimina el arco preview del mouse."""
        item = getattr(self, '_item_pith_mouse_preview', None)
        if item is not None:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
            self._item_pith_mouse_preview = None

    def _actualizar_circulo_pith(self):
        """Redibuja el círculo ajustado con la estimación de anillos faltantes.

        Algoritmo (simple y correcto para arcos en CUALQUIER dirección):
          1. Ajustar círculo a los puntos marcados (Duncan GM clásico)
          2. El centro del círculo ajustado es la médula estimada
          3. Distancia faltante = `dist(p_inner, centro)` — distancia
             euclidiana desde el primer anillo medido (el más cercano a la
             médula) hasta el centro estimado
          4. Cantidad de anillos = distancia_mm / promedio_ancho_internos

        Importante (corrección del error anterior):
          - NO proyectar sobre eje radial — los anillos son perpendiculares
            al radio, así que un arco bien marcado sobre un anillo tiene
            puntos casi-perpendiculares al radio. Proyectar el centro
            (que está sobre el eje radial) sobre ese mismo eje desde p0
            funciona, PERO requiere que la dirección de medición esté
            "alineada" con la suposición del código. Como p_inner puede
            ser p0 o pK según combo_dir, y la dirección de medición puede
            ir en cualquier sentido, la proyección era inestable.
          - La distancia euclidiana funciona para arcos en cualquier
            dirección (horizontal, vertical, diagonal, etc).

        p_inner se determina por `combo_dir`:
          - med_a_cor=True (medición médula→corteza): p_inner = coords[0]
          - med_a_cor=False (medición corteza→médula): p_inner = coords[-1]
        """
        resultado = ajustar_circulo_minimos_cuadrados(self._puntos_pith)
        if resultado is None:
            try:
                self._pestana.label_estado.setText(
                    "⚠ Puntos colineales. Mueve uno para que el ajuste pueda calcular.")
            except Exception:
                pass
            return
        cx, cy, radio = resultado

        # Detectar fit realmente degenerado: solo cuando los puntos son
        # casi exactamente colineales (radio MUCHÍSIMO más grande que el
        # span de los puntos). Umbral relajado: 50× en lugar de 15×.
        # Un anillo grande puede tener radio 20× el chord medido y NO ser
        # degenerado.
        seg_max = 0.0
        for i in range(len(self._puntos_pith)):
            for j in range(i + 1, len(self._puntos_pith)):
                p_i = self._puntos_pith[i]
                p_j = self._puntos_pith[j]
                seg_max = max(seg_max, math.hypot(p_j[0]-p_i[0], p_j[1]-p_i[1]))
        fit_degenerado = (seg_max > 0 and radio > seg_max * 50)

        # Limpiar items previos del círculo
        if self._item_circulo_pith is not None:
            try:
                self.scene().removeItem(self._item_circulo_pith)
            except Exception:
                pass
        for item in self._items_pith_extras:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
        self._items_pith_extras.clear()

        color_fit = "#FF6B6B" if fit_degenerado else "#FF8C00"

        # ── Círculo ajustado punteado ──
        pen_circ = QPen(QColor(color_fit))
        pen_circ.setCosmetic(True)
        pen_circ.setWidthF(2.0)
        pen_circ.setStyle(Qt.PenStyle.DashLine)
        self._item_circulo_pith = self.scene().addEllipse(
            cx - radio, cy - radio, 2*radio, 2*radio,
            pen_circ, QBrush(Qt.BrushStyle.NoBrush)
        )
        self._item_circulo_pith.setZValue(900)

        # ── Cruz en el centro del fit (puede caer fuera de la imagen) ──
        r_centro = 10 * self._escala_vista()
        pen_centro = QPen(QColor(color_fit))
        pen_centro.setCosmetic(True)
        pen_centro.setWidthF(2.5)
        linea_h = self.scene().addLine(cx - r_centro, cy, cx + r_centro, cy, pen_centro)
        linea_v = self.scene().addLine(cx, cy - r_centro, cx, cy + r_centro, pen_centro)
        linea_h.setZValue(901)
        linea_v.setZValue(901)
        self._items_pith_extras.extend([linea_h, linea_v])

        # ── Cálculo de distancia faltante (fórmula de Duncan GM) ──
        coords = self.coordenadas_anillos
        if coords:
            # Determinar cuál extremo de la medición es el más cercano a la
            # médula (p_inner), según la dirección de medición elegida.
            try:
                med_a_cor = self._pestana.combo_dir.currentIndex() == 0
            except Exception:
                med_a_cor = True

            if med_a_cor:
                p_inner = coords[0]
            else:
                p_inner = coords[-1] if len(coords) >= 2 else coords[0]

            # ── MÉTRICA PRIMARIA: distancia faltante = dist(p_inner, centro)
            # La médula está en el centro del círculo ajustado (fit center).
            # La distancia faltante SIEMPRE se cuenta desde p_inner (el
            # primer anillo medido más cercano a la médula) hasta el centro.
            #
            # Esto es independiente de DÓNDE marque el usuario el arco. El
            # arco marcado es solo la herramienta para encontrar la médula
            # (vía fit por mínimos cuadrados, Duncan GM 1989). Si el usuario
            # marca el anillo más interno visible: dist ≈ radio del fit.
            # Si marca un anillo más exterior (porque el interno no se ve
            # claro): radio > dist, pero los anillos faltantes se siguen
            # contando desde p_inner.
            dist_p_inner_centro_mm = (
                math.hypot(cx - p_inner[0], cy - p_inner[1])
                / self.pixeles_por_mm)
            missing_mm = dist_p_inner_centro_mm

            # Radio del fit como información secundaria (diagnóstico)
            radio_fit_mm = radio / self.pixeles_por_mm

            # Línea desde p_inner hasta el centro del fit (visualización
            # de la DISTANCIA FALTANTE — la métrica primaria)
            pen_dist = QPen(QColor(color_fit))
            pen_dist.setCosmetic(True)
            pen_dist.setWidthF(2.5)
            pen_dist.setStyle(Qt.PenStyle.SolidLine)
            linea_dist = self.scene().addLine(
                p_inner[0], p_inner[1], cx, cy, pen_dist)
            linea_dist.setZValue(903)
            self._items_pith_extras.append(linea_dist)

            # Línea desde el centro hasta uno de los puntos marcados, punteada
            # (visualización del radio del fit como referencia secundaria)
            if self._puntos_pith:
                p_marca = self._puntos_pith[0]
                pen_radio = QPen(QColor(color_fit))
                pen_radio.setCosmetic(True)
                pen_radio.setWidthF(1.5)
                pen_radio.setStyle(Qt.PenStyle.DotLine)
                linea_radio = self.scene().addLine(
                    cx, cy, p_marca[0], p_marca[1], pen_radio)
                linea_radio.setZValue(902)
                self._items_pith_extras.append(linea_radio)

            # ── Estimación de anillos (RG / BAI / Promedio) ──
            # El usuario elige el método en el diálogo. RG es el default
            # (estándar usado por CooRecorder). BAI y Promedio están
            # disponibles para mayor precisión según Altman et al. (2016).
            #
            # Lógica común (anillos de referencia):
            #   1. Encontrar el anillo medido geométricamente más cercano
            #      al arco marcado (su distancia al centro del fit es la
            #      más parecida al radio del fit).
            #   2. Desde ese anillo "ancla", tomar exactamente N anillos
            #      contando HACIA LA CORTEZA (N = `_pith_n_int`).
            #   3. Los anchos de esos N anillos son la referencia.
            #
            # RG: n = distancia_faltante / promedio_ancho
            # BAI: n = (π × distancia²) / mean_BAI_referencia
            #      donde mean_BAI_ref se calcula con las distancias
            #      absolutas de los anillos al centro del fit (que ahora
            #      conocemos).
            # Promedio: (n_rg + n_bai) / 2
            n_est = None
            mean_w_mm = None
            n_used = 0
            n_rg = None
            n_bai = None
            try:
                pestana = self._pestana
                n_int_user = getattr(pestana, '_pith_n_int', 5)
                metodo_calc = getattr(pestana, '_pith_metodo_calculo', 'rg')
                dm = pestana.datos_medidos

                if dm and len(coords) >= 2:
                    # Paso 1: anillo medido más cercano al arco marcado
                    distancias_coord = [
                        math.hypot(coords[i][0] - cx, coords[i][1] - cy)
                        for i in range(len(coords))
                    ]
                    diferencias = [abs(d - radio) for d in distancias_coord]
                    idx_anchor = diferencias.index(min(diferencias))

                    # Paso 2: tomar N anillos hacia corteza
                    max_idx_dm = len(dm) - 1
                    if med_a_cor:
                        start = min(idx_anchor, max_idx_dm)
                        end = min(start + n_int_user, max_idx_dm + 1)
                        indices = list(range(start, end))
                    else:
                        start = max(0, min(idx_anchor, max_idx_dm))
                        end_back = max(-1, start - n_int_user)
                        indices = list(range(start, end_back, -1))

                    # Paso 3: anchos de referencia
                    anchos_ref = [
                        dm[i]["ancho_mm"] for i in indices
                        if 0 <= i <= max_idx_dm and dm[i]["ancho_mm"] > 0
                    ]

                    if anchos_ref:
                        mean_w_mm = sum(anchos_ref) / len(anchos_ref)
                        n_used = len(anchos_ref)

                        # ── Cálculo RG ──
                        if mean_w_mm > 0:
                            n_rg = missing_mm / mean_w_mm

                        # ── Cálculo BAI ──
                        # Para BAI necesitamos la distancia del anillo ancla
                        # al centro del fit (posición absoluta desde la médula).
                        # Ahora SÍ podemos calcularlo porque tenemos cx, cy.
                        # No tenemos el problema de dependencia circular que
                        # mencionaba antes.
                        r_anchor_mm = distancias_coord[idx_anchor] / self.pixeles_por_mm
                        sum_w_ref = sum(anchos_ref)
                        r_outer_ref_mm = r_anchor_mm + sum_w_ref
                        # Área basal total cubierta por los N anillos de
                        # referencia (en mm²)
                        ba_total_ref_mm2 = math.pi * (
                            r_outer_ref_mm**2 - r_anchor_mm**2)
                        mean_bai_mm2 = ba_total_ref_mm2 / len(anchos_ref)
                        # Área basal faltante = disco de radio missing_mm
                        # (desde el centro hasta p_inner)
                        ba_faltante_mm2 = math.pi * missing_mm**2
                        if mean_bai_mm2 > 0:
                            n_bai = ba_faltante_mm2 / mean_bai_mm2

                        # ── Selección final según método ──
                        if metodo_calc == "rg":
                            n_est = n_rg
                        elif metodo_calc == "bai":
                            n_est = n_bai
                        elif metodo_calc == "promedio":
                            if n_rg is not None and n_bai is not None:
                                n_est = (n_rg + n_bai) / 2.0
                            elif n_rg is not None:
                                n_est = n_rg
                            else:
                                n_est = n_bai
                        else:
                            n_est = n_rg  # fallback
            except Exception:
                pass

            # Etiqueta del método usado (para el HUD)
            etiqueta_metodo = {
                "rg": "RG",
                "bai": "BAI",
                "promedio": "Promedio RG+BAI"
            }.get(getattr(self._pestana, '_pith_metodo_calculo', 'rg'), 'RG')

            # Construir texto del HUD según calidad del resultado
            if fit_degenerado:
                hud_text = (
                    "⚠ Estimación no confiable. "
                    "Los puntos parecen estar casi en línea recta. "
                    "Marca puntos formando un arco más curvado."
                )
                hud_color = "#FF6B6B"
            elif n_est is None:
                hud_text = (
                    f"📏 Distancia p_inner → médula: {missing_mm:.1f} mm "
                    f"(necesitas anillos medidos para estimar cantidad)"
                )
                hud_color = "#FF8C00"
            elif n_est > 500:
                hud_text = (
                    f"⚠ {missing_mm:.0f} mm → ≈{round(n_est)} anillos. "
                    f"Parece demasiado, ¿marcaste sobre el borde externo?"
                )
                hud_color = "#FF6B6B"
            else:
                # Texto principal con el método elegido + comparación si
                # se calcularon los otros dos
                comparacion = ""
                if n_rg is not None and n_bai is not None:
                    comparacion = (
                        f"  ·  RG: {round(n_rg)}  ·  BAI: {round(n_bai)}"
                    )
                hud_text = (
                    f"🪵 Faltan ≈{round(n_est)} anillos [{etiqueta_metodo}]  ·  "
                    f"Distancia: {missing_mm:.1f} mm  "
                    f"(promedio anillo: {mean_w_mm:.2f} mm  ·  "
                    f"radio arco: {radio_fit_mm:.1f} mm{comparacion})"
                )
                hud_color = "#FF8C00"

            # Mostrar en HUD del viewport
            self._actualizar_hud_pith(hud_text, hud_color)

    def _confirmar_pith(self):
        """Llamado desde PestanaImagen cuando el usuario confirma (Enter/botón)."""
        resultado = ajustar_circulo_minimos_cuadrados(self._puntos_pith)
        self._limpiar_items_pith()
        if resultado is None:
            try:
                self._pestana.label_estado.setText(
                    "⚠ No se pudo ajustar el círculo. "
                    "Asegúrate de que los puntos no sean colineales.")
            except Exception:
                pass
            return resultado
        return resultado

    def _limpiar_items_pith(self):
        """Elimina todos los marcadores visuales del modo pith."""
        for item in self._items_pith:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
        self._items_pith.clear()
        self._puntos_pith.clear()
        if self._item_circulo_pith is not None:
            try:
                self.scene().removeItem(self._item_circulo_pith)
            except Exception:
                pass
            self._item_circulo_pith = None
        for item in self._items_pith_extras:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
        self._items_pith_extras.clear()
        self._limpiar_preview_pith_mouse()
        # Ocultar HUD del resultado
        if hasattr(self, "_hud_pith"):
            self._hud_pith.setVisible(False)

    def _actualizar_hud_pith(self, html_text: str, color: str = "#FF8C00"):
        """Actualiza el HUD del pith (texto fijo en la esquina del viewport,
        independiente del pan/zoom de la escena).

        El HUD se posiciona en la parte superior central del viewport para
        que siempre esté visible, sin importar dónde caiga la médula
        estimada (que muchas veces está FUERA de la muestra).
        """
        if not hasattr(self, "_hud_pith"):
            return
        # Reconstruir el stylesheet con el color de fit (naranja=bueno,
        # rojo=no confiable). Mantener el resto fijo.
        self._hud_pith.setStyleSheet(
            f"QLabel {{ background-color: rgba(0,0,0,220); color: {color}; "
            f"padding: 6px 12px; border-radius: 4px; font-size: 13px; "
            f"font-weight: bold; font-family: Arial; "
            f"border: 1px solid rgba(255,140,0,150); }}"
        )
        self._hud_pith.setText(html_text)
        self._hud_pith.adjustSize()
        # Posicionar arriba al centro del viewport
        vp = self.viewport()
        x = max(10, (vp.width() - self._hud_pith.width()) // 2)
        self._hud_pith.move(x, 12)
        self._hud_pith.setVisible(True)
        self._hud_pith.raise_()

    def resizeEvent(self, event):
        """Reposicionar el HUD del pith y el panel de selección cuando
        cambia el tamaño del widget."""
        super().resizeEvent(event)
        if hasattr(self, "_hud_pith") and self._hud_pith.isVisible():
            vp = self.viewport()
            x = max(10, (vp.width() - self._hud_pith.width()) // 2)
            self._hud_pith.move(x, 12)
        # Reposicionar también el panel de selección si está visible
        if (hasattr(self, "_panel_seleccion")
                and self._panel_seleccion is not None
                and self._panel_seleccion.isVisible()):
            self._posicionar_panel_seleccion()

    def mapa_anio_coordenada(self) -> dict[int, tuple[float, float]]:
        """Devuelve un dict {año: (x, y)} para cada límite de anillo válido."""
        mapa: dict[int, tuple[float, float]] = {}
        coords = self.coordenadas_anillos
        if not coords or len(coords) < 2:
            return mapa
        try:
            pestana = self._pestana
            anio_medula = pestana.spin_medula.value()
            anio_corteza = pestana.spin_corteza.value()
            med_a_cor = pestana.combo_dir.currentIndex() == 0
        except Exception:
            return mapa

        anios, cierres = anios_por_punto(self.modelo_medicion.captura(),
            self.pixeles_por_mm, anio_medula, anio_corteza, med_a_cor)
        return {anios[i]: coords[i] for i in sorted(cierres)}

    def _segmento_mas_cercano(self, x: float, y: float) -> tuple[int, float, float] | None:
        """
        Devuelve (idx_segmento, t, d_px) del segmento del camino más cercano al punto
        (x, y), donde idx_segmento es el índice del punto inicial del segmento,
        t es la proyección paramétrica [0,1] sobre ese segmento, y d_px es la
        distancia en px de escena.
        Devuelve None si no hay segmentos o el más cercano supera la tolerancia.
        """
        coords = self.coordenadas_anillos
        if len(coords) < 2:
            return None
        tol = self._tolerancia_segmento()
        mejor_d, mejor_idx, mejor_t = float("inf"), -1, 0.0
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            l2 = (x2-x1)**2 + (y2-y1)**2
            if l2 < 1e-9:
                continue
            t = max(0.0, min(1.0, ((x-x1)*(x2-x1) + (y-y1)*(y2-y1)) / l2))
            px, py = x1 + t*(x2-x1), y1 + t*(y2-y1)
            d = math.hypot(x-px, y-py)
            if d < mejor_d:
                mejor_d, mejor_idx, mejor_t = d, i, t
        if mejor_idx == -1 or mejor_d > tol:
            return None
        return mejor_idx, mejor_t, mejor_d

    def _paso_espacio(self, x: float, y: float):
        """
        Modo espacio intra-anillo. Dos submodos según dónde cae el clic:

        A) SOBRE LÍNEA EXISTENTE (hay segmento azul cercano):
           Clic 1 → inserta tick AMARILLO (inicio del espacio) en la línea.
           Clic 2 → inserta tick AMARILLO (fin del espacio) en la línea.
           Resultado: prev_tick ─(azul)─ /═══espacio═══/ ─(azul)─ next_tick
           Ambos / son ticks amarillos ("espacio"), el tramo entre ellos también.

        B) EN EL EXTREMO ACTIVO (clic lejos de cualquier segmento):
           Actúa como Medir pero los puntos se insertan como "espacio".
           Clic 1 → añade tick amarillo al final del camino (inicio espacio).
           Clic 2 → añade tick amarillo al final (fin espacio).
           Vuelve automáticamente a Medir.

        Los ticks amarillos NO cuentan como límites de anillo.
        El ancho del anillo = solo los tramos azules (False), no los espacios.
        Esc cancela. Ctrl+Z deshace.
        """
        coords = self.coordenadas_anillos

        # ── Detectar si el clic cae sobre un segmento existente ───────────
        hit = self._segmento_mas_cercano(x, y) if len(coords) >= 2 else None

        pen_v = QPen(QColor("#FFD700"))   # amarillo para marcadores visuales
        pen_v.setCosmetic(True); pen_v.setWidthF(3.0)
        brush_nulo = QBrush(Qt.BrushStyle.NoBrush)

        # ══════════════════════════════════════════════════════════════════
        # SUBMODO B: extremo activo — clic lejos de la línea existente
        #
        # Estructura correcta del quiebre al medir en el extremo activo:
        #
        #  tick_N(False) ──azul── A("quiebre_ini") ══"espacio"══ B("espacio") ──azul── tick_N+1(False)
        #
        # Clic 1 → punto A: es_salto="quiebre_ini" → línea AZUL desde tick anterior,
        #                    suma distancia al anillo pero NO cierra el anillo.
        #
        # Clic 2 → punto B: es_salto="espacio" → línea AMARILLA desde A,
        #                                          tick AMARILLO (no cuenta)
        #          Vuelve a Medir. El siguiente clic normal agrega el límite final
        #          del anillo con línea azul desde B.
        # ══════════════════════════════════════════════════════════════════
        if hit is None:
            if not coords:
                try:
                    self._pestana.label_estado.setText(
                        "↔ Mide al menos un punto antes de insertar un quiebre.")
                except Exception:
                    pass
                return

            # Primer clic: punto A — suma distancia pero NO cierra anillo
            if self._idx_espacio_inicio is None:
                self.guardar_en_historial()
                self.modelo_medicion.agregar((x, y), TipoMarca.QUIEBRE_INI)   # línea azul, suma, no cierra
                self._idx_espacio_inicio = len(coords) - 1
                self._espacio_p1   = (x, y)
                self._espacio_seg1 = -1
                # Marcador visual (círculo verde para distinguirlo)
                r = 9 * self._escala_vista()
                m = self.scene().addEllipse(x-r, y-r, 2*r, 2*r, pen_v, brush_nulo)
                self._items_espacio.append(m)
                self.recalcular_todas_las_distancias()
                self.progreso_modificado.emit()
                try:
                    self._pestana.label_estado.setText(
                        "↔ Inicio del quiebre marcado. Haz clic en el borde final.")
                except Exception:
                    pass
                return

            # Segundo clic: punto B — línea AMARILLA desde A, tick amarillo
            self.guardar_en_historial()
            self.modelo_medicion.agregar((x, y), TipoMarca.ESPACIO)   # línea amarilla desde A, tick amarillo
            self._idx_espacio_inicio = None
            self._limpiar_espacio()
            self.recalcular_todas_las_distancias()
            self.progreso_modificado.emit()
            try:
                self._resaltar_anclado(len(self.coordenadas_anillos) - 1)
                self._pestana.label_estado.setText(
                    "↔ Quiebre marcado. Haz clic en el límite final del anillo.")
                self._pestana.set_modo(ModoMedicion.MEDIR)
            except Exception:
                pass
            return

        # ══════════════════════════════════════════════════════════════════
        # SUBMODO A: sobre línea existente
        # ══════════════════════════════════════════════════════════════════
        seg_idx, t, _ = hit
        x1, y1 = coords[seg_idx]
        x2, y2 = coords[seg_idx + 1]
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)

        # ── Primer clic A ─────────────────────────────────────────────────
        if self._idx_espacio_inicio is None:
            self._limpiar_espacio()
            r = 9 * self._escala_vista()
            m = self.scene().addEllipse(px-r, py-r, 2*r, 2*r, pen_v, brush_nulo)
            self._items_espacio.append(m)
            self._espacio_p1   = (px, py)
            self._espacio_seg1 = seg_idx
            self._idx_espacio_inicio = seg_idx
            try:
                self._pestana.label_estado.setText(
                    "↔ Inicio del espacio marcado. Haz clic en el borde final.")
            except Exception:
                pass
            return

        # ── Segundo clic A ────────────────────────────────────────────────
        p1, s1 = self._espacio_p1, self._espacio_seg1
        p2, s2 = (px, py), seg_idx
        self._idx_espacio_inicio = None
        self._limpiar_espacio()

        # Ordenar s1 ≤ s2
        if s1 > s2:
            p1, p2 = p2, p1
            s1, s2 = s2, s1
        elif s1 == s2:
            xr1, yr1 = coords[s1]
            d1 = math.hypot(p1[0]-xr1, p1[1]-yr1)
            d2 = math.hypot(p2[0]-xr1, p2[1]-yr1)
            if d1 > d2:
                p1, p2 = p2, p1

        if math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < 2:
            try:
                self._pestana.label_estado.setText("↔ Puntos demasiado cercanos. Cancelado.")
            except Exception:
                pass
            return

        # Validar que no hay ticks normales (anillos completos) entre s1 y s2
        for j in range(s1 + 1, s2 + 1):
            if j < len(self.es_salto) and self.es_salto[j] is False:
                try:
                    self._pestana.label_estado.setText(
                        "↔ El espacio no puede cruzar un límite de anillo.")
                except Exception:
                    pass
                return

        self.guardar_en_historial()

        # Estado final deseado:
        #   prev_tick ─("quiebre_ini")─ p1 ─("espacio")─ p2 ─(False)─ next_tick
        #                                ↑ tick amarillo   ↑ tick amarillo
        #
        # p1 tiene es_salto="quiebre_ini" (azul, SUMA distancia, no cierra)
        # el tramo p1→p2 tiene es_salto="espacio" (amarillo, no suma, no cierra)
        # p2→siguiente tiene es_salto=False (reanuda normal, suma y cierra)
        #
        # Insertar de atrás hacia adelante:
        #   1) p2 en s2+1 con es_salto=False (p2→siguiente normal)
        #   2) p1 en s1+1 con es_salto="quiebre_ini" (prev→p1 azul, suma)
        #   3) El segmento p1→p2 (índice s1+2) = "espacio"
        #   4) Segmentos intermedios si s1 < s2 → también "espacio"

        # 1) Insertar p2
        self.modelo_medicion.insertar(s2 + 1, p2, TipoMarca.NORMAL)   # p2→siguiente: reanuda normal

        # 2) Insertar p1 con es_salto="quiebre_ini" (suma distancia antes del quiebre)
        self.modelo_medicion.insertar(s1 + 1, p1, TipoMarca.QUIEBRE_INI)  # prev→p1: azul, suma

        # 3) Segmento p1→p2 = "espacio"
        idx_tramo = s1 + 2
        if idx_tramo < len(self.es_salto):
            self.modelo_medicion.marcar(idx_tramo, TipoMarca.ESPACIO)

        # 4) Segmentos intermedios (si s1 < s2)
        for j in range(idx_tramo + 1, s2 + 2):
            if j < len(self.es_salto) and self.es_salto[j] is False:
                self.modelo_medicion.marcar(j, TipoMarca.ESPACIO)

        self.recalcular_todas_las_distancias()
        self.progreso_modificado.emit()
        try:
            self._pestana.label_estado.setText(
                "↔ Quiebre insertado. Tramo amarillo no cuenta. Ctrl+Z para deshacer.")
            self._pestana.set_modo(ModoMedicion.MEDIR)
        except Exception:
            pass


    def _paso_ewlw(self, x: float, y: float):
        """
        Modo EW/LW: clic sobre la línea azul del camino.
        Inserta un punto "ew_lw" (tick naranja) que divide el anillo
        en earlywood (izquierda) y latewood (derecha).
        Un anillo puede tener como máximo un límite EW/LW.
        La distancia total del anillo no cambia (EW+LW = total).
        Esc cancela. Ctrl+Z deshace.
        """
        coords = self.coordenadas_anillos
        hit = self._segmento_mas_cercano(x, y) if len(coords) >= 2 else None
        if hit is None:
            try:
                self._pestana.label_estado.setText(
                    "🍂 Haz clic sobre la línea azul del anillo a dividir.")
            except Exception:
                pass
            return

        seg_idx, t, _ = hit
        # Verificar que el segmento no sea ya un tramo de espacio/quiebre
        val_seg = self.es_salto[seg_idx + 1] if seg_idx + 1 < len(self.es_salto) else False
        if _es_amarillo(val_seg):
            try:
                self._pestana.label_estado.setText(
                    "🍂 No se puede insertar EW/LW en un tramo de quiebre o salto.")
            except Exception:
                pass
            return

        # Verificar que no haya ya un ew_lw en este anillo
        # (buscar el anillo que contiene seg_idx)
        ini_anillo = seg_idx
        while ini_anillo > 0 and self.es_salto[ini_anillo] is not False:
            ini_anillo -= 1
        fin_anillo = seg_idx + 1
        while fin_anillo < len(coords) and self.es_salto[fin_anillo] is not False:
            fin_anillo += 1
        for j in range(ini_anillo + 1, fin_anillo):
            if j < len(self.es_salto) and _es_ewlw(self.es_salto[j]):
                try:
                    self._pestana.label_estado.setText(
                        "🍂 Este anillo ya tiene un límite EW/LW. "
                        "Usa 🖐 Mover para reposicionarlo.")
                except Exception:
                    pass
                return

        # Calcular punto exacto sobre el segmento
        x1, y1 = coords[seg_idx]
        x2, y2 = coords[seg_idx + 1]
        px = x1 + t * (x2 - x1)
        py = y1 + t * (y2 - y1)

        self.guardar_en_historial()
        self.modelo_medicion.insertar(seg_idx + 1, (px, py), TipoMarca.EW_LW)

        self.recalcular_todas_las_distancias()
        self.progreso_modificado.emit()
        try:
            self._pestana.label_estado.setText(
                "🍂 Límite EW/LW insertado. Usa 🖐 Mover para ajustarlo. "
                "Ctrl+Z para deshacer.")
        except Exception:
            pass

    def _limpiar_espacio(self):
        for item in self._items_espacio:
            try: self.scene().removeItem(item)
            except Exception: pass
        self._items_espacio.clear()
        # No limpiar _idx_espacio_inicio aquí — se maneja en _paso_espacio

    def keyPressEvent(self, event):
        """Enter confirma el modo pith; Esc lo cancela."""
        if self.modo_actual == ModoMedicion.PITH:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                try:
                    self._pestana._confirmar_estimacion_pith()
                except Exception:
                    pass
                return
            if event.key() == Qt.Key.Key_Escape:
                self._limpiar_items_pith()
                try:
                    self._pestana.set_modo(ModoMedicion.MEDIR)
                    self._pestana.label_estado.setText("Estimación cancelada.")
                except Exception:
                    pass
                return
        if self.modo_actual == ModoMedicion.ESPACIO:
            if event.key() == Qt.Key.Key_Escape:
                self._idx_espacio_inicio = None
                self._limpiar_espacio()
                try:
                    self._pestana.label_estado.setText("↔ Selección de espacio cancelada.")
                except Exception:
                    pass
                return
        # Modo selección múltiple: atajos de teclado
        if self.modo_actual == ModoMedicion.SELECCIONAR:
            # Delete o Backspace → borrar los seleccionados
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._ejecutar_borrar_seleccionados()
                return
            # Esc → limpiar selección y volver a Medir
            if event.key() == Qt.Key.Key_Escape:
                self._limpiar_seleccion_completa()
                try:
                    self._pestana.set_modo(ModoMedicion.MEDIR)
                except Exception:
                    pass
                return
        super().keyPressEvent(event)

    def _iniciar_mover(self, x, y, event):
        idx = self._indice_punto_mas_cercano(x, y)
        if idx is not None:
            self.guardar_en_historial()
            self._punto_arrastrado_idx = idx
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _insertar_en_segmento(self, x, y):
        if len(self.coordenadas_anillos) < 2:
            return
        tol = self._tolerancia_segmento()
        mejor_d, mejor_idx = float("inf"), -1
        for i in range(len(self.coordenadas_anillos) - 1):
            x1, y1 = self.coordenadas_anillos[i]
            x2, y2 = self.coordenadas_anillos[i + 1]
            d = self._dist_punto_segmento(x, y, x1, y1, x2, y2)
            if d < mejor_d:
                mejor_d, mejor_idx = d, i
        if mejor_d < tol and mejor_idx != -1:
            self.guardar_en_historial()
            self.modelo_medicion.insertar(mejor_idx + 1, (x, y), TipoMarca.NORMAL)
            self.recalcular_todas_las_distancias()
            self.progreso_modificado.emit()

    def _borrar_punto_cercano(self, x, y):
        idx = self._indice_punto_mas_cercano(x, y)
        if idx is not None:
            self.guardar_en_historial()
            self.modelo_medicion.borrar(idx)
            self.recalcular_todas_las_distancias()
            self.progreso_modificado.emit()

    def _paso_calibracion(self, x, y):
        """Procesa los clicks de calibración.

        Flujo:
          - Click 1: marca el punto inicial
          - Click 2: marca el punto final + dibuja línea + pregunta los mm
                     → aplica calibración y limpia las marcas
        """
        self.puntos_calibracion.append((x, y))

        # Dibujar el círculo del punto y agregar a la lista limpiable
        marker = self.scene().addEllipse(
            x - 5, y - 5, 10, 10,
            self._pen_calibracion, QBrush(QColor(COLOR_CALIBRACION)))
        marker.setZValue(500)
        self._items_calibracion.append(marker)

        # Solo hay un punto: pedir el segundo
        if len(self.puntos_calibracion) == 1:
            try:
                self._pestana.label_estado.setText(
                    "📏 Calibración: Haz clic en el segundo punto (final de la distancia conocida).")
            except Exception:
                pass
            return

        # Ya tenemos los 2 puntos
        p1, p2 = self.puntos_calibracion
        dist_px = math.hypot(p2[0] - p1[0], p2[1] - p1[1])

        # Dibujar la línea entre los 2 puntos
        pen_linea = QPen(QColor(COLOR_CALIBRACION))
        pen_linea.setCosmetic(True)
        pen_linea.setWidthF(2.5)
        pen_linea.setStyle(Qt.PenStyle.SolidLine)
        linea = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen_linea)
        linea.setZValue(499)
        self._items_calibracion.append(linea)

        # Etiqueta con la distancia, posicionada PEGADA AL BORDE INTERNO
        # de la imagen (el borde más cercano a la línea de calibración).
        # Quedaba afuera de la imagen porque calculábamos offsets estimados
        # (22 px de alto, etc.) — ahora usamos el boundingRect REAL del
        # texto después de setear el HTML para posicionarlo con precisión.
        from PyQt6.QtWidgets import QGraphicsItem

        # Crear el texto primero (necesario para conocer su tamaño)
        texto = self.scene().addText("")
        texto.setHtml(
            f"<div style='background:rgba(0,0,0,200); color:{COLOR_CALIBRACION}; "
            f"padding:2px 5px; border-radius:3px; font-size:12px; "
            f"font-weight:bold; font-family:Arial; white-space:nowrap;'>"
            f"📏 {dist_px:.1f} px"
            f"</div>"
        )
        texto.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        rect = texto.boundingRect()  # en píxeles de pantalla (por el flag)
        # Tamaño real del badge, no estimado
        rect_w_px = rect.width()
        rect_h_px = rect.height()

        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2

        # Bordes de la imagen (sceneRect coincide con la imagen — ver
        # _cargar_imagen donde se hace setSceneRect(0, 0, w, h)).
        scene_rect = self.scene().sceneRect()
        left, top = scene_rect.left(), scene_rect.top()
        right, bottom = scene_rect.right(), scene_rect.bottom()

        # Distancias del punto medio a cada borde
        d_top = my - top
        d_bottom = bottom - my
        d_left = mx - left
        d_right = right - mx
        min_d = min(d_top, d_bottom, d_left, d_right)

        # Margen INTERNO (en píxeles de pantalla) desde el borde de la
        # imagen. Garantiza que el badge entero queda DENTRO del rectángulo
        # de la imagen, independiente del zoom.
        MARGEN_INTERNO_PX = 6.0
        escala = self._escala_vista()

        # Convertir píxeles de pantalla a unidades de escena para colocar
        # el setPos en el lugar correcto. El badge ocupa rect_w_px x
        # rect_h_px en PANTALLA. La posición es la esquina top-left del
        # badge en coords de escena.
        rect_w_escena = rect_w_px * escala
        rect_h_escena = rect_h_px * escala
        margen_escena = MARGEN_INTERNO_PX * escala

        if min_d == d_top:
            # Borde superior: badge contra el borde superior, centrado en mx
            label_x = mx - rect_w_escena / 2.0
            label_y = top + margen_escena
        elif min_d == d_bottom:
            # Borde inferior: badge JUSTO ENCIMA del borde, alineado a su
            # base con (bottom - margen). Es decir, top-left.y = bottom -
            # rect_h - margen.
            label_x = mx - rect_w_escena / 2.0
            label_y = bottom - rect_h_escena - margen_escena
        elif min_d == d_left:
            # Borde izquierdo: badge contra el borde izquierdo, centrado
            # verticalmente en my
            label_x = left + margen_escena
            label_y = my - rect_h_escena / 2.0
        else:
            # Borde derecho: badge contra el borde derecho, top-left.x =
            # right - rect_w - margen
            label_x = right - rect_w_escena - margen_escena
            label_y = my - rect_h_escena / 2.0

        # Clamping defensivo: si por alguna razón el cálculo se desbordó,
        # forzar la posición a quedar dentro del sceneRect.
        label_x = max(left + margen_escena,
                      min(label_x, right - rect_w_escena - margen_escena))
        label_y = max(top + margen_escena,
                      min(label_y, bottom - rect_h_escena - margen_escena))

        texto.setPos(label_x, label_y)
        texto.setZValue(501)
        self._items_calibracion.append(texto)

        # Forzar repintado para que el usuario VEA la línea y la distancia
        # antes de que aparezca el diálogo
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        # Si ya teníamos un objetivo_mm pre-cargado (flujo viejo) lo usamos.
        # En el flujo nuevo es None, así que preguntamos al usuario.
        objetivo = getattr(self, "_objetivo_calibracion_mm", None)
        if objetivo and objetivo > 0:
            dist_mm = objetivo
            ok = True
        else:
            dlg = DialogoCalibracionRegla(self.window())
            dlg.setWindowTitle(f"Calibración (línea = {dist_px:.1f} px)")
            if dlg.exec():
                dist_mm = dlg.obtener_mm()
                ok = (dist_mm > 0)
            else:
                dist_mm = 0
                ok = False

        if ok and dist_mm > 0:
            self.pixeles_por_mm = dist_px / dist_mm
            # Marcar el origen del DPI como "calibrado por regla"
            # para que el diálogo de info lo refleje correctamente.
            try:
                self._pestana._dpi_modo = "regla"
            except Exception:
                pass
            QMessageBox.information(
                self.window(), "Calibración aplicada",
                f"  {dist_px:.2f} px = {dist_mm:.3f} mm\n"
                f"  1 mm = {self.pixeles_por_mm:.2f} px\n"
                f"  ≈ {self.pixeles_por_mm * MM_POR_PULGADA:.0f} DPI"
            )
            # La señal sincroniza años, gráfico y escena antes del guardado.
            self.recalcular_todas_las_distancias()
            self._pestana._guardar_estado()
            # Actualizar la etiqueta de la línea con los mm calibrados así
            # el usuario tiene un recordatorio visual de que la imagen
            # ya está calibrada y a qué escala.
            self._actualizar_etiqueta_calibracion(dist_px, dist_mm)
        else:
            # Si canceló el diálogo, limpiar las marcas (no hubo calibración)
            self._limpiar_items_calibracion()

        self._objetivo_calibracion_mm = None
        self._pestana.set_modo(ModoMedicion.MEDIR)
        self.progreso_modificado.emit()

    def _actualizar_etiqueta_calibracion(self, dist_px: float, dist_mm: float):
        """Reemplaza el texto de "📏 X px" por "✓ Calibrada: X mm = Y px"
        para que el usuario sepa que la calibración ya está aplicada.
        Las marcas (puntos y línea) se mantienen como recordatorio visual.

        El texto usa ItemIgnoresTransformations para tamaño constante en
        pantalla independiente del zoom.
        """
        from PyQt6.QtWidgets import QGraphicsTextItem, QGraphicsItem
        for i, item in enumerate(self._items_calibracion):
            if isinstance(item, QGraphicsTextItem):
                item.setHtml(
                    f"<div style='background:rgba(0,0,0,200); "
                    f"color:{COLOR_CALIBRACION}; "
                    f"padding:2px 5px; border-radius:3px; font-size:12px; "
                    f"font-weight:bold; font-family:Arial; white-space:nowrap;'>"
                    f"✓ Calibrada: {dist_px:.1f} px = {dist_mm:.2f} mm"
                    f"</div>"
                )
                # Asegurar el flag (por si vino de una versión vieja sin él)
                item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
                    True)
                break

    # ------------------------------------------------------------------
    # Modo MEDIR / SALTO con ancla seleccionable
    # ------------------------------------------------------------------

    def _limpiar_anclado(self):
        """Elimina el resaltado visual del punto ancla."""
        if self._item_anclado is not None:
            try:
                self.scene().removeItem(self._item_anclado)
            except Exception:
                pass
            self._item_anclado = None
        self._idx_anclado = None

    def _resaltar_anclado(self, idx: int):
        """Dibuja un círculo amarillo sobre el punto anclado."""
        self._limpiar_anclado()
        if idx < 0 or idx >= len(self.coordenadas_anillos):
            return   # índice inválido tras deshacer/borrar
        self._idx_anclado = idx
        x, y = self.coordenadas_anillos[idx]
        pen  = QPen(QColor("#FFD700")); pen.setCosmetic(True); pen.setWidthF(3.0)
        brush = QBrush(Qt.BrushStyle.NoBrush)
        r = 10 * self._escala_vista()
        self._item_anclado = self.scene().addEllipse(x - r, y - r, 2*r, 2*r, pen, brush)

    def _paso_medir(self, x: float, y: float):
        """
        Lógica unificada para los modos Medir y Salto.

        Estado de la máquina:
          • Sin ancla + puntos existentes → busca punto cercano para anclar.
            Si no hay ninguno cerca → ancla al extremo más cercano y añade.
          • Sin ancla + serie vacía       → primer punto de la serie.
          • Con ancla                     → inserta punto adyacente al ancla,
            detectando dirección automáticamente.
        """
        coords = self.coordenadas_anillos
        es_salto_modo = self.modo_actual == ModoMedicion.SALTO

        # ── Serie vacía: primer punto ────────────────────────────────────
        if not coords:
            self.guardar_en_historial()
            self.modelo_medicion.agregar((x, y), TipoMarca.NORMAL)
            self._resaltar_anclado(0)
            self.recalcular_todas_las_distancias()
            self.progreso_modificado.emit()
            return

        # ── Sin ancla: intentar seleccionar punto existente ──────────────
        if self._idx_anclado is None:
            idx = self._indice_punto_mas_cercano(x, y)
            if idx is not None:
                # El clic fue sobre un punto → anclar sin añadir nada
                self._resaltar_anclado(idx)
                return
            else:
                # Clic lejos de cualquier punto → anclar al extremo más cercano
                d0 = math.hypot(x - coords[0][0],  y - coords[0][1])
                d1 = math.hypot(x - coords[-1][0], y - coords[-1][1])
                self._resaltar_anclado(0 if d0 < d1 else len(coords) - 1)
                # Caemos al bloque "con ancla" para insertar de inmediato
                # (este clic también es el de inserción)

        # ── Con ancla: insertar punto adyacente ──────────────────────────
        idx_a = self._idx_anclado
        n = len(coords)
        # Guard: ancla puede haber quedado fuera de rango tras deshacer
        if idx_a is None or idx_a >= n:
            self._limpiar_anclado()
            idx_a = n - 1
            self._resaltar_anclado(idx_a)

        # Determinar dirección: el nuevo punto va ANTES o DESPUÉS del ancla.
        # Se compara la distancia euclidiana del cursor a los vecinos para
        # inferir en qué lado del ancla está el usuario apuntando.
        # Regla simple: si el ancla es el último punto → append.
        #               si el ancla es el primero       → prepend.
        #               si está en el medio             → detectar por posición.
        if idx_a == n - 1:
            # Ancla al final → añadir después (hacia corteza o médula según dirección global)
            insert_pos = n
        elif idx_a == 0:
            # Ancla al principio → insertar antes
            insert_pos = 0
        else:
            # Punto intermedio: insertar en el lado donde cae el nuevo clic.
            # Comparar proyección sobre el vector ancla→siguiente vs ancla→anterior
            ax, ay = coords[idx_a]
            bx, by = coords[idx_a + 1]   # siguiente
            px_prev, py_prev = coords[idx_a - 1]  # anterior
            # Distancia del nuevo clic a ambos vecinos
            d_sig  = math.hypot(x - bx,      y - by)
            d_prev = math.hypot(x - px_prev, y - py_prev)
            insert_pos = idx_a + 1 if d_sig < d_prev else idx_a

        self.guardar_en_historial()
        self.modelo_medicion.insertar(insert_pos, (x, y), TipoMarca.SALTO if es_salto_modo else TipoMarca.NORMAL)

        # El nuevo ancla pasa a ser el punto recién insertado
        self._resaltar_anclado(insert_pos)

        self.recalcular_todas_las_distancias()

        if es_salto_modo:
            self._limpiar_anclado()
            self._pestana.set_modo(ModoMedicion.MEDIR)

        self.progreso_modificado.emit()

    def _anadir_punto(self, x, y):
        """Alias de compatibilidad — delega a _paso_medir."""
        self._paso_medir(x, y)

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())
        x, y = pos.x(), pos.y()
        if self._actualizar_seleccion_mouse(x, y):
            return
        # ── Preview de arco en modo pith con 2 puntos ──
        if self.modo_actual == ModoMedicion.PITH and len(self._puntos_pith) == 2:
            self._preview_pith_mouse(x, y)

        self._actualizar_cursor_mouse(x, y)
        self._actualizar_tooltip_mouse(event)
        super().mouseMoveEvent(event)
        if self._actualizar_paneo_mouse(event):
            return
        if self._actualizar_arrastre_mouse(x, y):
            return
        self._actualizar_guia_mouse(event, x, y)

    def _actualizar_seleccion_mouse(self, x, y):
        # ── Selección por arrastre (ModoMedicion.SELECCIONAR) ──
        # Si comenzamos un drag desde un área vacía, dibujamos el
        # rectángulo de selección que sigue al mouse.
        # Si comenzamos sobre un punto pero el mouse se aleja del punto
        # de partida (umbral 4 px de pantalla), convertimos el "posible
        # toggle" en un drag-rectangle (cancela el candidato).
        if self.modo_actual == ModoMedicion.SELECCIONAR:
            mouse_se_movio = (
                math.hypot(x - self._sel_click_pos[0],
                           y - self._sel_click_pos[1])
                > 4.0 * self._escala_vista()
            )
            if (self._sel_click_idx_candidato is not None
                    and not self._sel_drag_iniciado
                    and mouse_se_movio):
                # El usuario empezó sobre un punto pero ahora está
                # arrastrando — convertir a drag-rectangle desde la pos
                # original.
                self._sel_click_idx_candidato = None
                self._sel_drag_iniciado = True
                # _sel_drag_start ya está seteado en mousePress

            if self._sel_drag_iniciado:
                x0, y0 = self._sel_drag_start
                xa, ya = min(x0, x), min(y0, y)
                xb, yb = max(x0, x), max(y0, y)
                # Crear/actualizar el rectángulo de preview
                if self._sel_drag_rect_item is None:
                    pen = QPen(QColor("#FFEB3B"))
                    pen.setCosmetic(True)
                    pen.setWidthF(1.5)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    brush = QBrush(QColor(255, 235, 59, 40))  # amarillo translúcido
                    self._sel_drag_rect_item = self.scene().addRect(
                        xa, ya, xb - xa, yb - ya, pen, brush)
                    self._sel_drag_rect_item.setZValue(951)
                else:
                    self._sel_drag_rect_item.setRect(xa, ya, xb - xa, yb - ya)
                return True

        return False

    def _actualizar_cursor_mouse(self, x, y):
        # Cursor dinámico según modo
        if self.modo_actual == ModoMedicion.ESPACIO:
            sobre_linea = self._segmento_mas_cercano(x, y) is not None
            self.setCursor(
                Qt.CursorShape.CrossCursor if sobre_linea
                else Qt.CursorShape.ArrowCursor
            )

        elif self.modo_actual == ModoMedicion.BORRAR:
            hovering = any(
                math.hypot(px - x, py - y) < self._tolerancia_punto()
                for px, py in self.coordenadas_anillos
            )
            self.setCursor(Qt.CursorShape.CrossCursor if hovering else Qt.CursorShape.ArrowCursor)

        elif self.modo_actual == ModoMedicion.INSERTAR:
            tol = self._tolerancia_segmento()
            hovering = any(
                self._dist_punto_segmento(
                    x, y,
                    self.coordenadas_anillos[i][0], self.coordenadas_anillos[i][1],
                    self.coordenadas_anillos[i + 1][0], self.coordenadas_anillos[i + 1][1],
                ) < tol
                for i in range(len(self.coordenadas_anillos) - 1)
            )
            self.setCursor(Qt.CursorShape.CrossCursor if hovering else Qt.CursorShape.ArrowCursor)

    def _actualizar_tooltip_mouse(self, event):
        # Tooltip en puntos
        item = self.itemAt(event.pos())
        if isinstance(item, QGraphicsEllipseItem) and hasattr(item, "anio_texto"):
            if item != self._item_hover_prev:
                QToolTip.showText(event.globalPosition().toPoint(), item.anio_texto, self.viewport())
                self._item_hover_prev = item
        elif self._item_hover_prev is not None:
            QToolTip.hideText()
            self._item_hover_prev = None

    def _actualizar_paneo_mouse(self, event):
        # Pan con botón central (independiente del modo)
        if self._is_panning and self._last_pan_pos and not (
            self.modo_actual == ModoMedicion.MOVER and self._punto_arrastrado_idx is not None
        ):
            if event.buttons() & Qt.MouseButton.MiddleButton or (
                self.modo_actual == ModoMedicion.MOVER and event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.pos() - self._last_pan_pos
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
                self._last_pan_pos = event.pos()
                return True

        # Pan de la imagen (modo mover, sin punto seleccionado)
        if self.modo_actual == ModoMedicion.MOVER and self._is_panning and self._last_pan_pos:
            delta = event.pos() - self._last_pan_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._last_pan_pos = event.pos()
            return True

        return False

    def _actualizar_arrastre_mouse(self, x, y):
        # Arrastre de punto
        if self.modo_actual == ModoMedicion.MOVER and self._punto_arrastrado_idx is not None:
            self.modelo_medicion.mover(self._punto_arrastrado_idx, (x, y))
            self.recalcular_todas_las_distancias()
            return True

        return False

    def _actualizar_guia_mouse(self, event, x, y):
        # Línea guía hacia el cursor
        if self.modo_actual == ModoMedicion.ESPACIO and self.coordenadas_anillos:
            # Línea guía desde el punto A ya insertado en el camino
            if self._idx_espacio_inicio is not None:
                x_ant, y_ant = self._espacio_p1
                pen_esp = QPen(QColor("#00FF88"))
                pen_esp.setCosmetic(True)
                pen_esp.setWidthF(1.5)
                pen_esp.setStyle(Qt.PenStyle.DashLine)
                if self._linea_guia is None:
                    self._linea_guia = self.scene().addLine(x_ant, y_ant, x, y, pen_esp)
                else:
                    self._linea_guia.setLine(x_ant, y_ant, x, y)
                    self._linea_guia.setPen(pen_esp)
            elif self._linea_guia:
                self.scene().removeItem(self._linea_guia)
                self._linea_guia = None

        elif self.modo_actual in (ModoMedicion.MEDIR, ModoMedicion.SALTO, ModoMedicion.ANOMALIA,
                                   ModoMedicion.INSERTAR, ModoMedicion.BORRAR) and self.coordenadas_anillos:
            # Botón derecho presionado → previsualizar salto
            es_salto_preview = bool(event.buttons() & Qt.MouseButton.RightButton)
            modo_guia = ModoMedicion.SALTO if es_salto_preview else self.modo_actual
            if modo_guia not in (ModoMedicion.MEDIR, ModoMedicion.SALTO):
                # En otros modos solo mostrar guía si hay ancla activa
                if self._idx_anclado is None:
                    return
            # La guía sale desde el punto anclado (o el último si no hay ancla)
            if self._idx_anclado is not None and self._idx_anclado < len(self.coordenadas_anillos):
                x_ant, y_ant = self.coordenadas_anillos[self._idx_anclado]
            else:
                self._limpiar_anclado()   # ancla inválida tras deshacer → resetear
                x_ant, y_ant = self.coordenadas_anillos[-1]
            pen = self._pen_salto if modo_guia == ModoMedicion.SALTO else self._pen_guia
            if self._linea_guia is None:
                self._linea_guia = self.scene().addLine(x_ant, y_ant, x, y, pen)
            else:
                self._linea_guia.setLine(x_ant, y_ant, x, y)
                self._linea_guia.setPen(pen)

    def mouseReleaseEvent(self, event):
        # ── Selección por arrastre (ModoMedicion.SELECCIONAR) ──
        # Si terminamos un drag-rectangle: encontrar todos los anillos
        # dentro del área y agregarlos a la selección.
        # Si fue solo un click sobre un punto (sin arrastre): toggle.
        if (self.modo_actual == ModoMedicion.SELECCIONAR
                and event.button() == Qt.MouseButton.LeftButton):
            if self._sel_drag_iniciado and self._sel_drag_rect_item is not None:
                # Calcular los bounds del rectángulo final
                rect = self._sel_drag_rect_item.rect()
                xa, ya = rect.left(), rect.top()
                xb, yb = rect.right(), rect.bottom()
                # Buscar anillos dentro
                indices_dentro = []
                for i, (px, py) in enumerate(self.coordenadas_anillos):
                    if xa <= px <= xb and ya <= py <= yb:
                        indices_dentro.append(i)
                # Agregar al set de seleccionados (no toggle, para que
                # arrastres sucesivos sumen sin deseleccionar lo previo).
                for i in indices_dentro:
                    self._puntos_seleccionados.add(i)
                # Limpiar el preview del rectángulo
                try:
                    self.scene().removeItem(self._sel_drag_rect_item)
                except Exception:
                    pass
                self._sel_drag_rect_item = None
                self._sel_drag_iniciado = False
                # Redibujar marcadores + actualizar panel
                self._dibujar_marcadores_seleccion()
                self._actualizar_panel_seleccion()
                return
            elif self._sel_click_idx_candidato is not None:
                # No hubo arrastre: ejecutar el toggle del punto candidato
                self._toggle_seleccion_punto(self._sel_click_idx_candidato)
                self._sel_click_idx_candidato = None
                return
            # Si no hubo ni drag ni candidato, no hacemos nada
            self._sel_drag_iniciado = False
            self._sel_click_idx_candidato = None

        # Botón central: fin del paneo
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self._last_pan_pos = None
            # Restaurar cursor según el modo activo
            cursores = {
                ModoMedicion.MEDIR:    Qt.CursorShape.CrossCursor,
                ModoMedicion.SALTO:    Qt.CursorShape.CrossCursor,
                ModoMedicion.MOVER:    Qt.CursorShape.OpenHandCursor,
                ModoMedicion.INSERTAR: Qt.CursorShape.ArrowCursor,
                ModoMedicion.BORRAR:   Qt.CursorShape.ArrowCursor,
                ModoMedicion.ANOMALIA: Qt.CursorShape.PointingHandCursor,
            }
            self.setCursor(cursores.get(self.modo_actual, Qt.CursorShape.ArrowCursor))
            return

        if self.modo_actual == ModoMedicion.MOVER:
            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._punto_arrastrado_idx is not None:
                self._punto_arrastrado_idx = None
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.progreso_modificado.emit()
            return
        super().mouseReleaseEvent(event)

    # -------------------------------------------------------------------------
    # Auto-detección de anillos
    # -------------------------------------------------------------------------

    def iniciar_autodetect(self, imagen_bgr: np.ndarray):
        """
        Activa el modo auto-detección y cachea la imagen BGR.
        Comportamiento:
          - Si hay puntos existentes: 1er clic ancla un punto, 2do clic define el extremo.
          - Si la serie está vacía: 1er clic = un extremo, 2do clic = el otro.

        Fix de foco: después de cambiar el modo, forzar foco en la vista
        y procesar eventos pendientes. Sin esto, el primer click sobre la
        imagen se "pierde" — el foco se queda en el botón/popup que invocó
        este método, y el mousePressEvent del primer click no llega
        limpio a la vista. El usuario tenía que hacer dos clicks para
        cada punto, que era exactamente lo que reportó como bug.
        """
        self._imagen_bgr = imagen_bgr
        self._puntos_autodetect = []
        self._idx_ancla_autodetect = None   # índice del punto anclado (si existe)
        for item in self._items_autodetect:
            self.scene().removeItem(item)
        self._items_autodetect.clear()
        self.cambiar_modo(ModoMedicion.AUTODETECT)
        # Forzar foco en la vista y procesar eventos pendientes — sin esto
        # el primer click se pierde porque el botón "🔍 Auto-detectar" del
        # top bar retiene el foco hasta el siguiente evento.
        self.setFocus()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def _paso_autodetect(self, x: float, y: float):
        """
        Máquina de estados del modo auto-detección.

        Con puntos existentes:
          Clic 1: si cae sobre un punto existente → ancla ese punto (amarillo).
                  Si no hay ninguno cerca → trata como extremo libre.
          Clic 2: define el otro extremo → lanza detección entre ancla y este punto.

        Sin puntos:
          Clic 1: primer extremo (verde).
          Clic 2: segundo extremo → lanza detección entre los dos.
        """
        pen_verde = QPen(QColor("#00FF88")); pen_verde.setCosmetic(True); pen_verde.setWidthF(3.0)
        brush_verde = QBrush(QColor("#00FF88"))
        pen_amarillo = QPen(QColor("#FFD700")); pen_amarillo.setCosmetic(True); pen_amarillo.setWidthF(3.0)
        brush_nulo = QBrush(Qt.BrushStyle.NoBrush)

        coords = self.coordenadas_anillos

        # ── Primer clic ───────────────────────────────────────────────────────
        if len(self._puntos_autodetect) == 0:
            idx_cercano = self._indice_punto_mas_cercano(x, y)

            if idx_cercano is not None and coords:
                # Anclar punto existente
                self._idx_ancla_autodetect = idx_cercano
                ax, ay = coords[idx_cercano]
                marker = self.scene().addEllipse(ax - 10, ay - 10, 20, 20,
                                                  pen_amarillo, brush_nulo)
                self._items_autodetect.append(marker)
                self._puntos_autodetect.append(coords[idx_cercano])
            else:
                # Extremo libre
                self._idx_ancla_autodetect = None
                marker = self.scene().addEllipse(x - 8, y - 8, 16, 16,
                                                  pen_verde, brush_verde)
                self._items_autodetect.append(marker)
                self._puntos_autodetect.append((x, y))
            return

        # ── Segundo clic: definir extremo y lanzar detección ─────────────────
        marker2 = self.scene().addEllipse(x - 8, y - 8, 16, 16, pen_verde, brush_verde)
        self._items_autodetect.append(marker2)
        self._puntos_autodetect.append((x, y))

        p1 = self._puntos_autodetect[0]
        p2 = self._puntos_autodetect[1]

        # Línea visual del segmento a detectar
        pen_linea = QPen(QColor("#00FF88")); pen_linea.setCosmetic(True); pen_linea.setWidthF(2.0)
        pen_linea.setStyle(Qt.PenStyle.DashLine)
        linea = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen_linea)
        self._items_autodetect.append(linea)

        # Delegar a la pestaña con información del ancla
        self._pestana._ejecutar_autodeteccion(
            p1, p2, self._imagen_bgr,
            idx_ancla=self._idx_ancla_autodetect,
        )

        # Limpiar y volver a Medir
        for item in self._items_autodetect:
            self.scene().removeItem(item)
        self._items_autodetect.clear()
        self._puntos_autodetect.clear()
        self._idx_ancla_autodetect = None
        self.cambiar_modo(ModoMedicion.MEDIR)

    def colocar_puntos_autodetectados(
        self,
        coordenadas: list[tuple[float, float]],
        idx_ancla: int | None = None,
        reemplazar_tramo: bool = False,
    ):
        """
        Inserta los puntos detectados respetando el ancla.

        idx_ancla=None      → append al final (comportamiento original).
        idx_ancla=i         → inserta a continuación del punto i, en la
                              dirección correcta detectada automáticamente.
        reemplazar_tramo    → si True, borra los puntos existentes entre
                              el ancla y el extremo antes de insertar.
        """
        if not coordenadas:
            return
        self.guardar_en_historial()

        if idx_ancla is None:
            # Sin ancla: añadir al final
            for coord in coordenadas:
                self.modelo_medicion.agregar(coord, TipoMarca.NORMAL)
        else:
            n = len(self.coordenadas_anillos)
            # Detectar dirección: ¿los nuevos puntos van después o antes del ancla?
            # Comparar distancia del primer punto detectado al vecino derecho vs izquierdo
            ax, ay = self.coordenadas_anillos[idx_ancla]
            fx, fy = coordenadas[0]   # primer punto detectado (el más cercano al ancla)
            d_der = math.hypot(fx - self.coordenadas_anillos[min(idx_ancla+1, n-1)][0],
                               fy - self.coordenadas_anillos[min(idx_ancla+1, n-1)][1]) if idx_ancla < n-1 else float('inf')
            d_izq = math.hypot(fx - self.coordenadas_anillos[max(idx_ancla-1, 0)][0],
                               fy - self.coordenadas_anillos[max(idx_ancla-1, 0)][1]) if idx_ancla > 0 else float('inf')
            insertar_despues = d_der <= d_izq or idx_ancla == 0

            if insertar_despues:
                insert_at = idx_ancla + 1
                if reemplazar_tramo:
                    # Determinar cuántos puntos hay hasta el extremo detectado
                    ultimo_x, ultimo_y = coordenadas[-1]
                    fin_tramo = insert_at
                    for k in range(insert_at, n):
                        kx, ky = self.coordenadas_anillos[k]
                        if math.hypot(kx - ultimo_x, ky - ultimo_y) < self._tolerancia_punto() * 3:
                            fin_tramo = k + 1
                            break
                    self.modelo_medicion.borrar(slice(insert_at, fin_tramo))
            else:
                insert_at = idx_ancla
                coordenadas = list(reversed(coordenadas))
                if reemplazar_tramo:
                    ultimo_x, ultimo_y = coordenadas[-1]
                    ini_tramo = 0
                    for k in range(insert_at - 1, -1, -1):
                        kx, ky = self.coordenadas_anillos[k]
                        if math.hypot(kx - ultimo_x, ky - ultimo_y) < self._tolerancia_punto() * 3:
                            ini_tramo = k
                            break
                    self.modelo_medicion.borrar(slice(ini_tramo, insert_at))
                    insert_at = ini_tramo

            for i, coord in enumerate(coordenadas):
                self.modelo_medicion.insertar(insert_at + i, coord, TipoMarca.NORMAL)

        self.recalcular_todas_las_distancias()
        self.progreso_modificado.emit()

    # -------------------------------------------------------------------------
    # Caminos inactivos (otros radios guardados)
    # -------------------------------------------------------------------------

    def cargar_caminos_inactivos(self, caminos: dict):
        # Cachear los datos: necesitamos volver a llamar a esta función
        # cuando cambia el zoom (para que las etiquetas de año y los grosores
        # de tick se rerenderan con la nueva escala). Sin esto los labels
        # viejos quedaban con el tamaño en escena de un zoom anterior.
        self._caminos_inactivos_data = dict(caminos)

        # Limpiar items previos (puntos, líneas Y textos)
        for visuales in self.items_caminos_inactivos.values():
            items_a_remover = (
                visuales.get("puntos", [])
                + visuales.get("lineas", [])
                + visuales.get("textos", [])
            )
            for item in items_a_remover:
                try:
                    self.scene().removeItem(item)
                except Exception:
                    pass
        self.items_caminos_inactivos.clear()

        # Grosor de tick adaptado al zoom (mismo helper que el camino activo)
        grosor = self._grosor_tick_zoom()

        pen_p = QPen(QColor(COLOR_PUNTO_INACTIVO))
        pen_p.setCosmetic(True); pen_p.setWidthF(grosor)
        brush_p = QBrush(QColor(COLOR_PUNTO_INACTIVO))
        pen_l = QPen(QColor("#80c080"))
        pen_l.setCosmetic(True); pen_l.setWidthF(grosor)

        escala = self._escala_vista()

        for nombre, datos in caminos.items():
            coords, saltos = datos.coordenadas, datos.marcas
            anio_medula = datos.anio_medula
            anio_corteza = datos.anio_corteza
            medula_a_corteza = (datos.dir_idx == 0)

            puntos, lineas, textos = [], [], []
            pen_tick_in = QPen(QColor(COLOR_PUNTO_INACTIVO))
            pen_tick_in.setCosmetic(True); pen_tick_in.setWidthF(grosor)

            anios_por_idx, cierres = anios_por_punto(datos.puntos,
                self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)

            # Primera pasada: dibujar TODOS los ticks y líneas (sin filtro).
            # El grosor ya está adaptado al zoom para evitar saturación.
            # Z-values: línea de conexión por debajo del tick (igual que el
            # camino activo) para que los límites siempre sean visibles.
            for i, c in enumerate(coords):
                # Línea de conexión primero (queda detrás del tick)
                if i > 0:
                    pen = self._pen_salto if _es_amarillo(saltos[i]) else pen_l
                    linea_conexion = self.scene().addLine(
                        coords[i - 1][0], coords[i - 1][1], c[0], c[1], pen)
                    linea_conexion.setZValue(1)  # debajo de los ticks
                    lineas.append(linea_conexion)
                # Tick perpendicular — SIEMPRE se dibuja, sin filtro.
                # El grosor se adapta vía pen_tick_in (ya ajustado al zoom).
                t1, t2 = self._perp_tick(coords, i, largo_px_pantalla=22.0)
                tick = self.scene().addLine(t1[0], t1[1], t2[0], t2[1], pen_tick_in)
                tick.setZValue(2)  # arriba de la línea de conexión
                puntos.append(tick)

            # Segunda pasada: etiquetas de año.
            # ESTAS SÍ se filtran por densidad (el helper compartido),
            # porque mostrar todos los números a la vez no aporta valor
            # cuando están comprimidos a pixeles. Además, filtro de
            # OVERLAP por bbox para evitar superposiciones (mismo
            # comportamiento que el camino activo).
            ultimo_bbox_inactivo = None
            for i in range(1, len(coords)):
                if i not in cierres:
                    continue
                anio = anios_por_idx[i]
                mostrar = self._filtro_densidad_anio(anio, escala)

                if mostrar:
                    # Chequeo de overlap antes de crear el label
                    bbox_nuevo = self._estimar_bbox_label_pantalla(
                        str(anio), coords[i], coords[i - 1])
                    if (ultimo_bbox_inactivo is not None
                            and self._labels_se_solapan(ultimo_bbox_inactivo,
                                                         bbox_nuevo)):
                        continue
                    # Mismo método que el camino activo: solo cambian los
                    # colores del texto. Color base verde claro para años
                    # normales y verde más brillante para décadas — análogo
                    # a "#cccccc" vs blanco del activo. El fondo negro por
                    # defecto se mantiene para que el comportamiento de zoom
                    # / lectura sea idéntico al camino activo (que el usuario
                    # validó).
                    color_etiqueta = "#a0d0a0" if anio % INTERVALO_MARCADOR_DECADA == 0 else "#80c080"
                    item_txt = self._crear_etiqueta_anio(
                        str(anio),
                        color_etiqueta,
                        coord_actual=coords[i],
                        coord_anterior=coords[i - 1],
                    )
                    textos.append(item_txt)
                    ultimo_bbox_inactivo = bbox_nuevo

            self.items_caminos_inactivos[nombre] = {
                "puntos": puntos,
                "lineas": lineas,
                "textos": textos,
            }

    def toggle_camino_inactivo(self, nombre: str, visible: bool):
        if nombre in self.items_caminos_inactivos:
            visuales = self.items_caminos_inactivos[nombre]
            for item in (
                visuales.get("puntos", [])
                + visuales.get("lineas", [])
                + visuales.get("textos", [])
            ):
                item.setVisible(visible)

    def cargar_camino_activo(self, coordenadas: list, es_salto: list, *, redibujar=True):
        self.modelo_medicion.cargar(coordenadas, es_salto)
        if redibujar:
            self.redibujar_todo()


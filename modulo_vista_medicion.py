"""Componentes de medición de DPI."""

from modulo_pith_ui import HerramientaPith

from modulo_render_medicion import RenderMedicion

import math
from modulo_calculo_medicion import anchos_puntos, anios_por_punto, dist_punto_segmento
import numpy as np
from modulo_modelo_medicion import ModeloMedicion, PuntoMedicion, HistorialMedicion, TipoMarca
from PyQt6.QtWidgets import QWidget, QDialog, QGraphicsView, QGraphicsScene, QPushButton, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QDoubleSpinBox, QComboBox, QToolTip, QGraphicsEllipseItem, QDialogButtonBox
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from modulo_pith import ajustar_circulo_minimos_cuadrados, ajuste_degenerado
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

    def __init__(self, escena_propia: QGraphicsScene, vista_principal, fuentes=lambda: ()):
        super().__init__()
        self._vista_principal = vista_principal
        self._fuentes = fuentes
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

        # El origen de las otras escenas lo aporta el contenedor.
        for clave, nombre, _ in self._fuentes():
            self.combo_fuente.addItem(f"📷 {nombre}", userData=clave)

        # Restaurar selección
        if seleccion_actual is not None:
            for i in range(self.combo_fuente.count()):
                if self.combo_fuente.itemData(i) == seleccion_actual:
                    self.combo_fuente.setCurrentIndex(i)
                    break

        self.combo_fuente.blockSignals(False)
        if seleccion_actual is not None and self.combo_fuente.currentData() != seleccion_actual:
            self._cambiar_fuente(self.combo_fuente.currentIndex())

    def _cambiar_fuente(self, idx):
        """Cambia la escena de la vista según la selección del combo."""
        data = self.combo_fuente.itemData(idx)
        if data == "__self__" or data is None:
            self.vista.setScene(self._escena_propia)
            return

        for clave, _, escena in self._fuentes():
            if clave == data:
                self.vista.setScene(escena)
                self.vista.fitInView(escena.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
                return
        self.vista.setScene(self._escena_propia)

    def _sincronizar_con_principal(self):
        """Copia zoom y posición de la vista principal."""
        self.vista.setTransform(self._vista_principal.transform())
        center = self._vista_principal.mapToScene(
            self._vista_principal.viewport().rect().center())
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
    estado_cambiado = pyqtSignal(str)
    modo_cambiado = pyqtSignal(object)
    anomalias_modificadas = pyqtSignal()
    confirmar_pith_solicitado = pyqtSignal()
    origen_calibracion_cambiado = pyqtSignal(str)
    guardado_solicitado = pyqtSignal()
    autodeteccion_solicitada = pyqtSignal(object, object, object, object)

    def __init__(self, escena: QGraphicsScene, parent=None, *, modelo=None,
                 datacion=lambda: None, tipo_anomalia=lambda: None,
                 configuracion_pith=lambda: (5, "rg"), mediciones=lambda: ()):
        super().__init__(escena, parent)
        self._obtener_datacion = datacion
        self._obtener_tipo_anomalia = tipo_anomalia

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
        self.modelo_medicion = modelo if modelo is not None else ModeloMedicion()
        self.puntos_calibracion: list[tuple[float, float]] = []
        # Items visuales de calibración (puntos, línea, texto) — se limpian
        # al cancelar/aceptar/reiniciar la calibración.
        self._items_calibracion: list = []
        self._pixeles_por_mm: float = PIXELES_POR_MM_DEFECTO

        self._render = RenderMedicion(self.scene, self._escala_vista,
                                      self._grosor_tick_zoom, self._perp_tick)

        # Estado de interacción
        self.modo_actual: ModoMedicion = ModoMedicion.MEDIR
        # Anomalías: {anio: tipo_str}
        self.anomalias: dict[int, str] = {}
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

        self._herramienta_pith = HerramientaPith(
            self.scene, self.viewport, self._escala_vista,
            lambda: self.coordenadas_anillos, lambda: self.pixeles_por_mm,
            lambda: (self._datacion_render() or (0, 0, True))[2],
            configuracion_pith, mediciones, self.estado_cambiado.emit)

        # ── Herramienta de selección múltiple ──
        # Permite al usuario seleccionar varios anillos a la vez (clic
        # alterna selección por punto) y aplicarles una acción común:
        # borrarlos todos, convertirlos a salto o convertirlos a quiebre.
        self._puntos_seleccionados: set[int] = set()
        self._items_seleccion: list = []  # marcadores visuales (círculos amarillos)

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

    def _cambiar_modo_usuario(self, modo):
        self.cambiar_modo(modo)
        self.modo_cambiado.emit(modo)

    def aplicar_accion_seleccion(self, modo):
        """Aplica acciones masivas desde la barra sin exponer la selección."""
        if self.modo_actual != ModoMedicion.SELECCIONAR or not self._puntos_seleccionados:
            return modo
        acciones = {ModoMedicion.BORRAR: self._ejecutar_borrar_seleccionados,
                    ModoMedicion.SALTO: self._ejecutar_convertir_a_salto,
                    ModoMedicion.ESPACIO: self._ejecutar_convertir_a_quiebre}
        if modo in acciones:
            acciones[modo]()
            return ModoMedicion.MEDIR
        return modo

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

    def _datacion_render(self):
        return self._obtener_datacion()

    def redibujar_todo(self):
        self._render.redibujar_todo(self.modelo_medicion.captura(), self.pixeles_por_mm,
            self._datacion_render(), self.anomalias,
            (self._pen_punto, self._pen_linea, self._pen_salto, self._pen_ewlw))

    def _anio_en_indice(self, idx: int) -> int | None:
        """Devuelve el año calendario del punto en coordenadas_anillos[idx], o None."""
        datacion = self._datacion_render()
        if datacion is None:
            return None
        anio_medula, anio_corteza, medula_a_corteza = datacion
        anios, _ = anios_por_punto(self.modelo_medicion.captura(),
            self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)
        return anios[idx] if 0 <= idx < len(anios) else None

    def _dibujar_anomalias(self):
        self._render._dibujar_anomalias(self.coordenadas_anillos, self.es_salto,
                                        self._datacion_render(), self.anomalias)

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

    def _editar_seleccion(self, tipo=None):
        if not self._puntos_seleccionados:
            return
        self.guardar_en_historial()
        self.modelo_medicion.editar_puntos(self._puntos_seleccionados, tipo)
        self._puntos_seleccionados.clear()
        self._dibujar_marcadores_seleccion()
        self.recalcular_todas_las_distancias()
        self._actualizar_panel_seleccion()
        self.progreso_modificado.emit()

    def _ejecutar_borrar_seleccionados(self):
        self._editar_seleccion()

    def _ejecutar_convertir_a_salto(self):
        self._editar_seleccion(TipoMarca.SALTO)

    def _ejecutar_convertir_a_quiebre(self):
        self._editar_seleccion(TipoMarca.ESPACIO)

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
        if self.coordenadas_anillos or self._render.hay_inactivos:
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
        if self._render.hay_inactivos:
            self._render.redibujar_inactivos(self.pixeles_por_mm, self._pen_salto)

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
                    self.modo_cambiado.emit(modo_previo)
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
            tipo_activo = self._obtener_tipo_anomalia()
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
            self.anomalias_modificadas.emit()
        except Exception:
            pass

    def _paso_pith(self, x: float, y: float):
        return self._herramienta_pith._paso_pith(x, y)

    def _preview_pith_mouse(self, x: float, y: float):
        return self._herramienta_pith._preview_pith_mouse(x, y)

    def _limpiar_preview_pith_mouse(self):
        return self._herramienta_pith._limpiar_preview_pith_mouse()

    def _actualizar_circulo_pith(self):
        return self._herramienta_pith._actualizar_circulo_pith()

    def _confirmar_pith(self):
        return self._herramienta_pith._confirmar_pith()

    def _limpiar_items_pith(self):
        return self._herramienta_pith._limpiar_items_pith()

    def _actualizar_hud_pith(self, html_text: str, color: str = "#FF8C00"):
        return self._herramienta_pith._actualizar_hud_pith(html_text, color)

    def resizeEvent(self, event):
        """Reposicionar el HUD del pith y el panel de selección cuando
        cambia el tamaño del widget."""
        super().resizeEvent(event)
        if hasattr(self, "_herramienta_pith"):
            self._herramienta_pith.reposicionar_hud()
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
        datacion = self._datacion_render()
        if datacion is None:
            return mapa
        anio_medula, anio_corteza, med_a_cor = datacion

        anios, cierres = anios_por_punto(self.modelo_medicion.captura(),
            self.pixeles_por_mm, anio_medula, anio_corteza, med_a_cor)
        return {anios[i]: coords[i] for i in sorted(cierres)}

    def _segmento_mas_cercano(self, x: float, y: float) -> tuple[int, float, float] | None:
        from modulo_calculo_medicion import segmento_mas_cercano
        return segmento_mas_cercano(self.coordenadas_anillos, x, y, self._tolerancia_segmento())

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
                    self.estado_cambiado.emit(
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
                    self.estado_cambiado.emit(
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
                self.estado_cambiado.emit(
                    "↔ Quiebre marcado. Haz clic en el límite final del anillo.")
                self._cambiar_modo_usuario(ModoMedicion.MEDIR)
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
                self.estado_cambiado.emit(
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
                self.estado_cambiado.emit("↔ Puntos demasiado cercanos. Cancelado.")
            except Exception:
                pass
            return

        # Validar que no hay ticks normales (anillos completos) entre s1 y s2
        for j in range(s1 + 1, s2 + 1):
            if j < len(self.es_salto) and self.es_salto[j] is False:
                try:
                    self.estado_cambiado.emit(
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
            self.estado_cambiado.emit(
                "↔ Quiebre insertado. Tramo amarillo no cuenta. Ctrl+Z para deshacer.")
            self._cambiar_modo_usuario(ModoMedicion.MEDIR)
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
                self.estado_cambiado.emit(
                    "🍂 Haz clic sobre la línea azul del anillo a dividir.")
            except Exception:
                pass
            return

        seg_idx, t, _ = hit
        # Verificar que el segmento no sea ya un tramo de espacio/quiebre
        val_seg = self.es_salto[seg_idx + 1] if seg_idx + 1 < len(self.es_salto) else False
        if _es_amarillo(val_seg):
            try:
                self.estado_cambiado.emit(
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
                    self.estado_cambiado.emit(
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
            self.estado_cambiado.emit(
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
                    self.confirmar_pith_solicitado.emit()
                except Exception:
                    pass
                return
            if event.key() == Qt.Key.Key_Escape:
                self._limpiar_items_pith()
                try:
                    self._cambiar_modo_usuario(ModoMedicion.MEDIR)
                    self.estado_cambiado.emit("Estimación cancelada.")
                except Exception:
                    pass
                return
        if self.modo_actual == ModoMedicion.ESPACIO:
            if event.key() == Qt.Key.Key_Escape:
                self._idx_espacio_inicio = None
                self._limpiar_espacio()
                try:
                    self.estado_cambiado.emit("↔ Selección de espacio cancelada.")
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
                    self._cambiar_modo_usuario(ModoMedicion.MEDIR)
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
                self.estado_cambiado.emit(
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
                self.origen_calibracion_cambiado.emit("regla")
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
            self.guardado_solicitado.emit()
            # Actualizar la etiqueta de la línea con los mm calibrados así
            # el usuario tiene un recordatorio visual de que la imagen
            # ya está calibrada y a qué escala.
            self._actualizar_etiqueta_calibracion(dist_px, dist_mm)
        else:
            # Si canceló el diálogo, limpiar las marcas (no hubo calibración)
            self._limpiar_items_calibracion()

        self._objetivo_calibracion_mm = None
        self._cambiar_modo_usuario(ModoMedicion.MEDIR)
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
            self._cambiar_modo_usuario(ModoMedicion.MEDIR)

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
        if self.modo_actual == ModoMedicion.PITH and self._herramienta_pith.esperando_curvatura:
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
        self.autodeteccion_solicitada.emit(p1, p2, self._imagen_bgr, self._idx_ancla_autodetect)

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
        self._render.cargar_caminos_inactivos(caminos, self.pixeles_por_mm, self._pen_salto)

    def eliminar_camino_inactivo(self, nombre):
        self._render.eliminar_inactivo(nombre)

    def toggle_camino_inactivo(self, nombre: str, visible: bool):
        self._render.toggle_inactivo(nombre, visible)

    def cargar_camino_activo(self, coordenadas: list, es_salto: list, *, redibujar=True):
        self.modelo_medicion.cargar(coordenadas, es_salto)
        if redibujar:
            self.redibujar_todo()


"""
modulo_medicion.py — Módulo de medición interactiva de anillos de árboles.

Contiene:
  - ExportadorDendro: escritura de archivos Tucson, CSV y Excel.
  - VistaInteractiva: lienzo con herramientas de marcado, calibración y edición.
  - PestanaImagen: pestaña completa por imagen con panel de co-datación en vivo.
"""

import os
import math
from modulo_calculo_medicion import anchos_puntos
import json
import logging
from modulo_datos_medicion import (mediciones_desde_anchos, mediciones_radio,
                                   normalizar_radio)
from modulo_sesion_medicion import guardar_sesion, leer_sesion

import cv2
import numpy as np
from modulo_dialogos_archivo import ultima_carpeta
import modulo_transformacion as _tr
from modulo_grafico_medicion import (correlacion_deslizante, correlacion_global,
                                     transformar_medicion)
from modulo_modelo_medicion import ModeloMedicion, PuntoMedicion, RadioMedicion
import pandas as pd
import pyqtgraph as pg
from PIL import Image
from modulo_imagen import detectar_dpi
from modulo_formatos import (leer_archivo_tucson, leer_wid, leer_dendro_auto,
                             leer_pos, escribir_pos,
                             _escribir_excel, _asegurar_extension,
                             _exportar_tabular, _exportar_tucson_ewlw, _escribir_tucson)

from PyQt6.QtWidgets import (
    QApplication, QGraphicsScene, QGraphicsPixmapItem, QFileDialog,
    QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QInputDialog, QMessageBox, QSpinBox,
    QComboBox, QButtonGroup, QLineEdit, QListWidget,
    QSplitter, QListWidgetItem, QDialog,
)
from PyQt6.QtGui import QImage, QPixmap, QPen, QColor, QBrush, QShortcut, QKeySequence
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSettings, QSignalBlocker

from estilos import SECUNDARIO_QSS, color_secundario
import json_seguro as _js
import estilos_graficos as _gr
from modulo_autodeteccion import (
    cargar_perfiles, guardar_perfiles,
    extraer_perfil, detectar_limites, posiciones_a_coordenadas,
    DialogoEspecie, DialogoPreviewDeteccion,
)
from modulo_intensidad import (
    extraer_intensidad_por_anillo,
    escribir_rwl_intensidad,
    DialogoConfigBI,
    DialogoGuardarBI,
)
from modulo_pith import (
    MODO_PITH,
    ajustar_circulo_minimos_cuadrados,
    estimar_anillos_faltantes,
    DialogoMetodoPith,
    DialogoEstimacionPith,
)
from constantes import (
    DPI_DEFECTO, MM_POR_PULGADA, PIXELES_POR_MM_DEFECTO, MAX_PASOS_HISTORIAL,
    TOLERANCIA_CLICK_PUNTO, TOLERANCIA_CLICK_SEGMENTO, TUCSON_MAX_CHARS_ID, TUCSON_VALOR_FIN,
    INTERVALO_MARCADOR_DECADA, INTERVALO_MARCADOR_CINCUENTENA, INTERVALO_MARCADOR_CENTENA, COLOR_PUNTO_ACTIVO,
    COLOR_LINEA_ACTIVA, COLOR_SALTO, COLOR_GUIA, COLOR_CALIBRACION,
    COLOR_PUNTO_INACTIVO, COLOR_EWLW, COLORES_SERIES_INACTIVAS, TIPOS_ANOMALIA,
)

logger = logging.getLogger(__name__)

# Modos de interacción del lienzo


# =============================================================================
# UTILIDADES DE es_salto
# =============================================================================
# es_salto[i] puede ser:
#   False        → límite de anillo normal (tick rojo, cuenta y cierra anillo)
#   True         → salto (tick amarillo, rompe la cuenta de anillos)
#   "espacio"    → tramo del quiebre intra-anillo (amarillo, NO suma, NO cierra)
#   "quiebre_ini"→ inicio de quiebre (azul, SUMA distancia, NO cierra anillo)
#   "ew_lw"      → límite earlywood/latewood (suma, NO cierra)


# =============================================================================
# EXPORTADOR
# =============================================================================

from modulo_marcas_medicion import (
    _es_salto_real,
    _es_espacio,
    _es_quiebre_ini,
    _es_ewlw,
    _es_amarillo,
    MODO_ANADIR,
    MODO_MEDIR,
    MODO_CALIBRAR,
    MODO_MOVER,
    MODO_SALTO,
    MODO_INSERTAR,
    MODO_BORRAR,
    MODO_AUTODETECT,
    MODO_ANOMALIA,
    MODO_PITH,
    MODO_ESPACIO,
    MODO_EWLW,
    MODO_SELECCIONAR,
)

from modulo_ewlw import (
    _calcular_ewlw_posiciones,
    _calcular_ewlw_posiciones_cancelable,
    _calcular_anchos_ewlw_por_anillo,
)

from modulo_vista_medicion import (
    VistaSplitView,
    PanelSplit,
    DialogoCalibracionRegla,
    VistaInteractiva,
)

from modulo_worker_medicion import (
    _WorkerSignals,
    _Worker,
    _DialogoProgreso,
)


class ExportadorDendro:
    """Gestiona la exportación de mediciones a Tucson, CSV y Excel."""

    def __init__(self, ventana_padre: QWidget):
        self._parent = ventana_padre

    def exportar_datos(self, id_serie: str, lista_mediciones: list[dict],
                        anchos_ewlw: list | None = None):
        """Exporta mediciones a Tucson, CSV o Excel.

        Parameters
        ----------
        id_serie : str
            Identificador de la serie (código).
        lista_mediciones : list[dict]
            Lista de dicts {anio, ancho_mm} con las mediciones totales por anillo.
        anchos_ewlw : list[tuple], opcional
            Lista paralela de (total_mm, ew_mm, lw_mm) para anillos con
            límite EW/LW detectado. None en ew_mm/lw_mm si el anillo no
            tiene split. Si se provee y al menos un anillo tiene split,
            la exportación a CSV/Excel agregará columnas EW_mm y LW_mm.
            Para formato Tucson, ofrece exportar archivos separados
            (codigo.rwl + codigo_EW.rwl + codigo_LW.rwl).
        """
        if not lista_mediciones:
            return QMessageBox.warning(self._parent, "Error", "No hay mediciones para exportar.")

        orden = sorted(range(len(lista_mediciones)), key=lambda i: lista_mediciones[i]["anio"])
        datos = [lista_mediciones[i] for i in orden]
        if anchos_ewlw is not None and len(anchos_ewlw) == len(datos):
            anchos_ewlw = [anchos_ewlw[i] for i in orden]
        anios = [d["anio"] for d in datos]
        anchos = [d["ancho_mm"] for d in datos]

        # Detectar si hay info EW/LW útil para incluir
        tiene_ewlw = False
        if anchos_ewlw and len(anchos_ewlw) == len(datos):
            tiene_ewlw = any(ew is not None and lw is not None
                             for (_, ew, lw) in anchos_ewlw)

        # Obtener última carpeta y armar la ruta sugerida
        carpeta = _ultima_carpeta()
        ruta_sugerida = os.path.join(carpeta, id_serie) if carpeta else id_serie

        ruta, fmt = QFileDialog.getSaveFileName(
            self._parent, "Guardar", ruta_sugerida,
            "Formato Tucson (*.txt *.rwl);;Excel (*.xlsx);;CSV (*.csv)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return

        ruta = _asegurar_extension(ruta, fmt)
        _ultima_carpeta(ruta)

        try:
            if "*.csv" in fmt:
                self._exportar_tabular(
                    id_serie, anios, anchos, ruta, "csv",
                    anchos_ewlw=anchos_ewlw if tiene_ewlw else None
                )
            elif "*.xlsx" in fmt:
                self._exportar_tabular(
                    id_serie, anios, anchos, ruta, "xlsx",
                    anchos_ewlw=anchos_ewlw if tiene_ewlw else None
                )
            else:
                mediciones_int = [int(round(m * 1000)) for m in anchos]
                self._escribir_tucson(id_serie, anios[0], mediciones_int, ruta, anios=anios)

                # Si hay EW/LW, ofrecer exportar archivos separados
                # (convención CooRecorder/Velmex: _EW.rwl y _LW.rwl).
                if tiene_ewlw:
                    resp = QMessageBox.question(
                        self._parent, "EW/LW detectado",
                        f"Se detectaron límites EW/LW en algunos anillos.\n\n"
                        f"¿Desea exportar también archivos Tucson separados\n"
                        f"para earlywood y latewood?\n\n"
                        f"Se crearán:\n"
                        f"  • {id_serie}_EW.rwl (earlywood)\n"
                        f"  • {id_serie}_LW.rwl (latewood)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if resp == QMessageBox.StandardButton.Yes:
                        self._exportar_tucson_ewlw(
                            id_serie, anios, anchos_ewlw, ruta
                        )

            QMessageBox.information(self._parent, "Éxito", f"Exportado a:\n{ruta}")
        except Exception as exc:
            logger.error("Error al exportar: %s", exc)
            QMessageBox.critical(self._parent, "Error", f"Fallo al exportar:\n{exc}")

    _exportar_tabular = staticmethod(_exportar_tabular)
    _exportar_tucson_ewlw = staticmethod(_exportar_tucson_ewlw)
    _escribir_tucson = staticmethod(_escribir_tucson)


def _ultima_carpeta(nueva_ruta: str | None = None) -> str:
    return ultima_carpeta("ultima_carpeta", nueva_ruta)


# =============================================================================
# PESTAÑA INDIVIDUAL POR IMAGEN
# =============================================================================

class PestanaImagen(QWidget):
    """
    Pestaña completa asociada a una imagen escaneada.
    Incluye el lienzo de marcado, la gestión de radios guardados,
    la co-datación en vivo y las funciones de importación/exportación.
    """
    # Emitida cada vez que médula, corteza o código cambian (incluso con blockSignals)
    metadatos_cambiados = pyqtSignal()

    def __init__(self, ruta_imagen: str, ventana_padre: QWidget):
        super().__init__()
        self._ventana_padre = ventana_padre
        self.ruta_imagen_actual = ruta_imagen
        # No escribir antes de comprobar si existe una sesión previa.
        self._sesion_protegida = ruta_imagen
        self.caminos_guardados: dict = {}
        self.serie_maestra: pd.DataFrame | None = None
        self.nombre_maestra: str = "Ninguna"
        self._exportador = ExportadorDendro(self)
        self.item_imagen = None
        # Imagen original para cambio de banda
        self._img_bgr_original: np.ndarray | None = None
        # Perfiles de especie para auto-detección
        self._perfiles_especie = cargar_perfiles()
        self._especie_activa: str = next(iter(self._perfiles_especie))
        # Estimación de médula
        self._pith_estimacion: dict | None = None
        self._pith_undo: dict | None = None
        # Blue/Red/Green Intensity
        self._bi_datos: list[dict] = []    # resultados por anillo
        self._bi_banda: int = 30           # banda de muestreo en px (estándar CooRecorder)
        self._bi_porcentaje: int = 100     # % del anillo a medir
        self._bi_alineacion: str = "centro"  # "ew" | "centro" | "lw"
        self._bi_canal_vis: str = "B"      # canal activo para visualización
        self._bi_canales: list[str] = ["B", "G", "R", "Gray"]
        self._bi_plot_items: dict = {}     # items del gráfico BI
        self._items_banda_bi: list = []    # marcadores de banda en la imagen
        self._pith_metodo: str = "arco"
        self._pith_n_int: int = 5
        self._pith_usar_ref: bool = False
        self._pith_dap_mm: float = 200.0
        self._pith_metodo_calculo: str = "rg"  # 'rg', 'bai', o 'promedio'

        # Origen del DPI actual. Posibles valores:
        #   "auto"     → detectado automáticamente desde metadata JFIF/EXIF/TIFF
        #   "manual"   → cambiado a mano por el usuario en el diálogo DPI
        #   "regla"    → calibrado midiendo una distancia conocida
        #   "default"  → no se detectó, se usa DPI_DEFECTO
        #   "guardado" → restaurado desde un estado/sesión guardada
        # Sirve para mostrar al usuario qué origen tiene el DPI con el que
        # está trabajando, sobre todo cuando lo cambia y vuelve a abrir el
        # diálogo (antes seguía diciendo "Detectado automáticamente" aun
        # después de un override manual, lo cual era confuso).
        self._dpi_modo: str = "default"

        self._construir_ui()
        self._cargar_imagen(ruta_imagen)

    # -------------------------------------------------------------------------
    # Construcción de la interfaz
    # -------------------------------------------------------------------------

    def _construir_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # ── Barra de herramientas colapsable ──
        self._panel_herramientas = QWidget()
        lh = QVBoxLayout(self._panel_herramientas)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(2)
        lh.addLayout(self._construir_barra_herramientas())

        self.label_estado = QLabel("Preparando imagen...")
        self.label_estado.setStyleSheet("font-size:12px; font-weight:bold; color:#5cb85c;")
        lh.addWidget(self.label_estado)

        layout.addWidget(self._panel_herramientas)

        # Botón colapsar barra de herramientas
        self._btn_toggle_barra = QPushButton("🔼 Herramientas")
        self._btn_toggle_barra.setFixedHeight(18)
        self._btn_toggle_barra.setStyleSheet(
            "QPushButton{font-size:10px; padding:0px 6px; border:none; "
            f"color:{SECUNDARIO_QSS}; background:transparent;}}"
            "QPushButton:hover{color:white; background:#555;}"
        )
        self._btn_toggle_barra.setToolTip("Mostrar/ocultar barra de herramientas (Ctrl+H)")
        self._btn_toggle_barra.clicked.connect(self._toggle_barra)
        layout.addWidget(self._btn_toggle_barra)

        layout.addWidget(self._construir_splitter_principal())

        # Atajos de teclado para colapsar paneles
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self._toggle_barra)
        QShortcut(QKeySequence("Ctrl+G"), self).activated.connect(self._toggle_grafico)

        # Código de serie por defecto
        nombre_base = os.path.splitext(os.path.basename(self.ruta_imagen_actual))[0]
        self.input_codigo.setText(nombre_base.replace(" ", "")[:TUCSON_MAX_CHARS_ID].upper())

    def _toggle_barra(self):
        """Muestra/oculta la barra de herramientas."""
        visible = self._panel_herramientas.isVisible()
        self._panel_herramientas.setVisible(not visible)
        # not visible = nuevo estado: True=ahora visible, False=ahora oculto
        self._btn_toggle_barra.setText(
            "🔼 Herramientas" if not visible else "🔽 Herramientas"
        )

    def _toggle_grafico(self):
        """Muestra/oculta el panel del gráfico."""
        visible = self._panel_codatacion.isVisible()
        self._panel_codatacion.setVisible(not visible)
        self._btn_toggle_grafico.setText(
            "🔼 Gráfico" if not visible else "🔽 Gráfico"
        )

    def _toggle_split_view(self):
        """Activa o desactiva la vista dividida."""
        es_visible = self.panel_split.isVisible()
        if es_visible:
            self.panel_split.hide()
            self._btn_split.setChecked(False)
        else:
            # Refrescar lista de imágenes y abrir
            self.panel_split.refrescar_combo()
            self.panel_split.show()
            self.panel_split._sincronizar_con_principal()
            # Ajustar splitter 50/50
            total = self._splitter_vistas.width()
            self._splitter_vistas.setSizes([total // 2, total // 2])
            self._btn_split.setChecked(True)

    # ── Popup helpers ─────────────────────────────────────────────────────

    def _crear_popup(self) -> QWidget:
        """Crea un QWidget flotante estilizado para usar como dropdown."""
        popup = QWidget(self, Qt.WindowType.Popup)
        popup.setStyleSheet(
            "QWidget{background-color:#333; border:1px solid #555; "
            "border-radius:6px; color:white;}"
            "QPushButton{background-color:#4a4a4a; color:white; "
            "padding:5px 10px; border-radius:3px; min-width:60px;}"
            "QPushButton:hover{background-color:#5a5a5a;}"
            "QPushButton:checked{background-color:#5cb85c; color:white; font-weight:bold;}"
            "QLabel{color:#ccc; font-size:11px; background:transparent;}"
            "QComboBox{background-color:#4a4a4a; color:white; padding:4px; border:1px solid #666;}"
            "QSlider::groove:horizontal{background:#555; height:6px; border-radius:3px;}"
            "QSlider::handle:horizontal{background:#FF8C00; width:14px; height:14px; "
            "border-radius:7px; margin:-4px 0;}"
        )
        return popup

    def _crear_separador(self) -> QWidget:
        """Crea una línea horizontal estilizada para separar secciones."""
        from PyQt6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame{color:#555; background:#555; max-height:1px;}")
        return sep

    def _toggle_popup(self, popup: QWidget):
        """Muestra u oculta un popup debajo de su botón padre."""
        if popup.isVisible():
            popup.hide()
            return
        # Cerrar el otro popup si está abierto
        for p in [self._popup_herram, self._popup_imagen, self._popup_ewlw]:
            if p is not popup and p.isVisible():
                p.hide()
        # Posicionar debajo del botón que lo activó
        btn = (self._btn_herram if popup is self._popup_herram
               else self._btn_imagen if popup is self._popup_imagen
               else self._btn_ewlw_dd)
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        popup.move(pos)
        popup.show()

    def _construir_barra_herramientas(self) -> QHBoxLayout:
        barra = QHBoxLayout()
        barra.setSpacing(3)

        # ══════════════════════════════════════════════════════════════════
        # SIEMPRE VISIBLES: botones de medición + edición
        # ══════════════════════════════════════════════════════════════════
        self.grupo_modos = QButtonGroup(self)
        self._botones_modo = {}

        _btn_colores = {
            MODO_MEDIR:    ("#2ecc71", "#27ae60"),  # verde
            MODO_SALTO:    ("#f39c12", "#d68910"),  # ámbar
            MODO_ESPACIO:  ("#9b59b6", "#8e44ad"),  # púrpura
            MODO_INSERTAR: ("#3498db", "#2980b9"),  # azul
            MODO_MOVER:    ("#1abc9c", "#16a085"),  # turquesa
            MODO_BORRAR:   ("#e74c3c", "#c0392b"),  # rojo
            MODO_SELECCIONAR: ("#FFEB3B", "#FBC02D"),  # amarillo
        }

        botones_visibles = [
            ("📍 Medir",       MODO_MEDIR,        "Ctrl+A", "Clic izq: añadir anillo · Clic der: salto · Scroll: zoom"),
            ("🎯 Seleccionar", MODO_SELECCIONAR,  "Ctrl+R", "Seleccionar múltiples anillos para borrar / convertir a salto / quiebre"),
            ("🔀 Salto",       MODO_SALTO,        "Ctrl+D", "Añadir salto (discontinuidad)"),
            ("⊘ Quiebre",      MODO_ESPACIO,      "Ctrl+E", "Marcar quiebre intra-anillo\nNo cuenta como anillo"),
            ("➕ Insertar",     MODO_INSERTAR,     "Ctrl+W", "Insertar punto en segmento existente"),
            ("🖐 Mover",        MODO_MOVER,        "Ctrl+S", "Mover punto"),
            ("✕ Borrar",       MODO_BORRAR,       "Ctrl+X", "Borrar punto con clic"),
        ]
        for texto, modo, atajo, tooltip in botones_visibles:
            bg, bg_hover = _btn_colores[modo]
            btn = QPushButton(texto)
            btn.setCheckable(True)
            # MODO_SELECCIONAR usa color amarillo claro: el texto blanco no
            # contrasta bien, así que aplicamos texto NEGRO en lugar de blanco.
            color_texto = "#222" if modo == MODO_SELECCIONAR else "white"
            btn.setStyleSheet(
                f"QPushButton{{background-color:{bg}; color:{color_texto}; font-weight:bold; "
                f"padding:4px 10px; border-radius:4px;}}"
                f"QPushButton:hover{{background-color:{bg_hover};}}"
                f"QPushButton:checked{{background-color:#fff; color:{bg}; "
                f"border:2px solid {bg};}}"
            )
            btn.setToolTip(f"{tooltip} ({atajo})")
            btn.clicked.connect(lambda checked, m=modo: self.set_modo(m))
            self.grupo_modos.addButton(btn)
            self._botones_modo[modo] = btn
            barra.addWidget(btn)
            QShortcut(QKeySequence(atajo), self).activated.connect(lambda m=modo: self.set_modo(m))
        self._botones_modo[MODO_MEDIR].setChecked(True)

        barra.addSpacing(6)

        # ══════════════════════════════════════════════════════════════════
        # 🍂 EW/LW (dropdown)
        # ══════════════════════════════════════════════════════════════════
        self._btn_ewlw_dd = QPushButton("🍂 EW/LW ▾")
        self._btn_ewlw_dd.setStyleSheet(
            "QPushButton{background-color:#FF8C00; color:white; font-weight:bold; "
            "padding:4px 10px; border-radius:4px;}"
            "QPushButton:hover{background-color:#e67e22;}"
        )
        self._btn_ewlw_dd.setToolTip("Herramientas Earlywood / Latewood")
        self._btn_ewlw_dd.clicked.connect(lambda: self._toggle_popup(self._popup_ewlw))
        barra.addWidget(self._btn_ewlw_dd)

        self._popup_ewlw = self._crear_popup()
        pe_layout = QVBoxLayout(self._popup_ewlw)
        pe_layout.setContentsMargins(8, 8, 8, 8)
        pe_layout.setSpacing(4)

        btn_ewlw_marcar = QPushButton("🍂 Marcar EW/LW")
        btn_ewlw_marcar.setCheckable(True)
        btn_ewlw_marcar.setToolTip("Marcar límite Earlywood/Latewood (Ctrl+L)")
        btn_ewlw_marcar.clicked.connect(
            lambda: (self.set_modo(MODO_EWLW), self._popup_ewlw.hide()))
        self.grupo_modos.addButton(btn_ewlw_marcar)
        self._botones_modo[MODO_EWLW] = btn_ewlw_marcar
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
            lambda: self.set_modo(MODO_EWLW))
        pe_layout.addWidget(btn_ewlw_marcar)

        self.btn_ewlw_auto = QPushButton("🔍 Auto-detectar EW/LW")
        self.btn_ewlw_auto.setToolTip("Detectar automáticamente EW/LW en cada anillo")
        self.btn_ewlw_auto.setStyleSheet(
            "QPushButton{background-color:#FF8C00; color:white; font-weight:bold;}")
        self.btn_ewlw_auto.clicked.connect(
            lambda: (self._detectar_ewlw_automatico(), self._popup_ewlw.hide()))
        pe_layout.addWidget(self.btn_ewlw_auto)

        self.btn_ewlw_eliminar = QPushButton("🗑 Eliminar todos EW/LW")
        self.btn_ewlw_eliminar.setToolTip("Eliminar todos los límites EW/LW del radio activo")
        self.btn_ewlw_eliminar.setStyleSheet(
            "QPushButton{background-color:#8B0000; color:white;}")
        self.btn_ewlw_eliminar.clicked.connect(
            lambda: (self._eliminar_ewlw(), self._popup_ewlw.hide()))
        pe_layout.addWidget(self.btn_ewlw_eliminar)

        # ══════════════════════════════════════════════════════════════════
        # 🔧 HERRAMIENTAS (dropdown)
        # ══════════════════════════════════════════════════════════════════
        self._btn_herram = QPushButton("🔧 Herramientas ▾")
        self._btn_herram.setStyleSheet(
            "QPushButton{background-color:#555; color:white; font-weight:bold; "
            "padding:4px 10px; border-radius:4px;}"
            "QPushButton:hover{background-color:#666;}"
        )
        self._btn_herram.setToolTip("Deshacer, anomalías, estimación, calibración")
        self._btn_herram.clicked.connect(lambda: self._toggle_popup(self._popup_herram))
        barra.addWidget(self._btn_herram)

        self._popup_herram = self._crear_popup()
        ph_layout = QVBoxLayout(self._popup_herram)
        ph_layout.setContentsMargins(8, 8, 8, 8)
        ph_layout.setSpacing(4)

        fila_undo = QHBoxLayout()
        self.btn_deshacer = QPushButton("⏪ Deshacer")
        self.btn_deshacer.setStyleSheet("background-color:#d9534f; color:white;")
        self.btn_deshacer.setToolTip("Deshacer (Ctrl+Z)")
        self.btn_deshacer.clicked.connect(self._deshacer)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._deshacer)
        fila_undo.addWidget(self.btn_deshacer)
        self.btn_rehacer = QPushButton("Rehacer ⏩")
        self.btn_rehacer.setStyleSheet("background-color:#5bc0de; color:white;")
        self.btn_rehacer.setToolTip("Rehacer (Ctrl+Y)")
        self.btn_rehacer.clicked.connect(self._rehacer)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self._rehacer)
        fila_undo.addWidget(self.btn_rehacer)
        ph_layout.addLayout(fila_undo)
        ph_layout.addWidget(self._crear_separador())

        fila_anom = QHBoxLayout()
        self.btn_anomalia = QPushButton("🔴 Anomalías")
        self.btn_anomalia.setCheckable(True)
        self.btn_anomalia.setToolTip("Modo anomalías (Ctrl+Q)")
        self.btn_anomalia.clicked.connect(
            lambda: (self.set_modo(MODO_ANOMALIA), self._popup_herram.hide()))
        self.grupo_modos.addButton(self.btn_anomalia)
        self._botones_modo[MODO_ANOMALIA] = self.btn_anomalia
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(
            lambda: self.set_modo(MODO_ANOMALIA))
        fila_anom.addWidget(self.btn_anomalia)
        self.combo_tipo_anomalia = QComboBox()
        self.combo_tipo_anomalia.setToolTip("Tipo de anomalía a marcar")
        self.combo_tipo_anomalia.setMinimumWidth(140)
        for tipo, (icono, etiqueta, color) in TIPOS_ANOMALIA.items():
            self.combo_tipo_anomalia.addItem(f"{icono} {etiqueta}", userData=tipo)
        fila_anom.addWidget(self.combo_tipo_anomalia)
        ph_layout.addLayout(fila_anom)
        ph_layout.addWidget(self._crear_separador())

        fila_pith = QHBoxLayout()
        self.btn_pith = QPushButton("🎯 Anillos al centro")
        self.btn_pith.setCheckable(True)
        self.btn_pith.setToolTip("Estimar anillos faltantes (Ctrl+P)")
        self.btn_pith.setStyleSheet(
            "QPushButton{background-color:#8B4513; color:white; font-weight:bold;}"
            "QPushButton:checked{background-color:#FF8C00; color:white;}")
        self.btn_pith.clicked.connect(
            lambda: (self._iniciar_estimacion_pith(), self._popup_herram.hide()))
        self.grupo_modos.addButton(self.btn_pith)
        self._botones_modo[MODO_PITH] = self.btn_pith
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._iniciar_estimacion_pith)
        fila_pith.addWidget(self.btn_pith)
        self.btn_deshacer_pith = QPushButton("↩ Deshacer estimación")
        self.btn_deshacer_pith.setStyleSheet(
            "QPushButton{background-color:#d9534f; color:white; font-weight:bold;}")
        self.btn_deshacer_pith.clicked.connect(self._deshacer_pith_offset)
        self.btn_deshacer_pith.hide()
        fila_pith.addWidget(self.btn_deshacer_pith)
        ph_layout.addLayout(fila_pith)
        ph_layout.addWidget(self._crear_separador())

        fila_cal = QHBoxLayout()
        self.btn_calibrar_dpi = QPushButton("📐 DPI")
        self.btn_calibrar_dpi.setToolTip("Información de imagen y configuración de DPI")
        self.btn_calibrar_dpi.clicked.connect(
            lambda: (self._calibrar_por_dpi(), self._popup_herram.hide()))
        fila_cal.addWidget(self.btn_calibrar_dpi)
        self.btn_calibrar = QPushButton("📏 Regla")
        self.btn_calibrar.setToolTip("Calibrar midiendo una distancia conocida")
        self.btn_calibrar.clicked.connect(
            lambda: (self._activar_calibracion(), self._popup_herram.hide()))
        fila_cal.addWidget(self.btn_calibrar)
        ph_layout.addLayout(fila_cal)

        # ══════════════════════════════════════════════════════════════════
        # 🎨 COLORES (dropdown)
        # ══════════════════════════════════════════════════════════════════
        from PyQt6.QtWidgets import QSlider

        self._btn_imagen = QPushButton("🎨 Colores ▾")
        self._btn_imagen.setStyleSheet(
            "QPushButton{background-color:#555; color:white; font-weight:bold; "
            "padding:4px 10px; border-radius:4px;}"
            "QPushButton:hover{background-color:#666;}"
        )
        self._btn_imagen.setToolTip("Visualización por banda y brillo/contraste")
        self._btn_imagen.clicked.connect(lambda: self._toggle_popup(self._popup_imagen))
        barra.addWidget(self._btn_imagen)

        self._popup_imagen = self._crear_popup()
        pi_layout = QVBoxLayout(self._popup_imagen)
        pi_layout.setContentsMargins(8, 8, 8, 8)
        pi_layout.setSpacing(6)
        pi_layout.addWidget(QLabel("Canal de visualización:"))

        fila_banda = QHBoxLayout()
        self._grupo_banda = QButtonGroup(self)
        self._grupo_banda.setExclusive(True)
        self._banda_actual = "RGB"
        btn_estilo = (
            "QPushButton{min-width:40px; padding:4px 8px; font-weight:bold; "
            "border:1px solid #555; border-radius:3px; font-size:13px;}"
            "QPushButton:checked{border:2px solid #FFD700;}")
        for nombre_b, color_b, atajo_b in [
            ("RGB", "#aaa", "1"), ("R", "#FF4444", "2"),
            ("G", "#44CC44", "3"), ("B", "#4488FF", "4"), ("Gris", "#999", "5"),
        ]:
            btn_b = QPushButton(nombre_b)
            btn_b.setCheckable(True)
            btn_b.setFixedHeight(30)
            btn_b.setStyleSheet(
                btn_estilo + f"QPushButton{{color:{color_b};}}"
                f"QPushButton:checked{{color:{color_b}; background:rgba(255,255,255,15);}}")
            btn_b.setToolTip(f"Canal {nombre_b} (tecla {atajo_b})")
            btn_b.clicked.connect(lambda _, b=nombre_b: self._cambiar_banda(b))
            self._grupo_banda.addButton(btn_b)
            fila_banda.addWidget(btn_b)
            QShortcut(QKeySequence(atajo_b), self).activated.connect(
                lambda b=nombre_b: self._cambiar_banda(b))
            if nombre_b == "RGB":
                btn_b.setChecked(True)
        pi_layout.addLayout(fila_banda)
        pi_layout.addWidget(self._crear_separador())

        fila_brillo = QHBoxLayout()
        fila_brillo.addWidget(QLabel("☀ Brillo"))
        self._slider_brillo = QSlider(Qt.Orientation.Horizontal)
        self._slider_brillo.setRange(-100, 100)
        self._slider_brillo.setValue(0)
        self._slider_brillo.sliderReleased.connect(self._guardar_ajustes_banda)
        fila_brillo.addWidget(self._slider_brillo)
        pi_layout.addLayout(fila_brillo)

        fila_contraste = QHBoxLayout()
        fila_contraste.addWidget(QLabel("◐ Contraste"))
        self._slider_contraste = QSlider(Qt.Orientation.Horizontal)
        self._slider_contraste.setRange(50, 300)
        self._slider_contraste.setValue(100)
        self._slider_contraste.sliderReleased.connect(self._guardar_ajustes_banda)
        fila_contraste.addWidget(self._slider_contraste)
        pi_layout.addLayout(fila_contraste)

        self._timer_banda = QTimer()
        self._timer_banda.setSingleShot(True)
        self._timer_banda.setInterval(120)
        self._timer_banda.timeout.connect(self._aplicar_banda_actual)
        self._slider_brillo.valueChanged.connect(lambda: self._timer_banda.start())
        self._slider_contraste.valueChanged.connect(lambda: self._timer_banda.start())
        self._slider_brillo.mouseDoubleClickEvent = lambda e: self._slider_brillo.setValue(0)
        self._slider_contraste.mouseDoubleClickEvent = lambda e: self._slider_contraste.setValue(100)

        # ══════════════════════════════════════════════════════════════════
        # Vista dividida
        barra.addSpacing(6)
        self._btn_split = QPushButton("◫ Ventana")
        self._btn_split.setCheckable(True)
        self._btn_split.setStyleSheet(
            "QPushButton{background-color:#555; color:white; font-weight:bold; "
            "padding:4px 10px; border-radius:4px;}"
            "QPushButton:hover{background-color:#666;}"
            "QPushButton:checked{background-color:#FF8C00; color:white;}"
        )
        self._btn_split.setToolTip(
            "Ventana auxiliar: muestra la misma imagen (u otra de las pestañas\n"
            "abiertas) en un panel con zoom y posición independientes.\n"
            "Útil para comparar zonas distantes o dos muestras a la vez. (Ctrl+B)")
        self._btn_split.clicked.connect(self._toggle_split_view)
        barra.addWidget(self._btn_split)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._toggle_split_view)

        # ══════════════════════════════════════════════════════════════════
        barra.addStretch()

        self.btn_importar_pos = QPushButton("📥 Cargar .pos")
        self.btn_importar_pos.setStyleSheet(
            "background-color:#5bc0de; color:white; font-weight:bold; padding:4px 8px;")
        self.btn_importar_pos.setToolTip("Importar archivo CooRecorder .pos")
        self.btn_importar_pos.clicked.connect(self._importar_pos)
        barra.addWidget(self.btn_importar_pos)

        # Metadatos ocultos (lógica interna, visualmente en main.py)
        self.input_codigo = QLineEdit()
        self.input_codigo.setMaxLength(TUCSON_MAX_CHARS_ID)
        self.input_codigo.hide()

        self.combo_dir = QComboBox()
        self.combo_dir.addItems(["Médula→Corteza (+1)", "Corteza→Médula (-1)"])
        self.combo_dir.currentIndexChanged.connect(self._al_cambiar_direccion)
        self.combo_dir.hide()

        self.spin_medula = QSpinBox()
        self.spin_medula.setRange(-10000, 5000)
        self.spin_medula.valueChanged.connect(self._aplicar_anio_medula)
        self.spin_medula.hide()

        self.spin_corteza = QSpinBox()
        self.spin_corteza.setRange(-10000, 5000)
        self.spin_corteza.valueChanged.connect(self._aplicar_anio_corteza)
        self.spin_corteza.hide()

        from PyQt6.QtWidgets import QCheckBox
        self.check_tiene_medula = QCheckBox()
        self.check_tiene_medula.setToolTip("¿La serie llega físicamente a la médula?")
        self.check_tiene_medula.hide()

        self.check_tiene_corteza = QCheckBox()
        self.check_tiene_corteza.setToolTip("¿La serie llega físicamente a la corteza?")
        self.check_tiene_corteza.hide()

        # ── Auto-detección: combo especie + botón (se construyen aquí,
        #    pero se EXPONEN mediante métodos para que main_anillos los mueva
        #    a la barra superior si lo desea) ──────────────────────────────
        self.combo_especie = QComboBox()
        self.combo_especie.setToolTip("Especie activa para la auto-detección")
        self.combo_especie.setMinimumWidth(130)
        self._refrescar_combo_especie()
        self.combo_especie.currentTextChanged.connect(self._al_cambiar_especie)
        self.combo_especie.hide()   # Se agrega desde main_anillos a barra_top

        self.btn_cfg_especie = QPushButton("⚙")
        self.btn_cfg_especie.setToolTip("Configurar parámetros de detección para esta especie")
        self.btn_cfg_especie.setFixedWidth(28)
        self.btn_cfg_especie.clicked.connect(self._configurar_especie)
        self.btn_cfg_especie.hide()

        self.btn_nueva_especie = QPushButton("＋")
        self.btn_nueva_especie.setToolTip("Crear nuevo perfil de especie")
        self.btn_nueva_especie.setFixedWidth(28)
        self.btn_nueva_especie.clicked.connect(self._nueva_especie)
        self.btn_nueva_especie.hide()

        self.btn_autodetect = QPushButton("🔍 Auto-detectar")
        self.btn_autodetect.setCheckable(True)
        self.btn_autodetect.setStyleSheet(
            "QPushButton{background-color:#5cb85c; color:white; font-weight:bold;}"
            "QPushButton:checked{background-color:#f0ad4e; color:white;}"
        )
        self.btn_autodetect.setToolTip(
            "Activa el modo auto-detección.\n"
            "Clic 1: médula   Clic 2: corteza\n"
            "El programa detecta todos los anillos automáticamente."
        )
        self.btn_autodetect.clicked.connect(self._toggle_autodetect)
        self.grupo_modos.addButton(self.btn_autodetect)
        self._botones_modo[MODO_AUTODETECT] = self.btn_autodetect
        self.btn_autodetect.hide()  # Se agrega desde main_anillos a barra_top

        self.btn_exportar = QPushButton("💾 Exp")
        self.btn_exportar.setToolTip(
            "Exportar la medición (Tucson / Excel / CSV / .pos CooRecorder)")
        self.btn_exportar.clicked.connect(self._ejecutar_exportacion)
        barra.addWidget(self.btn_exportar)

        self.btn_exportar_anom = QPushButton("🔖 Anom")
        self.btn_exportar_anom.setToolTip(
            "Exportar las anomalías a un archivo separado (CSV/TSV) para "
            "manejarlas en R u otros programas")
        self.btn_exportar_anom.clicked.connect(self._exportar_anomalias)
        barra.addWidget(self.btn_exportar_anom)

        return barra

    def _construir_splitter_principal(self) -> QWidget:
        contenedor = QWidget()
        layout_v = QVBoxLayout(contenedor)
        layout_v.setContentsMargins(0, 0, 0, 0)
        layout_v.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter_principal = splitter

        # -- Zona superior: imagen (+ vista dividida opcional) + lista de radios --
        splitter_sup = QSplitter(Qt.Orientation.Horizontal)

        # Splitter interno para vista principal + vista dividida
        self._splitter_vistas = QSplitter(Qt.Orientation.Horizontal)
        self.escena = QGraphicsScene()
        self.vista = VistaInteractiva(self.escena, self)
        self.vista.mediciones_actualizadas.connect(self._sincronizar_mediciones)
        self._timer_autoguardado = QTimer(self)
        self._timer_autoguardado.setSingleShot(True)
        self._timer_autoguardado.setInterval(350)
        self._timer_autoguardado.timeout.connect(self._guardar_estado)
        self.vista.progreso_modificado.connect(self._programar_guardado)
        self._splitter_vistas.addWidget(self.vista)

        # Vista secundaria (panel dividido, oculto por defecto)
        self.panel_split = PanelSplit(self.escena, self)
        self.panel_split.hide()
        self._splitter_vistas.addWidget(self.panel_split)

        splitter_sup.addWidget(self._splitter_vistas)
        splitter_sup.addWidget(self._construir_panel_radios())
        splitter_sup.setSizes([1000, 150])
        splitter.addWidget(splitter_sup)

        # -- Botón colapsar gráfico --
        self._btn_toggle_grafico = QPushButton("🔼 Gráfico")
        self._btn_toggle_grafico.setFixedHeight(18)
        self._btn_toggle_grafico.setStyleSheet(
            "QPushButton{font-size:10px; padding:0px 6px; border:none; "
            f"color:{SECUNDARIO_QSS}; background:transparent;}}"
            "QPushButton:hover{color:white; background:#555;}"
        )
        self._btn_toggle_grafico.setToolTip("Mostrar/ocultar panel de gráfico (Ctrl+G)")
        self._btn_toggle_grafico.clicked.connect(self._toggle_grafico)

        # -- Zona inferior: co-datación en vivo --
        self._panel_codatacion = self._construir_panel_codatacion()
        splitter.addWidget(self._panel_codatacion)
        splitter.setSizes([600, 200])
        splitter.setChildrenCollapsible(False)

        layout_v.addWidget(splitter)
        layout_v.addWidget(self._btn_toggle_grafico)
        return contenedor

    def _construir_panel_radios(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Radios Guardados:"))

        self.lista_caminos = QListWidget()
        self.lista_caminos.itemChanged.connect(self._toggle_visual_camino)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lista_caminos).activated.connect(self._eliminar_camino)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.lista_caminos).activated.connect(self._eliminar_camino)
        layout.addWidget(self.lista_caminos)

        btn_eliminar = QPushButton("🗑️ Eliminar")
        btn_eliminar.setStyleSheet("background-color:#d9534f; color:white;")
        btn_eliminar.clicked.connect(self._eliminar_camino)
        layout.addWidget(btn_eliminar)

        self.btn_editar_camino = QPushButton("✏️ Editar Radio")
        self.btn_editar_camino.setStyleSheet("background-color:#f0ad4e; color:white; font-weight:bold;")
        self.btn_editar_camino.clicked.connect(self._editar_camino)
        layout.addWidget(self.btn_editar_camino)

        self.btn_finalizar_camino = QPushButton("✅ Terminar Radio")
        self.btn_finalizar_camino.setStyleSheet("background-color:#5cb85c; color:white; font-weight:bold;")
        self.btn_finalizar_camino.clicked.connect(self._finalizar_camino)
        layout.addWidget(self.btn_finalizar_camino)

        return panel

    def _construir_panel_codatacion(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 5, 0, 0)

        # ── Fila de referencia + controles ───────────────────────────────
        fila_maestra = QHBoxLayout()
        fila_maestra.addWidget(QLabel("<b>Referencia:</b>"))
        self.btn_cargar_maestra = QPushButton("📂 Cargar referencia")
        self.btn_cargar_maestra.setToolTip(
            "Cargar serie o cronología de referencia.\n\n"
            "Acepta Tucson (.rwl, .txt), compacto, CooRecorder (.wid) y\n"
            "formatos de dos columnas (año + valor) en .txt, .csv, .xlsx\n"
            "y .ods — el mismo formato en que DPI exporta las cronologías.")
        self.btn_cargar_maestra.clicked.connect(self._cargar_serie_maestra)
        self.btn_cargar_wid = QPushButton("📂 .wid")
        self.btn_cargar_wid.setToolTip("Cargar cronología CooRecorder (.wid)")
        self.btn_cargar_wid.setStyleSheet(
            "background-color:#5bc0de; color:white; font-weight:bold;")
        self.btn_cargar_wid.clicked.connect(self._cargar_serie_wid)
        self.lbl_nombre_maestra = QLabel("Ninguna")
        self.lbl_nombre_maestra.setStyleSheet(f"color:{SECUNDARIO_QSS};")
        fila_maestra.addWidget(self.btn_cargar_maestra)
        fila_maestra.addWidget(self.btn_cargar_wid)
        fila_maestra.addWidget(self.lbl_nombre_maestra)

        # Botón para eliminar la maestra externa cargada
        self.btn_eliminar_maestra = QPushButton("🗑")
        self.btn_eliminar_maestra.setToolTip(
            "Eliminar la serie de referencia externa cargada")
        self.btn_eliminar_maestra.setFixedWidth(32)
        self.btn_eliminar_maestra.setStyleSheet(
            "QPushButton{background-color:#a94442; color:white; "
            "padding:2px; border-radius:3px; min-width:0px;}"
            "QPushButton:hover{background-color:#c9302c;}"
            "QPushButton:disabled{background-color:#555; color:#888;}"
        )
        self.btn_eliminar_maestra.clicked.connect(self._eliminar_serie_maestra)
        self.btn_eliminar_maestra.setEnabled(False)   # se habilita al cargar una
        fila_maestra.addWidget(self.btn_eliminar_maestra)

        # Combo selector de maestra propia
        fila_maestra.addSpacing(12)
        fila_maestra.addWidget(QLabel("Maestra:"))
        self.combo_maestra = QComboBox()
        self.combo_maestra.setToolTip(
            "Serie propia usada como referencia cuando no hay archivo externo cargado."
        )
        self.combo_maestra.setMinimumWidth(110)
        self.combo_maestra.currentIndexChanged.connect(self._actualizar_grafico_rt)
        fila_maestra.addWidget(self.combo_maestra)

        # Selector de ventana de correlación
        fila_maestra.addSpacing(12)
        fila_maestra.addWidget(QLabel("Ventana:"))
        self.spin_ventana_r = QSpinBox()
        self.spin_ventana_r.setRange(10, 100)
        self.spin_ventana_r.setSingleStep(5)
        self.spin_ventana_r.setValue(50)
        self.spin_ventana_r.setSuffix(" años")
        # Antes era 80px — muy angosto: el padding (4px) + borde (1px) + las
        # flechas de incremento (~16px) consumían casi todo el espacio y las
        # flechas quedaban recortadas/invisibles. 110px deja espacio cómodo.
        self.spin_ventana_r.setFixedWidth(110)
        self.spin_ventana_r.setToolTip(
            "Ventana máxima de correlación deslizante.\n"
            "Mientras la serie tenga menos años, la ventana crece desde 10.\n"
            "El solapamiento entre ventanas es siempre la mitad (estilo COFECHA)."
        )
        self.spin_ventana_r.valueChanged.connect(self._actualizar_grafico_rt)
        fila_maestra.addWidget(self.spin_ventana_r)

        fila_maestra.addSpacing(12)
        fila_maestra.addWidget(QLabel("Correlación:"))
        # Selector de método. Antes esta pestaña usaba siempre diferencias-log
        # mientras que Co-Datación usaba el método de COFECHA, así que el mismo
        # par de series daba r distintas en cada pestaña sin aviso alguno.
        self.combo_metodo_corr = _tr.crear_selector(self, _tr.DIFFLOG)
        self.combo_metodo_corr.currentIndexChanged.connect(
            self._actualizar_grafico_rt)
        fila_maestra.addWidget(self.combo_metodo_corr)

        fila_maestra.addStretch()

        # Label de r total
        self.lbl_r_total = QLabel("")
        self.lbl_r_total.setStyleSheet("font-size:12px; font-weight:bold;")
        fila_maestra.addWidget(self.lbl_r_total)

        self.btn_calcular_bi = QPushButton("🎨 Calcular BI")
        self.btn_calcular_bi.setToolTip(
            "Calcular Blue, Green, Red y Gray Intensity por anillo.\n"
            "El resultado queda en memoria — usa 💾 Guardar BI para exportar."
        )
        self.btn_calcular_bi.setStyleSheet(
            "background-color:#5bc0de; color:white; font-weight:bold;"
        )
        self.btn_calcular_bi.clicked.connect(self._calcular_bi)
        fila_maestra.addWidget(self.btn_calcular_bi)

        self.btn_graficar_bi = QPushButton("📊 Graficar BI")
        self.btn_graficar_bi.setToolTip(
            "Abrir ventana con el gráfico de BI/GI/RI/GrayI por anillo.\n"
            "Tiene zoom y paneo independientes del gráfico de series."
        )
        self.btn_graficar_bi.setEnabled(False)
        self.btn_graficar_bi.clicked.connect(self._graficar_bi_ventana)
        fila_maestra.addWidget(self.btn_graficar_bi)

        self.btn_guardar_bi = QPushButton("💾 Guardar BI")
        self.btn_guardar_bi.setToolTip(
            "Guardar los valores de intensidad calculados como archivos .rwl.\n"
            "Elige qué canales y métricas exportar."
        )
        self.btn_guardar_bi.setEnabled(False)
        self.btn_guardar_bi.clicked.connect(self._guardar_bi)
        fila_maestra.addWidget(self.btn_guardar_bi)

        self._btn_cfg_bi = QPushButton("⚙")
        self._btn_cfg_bi.setFixedWidth(28)
        self._btn_cfg_bi.setToolTip("Configurar banda de muestreo y canales")
        self._btn_cfg_bi.clicked.connect(self._configurar_bi)
        fila_maestra.addWidget(self._btn_cfg_bi)

        self.btn_mostrar_banda = QPushButton("👁 Ver área BI")
        self.btn_mostrar_banda.setCheckable(True)
        self.btn_mostrar_banda.setToolTip(
            "Mostrar/ocultar el área de muestreo BI sobre la imagen.\n"
            "Dibuja el rectángulo azul que cubre cada anillo (igual que CooRecorder)."
        )
        self.btn_mostrar_banda.toggled.connect(self._toggle_banda_bi)
        fila_maestra.addWidget(self.btn_mostrar_banda)

        layout.addLayout(fila_maestra)

        # ── Gráfico de series ─────────────────────────────────────────────
        self.grafico_unif = pg.PlotWidget()
        _gr.aplicar_a_pyqtgraph(self.grafico_unif)
        self.grafico_unif.showGrid(x=True, y=True, alpha=0.3)
        self.grafico_unif.setLabel("bottom", "Año")
        self.grafico_unif.setLabel("left",   "Ancho (mm)")
        self._legend = self.grafico_unif.addLegend(offset=(10, 10))
        self._plot_items: dict[str, object] = {}
        self._series_ocultas: set[str] = set()
        self._legend.scene().sigMouseClicked.connect(self._clic_leyenda)
        layout.addWidget(self.grafico_unif)

        # Controles de zoom, los mismos de Co-Datación: zoom por área,
        # ensanchar/comprimir el eje X y ver todo. En series largas son
        # imprescindibles para poder mirar el detalle año a año.
        try:
            from modulo_widgets import _crear_barra_zoom
            layout.addWidget(_crear_barra_zoom(self.grafico_unif))
        except Exception as _e:
            print("No se pudo agregar la barra de zoom:", _e)

        # ── Crosshair interactivo: línea vertical + etiqueta de año ────────
        from pyqtgraph import InfiniteLine, TextItem, SignalProxy
        self._graf_vline = InfiniteLine(angle=90, movable=False,
                                         pen=pg.mkPen("#888", width=1,
                                                      style=Qt.PenStyle.DotLine))
        self._graf_vline.setZValue(60)
        self._graf_vline.setVisible(False)
        self.grafico_unif.addItem(self._graf_vline, ignoreBounds=True)

        self._graf_label = TextItem(anchor=(0.0, 1.0),
                                     fill=pg.mkBrush(0, 0, 0, 180),
                                     border=pg.mkPen("#888", width=1))
        self._graf_label.setZValue(61)
        self._graf_label.setVisible(False)
        self.grafico_unif.addItem(self._graf_label, ignoreBounds=True)

        # Marcador del punto más cercano
        self._graf_dot = self.grafico_unif.plot(
            [], [], pen=None, symbol='o', symbolSize=10,
            symbolBrush='#FFD700', symbolPen=pg.mkPen('#FFF', width=1.5))
        self._graf_dot.setZValue(62)

        # Proxy para throttle del mouse-move (cada 30ms)
        self._graf_proxy = SignalProxy(
            self.grafico_unif.scene().sigMouseMoved,
            rateLimit=33, slot=self._graf_mouse_moved)

        # Click en el gráfico → navegar a ese año en la imagen
        self.grafico_unif.scene().sigMouseClicked.connect(self._graf_mouse_clicked)

        # Item de resaltado en la imagen al hacer clic en el gráfico
        self._item_highlight_anio = None

        # ── Barra de correlaciones por ventana (texto enriquecido) ────────
        self.lbl_ventanas_r = QLabel("")
        self.lbl_ventanas_r.setWordWrap(True)
        self.lbl_ventanas_r.setStyleSheet(
            "font-size:11px; padding:3px 6px; "
            "background-color: rgba(0,0,0,30); border-radius:4px;"
        )
        self.lbl_ventanas_r.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.lbl_ventanas_r)

        # ── Atributos de estado ───────────────────────────────────────────
        self._colores_radios = [
            "#5cb85c", "#5bc0de", "#f0ad4e", "#d9534f",
            "#9b59b6", "#1abc9c", "#e67e22", "#3498db",
        ]

        return panel

    # -------------------------------------------------------------------------
    # Carga de imagen
    # -------------------------------------------------------------------------

    def _mostrar_aviso_dpi(self, titulo: str, texto: str):
        """Muestra un aviso de DPI NO modal y con autocierre.

        Crítico: NO usa QMessageBox.information() (que llama exec() y es
        modal). Un diálogo modal disparado por QTimer durante la carga de
        imágenes —que usa processEvents() y abre las siguientes en cola—
        anida un bucle de eventos que re-entra en la carga y CONGELA el
        programa al abrir varias imágenes a la vez.

        Este aviso:
          • Es no modal: se muestra con show() y no bloquea el bucle.
          • Se guarda en una lista para que el GC no lo elimine.
          • Se cierra solo a los 7 segundos (o cuando el usuario pulsa OK).
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(titulo)
        box.setText(texto)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setWindowModality(Qt.WindowModality.NonModal)

        if not hasattr(self, "_avisos_no_modales"):
            self._avisos_no_modales = []
        self._avisos_no_modales.append(box)
        box.finished.connect(
            lambda _=None, b=box: (
                self._avisos_no_modales.remove(b)
                if b in self._avisos_no_modales else None))

        box.show()
        # Autocierre no bloqueante. El timer se parenta al box para que
        # muera junto con él si el usuario lo cierra antes.
        timer = QTimer(box)
        timer.setSingleShot(True)
        timer.timeout.connect(box.close)
        timer.start(7000)

    def _cargar_imagen(self, ruta: str):
        import time
        t0 = time.perf_counter()
 
        dpi_detectado = self._detectar_dpi(ruta)
        if dpi_detectado and dpi_detectado > 0:
            self.vista.pixeles_por_mm = dpi_detectado / MM_POR_PULGADA
            self._dpi_modo = "auto"
            msg_escala = f"Resolución detectada: {dpi_detectado:.0f} DPI."
            # Aviso NO modal (ver _mostrar_aviso_dpi). Se difiere 800 ms para
            # que aparezca tras cargar la imagen. NUNCA usar un QMessageBox
            # modal aquí: al abrir varias imágenes en cola, el exec() modal
            # anida un bucle de eventos que re-entra en la carga de la
            # siguiente imagen y congela el programa.
            QTimer.singleShot(800, lambda d=dpi_detectado: self._mostrar_aviso_dpi(
                "Resolución detectada",
                f"Se detectaron automáticamente <b>{d:.0f} DPI</b> "
                f"desde los metadatos de la imagen.<br><br>"
                f"Si necesitas cambiar este valor, puedes hacerlo desde "
                f"<b>Herramientas → 📐 DPI</b>.",
            ))
        else:
            self.vista.pixeles_por_mm = PIXELES_POR_MM_DEFECTO
            self._dpi_modo = "default"
            msg_escala = f"DPI no detectado. Asumiendo {DPI_DEFECTO} DPI por defecto."
            QTimer.singleShot(500, lambda: self._mostrar_aviso_dpi(
                "Aviso de Resolución",
                f"No se detectaron DPI en los metadatos.<br><br>"
                f"Se usará <b>{DPI_DEFECTO} DPI</b> por defecto.<br><br>"
                f"Si conoces el DPI real del escáner, puedes configurarlo "
                f"desde <b>Herramientas → 📐 DPI</b>.",
            ))
 
        print("[CARGA] DPI detectado en %.2fs", time.perf_counter() - t0)
        t1 = time.perf_counter()
 
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            img_cv = cv2.imread(ruta)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.label_estado.setText(f"⚠ Error al leer la imagen: {exc}")
            return
 
        if img_cv is None:
            QApplication.restoreOverrideCursor()
            self.label_estado.setText("⚠ Error: no se pudo abrir la imagen.")
            return
 
        h, w = img_cv.shape[:2]
        mp = (w * h) / 1e6
        print("[CARGA] cv2.imread %dx%d (%.1f MP) en %.2fs",
                    w, h, mp, time.perf_counter() - t1)
        t2 = time.perf_counter()
 
        img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        QApplication.processEvents()
        print("[CARGA] cvtColor en %.2fs", time.perf_counter() - t2)
        t3 = time.perf_counter()
 
        q_img = QImage(img_rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        del img_rgb
        QApplication.processEvents()
        print("[CARGA] QImage en %.2fs", time.perf_counter() - t3)
        t4 = time.perf_counter()
 
        self.item_imagen = QGraphicsPixmapItem(QPixmap.fromImage(q_img))
        self.item_imagen.setTransformationMode(
            Qt.TransformationMode.FastTransformation
        )
        del q_img
        self.escena.addItem(self.item_imagen)
        self.escena.setSceneRect(0, 0, w, h)
        print("[CARGA] Pixmap + escena en %.2fs", time.perf_counter() - t4)
        t5 = time.perf_counter()
 
        self._img_bgr_original = img_cv
        QApplication.restoreOverrideCursor()
 
        restaurado = self._cargar_estado()
        if restaurado:
            self.label_estado.setText(
                f"Progreso restaurado. Escala: {self.vista.pixeles_por_mm * MM_POR_PULGADA:.0f} DPI."
            )
        elif self._sesion_protegida == self.ruta_imagen_actual:
            self.label_estado.setText("Sesión no restaurada: autoguardado desactivado.")
        else:
            self.label_estado.setText(f"Imagen lista. {msg_escala}")
 
        print("[CARGA] _cargar_estado en %.2fs", time.perf_counter() - t5)
        print("[CARGA] TOTAL: %.2fs para %.1f MP", time.perf_counter() - t0, mp)
 
        QTimer.singleShot(100, self._ajustar_zoom_inicial)
 
    _detectar_dpi = staticmethod(detectar_dpi)

    def _ajustar_zoom_inicial(self):
        if self.item_imagen:
            self.vista.fitInView(self.escena.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    # -------------------------------------------------------------------------
    # Visualización por banda (R, G, B, Gray)
    # -------------------------------------------------------------------------

    def _cambiar_banda(self, banda: str):
        """Cambia la banda activa y actualiza la imagen."""
        self._banda_actual = banda
        # Marcar el botón correcto
        for btn in self._grupo_banda.buttons():
            btn.setChecked(btn.text() == banda)
        # Cargar ajustes guardados para esta especie+banda
        self._cargar_ajustes_banda()
        self._aplicar_banda_actual()

    def _aplicar_banda_actual(self):
        """Reenderiza la imagen con la banda y ajustes de brillo/contraste actuales.

        Usa cv2.LUT (lookup table de 256 bytes) para aplicar brillo/contraste
        sin crear copias float32 de la imagen completa — crítico para imágenes
        de alta resolución (2400+ DPI) que pueden superar los 500 MB.
        """
        if self._img_bgr_original is None or self.item_imagen is None:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            img = self._img_bgr_original
            banda = self._banda_actual
            brillo = self._slider_brillo.value()
            contraste = self._slider_contraste.value() / 100.0

            # ── Construir LUT de 256 entradas (O(256), no O(pixeles)) ──
            lut = np.arange(256, dtype=np.float32)
            lut = contraste * lut + brillo
            lut = np.clip(lut, 0, 255).astype(np.uint8)

            sin_ajuste = (brillo == 0 and contraste == 1.0)

            # ── Extraer canal y aplicar ──
            if banda == "RGB":
                if sin_ajuste:
                    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                else:
                    rgb = cv2.LUT(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), lut)
            else:
                if banda == "R":
                    gray = img[:, :, 2]
                elif banda == "G":
                    gray = img[:, :, 1]
                elif banda == "B":
                    gray = img[:, :, 0]
                else:  # Gris
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                if not sin_ajuste:
                    gray = cv2.LUT(gray, lut)
                rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
                del gray

            QApplication.processEvents()

            h, w = rgb.shape[:2]
            rgb = np.ascontiguousarray(rgb)
            q_img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
            self.item_imagen.setPixmap(QPixmap.fromImage(q_img.copy()))
            del rgb
        finally:
            QApplication.restoreOverrideCursor()

    def _guardar_ajustes_banda(self):
        """Guarda brillo/contraste de la banda activa en el perfil de especie."""
        try:
            especie = self._especie_activa
            settings = QSettings("MoiCedrus", "DPI")
            key = f"banda/{especie}/{self._banda_actual}"
            settings.setValue(f"{key}/brillo", self._slider_brillo.value())
            settings.setValue(f"{key}/contraste", self._slider_contraste.value())
        except Exception:
            pass

    def _cargar_ajustes_banda(self):
        """Restaura brillo/contraste guardados para la especie+banda actual."""
        try:
            especie = self._especie_activa
            settings = QSettings("MoiCedrus", "DPI")
            key = f"banda/{especie}/{self._banda_actual}"
            brillo = settings.value(f"{key}/brillo", 0, type=int)
            contraste = settings.value(f"{key}/contraste", 100, type=int)
            self._slider_brillo.blockSignals(True)
            self._slider_contraste.blockSignals(True)
            self._slider_brillo.setValue(brillo)
            self._slider_contraste.setValue(contraste)
            self._slider_brillo.blockSignals(False)
            self._slider_contraste.blockSignals(False)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Modos de interacción
    # -------------------------------------------------------------------------

    def set_modo(self, modo: int):
        # Caso especial: si estamos en MODO_SELECCIONAR con selección
        # activa y el usuario hace clic en alguno de los botones de
        # acción de la barra (Borrar / Salto / Quiebre), se ejecuta la
        # operación en BULK sobre la selección en vez de cambiar el modo
        # — exactamente lo que pidió el usuario para evitar duplicar
        # botones en el panel flotante.
        if (self.vista.modo_actual == MODO_SELECCIONAR
                and self.vista._puntos_seleccionados):
            if modo == MODO_BORRAR:
                self.vista._ejecutar_borrar_seleccionados()
                modo = MODO_MEDIR  # tras la acción volver a MEDIR
            elif modo == MODO_SALTO:
                self.vista._ejecutar_convertir_a_salto()
                modo = MODO_MEDIR
            elif modo == MODO_ESPACIO:
                self.vista._ejecutar_convertir_a_quiebre()
                modo = MODO_MEDIR

        btn = self._botones_modo.get(modo)
        if btn:
            btn.setChecked(True)
        self.vista.cambiar_modo(modo)
        self.vista.setFocus()

    def _deshacer(self):
        self.vista.deshacer_ultimo()

    def _rehacer(self):
        self.vista.rehacer_ultimo()

    # -------------------------------------------------------------------------
    # Auto-detección de anillos por especie
    # -------------------------------------------------------------------------

    def _refrescar_combo_especie(self):
        self.combo_especie.blockSignals(True)
        self.combo_especie.clear()
        self.combo_especie.addItems(list(self._perfiles_especie.keys()))
        if self._especie_activa in self._perfiles_especie:
            self.combo_especie.setCurrentText(self._especie_activa)
        self.combo_especie.blockSignals(False)

    def _guardar_perfiles_especie(self):
        """Guarda los perfiles y AVISA si no se pudo.

        Antes el fallo se tragaba y solo quedaba en el registro: el usuario
        afinaba una especie, pulsaba guardar, no veía nada raro y al reiniciar
        el perfil no estaba. Si falla hay que decirlo, porque es trabajo suyo
        el que se pierde.
        """
        from modulo_autodeteccion import guardar_perfiles, RUTA_PERFILES
        try:
            guardar_perfiles(self._perfiles_especie)
        except Exception as exc:
            QMessageBox.warning(
                self, "No se pudo guardar el perfil de especie",
                f"El perfil quedó activo en esta sesión, pero no se pudo "
                f"escribir en disco, así que se perderá al cerrar DPI.\n\n"
                f"Archivo: {RUTA_PERFILES}\n{exc}")

    def _al_cambiar_especie(self, nombre: str):
        if nombre in self._perfiles_especie:
            self._especie_activa = nombre

    def _configurar_especie(self):
        """Abre el diálogo de configuración para la especie activa."""
        perfil = self._perfiles_especie.get(self._especie_activa, {})
        dlg = DialogoEspecie(self._especie_activa, perfil, self)
        if dlg.exec():
            self._perfiles_especie[self._especie_activa] = dlg.obtener_perfil()
            self._guardar_perfiles_especie()

    def _nueva_especie(self):
        """Crea un perfil de especie nuevo a partir del nombre que ingrese el usuario."""
        from modulo_autodeteccion import PERFIL_DEFECTO
        nombre, ok = QInputDialog.getText(self, "Nueva especie", "Nombre de la especie:")
        if not ok or not nombre.strip():
            return
        nombre = nombre.strip()
        if nombre in self._perfiles_especie:
            QMessageBox.warning(self, "Especie existente",
                                f'Ya existe un perfil para "{nombre}".')
            return
        self._perfiles_especie[nombre] = PERFIL_DEFECTO.copy()
        guardar_perfiles(self._perfiles_especie)
        self._especie_activa = nombre
        self._refrescar_combo_especie()
        # Abrir configuración inmediatamente
        self._configurar_especie()

    def _toggle_autodetect(self):
        """Activa/desactiva el modo auto-detección desde el botón."""
        if self.btn_autodetect.isChecked():
            # Cargar imagen BGR si aún no está cacheada
            img_bgr = cv2.imread(self.ruta_imagen_actual, cv2.IMREAD_COLOR)
            if img_bgr is None:
                QMessageBox.critical(self, "Error",
                                     "No se pudo leer la imagen para la detección.")
                self.btn_autodetect.setChecked(False)
                return
            self.vista.iniciar_autodetect(img_bgr)
            self.label_estado.setText(
                "🔍 Auto-detección: clic en la MÉDULA, luego en la CORTEZA."
            )
        else:
            self.vista.cambiar_modo(MODO_MEDIR)
            self._botones_modo[MODO_MEDIR].setChecked(True)
            self.label_estado.setText("Modo añadir activado.")

    def _ejecutar_autodeteccion(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        imagen_bgr: np.ndarray,
        idx_ancla: int | None = None,
    ):
        """
        Llamado por VistaInteractiva tras los 2 clics de auto-detección.
        Extrae el perfil entre p1 y p2, muestra preview y coloca los puntos.

        idx_ancla: índice del punto existente desde el que se continúa,
                   o None si la detección es sobre una zona vacía.
        """
        perfil = self._perfiles_especie.get(self._especie_activa, {})
        ppm    = self.vista.pixeles_por_mm

        dist, intens = extraer_perfil(
            imagen_bgr, p1, p2,
            canal=perfil.get("canal", "gray"),
            banda_px=perfil.get("banda_px", 5),
        )

        if len(dist) == 0:
            QMessageBox.warning(self, "Sin datos",
                                "No se pudo extraer el perfil de intensidad.")
            return

        dlg = DialogoPreviewDeteccion(dist, intens, perfil, ppm, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        banda_nueva = dlg.obtener_banda_final()
        if banda_nueva != perfil.get("banda_px", 5):
            perfil["banda_px"] = banda_nueva
            self._perfiles_especie[self._especie_activa] = perfil
            self._guardar_perfiles_especie()
            dist, intens = extraer_perfil(
                imagen_bgr, p1, p2,
                canal=perfil.get("canal", "gray"),
                banda_px=banda_nueva,
            )

        perfil["prominencia"] = dlg.obtener_prominencia_final()

        posiciones_px = detectar_limites(dist, intens, perfil)
        if len(posiciones_px) == 0:
            QMessageBox.information(self, "Sin detecciones",
                                    "No se detectaron límites de anillo.\n"
                                    "Prueba a reducir la prominencia mínima o\n"
                                    "verificar el canal y la polaridad de la especie.")
            return

        coordenadas = posiciones_a_coordenadas(posiciones_px, p1, p2)

        # Si hay ancla, verificar si hay puntos en el tramo y preguntar qué hacer
        reemplazar_tramo = False
        if idx_ancla is not None and len(self.vista.coordenadas_anillos) > 1:
            n_total = len(self.vista.coordenadas_anillos)
            # Hay puntos más allá del ancla?
            tiene_vecinos = (idx_ancla > 0 or idx_ancla < n_total - 1)
            if tiene_vecinos:
                resp = QMessageBox.question(
                    self,
                    "Puntos existentes en el tramo",
                    "Ya hay puntos entre el ancla y el extremo detectado.\n\n"
                    "¿Qué desea hacer?\n\n"
                    "  • Sí  → Reemplazar los puntos existentes en ese tramo\n"
                    "  • No  → Insertar los nuevos sin borrar los existentes",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                reemplazar_tramo = resp == QMessageBox.StandardButton.Yes

        self.vista.colocar_puntos_autodetectados(
            coordenadas,
            idx_ancla=idx_ancla,
            reemplazar_tramo=reemplazar_tramo,
        )
        n = len(coordenadas)
        self.label_estado.setText(
            f"✅ Auto-detección: {n} anillos colocados"
            + (f" desde punto #{idx_ancla}" if idx_ancla is not None else "")
            + ". Usa las herramientas para corregir."
        )

    # -------------------------------------------------------------------------
    # Gestión de años (médula / corteza)
    # -------------------------------------------------------------------------

    @property
    def datos_medidos(self):
        """Proyección calculada; nunca se conserva ni se modifica como estado."""
        if not all(hasattr(self, n) for n in ("vista", "spin_medula",
                                                "spin_corteza", "combo_dir")):
            return []
        modelo = self.vista.modelo_medicion
        anchos = anchos_puntos(modelo.captura(), self.vista.pixeles_por_mm)
        return mediciones_desde_anchos(
            anchos, self.spin_medula.value(), self.spin_corteza.value(),
            self.combo_dir.currentIndex() == 0)

    def _recalcular_anios(self, ancla: str):
        n = len(self.datos_medidos)
        if not n:
            return
        self.spin_medula.blockSignals(True)
        self.spin_corteza.blockSignals(True)
        try:
            if ancla == "medula":
                self.spin_corteza.setValue(self.spin_medula.value() + n - 1)
            else:
                self.spin_medula.setValue(self.spin_corteza.value() - n + 1)
        finally:
            self.spin_medula.blockSignals(False)
            self.spin_corteza.blockSignals(False)
        self._guardar_estado()
        self.metadatos_cambiados.emit()
        self._actualizar_grafico_rt()
        self.vista.redibujar_todo()

    def _aplicar_anio_medula(self):
        self._recalcular_anios("medula")

    def _aplicar_anio_corteza(self):
        self._recalcular_anios("corteza")

    def _al_cambiar_direccion(self):
        self._recalcular_anios("medula")

    # -------------------------------------------------------------------------
    # Sincronización de mediciones desde el lienzo
    # -------------------------------------------------------------------------

    def _sincronizar_mediciones(self, lista_anchos: list[float]):
        n = len(lista_anchos)
        self.spin_medula.blockSignals(True)
        self.spin_corteza.blockSignals(True)
        try:
            if not n:
                self.label_estado.setText("Listo para el primer anillo.")
            else:
                if self.combo_dir.currentIndex() == 0:
                    extremo = self.spin_medula.value() + n - 1
                    self.spin_corteza.setValue(extremo)
                else:
                    extremo = self.spin_corteza.value() - n + 1
                    self.spin_medula.setValue(extremo)
                self.label_estado.setText(
                    f"Último: {lista_anchos[-1]:.3f} mm (año {extremo}) | Total: {n}"
                )
        finally:
            self.spin_medula.blockSignals(False)
            self.spin_corteza.blockSignals(False)
        self.metadatos_cambiados.emit()
        self._actualizar_grafico_rt()
        self.vista.redibujar_todo()

    # -------------------------------------------------------------------------
    # Co-datación en vivo
    # -------------------------------------------------------------------------

    def _cargar_serie_maestra(self):
        carpeta = _ultima_carpeta()
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Cargar Serie de Referencia", carpeta,
            "Series y cronologías (*.rwl *.txt *.cat *.cmp *.pos *.wid "
            "*.csv *.tsv *.xlsx *.xls *.ods);;Todos (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
        try:
            # AQUÍ ESTÁ EL CAMBIO PRINCIPAL
            self.serie_maestra, self.nombre_maestra = leer_dendro_auto(ruta)

            self.lbl_nombre_maestra.setText(self.nombre_maestra)
            self.lbl_nombre_maestra.setStyleSheet("color:#5cb85c;")
            self.btn_eliminar_maestra.setEnabled(True)
            self._actualizar_grafico_rt()

            # Seleccionar la referencia recién cargada como maestra. Sin esto
            # el combo conservaba la selección anterior (normalmente una serie
            # interna), así que las correlaciones y sus fondos de color se
            # seguían calculando contra esa y no contra la referencia — daba la
            # impresión de que cargarla no hacía nada.
            self._seleccionar_maestra_externa()
            _ultima_carpeta(ruta)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Error", f"No se pudo leer la referencia:\n{exc}")
            
    def _cargar_serie_wid(self):
        """Carga una cronología CooRecorder (.wid) como serie de referencia."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Cargar Cronología CooRecorder", _ultima_carpeta(),
            "CooRecorder WID (*.wid);;Todos (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
        try:
            self.serie_maestra, self.nombre_maestra = leer_wid(ruta)
            self.lbl_nombre_maestra.setText(f"🌲 {self.nombre_maestra}")
            self.lbl_nombre_maestra.setStyleSheet("color:#5bc0de; font-weight:bold;")
            self.btn_eliminar_maestra.setEnabled(True)
            self._actualizar_grafico_rt()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Error", f"No se pudo leer el archivo .wid:\n{exc}")

    def _eliminar_serie_maestra(self):
        """Elimina la serie maestra externa cargada.

        Útil cuando el usuario quiere volver a comparar solo entre radios
        internos sin la referencia externa, o cambiar a otra de cero.
        """
        if self.serie_maestra is None:
            return
        self.serie_maestra = None
        self.nombre_maestra = "Ninguna"
        self.lbl_nombre_maestra.setText("Ninguna")
        self.lbl_nombre_maestra.setStyleSheet(f"color:{SECUNDARIO_QSS};")
        self.btn_eliminar_maestra.setEnabled(False)
        # Limpiar items del gráfico que referenciaban la externa
        self._plot_items = {k: v for k, v in getattr(self, "_plot_items", {}).items()
                            if not k.startswith("📂") and not k.startswith("★")}
        self._actualizar_grafico_rt()

    # -------------------------------------------------------------------------
    # Interacción con el gráfico: crosshair + navegación por clic
    # -------------------------------------------------------------------------

    def _graf_mouse_moved(self, evt):
        """Muestra crosshair vertical con año y valores al mover el mouse."""
        pos = evt[0]
        vb = self.grafico_unif.getViewBox()
        if not self.grafico_unif.sceneBoundingRect().contains(pos):
            self._graf_vline.setVisible(False)
            self._graf_label.setVisible(False)
            self._graf_dot.setData([], [])
            return

        mouse_point = vb.mapSceneToView(pos)
        anio = round(mouse_point.x())

        # Buscar valores de cada serie visible en ese año
        lineas = []
        dot_x, dot_y = [], []
        for nombre, item in self._plot_items.items():
            if not item.isVisible():
                continue
            xdata, ydata = item.getData()
            if xdata is None or len(xdata) == 0:
                continue
            # Buscar índice más cercano al año
            idx = int(np.argmin(np.abs(np.array(xdata) - anio)))
            if abs(xdata[idx] - anio) < 1.0:
                val = ydata[idx]
                # Quitar ★ y (maestra) del nombre para mostrar más limpio
                nombre_corto = nombre.replace("★ ", "").replace(" (maestra)", "")
                lineas.append(f"{nombre_corto}: {val:.3f}")
                dot_x.append(xdata[idx])
                dot_y.append(val)

        if not lineas:
            self._graf_vline.setVisible(False)
            self._graf_label.setVisible(False)
            self._graf_dot.setData([], [])
            return

        # Posicionar crosshair
        self._graf_vline.setPos(anio)
        self._graf_vline.setVisible(True)

        # Texto
        texto_html = (
            f"<span style='color:white; font-size:9pt; font-family:Arial;'>"
            f"<b>{anio}</b><br/>"
            + "<br/>".join(lineas)
            + "</span>"
        )
        self._graf_label.setHtml(texto_html)
        # Posicionar arriba a la derecha de la línea
        [[_xmin, _xmax], [_ymin, y_max]] = vb.viewRange()
        self._graf_label.setPos(anio + (_xmax - _xmin) * 0.01, y_max)
        self._graf_label.setVisible(True)

        # Puntos amarillos
        self._graf_dot.setData(dot_x, dot_y)

    def _graf_mouse_clicked(self, ev):
        """Al hacer clic en el gráfico, centra la imagen en el año clickeado."""
        # Ignorar si ya fue aceptado (e.g. por clic en leyenda)
        if ev.isAccepted():
            return
        # Solo clic izquierdo, y solo si el clic es sobre el área del plot
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        # No navegar si el clic fue sobre la leyenda
        pos = ev.scenePos()
        if not self.grafico_unif.getViewBox().sceneBoundingRect().contains(pos):
            return

        vb = self.grafico_unif.getViewBox()
        mouse_point = vb.mapSceneToView(pos)
        anio = round(mouse_point.x())

        # Obtener mapa año→coordenada de la imagen
        mapa = self.vista.mapa_anio_coordenada()
        if anio not in mapa:
            # Buscar el año más cercano
            if not mapa:
                return
            anio = min(mapa.keys(), key=lambda a: abs(a - anio))

        coord = mapa[anio]
        # Centrar la vista en esa coordenada manteniendo el zoom actual
        self.vista.centerOn(coord[0], coord[1])

        # Resaltar el punto con un círculo pulsante
        self._resaltar_anio_en_imagen(coord, anio)
        ev.accept()

    def _resaltar_anio_en_imagen(self, coord: tuple, anio: int):
        """Dibuja un círculo brillante temporal sobre el punto del año en la imagen."""
        # Limpiar resaltado anterior
        if self._item_highlight_anio is not None:
            try:
                self.vista.scene().removeItem(self._item_highlight_anio)
            except Exception:
                pass
            self._item_highlight_anio = None

        x, y = coord
        r = 18 * self.vista._escala_vista()
        pen = QPen(QColor("#00BFFF"))
        pen.setCosmetic(True)
        pen.setWidthF(3.5)
        brush = QBrush(QColor(0, 191, 255, 50))
        self._item_highlight_anio = self.vista.scene().addEllipse(
            x - r, y - r, 2 * r, 2 * r, pen, brush)
        self._item_highlight_anio.setZValue(80)

        # Auto-eliminar después de 2 segundos
        QTimer.singleShot(2000, self._limpiar_highlight_anio)

    def _limpiar_highlight_anio(self):
        if self._item_highlight_anio is not None:
            try:
                self.vista.scene().removeItem(self._item_highlight_anio)
            except Exception:
                pass
            self._item_highlight_anio = None

    def _clic_leyenda(self, ev):
        """Toggle visibilidad al hacer clic en un item de la leyenda."""
        pos = ev.scenePos()
        for nombre, item in self._plot_items.items():
            sample, label = None, None
            for s, l in self._legend.items:
                # Comparar por referencia al item de datos, no por nombre
                if s.item is item:
                    sample, label = s, l
                    break
            if sample is None:
                # Fallback: buscar por texto (nombres sin ★)
                for s, l in self._legend.items:
                    if l.text == nombre:
                        sample, label = s, l
                        break
            if sample is None:
                continue
            sr = sample.mapRectToScene(sample.boundingRect())
            lr = label.mapRectToScene(label.boundingRect())
            if sr.contains(pos) or lr.contains(pos):
                if nombre in self._series_ocultas:
                    self._series_ocultas.discard(nombre)
                    item.setVisible(True)
                    label.setAttr("color", "FFFFFF")
                else:
                    self._series_ocultas.add(nombre)
                    item.setVisible(False)
                    label.setAttr("color", "666666")
                ev.accept()
                return

    def _normalizar(self, valores: list) -> list:
        """Z-score. Si std≈0 devuelve ceros."""
        arr = np.array(valores, dtype=float)
        std = arr.std()
        if std < 1e-9:
            return [0.0] * len(valores)
        return ((arr - arr.mean()) / std).tolist()

    def metodo_correlacion(self) -> str:
        """Método de transformación elegido en el selector de la barra."""
        combo = getattr(self, "combo_metodo_corr", None)
        if combo is None:
            return _tr.DIFFLOG
        return combo.currentData() or _tr.DIFFLOG

    def _transformar_corr(self, anios, anchos):
        return transformar_medicion(anios, anchos, self.metodo_correlacion())

    def _r_global(self, anios_a, anchos_a, anios_b, anchos_b):
        return correlacion_global(anios_a, anchos_a, anios_b, anchos_b,
                                  self.metodo_correlacion())

    def _r_deslizante(self, anios_a, anchos_a, anios_b, anchos_b, ventana: int):
        return correlacion_deslizante(anios_a, anchos_a, anios_b, anchos_b,
                                     ventana, self.metodo_correlacion())

    def _seleccionar_maestra_externa(self):
        """Apunta el combo de maestra a la referencia externa cargada."""
        if not getattr(self, "nombre_maestra", None):
            return
        idx = self.combo_maestra.findText(f"↑ Ext: {self.nombre_maestra}")
        if idx >= 0 and self.combo_maestra.currentIndex() != idx:
            # currentIndexChanged ya está conectado a _actualizar_grafico_rt,
            # así que basta con cambiar el índice.
            self.combo_maestra.setCurrentIndex(idx)

    def _actualizar_combo_maestra(self, entradas, nombre_maestra_ext):
        """Actualiza el combo selector de maestra con las series disponibles."""
        previo = self.combo_maestra.currentText()
        self.combo_maestra.blockSignals(True)
        self.combo_maestra.clear()
        if nombre_maestra_ext:
            self.combo_maestra.addItem(f"↑ Ext: {nombre_maestra_ext}")
        for nombre, *_ in entradas:
            self.combo_maestra.addItem(nombre)
        idx = self.combo_maestra.findText(previo)
        if idx >= 0:
            self.combo_maestra.setCurrentIndex(idx)
        self.combo_maestra.blockSignals(False)

    def _dibujar_segmentos_correlacion(self, pw, entradas, maestra):
        """
        Dibuja anotaciones de correlación por segmento directamente
        sobre el gráfico de series.

        Lógica de segmentación (igual a la descrita por el usuario):
          - Ventana W años → segmentos de W/2 años cada uno, sin solapamiento.
          - Ejemplo W=10: segmentos [0-5), [5-10), [10-15)...
          - Ejemplo W=20: segmentos [0-10), [10-20), [20-30)...
          - Cada segmento muestra su r como texto coloreado en el centro,
            sobre una barra de fondo semitransparente.
          - El primer segmento puede ser más pequeño si la serie tiene
            menos de W/2 años disponibles (ventana creciente al inicio).
        """
        from pyqtgraph import InfiniteLine, LinearRegionItem, TextItem

        if maestra is None or not entradas:
            return

        self._textos_corr_pendientes = []

        ventana = self.spin_ventana_r.value()
        paso    = max(5, ventana // 2)   # cada segmento = mitad de la ventana
        nombre_m, anios_m, anchos_m = maestra

        def _col_rgba(r):
            if r >= 0.50:  return (46,  204, 113, 55)   # verde fuerte
            if r >= 0.35:  return (92,  184,  92, 55)   # verde
            if r >= 0.15:  return (240, 173,  78, 55)   # naranja
            return (217,  83,  79, 55)                   # rojo

        def _col_hex(r):
            if r >= 0.50:  return "#2ecc71"
            if r >= 0.35:  return "#5cb85c"
            if r >= 0.15:  return "#f0ad4e"
            return "#d9534f"

        # Maestra transformada con el método seleccionado
        db_m = self._transformar_corr(anios_m, anchos_m)

        for nombre, anios, anchos, color, *_ in entradas:
            da = self._transformar_corr(anios, anchos)
            overlap = sorted(da.index.intersection(db_m.index))
            if len(overlap) < 5:
                continue

            yr_min = overlap[0]
            yr_max = overlap[-1]

            # Generar segmentos de paso años comenzando desde yr_min
            seg_inicio = yr_min
            while seg_inicio < yr_max:
                seg_fin = seg_inicio + paso
                seg = [y for y in overlap if seg_inicio <= y < seg_fin]
                if len(seg) < 3:
                    seg_inicio += paso
                    continue

                a_seg = da.loc[seg].values
                b_seg = db_m.loc[seg].values
                if np.std(a_seg) < 1e-9 or np.std(b_seg) < 1e-9:
                    seg_inicio += paso
                    continue

                r = float(np.corrcoef(a_seg, b_seg)[0, 1])
                if np.isnan(r):
                    seg_inicio += paso
                    continue

                # Fondo semitransparente para el segmento
                rgba = _col_rgba(r)
                region = LinearRegionItem(
                    values=[seg_inicio, seg_fin],
                    orientation='vertical',
                    brush=pg.mkBrush(*rgba),
                    pen=pg.mkPen(None),
                    movable=False,
                )
                region.setZValue(-10)
                pw.addItem(region)

                # Texto de correlación centrado en el segmento
                centro_x = (seg_inicio + seg_fin) / 2.0
                txt = TextItem(
                    anchor=(0.5, 0.0),
                    fill=pg.mkBrush(0, 0, 0, 160),
                    border=pg.mkPen(_col_hex(r), width=1),
                )
                txt.setHtml(
                    f"<span style='color:{_col_hex(r)}; font-size:10pt; "
                    f"font-weight:bold; font-family:Arial;'>"
                    f" r={r:+.2f} </span>"
                )
                txt.setZValue(50)
                pw.addItem(txt)
                # Posicionar en la parte alta del rango visible
                self._textos_corr_pendientes.append((txt, centro_x))

                seg_inicio += paso

    def _actualizar_correlaciones_texto(self, entradas, maestra):
        """
        Actualiza la barra de texto de correlaciones debajo del gráfico.

        Muestra para cada serie vs maestra:
          - Símbolo de calidad  ●●● / ●●○ / ●○○ / ○○○
          - r total coloreado
          - r por ventanas crecientes (10, 20, 30... hasta la ventana elegida)
          - N años de solapamiento
        """
        if maestra is None or not entradas:
            self.lbl_r_total.setText("")
            self.lbl_ventanas_r.setText("")
            return

        ventana_max = self.spin_ventana_r.value()
        nombre_m, anios_m, anchos_m = maestra

        def _col(r):
            if r is None:    return "#666666"
            if r >= 0.50:    return "#2ecc71"
            if r >= 0.35:    return "#5cb85c"
            if r >= 0.15:    return "#f0ad4e"
            return "#d9534f"

        def _simbolo(r):
            if r is None:    return "○○○"
            if r >= 0.50:    return "●●●"
            if r >= 0.35:    return "●●○"
            if r >= 0.15:    return "●○○"
            return "○○○"

        # Calcular ventanas a mostrar: 10, 20, 30... hasta ventana_max
        ventanas = list(range(10, ventana_max + 1, 10))
        if not ventanas or ventanas[-1] != ventana_max:
            ventanas.append(ventana_max)
        # Máximo 6 ventanas para no saturar el texto
        if len(ventanas) > 6:
            paso = len(ventanas) // 6
            ventanas = ventanas[::paso]
            if ventanas[-1] != ventana_max:
                ventanas.append(ventana_max)

        # Línea superior: r total por serie (label fila de referencia)
        partes_total = []
        for nombre, anios, anchos, color, *_ in entradas:
            r_tot = self._r_global(anios, anchos, anios_m, anchos_m)
            c = _col(r_tot)
            sym = _simbolo(r_tot)
            val = f"{r_tot:+.2f}" if r_tot is not None else "—"
            # Overlap
            sa = pd.Series(anchos, index=anios)
            sb = pd.Series(anchos_m, index=anios_m)
            n_ov = len(sa.index.intersection(sb.index))
            partes_total.append(
                f"<span style='color:{color}'><b>{nombre}</b></span>"
                f"&nbsp;<span style='color:{c}'>{sym}&nbsp;r={val}</span>"
                f"&nbsp;<span style='color:{color_secundario()}'>({n_ov} años)</span>"
            )

        self.lbl_r_total.setText("&nbsp;&nbsp;&nbsp;".join(partes_total))

        # Línea inferior: desglose por ventana
        if not partes_total:
            self.lbl_ventanas_r.setText("")
            return

        lineas_ventana = []
        for nombre, anios, anchos, color, *_ in entradas:
            celdas = [f"<span style='color:{color}'><b>{nombre}</b></span>&nbsp;"]
            for v in ventanas:
                res = self._r_deslizante(anios, anchos, anios_m, anchos_m, v)
                if res[0]:
                    # Media de todos los r de esa ventana
                    r_v = float(np.mean(res[1]))
                    c = _col(r_v)
                    celdas.append(
                        f"<span style='color:{color_secundario()}'>{v}a:</span>"
                        f"<span style='color:{c}'>&nbsp;{r_v:+.2f}</span>"
                    )
                else:
                    celdas.append(
                        f"<span style='color:{color_secundario()}'>{v}a:&nbsp;—</span>"
                    )
            lineas_ventana.append("&nbsp;&nbsp;".join(celdas))

        self.lbl_ventanas_r.setText("&nbsp;&nbsp;|&nbsp;&nbsp;".join(lineas_ventana))

    def _actualizar_grafico_unificado(self):
        """
        Gráfico de series (arriba) + correlación deslizante estilo COFECHA (abajo).
        La maestra puede ser externa (.rwl/.wid) o una serie propia elegida en el combo.
        """
        pw = self.grafico_unif
        pw.clear()
        self._legend.clear()
        self._plot_items.clear()
        self._textos_corr_pendientes = []

        def _color_r(r):
            return "#5cb85c" if r >= 0.4 else "#f0ad4e" if r >= 0.0 else "#d9534f"

        # ── Recopilar series propias ──────────────────────────────────────
        entradas = []
        for i, (nombre, datos) in enumerate(self.caminos_guardados.items()):
            dm = mediciones_radio(datos, self.vista.pixeles_por_mm)
            if not dm:
                continue
            color = self._colores_radios[i % len(self._colores_radios)]
            entradas.append((nombre, [d["anio"] for d in dm],
                             [d["ancho_mm"] for d in dm],
                             color, Qt.PenStyle.SolidLine))

        dm = self.datos_medidos
        if dm:
            nombre_act = self.input_codigo.text().strip() or "En medición"
            color_act  = self._colores_radios[
                len(self.caminos_guardados) % len(self._colores_radios)]
            entradas.append((nombre_act, [d["anio"] for d in dm],
                             [d["ancho_mm"] for d in dm],
                             color_act, Qt.PenStyle.SolidLine))

        # ── Determinar maestra ────────────────────────────────────────────
        # Lógica: si hay maestra externa cargada (.rwl/.wid) Y el combo está
        # mostrando "↑ Ext: ..." (la opción de la externa), usar la externa.
        # Si el usuario eligió otra entrada del combo, respetarlo y usar esa
        # serie interna como maestra. Así el combo nunca queda "muerto"
        # cuando hay externa cargada.
        #
        # IMPORTANTE: aunque el usuario haya elegido una interna en el combo,
        # la externa SIGUE existiendo y debe aparecer en el combo (como opción
        # "↑ Ext: ...") y dibujarse en el gráfico (como referencia adicional).
        # Bug previo: si user cargaba externa pero elegía interna en combo,
        # nombre_maestra_ext quedaba en None → la externa desaparecía del
        # combo y del gráfico. Por eso "no aparecen series en el gráfico".
        maestra = None
        nombre_maestra_ext = None
        serie_maestra_data = None  # tupla (nombre, anios, anchos) de la externa
        seleccion_combo = self.combo_maestra.currentText()
        es_seleccion_externa = seleccion_combo.startswith("↑ Ext:")

        # 1) Si hay externa cargada, siempre preparar sus datos para que
        #    aparezca en el combo y se dibuje en el plot (independientemente
        #    de qué tenga seleccionado el usuario).
        if self.serie_maestra is not None and not self.serie_maestra.empty:
            col = ("Ancho_mm" if "Ancho_mm" in self.serie_maestra.columns
                   else self.serie_maestra.columns[0])
            ref = self.serie_maestra[col].dropna()
            if not ref.empty:
                nombre_maestra_ext = self.nombre_maestra
                serie_maestra_data = (
                    self.nombre_maestra,
                    list(ref.index.astype(int)),
                    list(ref.values.astype(float)),
                )

        # 2) Decidir cuál se usa como maestra para la correlación (=lo que
        #    se compara contra las demás).
        if serie_maestra_data is not None and (
                es_seleccion_externa or not seleccion_combo):
            # Combo apunta a la externa (o está vacío al principio) → usar externa
            maestra = serie_maestra_data
        else:
            # Combo apunta a una interna → usar esa
            sel = seleccion_combo
            for e in entradas:
                if e[0] == sel:
                    maestra = (e[0], e[1], e[2])
                    break
            # Fallback: si el seleccionado no está en entradas pero hay
            # externa, usar externa para no quedar sin maestra.
            if maestra is None and serie_maestra_data is not None:
                maestra = serie_maestra_data

        # Actualizar combo
        self._actualizar_combo_maestra(entradas, nombre_maestra_ext)

        # ── Normalizar ────────────────────────────────────────────────────
        n_curvas = len(entradas) + (1 if nombre_maestra_ext else 0)
        normalizar = n_curvas > 1
        pw.setLabel("left", "Ancho norm. (z)" if normalizar else "Ancho (mm)")

        # ── Dibujar series ────────────────────────────────────────────────
        # NUEVA LÓGICA (acorde a lo solicitado):
        # - La serie SELECCIONADA como maestra (la que se compara contra las
        #   demás, sin importar si es externa o interna) lleva ★ en su nombre
        #   en la leyenda Y se dibuja con línea SÓLIDA gruesa.
        # - Todas las otras series se dibujan con línea PUNTEADA fina.
        # - La externa, si está cargada pero no es la seleccionada, se dibuja
        #   con su propio etiquetado de referencia.
        nombre_maestra_actual = maestra[0] if maestra else None
        es_maestra_externa = (
            maestra is not None and maestra is serie_maestra_data
        )

        for nombre, anios, anchos, color, estilo in entradas:
            y = self._normalizar(anchos) if normalizar else anchos
            es_seleccionada = (nombre == nombre_maestra_actual
                                and not es_maestra_externa)
            if es_seleccionada:
                # Línea sólida gruesa + ★ en la leyenda
                nombre_legend = f"★ {nombre} (maestra)"
                pen = pg.mkPen(color, width=3, style=Qt.PenStyle.SolidLine)
            else:
                # Línea punteada fina
                nombre_legend = nombre
                pen = pg.mkPen(color, width=1.8, style=Qt.PenStyle.DashLine)
            item = pw.plot(anios, y,
                           pen=pen,
                           symbol="o", symbolSize=3,
                           symbolBrush=color, symbolPen=None,
                           name=nombre_legend)
            self._plot_items[nombre] = item
            if nombre in self._series_ocultas:
                item.setVisible(False)

        # Dibujar maestra externa si está cargada
        if serie_maestra_data is not None:
            nombre_m, anios_m, anchos_m = serie_maestra_data
            y_m = self._normalizar(anchos_m) if normalizar else anchos_m
            if es_maestra_externa:
                # Externa SELECCIONADA → ★ + sólida gruesa
                nombre_m_legend = f"★ {nombre_m} (maestra)"
                pen_m = pg.mkPen("#f0ad4e", width=3, style=Qt.PenStyle.SolidLine)
            else:
                # Externa NO seleccionada (hay una interna como maestra) →
                # se muestra como referencia adicional, dashed delgada
                nombre_m_legend = f"📂 {nombre_m} (ref. ext.)"
                pen_m = pg.mkPen("#f0ad4e", width=1.5, style=Qt.PenStyle.DashLine)
            item_m = pw.plot(anios_m, y_m,
                             pen=pen_m,
                             name=nombre_m_legend)
            self._plot_items[nombre_m] = item_m
            if nombre_m in self._series_ocultas:
                item_m.setVisible(False)

        # ── Correlaciones por segmento sobre el gráfico ─────────────────
        # Excluir de correlación la serie que ES la maestra (no tiene
        # sentido correlacionarla consigo misma). Funciona tanto si la
        # maestra es interna como si es externa.
        entradas_corr = [e for e in entradas
                         if not (maestra and e[0] == maestra[0]
                                 and not es_maestra_externa)]
        self._dibujar_segmentos_correlacion(pw, entradas_corr, maestra)
        self._actualizar_correlaciones_texto(entradas_corr, maestra)

        # ── Encuadre del gráfico ────────────────────────────────────────
        # Antes se forzaba autoRange() en CADA llamada. Como esta función se
        # dispara con cada anillo medido, el zoom se reiniciaba de continuo y
        # el eje X terminaba abarcando la unión de todas las series (p. ej.
        # 0-2024 con una serie flotante y una cronología reciente), dejando
        # todo apelotonado en un extremo.
        #
        # Ahora el encuadre se recalcula SOLO cuando cambia el conjunto de
        # series dibujadas (se carga o se quita una) o cuando el usuario lo
        # pide con el botón. Medir anillos ya no mueve la vista.
        firma = tuple(sorted(self._plot_items.keys()))
        if getattr(self, "_firma_series_grafico", None) != firma:
            self._firma_series_grafico = firma
            self._encuadre_pendiente = True
        if getattr(self, "_encuadre_pendiente", True):
            self._encuadre_pendiente = False
            self._encuadrar_grafico(pw, solo_mas_larga=True)

        # Posicionar textos de correlación en la parte alta del gráfico
        self._posicionar_textos_correlacion(pw)
        # Reconectar: reposicionar textos al hacer zoom/pan
        try:
            pw.getViewBox().sigRangeChanged.disconnect(self._reposicionar_textos_corr)
        except (TypeError, RuntimeError):
            pass
        pw.getViewBox().sigRangeChanged.connect(self._reposicionar_textos_corr)

    # Aliases para compatibilidad con todas las llamadas existentes
    def _encuadrar_grafico(self, pw=None, solo_mas_larga: bool = True):
        """Fija el rango visible del gráfico a partir de los datos dibujados.

        `solo_mas_larga=True` usa la extensión de la serie con más años, que
        es lo que se quiere al mezclar una serie flotante (años 0-200) con una
        cronología fechada: la unión de ambas dejaría un hueco enorme y las
        curvas quedarían aplastadas contra los bordes.

        `solo_mas_larga=False` encuadra la unión de todo lo dibujado, para el
        botón «Encuadrar todo».
        """
        if pw is None:
            pw = getattr(self, "grafico_unif", None)
        if pw is None:
            return
        tramos = []
        for item in self._plot_items.values():
            try:
                if not item.isVisible():
                    continue
                x, y = item.getData()
            except Exception:
                continue
            if x is None or len(x) == 0:
                continue
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float) if y is not None else None
            finitos = np.isfinite(x)
            if not finitos.any():
                continue
            tramos.append((float(np.min(x[finitos])), float(np.max(x[finitos])),
                           y[finitos] if y is not None else None))
        if not tramos:
            return

        vb = pw.getViewBox()
        if solo_mas_larga:
            x0, x1, _ = max(tramos, key=lambda t: t[1] - t[0])
        else:
            x0 = min(t[0] for t in tramos)
            x1 = max(t[1] for t in tramos)
        if x1 <= x0:
            x1 = x0 + 1.0
        margen = (x1 - x0) * 0.02
        vb.enableAutoRange(axis=vb.XAxis, enable=False)
        vb.setXRange(x0 - margen, x1 + margen, padding=0)

        # El eje Y se ajusta a lo que cae dentro de la ventana X elegida
        ys = []
        for a, b, y in tramos:
            if y is None or b < x0 or a > x1:
                continue
            ys.append(y)
        if ys:
            todos = np.concatenate(ys)
            todos = todos[np.isfinite(todos)]
            if todos.size:
                y0, y1 = float(todos.min()), float(todos.max())
                if y1 <= y0:
                    y1 = y0 + 1.0
                m = (y1 - y0) * 0.05
                vb.enableAutoRange(axis=vb.YAxis, enable=False)
                vb.setYRange(y0 - m, y1 + m, padding=0)
        self._posicionar_textos_correlacion(pw)

    def _actualizar_grafico_serie(self):
        self._actualizar_grafico_unificado()

    def _actualizar_grafico_rt(self):
        self._actualizar_grafico_unificado()

    def _posicionar_textos_correlacion(self, pw):
        """Coloca los textos de correlación en la parte alta del rango Y visible."""
        pendientes = getattr(self, "_textos_corr_pendientes", [])
        if not pendientes:
            return
        vb = pw.getViewBox()
        [[_xmin, _xmax], [_ymin, y_max]] = vb.viewRange()
        # Posicionar justo en el tope del rango visible (anchor 0.0 = cuelga hacia abajo)
        y_top = y_max - (y_max - _ymin) * 0.01
        for txt, cx in pendientes:
            txt.setPos(cx, y_top)

    def _reposicionar_textos_corr(self, vb=None):
        """Slot: reposiciona textos de correlación cuando cambia el rango visible."""
        pw = self.grafico_unif
        self._posicionar_textos_correlacion(pw)

    # -------------------------------------------------------------------------
    # Gestión de radios guardados
    # -------------------------------------------------------------------------

    def _finalizar_camino(self):
        if not self.datos_medidos:
            return
        sufijo = "A" if not self.caminos_guardados else "B"
        nombre_defecto = self.input_codigo.text().strip() + sufijo
        nombre, ok = QInputDialog.getText(self, "Guardar Radio", "Identificador:", text=nombre_defecto)
        if not ok:
            return
        nombre = nombre.strip()
        if not nombre or nombre in self.caminos_guardados:
            return QMessageBox.warning(self, "Identificador", "Nombre vacío o ya existente.")

        self.caminos_guardados[nombre] = self._capturar_radio(nombre).a_dict()
        item = QListWidgetItem(nombre)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.lista_caminos.addItem(item)

        self.vista.limpiar_historial()
        self.vista.modelo_medicion.limpiar()
        self.vista.anomalias.clear()
        self._ultima_ruta_exportada = None
        with QSignalBlocker(self.check_tiene_medula), QSignalBlocker(self.check_tiene_corteza):
            self.check_tiene_medula.setChecked(False)
            self.check_tiene_corteza.setChecked(False)
        self.vista.redibujar_todo()

        self.spin_medula.blockSignals(True)
        self.spin_corteza.blockSignals(True)
        self.spin_medula.setValue(0)
        self.spin_corteza.setValue(0)
        self.spin_medula.blockSignals(False)
        self.spin_corteza.blockSignals(False)

        self.vista.cargar_caminos_inactivos(self.caminos_guardados)
        self._guardar_estado()
        self._actualizar_grafico_rt()
        self.label_estado.setText(f"Radio '{nombre}' guardado. Listo para medir nuevo radio.")

    def _editar_camino(self):
        items = self.lista_caminos.selectedItems()
        if not items:
            return QMessageBox.information(self, "Aviso", "Seleccione un radio para editar.")
        if self.datos_medidos:
            if QMessageBox.question(
                self, "Atención",
                "Tiene un radio en progreso. ¿Desea descartarlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return

        nombre = items[0].text()
        datos = normalizar_radio(self.caminos_guardados[nombre])
        if not datos.get("coords"):
            return QMessageBox.warning(self, "Aviso", "El radio no tiene coordenadas editables.")
        self.caminos_guardados.pop(nombre)

        self.vista.limpiar_historial()
        self.vista.modelo_medicion.limpiar()
        self.vista.redibujar_todo()

        if nombre in self.vista.items_caminos_inactivos:
            # Remover TODOS los items del radio inactivo, incluyendo los
            # textos de año (antes solo se removían puntos y líneas — eso
            # dejaba etiquetas de año verdes huérfanas sobre la imagen,
            # superpuestas con las del radio activo recién cargado).
            visuales_inact = self.vista.items_caminos_inactivos[nombre]
            for grupo in ("puntos", "lineas", "textos"):
                for item in visuales_inact.get(grupo, []):
                    try:
                        self.escena.removeItem(item)
                    except Exception:
                        pass
            del self.vista.items_caminos_inactivos[nombre]
            # También quitar del caché de datos: si no lo hacemos, al
            # próximo zoom `_redibujar_post_zoom` re-renderiza el radio
            # como inactivo encima del activo, recreando el bug.
            if hasattr(self.vista, "_caminos_inactivos_data"):
                self.vista._caminos_inactivos_data.pop(nombre, None)

        self.lista_caminos.takeItem(self.lista_caminos.row(items[0]))

        self.spin_medula.blockSignals(True)
        self.spin_corteza.blockSignals(True)
        self.combo_dir.blockSignals(True)
        try:
            self.combo_dir.setCurrentIndex(datos["dir_idx"])
            self.spin_medula.setValue(datos["anio_medula"])
            self.spin_corteza.setValue(datos["anio_corteza"])
            self.vista.cargar_camino_activo(datos["coords"], datos["es_salto"], redibujar=False)
        finally:
            self.combo_dir.blockSignals(False)
            self.spin_medula.blockSignals(False)
            self.spin_corteza.blockSignals(False)

        self.input_codigo.setText(nombre)
        self._restaurar_metadatos_radio(datos)
        self._ultima_ruta_exportada = None
        self.vista.recalcular_todas_las_distancias()
        # IMPORTANTE: emitir metadatos_cambiados para que main_anillos.py
        # sincronice los spinboxes/combo GLOBALES del top bar con los locales
        # (ocultos) recién restaurados. Sin esto, el usuario sigue viendo
        # año=0 en la barra superior aunque el radio cargado tenga año 1500
        # — esa era la causa real del bug "se volvió al año cero".
        self.metadatos_cambiados.emit()
        self._guardar_estado()
        self.label_estado.setText(f"Editando radio '{nombre}'.")

    def _eliminar_camino(self):
        items = self.lista_caminos.selectedItems()
        if not items:
            return
        if QMessageBox.question(
            self, "Eliminar",
            "¿Eliminar permanentemente el radio seleccionado?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        for item in items:
            nombre = item.text()
            self.caminos_guardados.pop(nombre, None)
            self.lista_caminos.takeItem(self.lista_caminos.row(item))

        # Redibujar TODOS los caminos inactivos restantes desde cero.
        # cargar_caminos_inactivos limpia primero TODOS los items (puntos,
        # líneas Y textos) y vuelve a dibujar solo los que quedan. Antes se
        # hacía una eliminación manual que quitaba puntos y líneas pero NO
        # las etiquetas de año (textos), por lo que el radio borrado seguía
        # dejando rastros verdes en la imagen.
        self.vista.cargar_caminos_inactivos(self.caminos_guardados)

        # cargar_caminos_inactivos dibuja todo visible; re-aplicar la
        # visibilidad según el check de cada radio para no "resucitar"
        # radios que el usuario había ocultado.
        for i in range(self.lista_caminos.count()):
            it = self.lista_caminos.item(i)
            visible = it.checkState() == Qt.CheckState.Checked
            self.vista.toggle_camino_inactivo(it.text(), visible)

        self._guardar_estado()
        self._actualizar_grafico_rt()

    def _toggle_visual_camino(self, item: QListWidgetItem):
        self.vista.toggle_camino_inactivo(item.text(), item.checkState() == Qt.CheckState.Checked)
        self._actualizar_grafico_rt()

    # -------------------------------------------------------------------------
    # Calibración
    # -------------------------------------------------------------------------

    def _calibrar_por_dpi(self):
        """Abre una ventana auxiliar con información completa de la imagen
        y permite cambiar el DPI manualmente.

        La ventana muestra:
          - Dimensiones en píxeles + megapíxeles totales
          - DPI actual y método con el que se detectó (JFIF / EXIF /
            TIFF / manual / default)
          - Tamaño físico calculado (mm y cm)
          - Resolución espacial (px / mm)
          - Spin box para override manual del DPI

        Útil para:
          - Verificar que el DPI detectado coincide con el real del
            escáner (cuando el usuario lo conoce)
          - Diagnosticar imágenes sin metadata (DPI default)
          - Confirmar tamaño físico calculado vs. tamaño real de la
            pieza escaneada

        Históricamente: reemplaza al QInputDialog simple que solo mostraba
        un número, sin contexto sobre cómo se obtuvo ni qué implicaba.
        """
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
            QPushButton, QFrame, QGridLayout,
        )
        from PyQt6.QtGui import QFont

        # ── Recopilar información actual ──────────────────────────────
        dpi_actual = int(round(self.vista.pixeles_por_mm * MM_POR_PULGADA))
        ruta_img = getattr(self, "ruta_imagen_actual", None)

        # Tamaño de la imagen cargada (pixmap)
        if self.item_imagen is not None:
            pm = self.item_imagen.pixmap()
            w_px, h_px = pm.width(), pm.height()
        else:
            w_px = h_px = 0

        # Re-detectar para mostrar el método empleado
        dpi_detectado = None
        if ruta_img:
            dpi_detectado = self._detectar_dpi(ruta_img)

        # Texto descriptivo del MODO actual (puede ser distinto al
        # resultado de la metadata si el usuario lo cambió manualmente).
        modo_label = {
            "auto":     "✓ Detectado automáticamente desde metadata",
            "manual":   "✏️ Cambiado manualmente por el usuario",
            "regla":    "📏 Calibrado midiendo una distancia conocida",
            "default":  "⚠ No se detectó — usando DPI por defecto",
            "guardado": "💾 Restaurado desde sesión guardada",
        }
        metodo_deteccion = modo_label.get(
            getattr(self, "_dpi_modo", "default"),
            "Desconocido")

        # Cálculos derivados
        if dpi_actual > 0:
            w_mm = w_px / dpi_actual * MM_POR_PULGADA
            h_mm = h_px / dpi_actual * MM_POR_PULGADA
        else:
            w_mm = h_mm = 0
        mp = (w_px * h_px) / 1e6

        # ── Construir el diálogo ──────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle("Información de imagen — Configuración DPI")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # Título
        titulo = QLabel("📐 Información de la imagen")
        f = QFont(); f.setBold(True); f.setPointSize(11)
        titulo.setFont(f)
        layout.addWidget(titulo)

        # Grid con datos
        grid_frame = QFrame()
        grid_frame.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(grid_frame)
        grid.setSpacing(8)

        def add_row(row: int, label: str, valor: str, destacar: bool = False):
            lab = QLabel(label)
            val = QLabel(valor)
            if destacar:
                fb = QFont(); fb.setBold(True)
                val.setFont(fb)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(lab, row, 0)
            grid.addWidget(val, row, 1)

        add_row(0, "Dimensiones (px):", f"{w_px:,} × {h_px:,}".replace(",", "."))
        add_row(1, "Megapíxeles totales:", f"{mp:.1f} MP")
        add_row(2, "DPI actual:", f"{dpi_actual} DPI", destacar=True)
        add_row(3, "Método de detección:", metodo_deteccion)
        if dpi_detectado is not None and dpi_detectado != dpi_actual:
            add_row(4, "DPI desde metadata:", f"{int(round(dpi_detectado))} DPI")
            offset = 5
        else:
            offset = 4
        add_row(offset, "Tamaño físico calculado:",
                f"{w_mm:.1f} × {h_mm:.1f} mm  ({w_mm/10:.1f} × {h_mm/10:.1f} cm)")
        add_row(offset + 1, "Resolución espacial:",
                f"{self.vista.pixeles_por_mm:.2f} px/mm  "
                f"({1000/self.vista.pixeles_por_mm:.1f} μm/px)")
        layout.addWidget(grid_frame)

        # Ayuda
        ayuda = QLabel(
            "💡 Si el DPI detectado no coincide con el real del escáner, "
            "puedes sobreescribirlo manualmente aquí. El cambio recalcula "
            "todas las mediciones existentes."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {SECUNDARIO_QSS}; font-style: italic;")
        layout.addWidget(ayuda)

        # Spin box para override
        fila_override = QHBoxLayout()
        fila_override.addWidget(QLabel("DPI manual:"))
        spin_dpi = QSpinBox()
        spin_dpi.setRange(72, 12800)
        spin_dpi.setValue(dpi_actual)
        spin_dpi.setSuffix(" DPI")
        spin_dpi.setSingleStep(100)
        spin_dpi.setMinimumWidth(120)
        fila_override.addWidget(spin_dpi)

        # Botones rápidos de DPI común
        for dpi_preset in (1200, 1600, 2400, 3200):
            btn_p = QPushButton(str(dpi_preset))
            btn_p.setMaximumWidth(60)
            btn_p.clicked.connect(lambda _, v=dpi_preset: spin_dpi.setValue(v))
            fila_override.addWidget(btn_p)
        fila_override.addStretch()
        layout.addLayout(fila_override)

        # Botones
        botonera = QHBoxLayout()
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(dlg.reject)
        btn_aplicar = QPushButton("✓ Aplicar DPI")
        btn_aplicar.setDefault(True)
        btn_aplicar.setStyleSheet(
            "QPushButton{background:#5cb85c; color:white; "
            "font-weight:bold; padding:6px 14px; border-radius:4px;}")
        btn_aplicar.clicked.connect(dlg.accept)
        botonera.addStretch()
        botonera.addWidget(btn_cancelar)
        botonera.addWidget(btn_aplicar)
        layout.addLayout(botonera)

        # ── Ejecutar ──────────────────────────────────────────────────
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        dpi_nuevo = spin_dpi.value()
        if dpi_nuevo <= 0 or dpi_nuevo == dpi_actual:
            return

        # Aplicar el cambio
        self.vista.pixeles_por_mm = dpi_nuevo / MM_POR_PULGADA
        # Marcar el origen como manual para que el diálogo lo refleje
        # correctamente la próxima vez que se abra.
        self._dpi_modo = "manual"
        # Recalcular y sincronizar una sola vez con la nueva escala.
        self.vista.recalcular_todas_las_distancias()
        self._guardar_estado()
        self.label_estado.setText(
            f"📐 DPI cambiado manualmente: {dpi_nuevo} "
            f"(1 mm = {self.vista.pixeles_por_mm:.2f} px). "
            f"Mediciones recalculadas."
        )

    def _activar_calibracion(self):
        """Activa el modo de calibración por regla.

        Flujo nuevo (acorde a la solicitud del usuario):
          1. Activar modo
          2. Usuario hace clic en 2 puntos sobre la imagen
          3. Después del 2° clic, se dibuja la línea con la distancia en px
             y aparece el diálogo pidiendo los mm
          4. Al aplicar, las marcas visuales se borran solas

        Antes el flujo era inverso: preguntaba primero los mm y después
        el usuario marcaba — era contra-intuitivo y dejaba las marcas
        permanentes en la imagen.
        """
        self.vista.iniciar_calibracion()
        self.label_estado.setText(
            "📏 Calibración: Haz clic en el primer punto de la distancia conocida.")
    # -------------------------------------------------------------------------
    # Importación de archivos .pos (CooRecorder)
    # -------------------------------------------------------------------------

    def _importar_pos(self):
        if self.datos_medidos:
            if QMessageBox.question(
                self, "Atención",
                "Tiene un radio en progreso. ¿Sobrescribirlo con el archivo importado?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return

        ruta, _ = QFileDialog.getOpenFileName(
            self, "Importar CooRecorder .pos", _ultima_carpeta(),
            "CooRecorder POS (*.pos);;Todos (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return

        try:
            dpi_pos, anio_datado, coords_px, saltos = leer_pos(ruta)
        except (OSError, ValueError) as exc:
            return QMessageBox.critical(self, "Error", f"No se pudo procesar el archivo:\n{exc}")

        if not coords_px:
            return QMessageBox.warning(self, "Error", "No se encontraron coordenadas válidas.")

        self.vista.limpiar_historial()
        self.vista.pixeles_por_mm = dpi_pos / MM_POR_PULGADA
        self.vista.modelo_medicion.cargar(coords_px, saltos)

        # Detectar automáticamente médula/corteza:
        # el año más reciente (#C DATED) = corteza; el más antiguo = médula.
        anillos_validos = sum(1 for s in saltos[1:] if not s)
        self.spin_medula.blockSignals(True)
        self.spin_corteza.blockSignals(True)
        if anio_datado is not None:
            # El archivo declara explícitamente el año de corteza
            anio_corteza = anio_datado
            anio_medula  = anio_datado - anillos_validos + 1
        else:
            # Sin fecha declarada: usar año actual como corteza estimada
            import datetime
            anio_corteza = datetime.date.today().year
            anio_medula  = anio_corteza - anillos_validos + 1
        self.spin_corteza.setValue(anio_corteza)
        self.spin_medula.setValue(anio_medula)
        # Asegurar que la dirección quede en Médula→Corteza (+1)
        self.combo_dir.setCurrentIndex(0)
        self.spin_medula.blockSignals(False)
        self.spin_corteza.blockSignals(False)

        self.input_codigo.setText(os.path.splitext(os.path.basename(ruta))[0][:TUCSON_MAX_CHARS_ID].upper())
        self.vista.recalcular_todas_las_distancias()
        self._guardar_estado()
        self.label_estado.setText(f"Archivo importado correctamente ({dpi_pos:.0f} DPI).")

    def _exportar_anomalias(self):
        """Exporta las anomalías de un radio en formato DendroEventos:
        matriz binaria con los AÑOS en la primera columna y una columna por
        cada TIPO de anomalía presente, con valores 0/1 (1 = ese año tiene
        ese tipo de anomalía). El nombre de archivo sugerido es el de la
        serie.

        Las filas cubren TODO el rango de años de la medición (no solo los
        años con anomalía), para que el archivo sea una serie temporal
        completa lista para análisis de eventos en R u otros programas.
        """
        opciones = []
        if self.vista.anomalias:
            opciones.append("Radio Actual (En progreso)")
        for nombre, datos in self.caminos_guardados.items():
            if datos.get("anomalias"):
                opciones.append(nombre)
        if not opciones:
            return QMessageBox.information(
                self, "Sin anomalías",
                "No hay anomalías registradas en ningún radio.")

        seleccion, ok = QInputDialog.getItem(
            self, "Exportar anomalías (DendroEventos)",
            "¿De qué radio exportar las anomalías?", opciones, 0, False)
        if not ok or not seleccion:
            return

        if seleccion == "Radio Actual (En progreso)":
            anomalias = dict(self.vista.anomalias)
            codigo = self.input_codigo.text().strip() or "radio"
            datos_med = self.datos_medidos
        else:
            anomalias = dict(self.caminos_guardados[seleccion].get("anomalias", {}))
            codigo = seleccion
            datos_med = mediciones_radio(self.caminos_guardados[seleccion],
                                         self.vista.pixeles_por_mm)

        # Normalizar claves de año a int (al venir de JSON pueden ser str)
        anomalias = {int(k): v for k, v in anomalias.items()}
        if not anomalias:
            return QMessageBox.information(
                self, "Sin anomalías", "Ese radio no tiene anomalías.")

        # Rango de años: completo desde la medición; si no hay datos
        # medidos, usar solo el rango de las anomalías.
        anios_medidos = sorted({int(d["anio"]) for d in datos_med}) if datos_med else []
        if anios_medidos:
            todos_anios = list(range(anios_medidos[0], anios_medidos[-1] + 1))
        else:
            a = sorted(anomalias.keys())
            todos_anios = list(range(a[0], a[-1] + 1))

        # Tipos presentes, en el orden de definición de TIPOS_ANOMALIA.
        # Las columnas usan el NOMBRE legible del tipo (ej. "Fuego",
        # "Frost ring"). Si DendroEventos espera otros encabezados, se
        # ajusta fácil aquí.
        presentes = set(anomalias.values())
        tipos_cols = [(t, TIPOS_ANOMALIA[t][1]) for t in TIPOS_ANOMALIA
                      if t in presentes]

        ruta_sugerida = os.path.join(_ultima_carpeta(), f"{codigo}.csv")
        ruta, fmt = QFileDialog.getSaveFileName(
            self, "Exportar anomalías (DendroEventos)", ruta_sugerida,
            "CSV separado por punto y coma (*.csv);;"
            "Texto separado por tabulaciones (*.txt);;"
            "Excel (*.xlsx)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
        ruta = _asegurar_extension(ruta, fmt)
        _ultima_carpeta(ruta)

        try:
            import pandas as pd
            filas = []
            for anio in todos_anios:
                tipo_anio = anomalias.get(anio)
                fila = {"Año": anio}
                for tipo_cod, tipo_nom in tipos_cols:
                    fila[tipo_nom] = 1 if tipo_anio == tipo_cod else 0
                filas.append(fila)
            df = pd.DataFrame(filas)

            ext = os.path.splitext(ruta)[1].lower()
            if ext == ".xlsx":
                _escribir_excel(df, ruta)
            elif ext == ".txt":
                df.to_csv(ruta, index=False, sep="\t")
            else:
                df.to_csv(ruta, index=False, sep=";")

            cols_txt = ", ".join(nom for _, nom in tipos_cols)
            QMessageBox.information(
                self, "Éxito",
                f"Anomalías exportadas (formato DendroEventos):\n{ruta}\n\n"
                f"Años: {todos_anios[0]}–{todos_anios[-1]} "
                f"({len(todos_anios)} filas)\n"
                f"Columnas de evento (0/1): {cols_txt}")
        except Exception as exc:
            QMessageBox.critical(
                self, "Error", f"No se pudo exportar:\n{exc}")

    # -------------------------------------------------------------------------
    # Persistencia (guardado automático en JSON oculto)
    # -------------------------------------------------------------------------

    def _restaurar_metadatos_radio(self, datos):
        self.vista.anomalias = {int(k): v for k, v in datos.get("anomalias", {}).items()}
        with QSignalBlocker(self.check_tiene_medula), QSignalBlocker(self.check_tiene_corteza):
            self.check_tiene_medula.setChecked(datos.get("medula", False))
            self.check_tiene_corteza.setChecked(datos.get("corteza", False))

    def _capturar_radio(self, codigo=None):
        return RadioMedicion(
            codigo=self.input_codigo.text() if codigo is None else codigo,
            puntos=self.vista.modelo_medicion.captura(),
            anio_medula=self.spin_medula.value(),
            anio_corteza=self.spin_corteza.value(),
            dir_idx=self.combo_dir.currentIndex(),
            anomalias=dict(self.vista.anomalias),
            medula=self.check_tiene_medula.isChecked(),
            corteza=self.check_tiene_corteza.isChecked(),
        )

    def _programar_guardado(self):
        self._timer_autoguardado.start()

    def guardar_pendiente(self):
        if self._timer_autoguardado.isActive():
            self._guardar_estado()

    def _guardar_estado(self):
        timer = getattr(self, "_timer_autoguardado", None)
        if timer is not None:
            timer.stop()
        if getattr(self, "_sesion_protegida", None) == self.ruta_imagen_actual:
            return
        try:
            guardar_sesion(
                self.ruta_imagen_actual,
                self.vista.pixeles_por_mm,
                self.caminos_guardados,
                self._capturar_radio().a_dict(activo=True),
            )
        except Exception:
            logger.exception("No se pudo guardar el estado")

    def _cargar_estado(self) -> bool:
        self._sesion_protegida = None
        try:
            datos = leer_sesion(self.ruta_imagen_actual)
            if datos is None:
                return False
            activo = datos["camino_activo"]
            if activo:
                for campo, control in (("anio_medula", self.spin_medula),
                                       ("anio_corteza", self.spin_corteza)):
                    if not control.minimum() <= activo[campo] <= control.maximum():
                        raise ValueError(f"{campo} fuera del rango permitido")
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            self._sesion_protegida = self.ruta_imagen_actual
            logger.warning("No se pudo cargar el estado guardado: %s", exc)
            self._mostrar_aviso_dpi("Sesión protegida",
                "No se pudo restaurar la sesión. El autoguardado queda desactivado "
                "para esta imagen hasta resolver el archivo de sesión.")
            return False

        # La lectura, migración y validación han terminado antes de tocar Qt.
        if "pixeles_por_mm" in datos:
            self.vista.pixeles_por_mm = datos["pixeles_por_mm"]
            self._dpi_modo = "guardado"

        self.caminos_guardados = datos["caminos_guardados"]
        with QSignalBlocker(self.lista_caminos):
            self.lista_caminos.clear()
            for nombre in self.caminos_guardados:
                item = QListWidgetItem(nombre)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self.lista_caminos.addItem(item)
        self.vista.cargar_caminos_inactivos(self.caminos_guardados)

        if activo:
            with (QSignalBlocker(self.spin_medula),
                  QSignalBlocker(self.spin_corteza),
                  QSignalBlocker(self.combo_dir),
                  QSignalBlocker(self.input_codigo)):
                self.input_codigo.setText(activo.get("codigo", self.input_codigo.text()))
                self.combo_dir.setCurrentIndex(activo["dir_idx"])
                self.spin_medula.setValue(activo["anio_medula"])
                self.spin_corteza.setValue(activo["anio_corteza"])
                self.vista.limpiar_historial()
                self.vista.cargar_camino_activo(
                    activo["coordenadas"], activo["es_salto"], redibujar=False)
            self._restaurar_metadatos_radio(activo)
            self.vista.recalcular_todas_las_distancias()
        else:
            self._actualizar_grafico_rt()
        return True

    # -------------------------------------------------------------------------
    # Exportación
    # -------------------------------------------------------------------------

    def _ejecutar_exportacion(self):
        opciones = []
        if self.datos_medidos:
            opciones.append("Radio Actual (En progreso)")
        opciones.extend(list(self.caminos_guardados.keys()))
        if not opciones:
            return QMessageBox.warning(self, "Aviso", "No hay radios para exportar.")

        seleccion, ok = QInputDialog.getItem(
            self, "Exportar", "Seleccione el radio a exportar:", opciones, 0, False
        )
        if not ok or not seleccion:
            return

        if seleccion == "Radio Actual (En progreso)":
            datos = self.datos_medidos
            codigo = self.input_codigo.text().strip()
            anomalias_export = self.vista.anomalias
            # Para EW/LW: usar el estado en vivo de la vista
            coords_export = self.vista.coordenadas_anillos
            saltos_export = self.vista.es_salto
        else:
            datos = mediciones_radio(self.caminos_guardados[seleccion],
                                     self.vista.pixeles_por_mm)
            codigo = seleccion
            anom_data = self.caminos_guardados[seleccion].get("anomalias", {})
            anomalias_export = anom_data
            # Para EW/LW: usar los coords/saltos GUARDADOS del radio elegido,
            # NO los de la vista en vivo (que pueden estar vacíos o ser de
            # otro radio en progreso). Este era el bug que hacía que el
            # usuario nunca pudiera "guardar" la info de EW/LW de un radio
            # ya finalizado.
            coords_export = self.caminos_guardados[seleccion].get("coords", [])
            saltos_export = self.caminos_guardados[seleccion].get("es_salto", [])

        if not codigo:
            return QMessageBox.warning(self, "Aviso", "El radio no tiene nombre/código.")

        # Diálogo de guardado para capturar ruta y guardar sidecar
        # Obtener última carpeta y armar la ruta sugerida
        carpeta = _ultima_carpeta()
        ruta_sugerida = os.path.join(carpeta, codigo) if carpeta else codigo

        # Diálogo de guardado para capturar ruta y guardar sidecar
        ruta, fmt = QFileDialog.getSaveFileName(
            self, "Guardar", ruta_sugerida,
            "Formato Tucson (*.txt *.rwl);;Excel (*.xlsx);;CSV (*.csv);;"
            "CooRecorder POS (*.pos)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return

        # Garantizar la extensión según el filtro elegido (el diálogo no
        # nativo no la agrega solo; sin ella, .xlsx/.pos no se reconocen).
        ruta = _asegurar_extension(ruta, fmt)
        # Guardar la ruta elegida
        _ultima_carpeta(ruta)

        # ── Exportación a .pos (CooRecorder) ──
        # Solo coordenadas (en mm) + DPI + año de corteza, para compartir la
        # medición e interoperar con CooRecorder u otros programas. Las
        # anomalías y la info de EW/LW se exportan por separado.
        if "*.pos" in fmt or ruta.lower().endswith(".pos"):
            try:
                anio_corteza = max((d["anio"] for d in datos), default=None)
                dpi = self.vista.pixeles_por_mm * MM_POR_PULGADA
                escribir_pos(ruta, coords_export, saltos_export,
                                   dpi, anio_corteza, codigo, self.ruta_imagen_actual)
                QMessageBox.information(
                    self, "Éxito",
                    f"Medición exportada en formato .pos:\n{ruta}\n\n"
                    f"Contiene las coordenadas de los anillos (en mm), el DPI "
                    f"y el año de corteza. Las anomalías se exportan aparte.")
            except Exception as exc:
                QMessageBox.critical(
                    self, "Error", f"No se pudo exportar .pos:\n{exc}")
            return
        
        try:
            import pandas as pd
            anios  = [d["anio"]     for d in sorted(datos, key=lambda d: d["anio"])]
            anchos = [d["ancho_mm"] for d in sorted(datos, key=lambda d: d["anio"])]

            # Calcular EW/LW por anillo si hay límites — para incluir como
            # columnas extras en CSV/Excel.
            ppm = self.vista.pixeles_por_mm
            anchos_ewlw = None
            tiene_ewlw_en_radio = any(_es_ewlw(v) for v in saltos_export)
            if tiene_ewlw_en_radio and coords_export:
                try:
                    anchos_ewlw = _calcular_anchos_ewlw_por_anillo(
                        coords_export, saltos_export, ppm
                    )
                    # Alinear largo con datos por seguridad
                    if len(anchos_ewlw) != len(datos):
                        anchos_ewlw = None
                except Exception as exc:
                    logger.warning("No se pudo calcular EW/LW para tabla: %s", exc)
                    anchos_ewlw = None

            if "*.csv" in fmt:
                ExportadorDendro._exportar_tabular(
                    codigo, anios, anchos, ruta, "csv",
                    anchos_ewlw=anchos_ewlw)
            elif "*.xlsx" in fmt:
                ExportadorDendro._exportar_tabular(
                    codigo, anios, anchos, ruta, "xlsx",
                    anchos_ewlw=anchos_ewlw)
            else:
                mediciones_int = [int(round(m * 1000)) for m in anchos]
                ExportadorDendro._escribir_tucson(codigo, anios[0], mediciones_int, ruta, anios=anios)

            # Exportar EW/LW si hay límites marcados en el radio elegido
            # (no en la vista en vivo, que puede ser distinta).
            tiene_ewlw = any(_es_ewlw(v) for v in saltos_export)
            if tiene_ewlw:
                self._exportar_ewlw(
                    codigo, ruta,
                    coords=coords_export,
                    saltos=saltos_export,
                    datos_medidos=datos,
                )

            QMessageBox.information(self, "Éxito", f"Exportado a:\n{ruta}")
            # No asociar las anomalías del radio activo a otro radio.
            if seleccion == "Radio Actual (En progreso)":
                self._ultima_ruta_exportada = ruta
                self._guardar_sidecar_anom(ruta)
            else:
                radio = self.caminos_guardados[seleccion]
                _js.guardar_json(self._ruta_sidecar(ruta), {
                    "code": codigo, "medula": radio.get("medula", False),
                    "corteza": radio.get("corteza", False),
                    "anomalias": radio.get("anomalias", {}),
                })
        except Exception as exc:
            logger.error("Error al exportar: %s", exc)
            QMessageBox.critical(self, "Error", f"Fallo al exportar:\n{exc}")

    # -------------------------------------------------------------------------
    # Sidecar de anomalías  (.rwl.anom.json)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Estimación de anillos faltantes hacia la médula
    # -------------------------------------------------------------------------

    def _iniciar_estimacion_pith(self):
        """Abre el diálogo de configuración y activa el modo PITH."""
        # Limpieza defensiva: si por algún motivo quedaron items del modo
        # pith de una sesión anterior (incompleta, mal cancelada, etc.),
        # los borramos antes de empezar. Sin esto, los círculos/líneas/
        # texto naranjas anteriores se solapaban con los nuevos.
        if hasattr(self.vista, "_limpiar_items_pith"):
            self.vista._limpiar_items_pith()

        n_disponibles = len(self.datos_medidos)
        if n_disponibles < 3:
            QMessageBox.warning(self, "Pocos anillos",
                "Necesitas al menos 3 anillos medidos para usar esta función.")
            self.btn_pith.setChecked(False)
            return

        tiene_ref = (self.serie_maestra is not None
                     and not self.serie_maestra.empty)

        dlg = DialogoMetodoPith(
            tiene_referencia=tiene_ref,
            n_anillos_disponibles=n_disponibles,
            parent=self,
        )
        if dlg.exec() != DialogoMetodoPith.DialogCode.Accepted:
            self.btn_pith.setChecked(False)
            return

        self._pith_metodo    = dlg.metodo
        self._pith_n_int     = dlg.n_internos
        self._pith_usar_ref  = dlg.usar_referencia
        self._pith_dap_mm    = dlg.dap_mm
        self._pith_metodo_calculo = dlg.metodo_calculo  # 'rg', 'bai', 'promedio'

        if self._pith_metodo == "arco":
            self.set_modo(MODO_PITH)
            self.label_estado.setText(
                "🎯 Paso 1/3: Haz clic en un EXTREMO del arco del anillo más interno."
            )
        else:
            # DAP: no necesita marcado en imagen, calcular directamente
            self.btn_pith.setChecked(False)
            self._calcular_pith_por_dap()

    def _calcular_pith_por_dap(self):
        """Calcula la distancia faltante usando el DAP ingresado."""
        radio_mm    = self._pith_dap_mm / 2.0
        radio_px    = radio_mm * self.vista.pixeles_por_mm

        # Longitud del radio medido: distancia desde el primer punto hasta el último
        if len(self.vista.coordenadas_anillos) < 2:
            QMessageBox.warning(self, "Sin camino",
                "Necesitas tener puntos medidos en el camino activo.")
            return

        coords = self.vista.coordenadas_anillos
        longitud_medida_px = sum(
            math.hypot(coords[i][0]-coords[i-1][0], coords[i][1]-coords[i-1][1])
            for i in range(1, len(coords))
            if not self.vista.es_salto[i]
        )

        distancia_faltante_px = max(0.0, radio_px - longitud_medida_px)

        if distancia_faltante_px <= 0:
            QMessageBox.information(self, "Sin anillos faltantes",
                "La longitud medida ya cubre o supera el radio estimado por DAP.")
            return

        # Centro estimado: extrapolando desde el primer punto
        cx = coords[0][0]
        cy = coords[0][1]

        self._mostrar_dialogo_resultados_pith(
            cx, cy, radio_px, distancia_faltante_px, metodo="dap"
        )

    def _confirmar_estimacion_pith(self):
        """Confirma la estimación de pith por método arco.

        Llamado desde VistaInteractiva al presionar Enter en MODO_PITH.

        Algoritmo:
          1. La médula está en el centro del círculo ajustado (Duncan GM,
             1989): r = L²/(8h) + h/2 = radio del círculo por mínimos
             cuadrados a través de los puntos marcados.
          2. La distancia faltante es `dist(p_inner, centro)`: desde el
             primer anillo medido más cercano a la médula hasta el centro
             estimado. Esta es la métrica relevante INDEPENDIENTEMENTE
             de qué anillo marque el usuario — el arco marcado es solo
             la herramienta para localizar la médula.
          3. Los anillos faltantes se calculan en el diálogo de resultados
             usando RG (Altman 2016): anillos = distancia / promedio_ancho,
             donde el promedio viene de N anillos junto al arco marcado
             contando hacia la corteza.
        """
        resultado = self.vista._confirmar_pith()
        self.set_modo(MODO_MEDIR)
        self.btn_pith.setChecked(False)

        if resultado is None:
            return

        cx, cy, radio_px = resultado
        coords = self.vista.coordenadas_anillos

        if radio_px <= 0 or not coords:
            QMessageBox.warning(self, "Estimación inválida",
                "El círculo ajustado tiene radio 0. Verifica los puntos marcados.")
            return

        # p_inner según dirección de medición
        try:
            med_a_cor = self.combo_dir.currentIndex() == 0
        except Exception:
            med_a_cor = True

        if med_a_cor:
            p_inner = coords[0]
        else:
            p_inner = coords[-1] if len(coords) >= 2 else coords[0]

        # Distancia faltante = dist(p_inner, centro). NO usar radio.
        distancia_faltante_px = math.hypot(cx - p_inner[0], cy - p_inner[1])

        if distancia_faltante_px <= 0:
            QMessageBox.warning(self, "Estimación inválida",
                "El primer anillo medido coincide con la médula estimada.\n"
                "No hay anillos faltantes para estimar.")
            return

        self._mostrar_dialogo_resultados_pith(
            cx, cy, radio_px, distancia_faltante_px, metodo="arco"
        )

    def _mostrar_dialogo_resultados_pith(
        self,
        cx: float, cy: float,
        radio_px: float,
        distancia_faltante_px: float,
        metodo: str,
    ):
        """Calcula los resultados y muestra el diálogo de confirmación."""
        import math as _math

        n_int = getattr(self, '_pith_n_int', 5)
        usar_ref = getattr(self, '_pith_usar_ref', False)

        # Obtener los N anillos más internos (los primeros en la lista)
        # datos_medidos está ordenado médula→corteza
        med_a_cor = self.combo_dir.currentIndex() == 0
        dm = self.datos_medidos
        if med_a_cor:
            # Los más internos son los del inicio
            anchos_internos = [d["ancho_mm"] for d in dm[:n_int]]
            anio_inicio = dm[0]["anio"] if dm else None
        else:
            # Los más internos son los del final
            anchos_internos = [d["ancho_mm"] for d in dm[-n_int:]]
            anio_inicio = dm[-1]["anio"] if dm else None

        anchos_internos = [a for a in anchos_internos if a > 0]

        # Serie de referencia si está disponible y seleccionada
        serie_ref = None
        if usar_ref and self.serie_maestra is not None and not self.serie_maestra.empty:
            col = ("Ancho_mm" if "Ancho_mm" in self.serie_maestra.columns
                   else self.serie_maestra.columns[0])
            serie_ref = self.serie_maestra[col].dropna()

        resultados = estimar_anillos_faltantes(
            distancia_faltante_mm=distancia_faltante_px / self.vista.pixeles_por_mm,
            anchos_internos_mm=anchos_internos,
            serie_ref=serie_ref,
            anio_inicio_serie=anio_inicio,
        )

        if not resultados:
            QMessageBox.warning(self, "Sin resultados",
                "No se pudo calcular la estimación. Verifica los datos.")
            return

        tiene_ref = (serie_ref is not None)
        dlg = DialogoEstimacionPith(
            resultados=resultados,
            radio_px=radio_px,
            distancia_faltante_px=distancia_faltante_px,
            pixeles_por_mm=self.vista.pixeles_por_mm,
            n_anillos_internos=len(anchos_internos),
            tiene_referencia=tiene_ref,
            parent=self,
        )
        dlg.poblar_grafico(anchos_internos)
        dlg.aplicar_offset.connect(
            lambda n: self._aplicar_pith_offset(n, dlg.marcar_estimada, resultados, metodo,
                                                 radio_px / self.vista.pixeles_por_mm,
                                                 distancia_faltante_px / self.vista.pixeles_por_mm)
        )
        dlg.exec()

    def _aplicar_pith_offset(
        self,
        n_anillos: int,
        marcar_estimada: bool,
        resultados: dict,
        metodo: str,
        radio_mm: float,
        distancia_faltante_mm: float,
    ):
        """
        Aplica el offset: retrocede el año de médula en n_anillos.
        Actualiza el sidecar con la información de la estimación.
        """
        if n_anillos <= 0:
            return

        # Guardar estado previo para poder deshacer
        med_a_cor = self.combo_dir.currentIndex() == 0
        self._pith_undo = {
            "med_a_cor":        med_a_cor,
            "anio_medula_old":  self.spin_medula.value(),
            "anio_corteza_old": self.spin_corteza.value(),
            "medula_checked":   self.check_tiene_medula.isChecked(),
            "n_anillos":        n_anillos,
        }

        if med_a_cor:
            nuevo_anio_medula = self.spin_medula.value() - n_anillos
            self.spin_medula.setValue(nuevo_anio_medula)
        else:
            nuevo_anio_corteza = self.spin_corteza.value() + n_anillos
            self.spin_corteza.setValue(nuevo_anio_corteza)

        if marcar_estimada:
            self.check_tiene_medula.setChecked(True)

        # Guardar en el sidecar
        self._pith_estimacion = {
            "pith_estimated":       True,
            "pith_offset":          n_anillos,
            "pith_method":          metodo,
            "pith_radio_mm":        round(radio_mm, 2),
            "pith_distancia_mm":    round(distancia_faltante_mm, 2),
            "pith_n_media":         resultados.get("n_media"),
            "pith_n_tendencia":     resultados.get("n_tendencia"),
            "pith_n_referencia":    resultados.get("n_referencia"),
            "pith_ancho_medio":     resultados.get("ancho_medio"),
            "pith_rango_min":       resultados.get("incertidumbre_min"),
            "pith_rango_max":       resultados.get("incertidumbre_max"),
        }
        self._guardar_sidecar_anom()
        self._guardar_estado()

        dist = distancia_faltante_mm
        self.label_estado.setText(
            f"✅ Estimación aplicada: {n_anillos} anillos faltantes al centro · "
            f"distancia {dist:.1f} mm · año médula → {self.spin_medula.value()}"
        )
        self.btn_deshacer_pith.show()

    def _deshacer_pith_offset(self):
        """Revierte la última estimación de médula aplicada."""
        undo = getattr(self, "_pith_undo", None)
        if not undo:
            QMessageBox.information(self, "Nada que deshacer",
                "No hay estimación para revertir.")
            return

        resp = QMessageBox.question(
            self, "Deshacer estimación",
            f"¿Revertir la estimación de {undo['n_anillos']} anillos faltantes?\n"
            f"El año de médula volverá a su valor anterior.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Restaurar años
        self.spin_medula.setValue(undo["anio_medula_old"])
        self.spin_corteza.setValue(undo["anio_corteza_old"])
        self.check_tiene_medula.setChecked(undo["medula_checked"])

        # Limpiar estimación
        self._pith_estimacion = None
        self._pith_undo = None
        self.btn_deshacer_pith.hide()

        self._guardar_sidecar_anom()
        self._guardar_estado()
        self.vista.recalcular_todas_las_distancias()

        self.label_estado.setText(
            f"↩ Estimación revertida · "
            f"año médula → {self.spin_medula.value()}"
        )

    # -------------------------------------------------------------------------
    # Earlywood / Latewood
    # -------------------------------------------------------------------------

    def _eliminar_ewlw(self):
        """Elimina todos los límites EW/LW del radio activo tras confirmación."""
        n_ewlw = sum(1 for v in self.vista.es_salto if _es_ewlw(v))
        if n_ewlw == 0:
            QMessageBox.information(self, "Sin límites EW/LW",
                "No hay límites EW/LW en el radio activo.")
            return
        resp = QMessageBox.question(
            self, "Eliminar límites EW/LW",
            f"¿Eliminar los {n_ewlw} límite(s) EW/LW del radio activo?\n"
            "Esta acción se puede deshacer con Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.vista.guardar_en_historial()
        # Eliminar de atrás hacia adelante para no invalidar índices
        indices = [i for i, v in enumerate(self.vista.es_salto) if _es_ewlw(v)]
        for i in reversed(indices):
            self.vista.modelo_medicion.borrar(i)
        self.vista.recalcular_todas_las_distancias()
        self.vista.progreso_modificado.emit()
        self.label_estado.setText(
            f"🗑 {n_ewlw} límite(s) EW/LW eliminados. Ctrl+Z para deshacer.")

    def _detectar_ewlw_automatico(self):
        """Detecta EW/LW automáticamente en hilo separado.

        Bug histórico (causaba freezes y en un caso reinicio de la PC):
          1. cv2.imread() corría en el MAIN thread → bloqueaba la UI varios
             segundos en imágenes grandes (scanners a 2400dpi).
          2. No había protección contra doble clic → se podían lanzar varios
             workers concurrentes, cada uno con su propia copia del array
             gris en memoria (decenas/cientos de MB) → OOM kill.
          3. dlg.cancelado.connect(worker.terminate) — QThread.terminate()
             es UNSAFE según docs de Qt: para el thread sin limpiar
             recursos, puede corromper memoria si estaba en numpy/cv2.
          4. Re-leía la imagen del disco aunque self._img_bgr_original ya
             la tuviera cacheada en RAM.

        Fixes aplicados:
          - Si hay otro worker activo, mensaje y bail (sin lanzar segundo).
          - Reusa self._img_bgr_original cuando está disponible.
          - Mueve cv2.cvtColor también fuera del main thread.
          - Cancelación cooperativa con flag en vez de terminate().
          - Limpia self._ewlw_worker al terminar para liberar memoria.
        """
        # Protección contra doble lanzamiento — uno de los caminos al crash.
        worker_previo = getattr(self, "_ewlw_worker", None)
        if worker_previo is not None and worker_previo.isRunning():
            QMessageBox.information(
                self, "Detección en curso",
                "Ya se está ejecutando una detección de EW/LW.\n"
                "Espera a que termine o cancela el diálogo de progreso."
            )
            return

        if not self.vista.coordenadas_anillos or len(self.vista.coordenadas_anillos) < 2:
            QMessageBox.information(
                self, "Sin anillos",
                "No hay anillos marcados todavía. Marca al menos un anillo antes.")
            return

        # Capturar estado antes de lanzar el hilo
        coords = list(self.vista.coordenadas_anillos)
        saltos = list(self.vista.es_salto)
        banda  = self._bi_banda
        ruta   = self.ruta_imagen_actual
        # Usar la imagen cacheada si existe (común: ya cargada al abrir
        # la pestaña). Solo re-leemos del disco si por algún motivo no
        # está disponible.
        img_cached = self._img_bgr_original

        dlg = _DialogoProgreso("Detectando límites EW/LW", parent=self)
        # Flag de cancelación cooperativa — más seguro que terminate().
        # Se chequea dentro del loop principal de la función worker.
        cancel_flag = {"stop": False}
        dlg.show()

        def _tarea_ewlw(sig_prog, img_bgr, c, s, b, ruta_disco):
            """Ejecuta en thread secundario. NO toca widgets Qt directamente."""
            import cv2 as _cv2
            if img_bgr is None:
                # Fallback: leer del disco (solo si no está cacheada)
                img_bgr = _cv2.imread(ruta_disco, _cv2.IMREAD_COLOR)
                if img_bgr is None:
                    raise RuntimeError(
                        "No se pudo leer la imagen desde el disco para detectar EW/LW.")
            gray = _cv2.cvtColor(img_bgr, _cv2.COLOR_BGR2GRAY).astype(np.float32)
            return _calcular_ewlw_posiciones(
                sig_prog, gray, c, s, b, cancel_flag)

        worker = _Worker(_tarea_ewlw, img_cached, coords, saltos, banda, ruta)
        self._ewlw_worker = worker

        worker.signals.progreso.connect(dlg.actualizar)

        def _on_error(e):
            dlg.close()
            QMessageBox.critical(self, "Error EW/LW", e)
        worker.signals.error.connect(_on_error)

        def _on_ewlw(inserciones):
            """Callback que aplica los resultados del worker EW/LW.

            Bug arreglado (causaba el "crash al 99%"):
              - Antes: aplicaba TODAS las inserciones (incluso parciales
                de una cancelación) y llamaba redibujar_todo de forma
                sincrónica. Con 200+ inserts + redibujar el main thread
                quedaba freezeado varios segundos → usuario veía el
                progreso pegado al 99% y pensaba que crasheaba.
              - Ahora: (1) si se canceló, descarta los parciales sin
                aplicar nada; (2) si hay resultados, los aplica en
                chunks con QApplication.processEvents() entre chunks
                para que la UI responda; (3) muestra el estado del
                proceso en el diálogo ("Aplicando...", "Redibujando...")
                en vez de quedar 99% silencioso.
            """
            # ── Caso 1: el usuario canceló ──
            # Descartar parciales para no aplicar 200 EW/LW que no quería.
            if cancel_flag.get("stop"):
                try:
                    dlg.close()
                except Exception:
                    pass
                self.label_estado.setText(
                    "🛑 Detección EW/LW cancelada — sin cambios aplicados."
                )
                return

            # ── Caso 2: sin resultados ──
            if not inserciones:
                try:
                    dlg.close()
                except Exception:
                    pass
                self.label_estado.setText(
                    "🍂 No se encontraron límites EW/LW."
                )
                return

            if (self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos):
                dlg.close()
                self.label_estado.setText("Resultados EW/LW descartados: cambió el radio.")
                return

            # ── Caso 3: aplicar resultados ──
            # Actualizar el diálogo para indicar la fase de aplicación.
            # El diálogo sigue VISIBLE durante esta fase para que el
            # usuario sepa que el programa está trabajando, no crasheado.
            try:
                if hasattr(dlg, "_bar"):
                    dlg._bar.setValue(100)
                if hasattr(dlg, "_lbl"):
                    dlg._lbl.setText(
                        f"Aplicando {len(inserciones)} límites EW/LW…")
                QApplication.processEvents()
            except Exception:
                pass

            # processEvents puede haber atendido una cancelación o edición.
            if (cancel_flag.get("stop") or self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos):
                dlg.close()
                return
            # Preparar todos los cambios fuera del modelo activo.
            puntos = list(self.vista.modelo_medicion.captura())
            try:
                for insert_at, px_ins, py_ins in reversed(inserciones):
                    if not 0 <= insert_at <= len(puntos):
                        raise ValueError("Índice de inserción inválido")
                    puntos.insert(insert_at, PuntoMedicion((px_ins, py_ins), "ew_lw"))
            except (ValueError, TypeError, IndexError) as exc:
                dlg.close()
                QMessageBox.warning(self, "EW/LW", str(exc))
                return
            self.vista.guardar_en_historial()
            self.vista.modelo_medicion.restaurar(puntos)
            self.vista.recalcular_todas_las_distancias()
            self.vista.progreso_modificado.emit()

            # Cerrar el diálogo SOLO cuando todo terminó.
            try:
                dlg.close()
            except Exception:
                pass
            self.label_estado.setText(
                f"🍂 EW/LW automático: {len(inserciones)} límites insertados. "
                "Usa 🖐 Mover para ajustar."
            )

        worker.signals.resultado.connect(_on_ewlw)

        def _on_cancel():
            """Cancelación segura: setea flag, el worker termina en próxima
            iteración del loop. Mucho más seguro que worker.terminate()."""
            cancel_flag["stop"] = True
            dlg._lbl.setText("Cancelando... espera a que termine la iteración actual.")

        dlg.cancelado.connect(_on_cancel)
        worker.start()
        return

        # — CÓDIGO SÍNCRONO ORIGINAL ELIMINADO (reemplazado por _calcular_ewlw_posiciones) —
        h, w = gray_img.shape
        n = len(coords)
        ppm = self.vista.pixeles_por_mm
        banda_unused = banda  # mantenido para compatibilidad

        # Recopilar anillos: cada anillo es lista de índices entre dos False
        anillos = []
        ini = 0
        for i in range(1, n):
            if saltos[i] is False:
                anillos.append(list(range(ini, i + 1)))
                ini = i
        # Ultimo anillo abierto
        if ini < n - 1:
            anillos.append(list(range(ini, n)))

        self.vista.guardar_en_historial()
        insertar_count = 0

        # Procesar de atrás hacia adelante para no invalidar índices
        for anillo_idxs in reversed(anillos):
            if len(anillo_idxs) < 3:
                continue
            # Verificar que no haya ya un ew_lw en este anillo
            tiene_ewlw = any(
                _es_ewlw(saltos[j]) for j in anillo_idxs[1:]
                if j < len(saltos)
            )
            if tiene_ewlw:
                continue

            # Extraer perfil de intensidad gris a lo largo del anillo
            perfil = []
            posiciones_px = []   # posición acumulada en px
            acum = 0.0
            for k in range(1, len(anillo_idxs)):
                idx_prev = anillo_idxs[k - 1]
                idx_curr = anillo_idxs[k]
                if idx_curr >= n:
                    break
                val_k = saltos[idx_curr] if idx_curr < len(saltos) else False
                if _es_amarillo(val_k):
                    continue  # saltar quiebres/espacios

                x0, y0 = coords[idx_prev]
                x1, y1 = coords[idx_curr]
                seg_len = math.hypot(x1 - x0, y1 - y0)
                if seg_len < 1:
                    continue

                ux = (x1 - x0) / seg_len
                uy = (y1 - y0) / seg_len
                perp_x, perp_y = -uy, ux
                n_s = max(2, int(seg_len))
                ts = np.linspace(0, 1, n_s)

                xs_c = x0 + ts * (x1 - x0)
                ys_c = y0 + ts * (y1 - y0)

                vals_seg = []
                for off in range(-banda, banda + 1):
                    xs = xs_c + off * perp_x
                    ys = ys_c + off * perp_y
                    mask = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
                    xi = xs[mask].astype(int)
                    yi = ys[mask].astype(int)
                    if len(xi):
                        vals_seg.extend(gray[yi, xi].tolist())

                if vals_seg:
                    perfil_seg = np.mean(vals_seg) if vals_seg else 128.0
                else:
                    perfil_seg = 128.0

                # Guardar una muestra por unidad de px a lo largo del segmento
                for j, t_j in enumerate(np.linspace(0, 1, n_s)):
                    px_j = x0 + t_j * (x1 - x0)
                    py_j = y0 + t_j * (y1 - y0)
                    perfil.append(perfil_seg)
                    posiciones_px.append((acum + j, px_j, py_j, idx_prev, idx_curr, t_j))
                acum += n_s

            if len(perfil) < 5:
                continue

            # Segunda derivada del perfil suavizado
            arr = np.array(perfil, dtype=float)
            # Suavizar antes de derivar
            from scipy.signal import savgol_filter
            if len(arr) > 7:
                arr = savgol_filter(arr, min(11, len(arr) if len(arr) % 2 == 1
                                             else len(arr) - 1), 2)
            d2 = np.gradient(np.gradient(arr))
            # El mínimo de d2 = mayor tasa de cambio (paso EW→LW oscuro)
            # Rango asimétrico: 15% desde médula (inicio EW) y 5% desde corteza
            # (fin LW). Esto captura latewood muy delgado sin tocar los límites.
            margen_ini = max(1, int(len(arr) * 0.15))   # 15% lado médula
            margen_fin = max(1, int(len(arr) * 0.05))   # 5%  lado corteza
            d2_sub = d2[margen_ini:-margen_fin]
            if len(d2_sub) == 0:
                continue
            idx_min = int(np.argmin(d2_sub)) + margen_ini
            _, px_ins, py_ins, idx_seg_prev, idx_seg_curr, t_ins = posiciones_px[idx_min]

            # Insertar punto "ew_lw" entre idx_seg_prev e idx_seg_curr
            # (usar idx_seg_curr como posición de inserción)
            insert_at = idx_seg_curr
            self.vista.modelo_medicion.insertar(insert_at, (px_ins, py_ins), "ew_lw")
            insertar_count += 1
            # Actualizar coords/saltos locales para los siguientes anillos
            coords = list(self.vista.coordenadas_anillos)
            saltos = list(self.vista.es_salto)
            n = len(coords)

        self.vista.recalcular_todas_las_distancias()
        self.vista.progreso_modificado.emit()
        self.label_estado.setText(
            f"🍂 EW/LW automático: {insertar_count} límites insertados. "
            "Usa 🖐 Mover para ajustar.")

    def _exportar_ewlw(self, codigo: str, ruta_base: str,
                        coords: list | None = None,
                        saltos: list | None = None,
                        datos_medidos: list | None = None):
        """
        Genera codigo_ew.rwl y codigo_lw.rwl con los anchos de earlywood
        y latewood.

        Si coords/saltos/datos_medidos vienen explícitos, los usa (caso
        común: exportar un radio guardado). Si no vienen, cae al estado
        de la vista activa (caso: exportar el radio en progreso).

        Bug histórico: antes siempre leía self.vista.coordenadas_anillos
        y self.vista.es_salto, ignorando el radio que el usuario estaba
        exportando. Si el usuario exportaba un radio guardado pero la
        vista activa estaba vacía, tiene_ewlw era False y nunca se
        generaban los archivos _ew/_lw.
        """
        # Usar parámetros explícitos si se pasaron, si no caer a la vista
        if coords is None:
            coords = self.vista.coordenadas_anillos
        if saltos is None:
            saltos = self.vista.es_salto
        if datos_medidos is None:
            datos_medidos = self.datos_medidos

        if not datos_medidos:
            return

        n = len(coords)
        ppm = self.vista.pixeles_por_mm
        med_a_cor = self.combo_dir.currentIndex() == 0

        anios_ew, anchos_ew = [], []
        anios_lw, anchos_lw = [], []

        acum_ew = 0.0
        acum_lw = 0.0
        en_lw = False
        anio_actual = datos_medidos[0]["anio"] if datos_medidos else 0
        anillo_idx = 0

        for i in range(1, n):
            val = saltos[i]
            d = math.hypot(coords[i][0]-coords[i-1][0],
                           coords[i][1]-coords[i-1][1]) / ppm

            if val is True:  # salto
                acum_ew = acum_lw = 0.0
                en_lw = False
                continue
            if _es_espacio(val):
                continue
            if _es_ewlw(val):
                en_lw = True
                if d > 0:
                    acum_lw = 0.0  # reiniciar LW desde aquí
                continue
            if val is False:
                # Fin de anillo
                if en_lw:
                    acum_lw += d
                else:
                    acum_ew += d

                # ¿El siguiente es un límite de anillo o fin?
                val_next = saltos[i + 1] if i + 1 < n else False
                if val_next is False or i == n - 1:
                    if anillo_idx < len(datos_medidos):
                        anio = datos_medidos[anillo_idx]["anio"]
                        anios_ew.append(anio)
                        anchos_ew.append(acum_ew)
                        anios_lw.append(anio)
                        anchos_lw.append(acum_lw)
                        anillo_idx += 1
                    acum_ew = acum_lw = 0.0
                    en_lw = False
                else:
                    if en_lw:
                        acum_lw += d
                    else:
                        acum_ew += d
                continue

            # Tramo normal (también acumula según estado EW/LW)
            if en_lw:
                acum_lw += d
            else:
                acum_ew += d

        if not anios_ew:
            return

        import os
        dir_base = os.path.dirname(ruta_base)
        nombre_base = os.path.splitext(os.path.basename(ruta_base))[0]

        from constantes import TUCSON_MAX_CHARS_ID

        for sufijo, anios, anchos in [("ew", anios_ew, anchos_ew),
                                       ("lw", anios_lw, anchos_lw)]:
            ruta_rwl = os.path.join(dir_base, f"{nombre_base}_{sufijo}.rwl")
            try:
                mediciones_int = [int(round(a * 1000)) for a in anchos]
                ExportadorDendro._escribir_tucson(
                    f"{codigo[:7]}{sufijo[0]}", anios[0], mediciones_int, ruta_rwl, anios=anios
                )
            except Exception as exc:
                logger.warning("Error escribiendo %s: %s", ruta_rwl, exc)

    # -------------------------------------------------------------------------
    # Blue / Red / Green Intensity
    # -------------------------------------------------------------------------

    def _configurar_bi(self):
        """Abre el diálogo de configuración de la extracción de intensidad."""
        dlg = DialogoConfigBI(
            banda_actual=self._bi_banda,
            canales_activos=self._bi_canales,
            porcentaje=self._bi_porcentaje,
            alineacion=self._bi_alineacion,
            canal_vis=self._bi_canal_vis,
            parent=self,
        )
        if dlg.exec():
            self._bi_banda       = dlg.banda
            self._bi_canales     = dlg.canales
            self._bi_porcentaje  = dlg.porcentaje
            self._bi_alineacion  = dlg.alineacion
            self._bi_canal_vis   = dlg.canal_vis
            # Redibujar banda si está activa
            if self.btn_mostrar_banda.isChecked():
                self._dibujar_banda_bi()

    def _calcular_bi(self):
        """Calcula BI/GI/RI en hilo separado con barra de progreso."""
        if not self.datos_medidos:
            QMessageBox.information(self, "Sin mediciones",
                "Mide al menos un anillo antes de calcular la intensidad.")
            return

        # Protección contra doble lanzamiento (mismo problema que en EW/LW:
        # múltiples workers concurrentes con copias de la imagen llevan a OOM
        # y posible crash del sistema).
        worker_previo = getattr(self, "_bi_worker", None)
        if worker_previo is not None and worker_previo.isRunning():
            QMessageBox.information(
                self, "Cálculo en curso",
                "Ya se está ejecutando un cálculo de intensidad.\n"
                "Espera a que termine.")
            return

        # Asegurar que haya canales activos (si el usuario no configuró, usar todos)
        if not self._bi_canales:
            self._bi_canales = ["B", "G", "R", "Gray"]

        ruta = getattr(self, "ruta_imagen_actual", None)
        if not ruta:
            QMessageBox.warning(self, "Sin imagen",
                "No hay imagen cargada para extraer la intensidad.")
            return

        # Usar imagen cacheada si está disponible — evita re-leer del disco
        img_bgr = self._img_bgr_original
        if img_bgr is None:
            img_bgr = cv2.imread(ruta, cv2.IMREAD_COLOR)
            if img_bgr is None:
                QMessageBox.critical(self, "Error",
                    "No se pudo leer la imagen para extraer la intensidad.")
                return

        # Capturar estado en este momento (el worker corre en otro hilo)
        coords   = list(self.vista.coordenadas_anillos)
        saltos   = list(self.vista.es_salto)
        ppm      = self.vista.pixeles_por_mm
        banda    = self._bi_banda
        canales  = list(self._bi_canales)
        anios_capturados = [d["anio"] for d in self.datos_medidos]
        n_anillos = len(anios_capturados)

        dlg = _DialogoProgreso("Calculando intensidad de color", parent=self)
        dlg.show()

        pct_calculo  = self._bi_porcentaje / 100.0
        alin_calculo = self._bi_alineacion

        def _tarea(sig_prog, img, c, s, p, b, ch, pct, alin):
            return extraer_intensidad_por_anillo(
                signal_progreso=sig_prog,
                imagen_bgr=img,
                coordenadas=c,
                es_salto=s,
                pixeles_por_mm=p,
                banda_px=b,
                canales=ch,
                porcentaje=pct,
                alineacion=alin,
            )

        worker = _Worker(_tarea, img_bgr, coords, saltos, ppm, banda, canales,
                          pct_calculo, alin_calculo)
        self._bi_worker = worker  # evitar que el GC lo destruya

        worker.signals.progreso.connect(dlg.actualizar)

        def _on_error(e):
            dlg.close()
            QMessageBox.critical(self, "Error al calcular BI", e)
        worker.signals.error.connect(_on_error)

        def _on_resultado(resultados):
            dlg.close()
            if (self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos
                    or self.vista.pixeles_por_mm != ppm
                    or [d["anio"] for d in self.datos_medidos] != anios_capturados):
                self.label_estado.setText("Resultados BI descartados: cambió el radio.")
                return
            for k in range(min(len(resultados), n_anillos)):
                resultados[k]["anio"] = anios_capturados[k]
            self._bi_datos = resultados
            self.btn_guardar_bi.setEnabled(bool(resultados))
            self.btn_graficar_bi.setEnabled(bool(resultados))
            self.label_estado.setText(
                f"🎨 {len(resultados)} anillos · banda {banda}px · "
                f"canales: {', '.join(canales)}")

        worker.signals.resultado.connect(_on_resultado)

        def _on_cancel():
            """Cancelación segura: cierra el diálogo y desconecta callbacks,
            pero deja al worker terminar en silencio. NO usa terminate()
            porque interrumpir un thread con cv2/numpy en pleno cálculo
            puede corromper memoria o reiniciar el sistema."""
            try:
                worker.signals.resultado.disconnect()
                worker.signals.error.disconnect()
                worker.signals.progreso.disconnect()
            except (TypeError, RuntimeError):
                pass
            dlg.close()
            self.label_estado.setText(
                "Cálculo BI cancelado (terminará silenciosamente en background).")

        dlg.cancelado.connect(_on_cancel)
        worker.start()

    # ── Banda de muestreo BI sobre la imagen ─────────────────────────────
    def _toggle_banda_bi(self, activo: bool):
        """Muestra u oculta la banda de muestreo BI sobre la imagen."""
        if activo:
            self._dibujar_banda_bi()
        else:
            self._limpiar_banda_bi()

    def _dibujar_banda_bi(self):
        """
        Dibuja el área de muestreo BI sobre la imagen.

        Para cada anillo (entre dos límites False consecutivos):
          - Dibuja un polígono por columna de píxeles, coloreado con
            la intensidad real del canal elegido.
          - Sigue la curvatura exacta del camino.
          - Respeta el porcentaje y alineación configurados.
        """
        self._limpiar_banda_bi()

        ruta = getattr(self, "ruta_imagen_actual", None)
        if not ruta:
            return
        img_bgr = cv2.imread(ruta, cv2.IMREAD_COLOR)
        if img_bgr is None:
            return

        import cv2 as _cv2
        from PyQt6.QtGui import QPolygonF, QColor as QC
        from PyQt6.QtCore import QPointF

        canal = self._bi_canal_vis
        if canal == "B":
            ch_img = img_bgr[:, :, 0].astype(np.float32)
            def _rgba(v): return QC(int(v*0.25), int(v*0.55), int(v), 210)
        elif canal == "G":
            ch_img = img_bgr[:, :, 1].astype(np.float32)
            def _rgba(v): return QC(0, int(v), 0, 210)
        elif canal == "R":
            ch_img = img_bgr[:, :, 2].astype(np.float32)
            def _rgba(v): return QC(int(v), 0, 0, 210)
        else:
            ch_img = _cv2.cvtColor(img_bgr, _cv2.COLOR_BGR2GRAY).astype(np.float32)
            def _rgba(v): return QC(int(v), int(v), int(v), 210)

        h_img, w_img = ch_img.shape

        color_borde = {"B": "#4488FF", "G": "#44BB44",
                       "R": "#FF4444", "Gray": "#AAAAAA"}[canal]
        pen_borde = QPen(QColor(color_borde))
        pen_borde.setCosmetic(True)
        pen_borde.setWidthF(1.0)
        pen_sin = QPen(Qt.PenStyle.NoPen)

        coords = self.vista.coordenadas_anillos
        saltos = self.vista.es_salto
        banda  = self._bi_banda
        pct    = self._bi_porcentaje / 100.0
        alin   = self._bi_alineacion
        n      = len(coords)
        if n < 2:
            return

        escena = self.vista.scene()
        items  = []

        # ── Recopilar anillos ────────────────────────────────────────────
        # Un anillo es la lista de segmentos entre dos límites False
        def _recopilar_anillos():
            """
            Cada anillo = todos los segmentos entre dos límites False.
            Los segmentos ew_lw son parte del anillo (no lo cierran).
            Los quiebres/espacios se saltan pero no cierran el anillo.
            Los saltos reales (True) descartan el acumulado.
            """
            anillos = []
            segs = []
            for i in range(1, n):
                val = saltos[i] if i < len(saltos) else False
                if val is True:        # salto real: descartar y reiniciar
                    segs = []
                    continue
                if _es_espacio(val):   # quiebre/espacio: no cuenta como segmento
                    continue
                # Segmento normal (False) o ew_lw: añadir al anillo actual
                segs.append((i-1, i))
                # Solo cerrar el anillo en el límite final (val is False)
                # ew_lw NO cierra el anillo — es interno
                if val is False:
                    if segs:
                        anillos.append(list(segs))
                    segs = []
                # Nota: val == "ew_lw" → continúa acumulando en el mismo anillo
            if segs:
                anillos.append(segs)
            return anillos

        anillos = _recopilar_anillos()

        for segs in anillos:
            if not segs:
                continue

            # Calcular longitud total
            long_total = sum(
                math.hypot(coords[ic][0]-coords[ip][0],
                           coords[ic][1]-coords[ip][1])
                for ip, ic in segs
            )
            if long_total < 2:
                continue

            # Rango de longitud a visualizar según alineación
            recorte = 1.0 - pct
            if alin == "ew":
                l_ini, l_fin = 0.0, long_total * pct
            elif alin == "lw":
                l_ini, l_fin = long_total * recorte, long_total
            else:
                m = recorte / 2.0
                l_ini, l_fin = long_total * m, long_total * (1.0 - m)

            # ── Construir columnas pixel a pixel ─────────────────────────
            # Paso 1: recopilar todos los valores y posiciones del anillo
            cols_vals = []   # valor medio del canal en cada columna
            cols_pts  = []   # (sup, inf) QPointF para cada columna
            cols_activa = [] # bool: está dentro del rango l_ini..l_fin

            acum = 0.0
            for ip, ic in segs:
                x0, y0 = coords[ip]
                x1, y1 = coords[ic]
                seg_len = math.hypot(x1-x0, y1-y0)
                if seg_len < 1:
                    continue
                ux = (x1-x0)/seg_len; uy = (y1-y0)/seg_len
                perp_x, perp_y = -uy, ux

                n_s = max(2, int(round(seg_len)))
                for j in range(n_s):
                    t_j   = j / max(1, n_s-1)
                    pos_j = acum + j * (seg_len / max(1, n_s-1))
                    cx = x0 + t_j*(x1-x0)
                    cy = y0 + t_j*(y1-y0)
                    sup = QPointF(cx + banda*perp_x, cy + banda*perp_y)
                    inf = QPointF(cx - banda*perp_x, cy - banda*perp_y)

                    activa = l_ini <= pos_j <= l_fin
                    if activa:
                        offs = np.arange(-banda, banda+1)
                        xs = np.clip(cx + offs*perp_x, 0, w_img-1).astype(np.int32)
                        ys = np.clip(cy + offs*perp_y, 0, h_img-1).astype(np.int32)
                        cols_vals.append(float(ch_img[ys, xs].mean()))
                    else:
                        cols_vals.append(None)
                    cols_pts.append((sup, inf))
                    cols_activa.append(activa)
                acum += seg_len

            if not any(cols_activa):
                continue

            # Paso 2: normalizar al rango del anillo para maximizar contraste
            vals_activos = [v for v in cols_vals if v is not None]
            v_min = min(vals_activos)
            v_max = max(vals_activos)
            v_rng = v_max - v_min if v_max > v_min else 1.0

            # Paso 3: dibujar polígono por columna con color normalizado
            prev_pts = None
            for k, (sup, inf) in enumerate(cols_pts):
                if not cols_activa[k]:
                    prev_pts = None
                    continue
                # Normalizar al rango 40-255 para que siempre se vea algo
                v_norm = 40 + int(215 * (cols_vals[k] - v_min) / v_rng)
                color = _rgba(v_norm)
                brush = QBrush(color)

                if prev_pts is not None:
                    p_sup_ant, p_inf_ant = prev_pts
                    poly = QPolygonF([p_sup_ant, sup, inf, p_inf_ant])
                    item = escena.addPolygon(poly, pen_sin, brush)
                    item.setZValue(5)
                    items.append(item)
                prev_pts = (sup, inf)

            # Borde exterior del área (polígono de contorno)
            # Reconstruir los puntos del borde para el contorno
            acum = 0.0
            pts_sup, pts_inf = [], []
            for ip, ic in segs:
                x0, y0 = coords[ip]
                x1, y1 = coords[ic]
                seg_len = math.hypot(x1-x0, y1-y0)
                if seg_len < 1:
                    continue
                ux = (x1-x0)/seg_len; uy = (y1-y0)/seg_len
                perp_x, perp_y = -uy, ux
                n_s = max(2, int(round(seg_len)))
                for j in range(n_s):
                    t_j   = j / max(1, n_s-1)
                    pos_j = acum + j*(seg_len/max(1, n_s-1))
                    if pos_j < l_ini or pos_j > l_fin:
                        continue
                    cx = x0 + t_j*(x1-x0)
                    cy = y0 + t_j*(y1-y0)
                    pts_sup.append(QPointF(cx + banda*perp_x, cy + banda*perp_y))
                    pts_inf.append(QPointF(cx - banda*perp_x, cy - banda*perp_y))
                acum += seg_len

            if len(pts_sup) >= 2:
                poly_borde = QPolygonF(pts_sup + list(reversed(pts_inf)))
                borde = escena.addPolygon(
                    poly_borde, pen_borde, QBrush(Qt.BrushStyle.NoBrush))
                borde.setZValue(6)
                items.append(borde)

        self._items_banda_bi = items

    def _limpiar_banda_bi(self):
        """Elimina los marcadores de banda del escenario."""
        for item in getattr(self, "_items_banda_bi", []):
            try:
                self.vista.scene().removeItem(item)
            except Exception:
                pass
        self._items_banda_bi = []

    def _graficar_bi_ventana(self):
        """Abre una ventana independiente con el gráfico de BI/GI/RI con zoom."""
        if not self._bi_datos:
            return

        anios = [d.get("anio", i) for i, d in enumerate(self._bi_datos)]
        colores = {"B": "#4488FF", "G": "#44BB44", "R": "#FF4444", "Gray": "#AAAAAA"}
        estilos = {
            "mean": (Qt.PenStyle.SolidLine,  "Promedio"),
            "min":  (Qt.PenStyle.DashLine,   "Mínimo"),
            "max":  (Qt.PenStyle.DotLine,    "Máximo"),
        }

        win = QDialog(self)
        win.setWindowTitle("Intensidad de color — BI/GI/RI/GrayI")
        win.resize(900, 450)
        lay = QVBoxLayout(win)

        pw = pg.PlotWidget()
        _gr.aplicar_a_pyqtgraph(pw)
        pw.showGrid(x=True, y=True, alpha=0.3)
        pw.setLabel("bottom", "Año")
        pw.setLabel("left",   "Intensidad (0-255)")
        pw.setYRange(0, 255, padding=0.05)
        pw.addLegend(offset=(10, 10))
        pw.setMouseEnabled(x=True, y=True)
        lay.addWidget(pw)

        from PyQt6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout as QHL
        chks_canal: dict[str, QCheckBox] = {}
        chks_met:   dict[str, QCheckBox] = {}

        def _reconstruir():
            pw.clear()
            pw.addLegend(offset=(10, 10))
            for canal, chk_c in chks_canal.items():
                if not chk_c.isChecked():
                    continue
                color = colores.get(canal, "#888888")
                for met, (estilo, etiq) in estilos.items():
                    if not chks_met[met].isChecked():
                        continue
                    key = f"{canal}_{met}"
                    vals = [d.get(key) for d in self._bi_datos if key in d]
                    if not vals or len(vals) != len(anios):
                        continue
                    pw.plot(anios, vals,
                            pen=pg.mkPen(color,
                                         width=2.0 if met == "mean" else 1.0,
                                         style=estilo),
                            name=f"{canal} {etiq}")

        fila = QHL()
        grp_c = QGroupBox("Canales")
        lay_c = QHL(grp_c)
        for canal in ["B", "G", "R", "Gray"]:
            chk = QCheckBox(canal)
            chk.setChecked(canal in self._bi_canales)
            chk.toggled.connect(_reconstruir)
            lay_c.addWidget(chk)
            chks_canal[canal] = chk
        fila.addWidget(grp_c)

        grp_m = QGroupBox("Métricas")
        lay_m = QHL(grp_m)
        for met, etiq in [("mean","Promedio"), ("min","Mínimo"), ("max","Máximo")]:
            chk = QCheckBox(etiq)
            chk.setChecked(True)
            chk.toggled.connect(_reconstruir)
            lay_m.addWidget(chk)
            chks_met[met] = chk
        fila.addWidget(grp_m)
        fila.addStretch()
        lay.addLayout(fila)

        _reconstruir()
        win.show()
        self._bi_ventana = win   # evitar GC

    def _guardar_bi(self):
        """
        Abre el diálogo de selección de métricas y guarda en el formato
        elegido por la extensión del archivo:
          • .rwl       → un archivo Tucson por canal×métrica
          • .xlsx      → un Excel multi-columna con todas las series
          • .csv/.txt  → un texto multi-columna con coma decimal
        """
        if not self._bi_datos:
            QMessageBox.information(self, "Sin datos",
                "Primero calcula la intensidad con el botón 🎨 Calcular BI.")
            return
 
        # 1. Diálogo de selección de canales y métricas
        dlg = DialogoGuardarBI(
            canales_calculados=self._bi_canales,
            parent=self,
        )
        if dlg.exec() != DialogoGuardarBI.DialogCode.Accepted:
            return
 
        seleccion = dlg.seleccion
        if not seleccion:
            QMessageBox.information(self, "Sin selección",
                "No se seleccionó ningún canal/métrica para exportar.")
            return
 
        # 2. Selector de archivo con formato
        codigo = self.input_codigo.text().strip() or "serie"
        ruta_default = os.path.join(_ultima_carpeta(), f"{codigo}_bi.txt")
 
        ruta, filtro = QFileDialog.getSaveFileName(
            self, "Guardar intensidad de color",
            ruta_default,
            "Texto multi-columna (*.txt);;"
            "CSV multi-columna (*.csv);;"
            "Excel multi-columna (*.xlsx);;"
            "Tucson — un archivo por canal (*.rwl)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
 
        _ultima_carpeta(ruta)
        ext = os.path.splitext(ruta)[1].lower()
        if not ext:
            # Si no escribieron extensión, deducir del filtro
            if "rwl" in filtro:
                ruta += ".rwl"
                ext = ".rwl"
            elif "csv" in filtro:
                ruta += ".csv"
                ext = ".csv"
            elif "xlsx" in filtro:
                ruta += ".xlsx"
                ext = ".xlsx"
            else:
                ruta += ".txt"
                ext = ".txt"
 
        anios = [d.get("anio", i) for i, d in enumerate(self._bi_datos)]
        if not anios:
            return
 
        try:
            if ext == ".rwl":
                self._exportar_bi_tucson(ruta, anios, seleccion)
            else:
                self._exportar_bi_multicolumna(ruta, ext, anios, seleccion, codigo)
        except Exception as exc:
            logger.error("Error al exportar BI: %s", exc)
            QMessageBox.critical(self, "Error",
                                 f"Fallo al exportar:\n{exc}")
 
    def _exportar_bi_tucson(self, ruta: str, anios: list, seleccion: list):
        """Genera un .rwl Tucson por cada (canal, métrica)."""
        codigo = self.input_codigo.text().strip() or "serie"
        directorio = os.path.dirname(ruta)
        base = os.path.splitext(os.path.basename(ruta))[0]
        # Si terminaba en "_bi", quitarlo para evitar duplicación
        if base.lower().endswith("_bi"):
            base = base[:-3]
 
        escritos = []
        errores = []
 
        for canal, met in seleccion:
            if canal in ("B_R", "B_G"):
                canal2 = "R" if canal == "B_R" else "G"
                vals_b = [d.get("B_mean", 0.0) for d in self._bi_datos]
                vals_x = [d.get(f"{canal2}_mean", 1.0) for d in self._bi_datos]
                vals_ratio = [b / x if x > 0 else 0.0
                              for b, x in zip(vals_b, vals_x)]
                r_max = max(vals_ratio) if vals_ratio else 1.0
                vals_norm = [v / r_max for v in vals_ratio]
                suf = canal.lower().replace("_", "div")
            else:
                key = f"{canal}_{met}"
                vals = [d.get(key, 0.0) for d in self._bi_datos]
                vals_norm = [v / 255.0 for v in vals]
                suf = f"{canal.lower()}_{met}"
 
            nombre_archivo = f"{base}_{suf}.rwl"
            ruta_rwl = os.path.join(directorio, nombre_archivo)
            try:
                escribir_rwl_intensidad(
                    codigo=f"{codigo[:6]}{canal[:1].lower()}{met[:1] if met else ''}",
                    anio_inicio=anios[0],
                    valores=vals_norm,
                    ruta=ruta_rwl,
                )
                escritos.append(nombre_archivo)
            except Exception as exc:
                errores.append(f"{nombre_archivo}: {exc}")
 
        msg = f"✅ Guardados {len(escritos)} archivos Tucson en:\n{directorio}"
        if escritos:
            msg += "\n\n" + "\n".join(f"  • {f}" for f in escritos)
        if errores:
            msg += "\n\n⚠ Errores:\n" + "\n".join(errores)
        QMessageBox.information(self, "Guardado completado", msg)
 
    def _exportar_bi_multicolumna(self, ruta: str, ext: str, anios: list,
                                    seleccion: list, codigo: str):
        """Genera un solo archivo Excel/CSV/TXT con todas las series como columnas."""
        # Construir DataFrame con una columna por cada (canal, métrica)
        data = {"Anio": anios}
        for canal, met in seleccion:
            if canal in ("B_R", "B_G"):
                canal2 = "R" if canal == "B_R" else "G"
                vals_b = [d.get("B_mean", 0.0) for d in self._bi_datos]
                vals_x = [d.get(f"{canal2}_mean", 1.0) for d in self._bi_datos]
                col_name = f"{canal2}div"  # rdiv, gdiv
                col_label = f"B_{canal2}_ratio"
                vals = [b / x if x > 0 else 0.0
                        for b, x in zip(vals_b, vals_x)]
                data[col_label] = vals
            else:
                key = f"{canal}_{met}"
                vals = [d.get(key, 0.0) for d in self._bi_datos]
                col_label = f"{canal}_{met}"
                data[col_label] = vals
 
        df = pd.DataFrame(data)
 
        if ext == ".xlsx":
            _escribir_excel(df, ruta)
        elif ext == ".csv":
            # CSV chileno: separador ; y decimal con coma
            df.to_csv(ruta, index=False, sep=";", decimal=",",
                      float_format="%.6f")
        else:  # .txt
            df.to_csv(ruta, index=False, sep="\t", decimal=",",
                      float_format="%.6f")
 
        n_cols = len(df.columns) - 1  # restar la columna Anio
        QMessageBox.information(
            self, "✅ Exportación completada",
            f"Archivo guardado:\n{ruta}\n\n"
            f"Formato: multi-columna ({n_cols} series)\n"
            f"Filas: {len(df)} años\n"
            f"Columnas: Anio + {n_cols} canales/métricas"
        )
 

    def _ruta_sidecar(self, ruta_rwl: str | None = None) -> str | None:
        """Devuelve la ruta del archivo sidecar (oculto) para el radio exportado más reciente."""
        ruta = ruta_rwl or getattr(self, '_ultima_ruta_exportada', None)
        if not ruta:
            return None
        directorio = os.path.dirname(ruta)
        nombre = os.path.basename(ruta)
        return os.path.join(directorio, f".{nombre}.anom.json")

    def _guardar_sidecar_anom(self, ruta_rwl: str | None = None):
        """Escribe el .anom.json con anomalías + metadata del radio activo."""
        ruta_s = self._ruta_sidecar(ruta_rwl)
        if not ruta_s:
            return  # No hay ruta — silencioso (serie aún no exportada)
        try:
            datos = {
                "code":    self.input_codigo.text().strip(),
                "medula":  self.check_tiene_medula.isChecked(),
                "corteza": self.check_tiene_corteza.isChecked(),
                "anomalias": {
                    str(anio): tipo
                    for anio, tipo in self.vista.anomalias.items()
                },
            }
            # Agregar datos de estimación de médula si existen
            pith_est = getattr(self, "_pith_estimacion", None)
            if pith_est:
                datos.update(pith_est)
            _js.guardar_json(ruta_s, datos)
        except Exception as e:
            logger.warning("No se pudo guardar sidecar: %s", e)

    def _cargar_sidecar_anom(self, ruta_rwl: str):
        """Lee el .anom.json (oculto) y carga anomalías + checkboxes si existe."""
        directorio = os.path.dirname(ruta_rwl)
        nombre = os.path.basename(ruta_rwl)
        ruta_s = os.path.join(directorio, f".{nombre}.anom.json")
        # Retrocompatibilidad: buscar formato anterior (no oculto)
        if not os.path.exists(ruta_s):
            ruta_legacy = ruta_rwl + ".anom.json"
            if os.path.exists(ruta_legacy):
                ruta_s = ruta_legacy
            else:
                return
        try:
            with open(ruta_s, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
            self.check_tiene_medula.setChecked(bool(datos.get("medula", False)))
            self.check_tiene_corteza.setChecked(bool(datos.get("corteza", False)))
            self.vista.anomalias = {
                int(k): v for k, v in datos.get("anomalias", {}).items()
            }
            self.vista._dibujar_anomalias()
            # Restaurar datos de estimación de médula si existen
            if datos.get("pith_estimated"):
                self._pith_estimacion = {
                    k: datos[k] for k in datos
                    if k.startswith("pith_")
                }
                # Reconstruir undo para permitir revertir
                offset = datos.get("pith_offset", 0)
                if offset > 0:
                    med_a_cor = self.combo_dir.currentIndex() == 0
                    self._pith_undo = {
                        "med_a_cor":        med_a_cor,
                        "anio_medula_old":  self.spin_medula.value() + (offset if med_a_cor else 0),
                        "anio_corteza_old": self.spin_corteza.value() - (offset if not med_a_cor else 0),
                        "medula_checked":   False,
                        "n_anillos":        offset,
                    }
                    self.btn_deshacer_pith.show()
        except Exception as e:
            logger.warning("No se pudo cargar sidecar: %s", e)

    def _anomalias_modificadas(self):
        """Llamado desde la vista cuando el usuario cambia una anomalía."""
        self._guardar_estado()
        self._guardar_sidecar_anom()

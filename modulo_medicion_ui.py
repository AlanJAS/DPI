"""Operaciones de interfaz; reciben explícitamente su widget propietario."""
from modulo_widgets import crear_boton
from modulo_grafico_medicion_ui import GraficoMedicion
import modulo_transformacion as _tr
import pyqtgraph as pg
from PyQt6.QtWidgets import QGraphicsScene, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSpinBox, QComboBox, QButtonGroup, QLineEdit, QListWidget, QSplitter
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtCore import Qt, QTimer
from estilos import SECUNDARIO_QSS
import estilos_graficos as _gr
from constantes import TUCSON_MAX_CHARS_ID, TIPOS_ANOMALIA
from modulo_marcas_medicion import ModoMedicion
from modulo_vista_medicion import PanelSplit, VistaInteractiva


def _construir_barra_herramientas(self) -> QHBoxLayout:
    barra = QHBoxLayout()
    barra.setSpacing(3)

    # ══════════════════════════════════════════════════════════════════
    # SIEMPRE VISIBLES: botones de medición + edición
    # ══════════════════════════════════════════════════════════════════
    self.grupo_modos = QButtonGroup(self)
    self._botones_modo = {}

    _btn_colores = {
        ModoMedicion.MEDIR:    ("#2ecc71", "#27ae60"),  # verde
        ModoMedicion.SALTO:    ("#f39c12", "#d68910"),  # ámbar
        ModoMedicion.ESPACIO:  ("#9b59b6", "#8e44ad"),  # púrpura
        ModoMedicion.INSERTAR: ("#3498db", "#2980b9"),  # azul
        ModoMedicion.MOVER:    ("#1abc9c", "#16a085"),  # turquesa
        ModoMedicion.BORRAR:   ("#e74c3c", "#c0392b"),  # rojo
        ModoMedicion.SELECCIONAR: ("#FFEB3B", "#FBC02D"),  # amarillo
    }

    botones_visibles = [
        ("📍 Medir",       ModoMedicion.MEDIR,        "Ctrl+A", "Clic izq: añadir anillo · Clic der: salto · Scroll: zoom"),
        ("🎯 Seleccionar", ModoMedicion.SELECCIONAR,  "Ctrl+R", "Seleccionar múltiples anillos para borrar / convertir a salto / quiebre"),
        ("🔀 Salto",       ModoMedicion.SALTO,        "Ctrl+D", "Añadir salto (discontinuidad)"),
        ("⊘ Quiebre",      ModoMedicion.ESPACIO,      "Ctrl+E", "Marcar quiebre intra-anillo\nNo cuenta como anillo"),
        ("➕ Insertar",     ModoMedicion.INSERTAR,     "Ctrl+W", "Insertar punto en segmento existente"),
        ("🖐 Mover",        ModoMedicion.MOVER,        "Ctrl+S", "Mover punto"),
        ("✕ Borrar",       ModoMedicion.BORRAR,       "Ctrl+X", "Borrar punto con clic"),
    ]
    for texto, modo, atajo, tooltip in botones_visibles:
        bg, bg_hover = _btn_colores[modo]
        btn = crear_boton(texto, lambda checked, m=modo: self.set_modo(m),
                          tooltip=f"{tooltip} ({atajo})", checkable=True)
        # ModoMedicion.SELECCIONAR usa color amarillo claro: el texto blanco no
        # contrasta bien, así que aplicamos texto NEGRO en lugar de blanco.
        color_texto = "#222" if modo == ModoMedicion.SELECCIONAR else "white"
        btn.setStyleSheet(
            f"QPushButton{{background-color:{bg}; color:{color_texto}; font-weight:bold; "
            f"padding:4px 10px; border-radius:4px;}}"
            f"QPushButton:hover{{background-color:{bg_hover};}}"
            f"QPushButton:checked{{background-color:#fff; color:{bg}; "
            f"border:2px solid {bg};}}"
        )
        self.grupo_modos.addButton(btn)
        self._botones_modo[modo] = btn
        barra.addWidget(btn)
        QShortcut(QKeySequence(atajo), self).activated.connect(lambda m=modo: self.set_modo(m))
    self._botones_modo[ModoMedicion.MEDIR].setChecked(True)

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
        lambda: (self.set_modo(ModoMedicion.EWLW), self._popup_ewlw.hide()))
    self.grupo_modos.addButton(btn_ewlw_marcar)
    self._botones_modo[ModoMedicion.EWLW] = btn_ewlw_marcar
    QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
        lambda: self.set_modo(ModoMedicion.EWLW))
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
        lambda: (self.set_modo(ModoMedicion.ANOMALIA), self._popup_herram.hide()))
    self.grupo_modos.addButton(self.btn_anomalia)
    self._botones_modo[ModoMedicion.ANOMALIA] = self.btn_anomalia
    QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(
        lambda: self.set_modo(ModoMedicion.ANOMALIA))
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
    self._botones_modo[ModoMedicion.PITH] = self.btn_pith
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
    self._botones_modo[ModoMedicion.AUTODETECT] = self.btn_autodetect
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
    self.combo_maestra.currentIndexChanged.connect(self._actualizar_grafico)
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
    self.spin_ventana_r.valueChanged.connect(self._actualizar_grafico)
    fila_maestra.addWidget(self.spin_ventana_r)

    fila_maestra.addSpacing(12)
    fila_maestra.addWidget(QLabel("Correlación:"))
    # Selector de método. Antes esta pestaña usaba siempre diferencias-log
    # mientras que Co-Datación usaba el método de COFECHA, así que el mismo
    # par de series daba r distintas en cada pestaña sin aviso alguno.
    self.combo_metodo_corr = _tr.crear_selector(self, _tr.DIFFLOG)
    self.combo_metodo_corr.currentIndexChanged.connect(
        self._actualizar_grafico)
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
    layout.addWidget(self.grafico_unif)

    # Controles de zoom, los mismos de Co-Datación: zoom por área,
    # ensanchar/comprimir el eje X y ver todo. En series largas son
    # imprescindibles para poder mirar el detalle año a año.
    try:
        from modulo_widgets import _crear_barra_zoom
        layout.addWidget(_crear_barra_zoom(self.grafico_unif))
    except Exception as _e:
        print("No se pudo agregar la barra de zoom:", _e)

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

    self.grafico_medicion = GraficoMedicion(
        self.grafico_unif, self.combo_maestra, self.spin_ventana_r,
        self.lbl_r_total, self.lbl_ventanas_r,
        self.metodo_correlacion, self._navegar_anio_grafico)

    return panel


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
    self.vista = VistaInteractiva(self.escena, self, modelo=self.modelo_sesion.activo,
        datacion=self._datacion_activa, tipo_anomalia=self._tipo_anomalia_activo,
        configuracion_pith=self._configuracion_pith, mediciones=lambda: self.datos_medidos)
    self.vista.estado_cambiado.connect(self.label_estado.setText)
    self.vista.modo_cambiado.connect(self._reflejar_modo_vista)
    self.vista.anomalias_modificadas.connect(self._anomalias_modificadas)
    self.vista.confirmar_pith_solicitado.connect(self._confirmar_estimacion_pith)
    self.vista.origen_calibracion_cambiado.connect(self._origen_calibracion)
    self.vista.guardado_solicitado.connect(self._guardar_estado)
    self.vista.autodeteccion_solicitada.connect(self._ejecutar_autodeteccion)
    self.vista.mediciones_actualizadas.connect(self._sincronizar_mediciones)
    self._timer_autoguardado = QTimer(self)
    self._timer_autoguardado.setSingleShot(True)
    self._timer_autoguardado.setInterval(350)
    self._timer_autoguardado.timeout.connect(self._guardar_estado)
    self.vista.progreso_modificado.connect(self._programar_guardado)
    self._splitter_vistas.addWidget(self.vista)

    # Vista secundaria (panel dividido, oculto por defecto)
    self.panel_split = PanelSplit(self.escena, self.vista, self._fuentes_split)
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

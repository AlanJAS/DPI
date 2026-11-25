"""Operaciones de interfaz; reciben explícitamente su widget propietario."""
import sys
import pyqtgraph as pg
from modulo_widgets import _agregar_hover_anio, _crear_barra_zoom, SpinBoxFlechas, SeccionColapsable
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QSplitter, QSpinBox, QTableWidget, QHeaderView, QAbstractItemView, QComboBox, QCheckBox, QGroupBox, QApplication, QScrollArea, QFrame, QTabWidget, QPlainTextEdit, QTextBrowser
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtCore import Qt
import estilos_graficos as _gr
from constantes import VENTANA_COFECHADO_DEFECTO
from modulo_datacion import MAX_CORRECCION
TOOLTIP_STATS = (
    "<b>Estadísticos de cofechado:</b><br><br>"
    "<b>r (Pearson):</b> correlación lineal.<br>"
    "&nbsp;&nbsp;• <span style='color:#28a745'>≥0.50</span>: excelente<br>"
    "&nbsp;&nbsp;• <span style='color:#a3c44e'>≥0.35</span>: bueno<br>"
    "&nbsp;&nbsp;• <span style='color:#f0ad4e'>≥0.20</span>: aceptable<br>"
    "&nbsp;&nbsp;• <span style='color:#d9534f'>&lt;0.20</span>: pobre<br><br>"
    "<b>GLK:</b> % años con misma dirección. Asteriscos = significancia.<br>"
    "&nbsp;&nbsp;• <span style='color:#28a745'>≥0.70</span>: muy bueno<br>"
    "&nbsp;&nbsp;• <span style='color:#a3c44e'>≥0.65</span>: bueno<br>"
    "&nbsp;&nbsp;• <span style='color:#f0ad4e'>≥0.60</span>: aceptable<br>"
    "&nbsp;&nbsp;• <span style='color:#d9534f'>&lt;0.60</span>: subóptimo<br><br>"
    "<b>t-BP (Baillie-Pilcher):</b> t-statistic sobre series filtradas.<br>"
    "&nbsp;&nbsp;• <span style='color:#28a745'>≥6.0</span>: excelente<br>"
    "&nbsp;&nbsp;• <span style='color:#a3c44e'>≥4.0</span>: bueno<br>"
    "&nbsp;&nbsp;• <span style='color:#f0ad4e'>≥3.0</span>: aceptable<br>"
    "&nbsp;&nbsp;• <span style='color:#d9534f'>&lt;3.0</span>: no significativo<br><br>"
    "<b>n:</b> años de overlap.<br><br>"
    "<i>Los tres altos = cofechado sólido.</i>"
)
ESTILO_BTN_COFECHA = (
    "QPushButton{background:transparent; padding:4px 10px; "
    "border:2px solid #888; border-radius:4px; font-weight:bold;}"
    "QPushButton:hover{border:2px solid #FF8C00;}"
    "QPushButton:checked{border:2px solid #FF8C00; background:#FF8C00; color:white;}"
)
from modulo_codatacion_util import ESTILO_CHK_COFECHA


def _construir_ui(self):
    layout_principal = QHBoxLayout(self)
    layout_principal.setContentsMargins(0, 0, 0, 0)

    splitter_principal = QSplitter(Qt.Orientation.Horizontal)

    # ═══════════════════════════════════════════════════════════════
    # PANEL IZQUIERDO: Scroll area con secciones colapsables
    # ═══════════════════════════════════════════════════════════════
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setMinimumWidth(220)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    widget_izq = QWidget()
    # Guardamos referencia para poder ajustar su fondo según el tema
    # activo (el global de la app no estila QWidget genérico).
    self._widget_izq_panel = widget_izq
    panel_izq = QVBoxLayout(widget_izq)
    panel_izq.setContentsMargins(4, 4, 4, 4)
    panel_izq.setSpacing(6)

    # ── BLOQUE FIJO ARRIBA: Carga y gestión de series ──
    fila_carga = QHBoxLayout()
    self.btn_cargar_rwl = QPushButton("📂 Series")
    self.btn_cargar_rwl.setToolTip("Cargar series de medición")
    self.btn_cargar_rwl.clicked.connect(self.cargar_archivos_rwl)
    fila_carga.addWidget(self.btn_cargar_rwl)
    self.btn_cargar_crono = QPushButton("📚 Crono")
    self.btn_cargar_crono.setToolTip(
        "Cargar una cronología externa.\n"
        "Si el archivo trae varias series, se auto-genera la cronología.")
    self.btn_cargar_crono.setStyleSheet(
        "QPushButton{background-color:#6f42c1; color:white; font-weight:bold;}"
        "QPushButton:hover{background-color:#5a32a3;}")
    self.btn_cargar_crono.clicked.connect(self.cargar_cronologias_externas)
    fila_carga.addWidget(self.btn_cargar_crono)

    # Series solo para el contraste: no entran a la lista ni se cofechan.
    # Sirven cuando se tiene la cronología ya hecha y una sola serie por
    # cofechar, que es el caso donde el localizador se quedaba sin nulo.
    self.btn_series_nulo = QPushButton("📊 Referencia")
    self.btn_series_nulo.setToolTip(
        "Cargar series YA FECHADAS que sirvan solo de contraste.\n\n"
        "El localizador de quiebres decide si una corrección es real\n"
        "midiendo cuánto gana la misma búsqueda en series sin error.\n"
        "Con nueve o más, ese contraste pasa a ser el bueno.\n\n"
        "No aparecen en la lista ni se cofechan.\n"
        "Si ya cargaste series acá o construiste la cronología en su\n"
        "pestaña, esas se usan solas y este botón no hace falta.")
    self.btn_series_nulo.clicked.connect(self.cargar_series_referencia)
    fila_carga.addWidget(self.btn_series_nulo)
    panel_izq.addLayout(fila_carga)

    self.btn_toggle_sel = QPushButton("☑ Des / Seleccionar Todo")
    self.btn_toggle_sel.clicked.connect(self.toggle_seleccion)
    panel_izq.addWidget(self.btn_toggle_sel)

    panel_izq.addWidget(QLabel("Series en Memoria:"))
    self.lista_series = QListWidget()
    self.lista_series.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection)
    self.lista_series.setMinimumHeight(120)
    self.lista_series.itemChanged.connect(self.graficar_series)
    panel_izq.addWidget(self.lista_series)

    QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lista_series).activated.connect(self.eliminar_series)
    QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.lista_series).activated.connect(self.eliminar_series)

    fila_btns = QHBoxLayout()
    btn_elim = QPushButton("🗑️ Eliminar")
    btn_elim.setStyleSheet("background-color: #d9534f; color: white;")
    btn_elim.clicked.connect(self.eliminar_series)
    fila_btns.addWidget(btn_elim)
    btn_anio = QPushButton("📅 Editar Año Base")
    btn_anio.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")
    btn_anio.clicked.connect(self.editar_anio_serie)
    fila_btns.addWidget(btn_anio)
    panel_izq.addLayout(fila_btns)

    btn_exp = QPushButton("💾 Exportar Seleccionada")
    btn_exp.clicked.connect(self.exportar_serie_codatada)
    panel_izq.addWidget(btn_exp)

    # Botón directo de comparación múltiple vs cronología activa.
    # Permite al usuario marcar varias series en la lista y compararlas
    # contra la cronología ya cargada sin tener que abrir la ventana
    # de cronología por separado. La cronología activa se mantiene
    # entre llamadas (en `_cronologia_para_comparacion`), así que
    # típicamente: cargo cronología una vez → comparo decenas de
    # series con dos clics.
    self.btn_multi_vs_crono = QPushButton("📊 Series múltiples vs Crono")
    self.btn_multi_vs_crono.setStyleSheet(
        "QPushButton{background-color:#8e44ad; color:white; "
        "font-weight:bold; padding:5px 10px; border-radius:4px;}"
        "QPushButton:hover{background-color:#9b59b6;}"
        "QPushButton:disabled{background-color:#555; color:#aaa;}"
    )
    self.btn_multi_vs_crono.setToolTip(
        "Comparar las series marcadas contra una cronología.\n"
        "• Si todavía no hay cronología cargada, se pedirá elegir un archivo .rwl\n"
        "• Si ya hay una cargada, se reutiliza automáticamente\n"
        "• Funciona con 1 o más series marcadas\n"
        "• Resultados en tabla resumen con r, GLK, t-BP y puntaje compuesto")
    self.btn_multi_vs_crono.clicked.connect(self.comparar_series_marcadas_vs_crono)
    panel_izq.addWidget(self.btn_multi_vs_crono)

    self.btn_skeleton = QPushButton("📊 Skeleton plot — cofechado visual")
    self.btn_skeleton.setStyleSheet(
        "QPushButton{background-color:#6f42c1; color:white; "
        "font-weight:bold; padding:8px; font-size:13px; border-radius:4px;}"
        "QPushButton:hover{background-color:#8250d6;}")
    self.btn_skeleton.setToolTip(
        "Cofechado visual: referencia arriba, serie flotante abajo,\n"
        "deslizable año a año para ver dónde calzan los anillos.\n\n"
        "Marca DOS series: la cronología (📚) o la primera será la\n"
        "referencia; la otra será la flotante.")
    self.btn_skeleton.clicked.connect(self.abrir_skeleton_plot)
    panel_izq.addWidget(self.btn_skeleton)

    # Botón para editar anillos (insertar/eliminar conservando el ancho)
    # de la serie marcada, accesible directamente desde el panel.
    self.btn_editar_anillos = QPushButton("✏️ Editar anillos de serie marcada")
    self.btn_editar_anillos.setStyleSheet(
        "QPushButton{background-color:#8e44ad; color:white; "
        "font-weight:bold; padding:5px 10px; border-radius:4px;}"
        "QPushButton:hover{background-color:#9b59b6;}"
        "QPushButton:disabled{background-color:#555; color:#aaa;}")
    self.btn_editar_anillos.setToolTip(
        "Abre el editor de anillos (insertar/eliminar conservando el "
        "ancho total) para la serie marcada con check.\n"
        "Marca exactamente UNA serie.")
    self.btn_editar_anillos.clicked.connect(self._abrir_editor_anillos_marcada)
    panel_izq.addWidget(self.btn_editar_anillos)

    # ── Modo COFECHA (control global del cofechado) ──
    # Va aquí, a nivel del panel (no dentro de una sección colapsable),
    # porque gobierna TODAS las correlaciones del módulo: con él el
    # usuario decide si las series/cronologías se estandarizan o se usan
    # tal cual. Por eso debe estar siempre visible, justo bajo el botón
    # de comparación múltiple.
    grp_cof = QGroupBox("Modo COFECHA")
    grp_cof.setStyleSheet(
        "QGroupBox{border:1px solid #555; border-radius:4px; "
        "margin-top:6px; padding-top:4px;}"
        "QGroupBox::title{subcontrol-origin:margin; left:8px; padding:0 3px;}"
    )
    layout_cof = QVBoxLayout(grp_cof)
    layout_cof.setSpacing(4)
    layout_cof.setContentsMargins(6, 4, 6, 6)

    self.btn_modo_cofecha = QPushButton("🎯 Activar Modo COFECHA")
    self.btn_modo_cofecha.setCheckable(True)
    self.btn_modo_cofecha.setStyleSheet(ESTILO_BTN_COFECHA)
    self.btn_modo_cofecha.setToolTip(
        "Activa transformaciones tipo COFECHA (spline + log + AR(1))\n"
        "con los parámetros configurados (botón ⚙ al lado para ajustar).\n"
        "Al activarlo, el gráfico muestra las series transformadas y\n"
        "todas las correlaciones usan esa estandarización."
    )
    self.btn_modo_cofecha.toggled.connect(self._on_modo_cofecha_toggled)

    self.btn_cof_config = QPushButton("⚙")
    self.btn_cof_config.setMaximumWidth(34)
    self.btn_cof_config.setToolTip(
        "Configurar parámetros del Modo COFECHA\n"
        "(rigidez del spline, log, AR(1), primeras diferencias)"
    )
    self.btn_cof_config.setStyleSheet(
        "QPushButton{padding:4px 8px; font-size:14px; font-weight:bold; "
        "border:2px solid #888; border-radius:4px; "
        "background:transparent;}"
        "QPushButton:hover{border-color:#FF8C00; color:#FF8C00;}"
    )
    self.btn_cof_config.clicked.connect(self._configurar_modo_cofecha)

    fila_cof_btn = QHBoxLayout()
    fila_cof_btn.addWidget(self.btn_modo_cofecha, 1)
    fila_cof_btn.addWidget(self.btn_cof_config)
    layout_cof.addLayout(fila_cof_btn)

    fila_aplicar = QHBoxLayout()
    lbl_aplicar = QLabel("Aplicar a:")
    lbl_aplicar.setStyleSheet("font-size:11px;")
    fila_aplicar.addWidget(lbl_aplicar)
    self.chk_cof_serie = QCheckBox("Serie")
    self.chk_cof_serie.setChecked(True)
    self.chk_cof_serie.setStyleSheet(ESTILO_CHK_COFECHA)
    self.chk_cof_serie.setToolTip(
        "Estandariza la SERIE a datar con el mismo método de la\n"
        "cronología activa, para que ambas queden en el mismo espacio\n"
        "y la correlación sea válida.\n\n"
        "Desactívalo solo si subiste la serie YA estandarizada."
    )
    self.chk_cof_serie.toggled.connect(self._on_cofecha_aplicar_cambiado)
    fila_aplicar.addWidget(self.chk_cof_serie)
    self.chk_cof_crono = QCheckBox("Cronología")
    self.chk_cof_crono.setChecked(False)
    self.chk_cof_crono.setStyleSheet(ESTILO_CHK_COFECHA)
    self.chk_cof_crono.setToolTip(
        "Normalmente NO se activa: una cronología generada con el botón\n"
        "Crono (o exportada por DPI/ARSTAN) ya viene estandarizada, y\n"
        "volver a aplicarle spline + log + AR la daña y hace caer la\n"
        "correlación.\n\n"
        "Actívalo solo si la cronología cargada NO está estandarizada\n"
        "(por ejemplo, una cronología de anchos crudos en mm)."
    )
    self.chk_cof_crono.toggled.connect(self._on_cofecha_aplicar_cambiado)
    fila_aplicar.addWidget(self.chk_cof_crono)
    fila_aplicar.addStretch()
    # Esta fila DEBE agregarse al layout del grupo. Al retirar la casilla
    # de leave-one-out se perdió esta línea y las casillas quedaron
    # creadas pero fuera de todo layout, o sea invisibles.
    layout_cof.addLayout(fila_aplicar)
    panel_izq.addWidget(grp_cof)

    # ── SECCIÓN COLAPSABLE: Cronología ──
    # Todas las secciones inician COLAPSADAS para no abrumar al usuario
    # con un panel sobrecargado de botones al abrir el programa. El
    # usuario expande la sección que necesita en cada momento.
    # ── Sección "Cronología" ELIMINADA de esta pestaña ──
    # La generación y gestión de cronologías vive en su propia pestaña,
    # así que aquí no aporta. Se conservan estos dos widgets OCULTOS (no
    # se agregan a ningún layout) solo para que set_cronologia_activa
    # pueda seguir actualizando el indicador y el estado de EPS sin
    # romperse.
    self.lbl_info_crono = QLabel("", self)
    self.lbl_info_crono.setVisible(False)
    self.btn_eps_crono = QPushButton(self)
    self.btn_eps_crono.setVisible(False)
    self.btn_eps_crono.setEnabled(False)
    self.btn_eps_crono.clicked.connect(self._mostrar_eps_cronologia_activa)

    # ── SECCIÓN COLAPSABLE: Cofechado con año conocido ──
    sec_conocido = SeccionColapsable(
        "📊 Cofechado con Año Conocido", expandida=False)

    # Parámetros del motor (compactos lado a lado)
    fila_params = QHBoxLayout()
    fila_params.addWidget(QLabel("Ventana:"))
    self.spin_ventana = SpinBoxFlechas()
    self.spin_ventana.setRange(10, 200)
    self.spin_ventana.setValue(VENTANA_COFECHADO_DEFECTO)
    self.spin_ventana.setSingleStep(10)
    self.spin_ventana.setSuffix(" años")
    fila_params.addWidget(self.spin_ventana)
    fila_params.addWidget(QLabel("Máx corr:"))
    self.spin_max_corr = SpinBoxFlechas()
    self.spin_max_corr.setRange(1, 10)
    self.spin_max_corr.setValue(MAX_CORRECCION)
    fila_params.addWidget(self.spin_max_corr)
    sec_conocido.agregar_layout(fila_params)

    # Anclaje: qué extremo de la serie queda fijo al insertar/eliminar
    # un anillo. Para árboles vivos fechados desde la corteza (el caso
    # normal) debe quedar fija la CORTEZA: así, al insertar el anillo que
    # falta, la serie sigue terminando en el mismo año y se corrige todo
    # lo anterior. Con médula fija la serie se corría hacia el presente y
    # el buscador proponía años equivocados.
    fila_ancla = QHBoxLayout()
    fila_ancla.addWidget(QLabel("Anclar en:"))
    self.combo_anclaje = QComboBox()
    self.combo_anclaje.addItem("Corteza (último año fijo)", "corteza")
    self.combo_anclaje.addItem("Médula (primer año fijo)", "medula")
    self.combo_anclaje.setToolTip(
        "Qué extremo de la serie NO se mueve al insertar o eliminar un anillo.\n\n"
        "• Corteza: el último año queda fijo y se desplazan los años anteriores.\n"
        "  Es lo correcto en árboles vivos, donde el año del anillo externo se\n"
        "  conoce con certeza. Si falta un anillo en 2023, al insertarlo la serie\n"
        "  sigue terminando en 2024 y todo lo anterior retrocede un año.\n\n"
        "• Médula: el primer año queda fijo y se desplazan los posteriores.\n"
        "  Para series flotantes o fechadas desde la médula."
    )
    fila_ancla.addWidget(self.combo_anclaje, 1)
    sec_conocido.agregar_layout(fila_ancla)

    self.btn_ver_cofechado = QPushButton("📊 Ver Cofechado Actual")
    self.btn_ver_cofechado.setStyleSheet("background-color: #5bc0de; color: white;")
    self.btn_ver_cofechado.clicked.connect(self.verificar_datacion)
    sec_conocido.agregar_widget(self.btn_ver_cofechado)

    self.btn_buscar = QPushButton("🔎 Buscar Anillos Faltantes/Sobrantes")
    self.btn_buscar.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
    self.btn_buscar.clicked.connect(self.buscar_errores)
    sec_conocido.agregar_widget(self.btn_buscar)

    panel_izq.addWidget(sec_conocido)

    # ── SECCIÓN COLAPSABLE: Cofechado serie flotante ──
    sec_flotante = SeccionColapsable(
        "🔍 Cofechado Serie Flotante", expandida=False)

    btn_off = QPushButton("🔍 Analizar Serie Flotante")
    btn_off.setStyleSheet("background-color: #5bc0de; color: white;")
    btn_off.clicked.connect(self.analizar_offset)
    sec_flotante.agregar_widget(btn_off)

    self.btn_ver_tabla_off = QPushButton("📊 Ver tabla de desfases")
    self.btn_ver_tabla_off.setEnabled(False)
    self.btn_ver_tabla_off.clicked.connect(self.mostrar_tabla_offset)
    sec_flotante.agregar_widget(self.btn_ver_tabla_off)

    # Métrica al final, label arriba y combo a todo el ancho
    lbl_met = QLabel("📐 Métrica del gráfico:")
    lbl_met.setStyleSheet("font-size: 11px; padding-top: 4px;")
    sec_flotante.agregar_widget(lbl_met)
    self.combo_metrica_offset = QComboBox()
    self.combo_metrica_offset.addItems([
        "🎯 Compuesto (las tres juntas)",
        "t-BP (Baillie-Pilcher)",
        "r (Pearson)",
        "GLK (Eckstein)",
    ])
    self.combo_metrica_offset.setToolTip(
        "Métrica del gráfico de barras de desfase.\n\n"
        "🎯 Compuesto: media geométrica de las tres métricas.\n"
        "    La fecha verdadera tiene puntaje alto SOLO cuando\n"
        "    las tres son altas simultáneamente.\n\n"
        "t-BP: pondera r por tamaño de muestra.\n"
        "r: engañoso solo — puede dar máximos azarosos.\n"
        "GLK: robusto pero menos sensible que t-BP."
    )
    self.combo_metrica_offset.currentTextChanged.connect(self._redibujar_offset)
    sec_flotante.agregar_widget(self.combo_metrica_offset)

    panel_izq.addWidget(sec_flotante)

    # ── SECCIÓN COLAPSABLE: Sugerencias ──
    self.sec_sug = SeccionColapsable("💡 Sugerencias", expandida=False)

    self.lbl_estado_sug = QLabel("")
    self.lbl_estado_sug.setWordWrap(True)
    self.lbl_estado_sug.setTextFormat(Qt.TextFormat.RichText)
    self.lbl_estado_sug.setStyleSheet(
        "QLabel{font-size:10px; padding:4px 6px; "
        "background-color: rgba(0,0,0,30); border-radius:3px;}")
    self.lbl_estado_sug.setVisible(False)
    self.sec_sug.agregar_widget(self.lbl_estado_sug)

    self.tabla_sugerencias = QTableWidget(0, 5)
    # Selección de FILA COMPLETA, con un color que se ve por encima del
    # fondo con que se marcan las filas según su origen. Sin esto, al
    # moverse con las flechas no se distinguía dónde estaba el cursor.
    self.tabla_sugerencias.setSelectionBehavior(
        QAbstractItemView.SelectionBehavior.SelectRows)
    self.tabla_sugerencias.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection)
    self.tabla_sugerencias.setStyleSheet(
        "QTableWidget::item:selected{background-color:#2d6ea8;"
        " color:#ffffff;}")
    self.tabla_sugerencias.setHorizontalHeaderLabels(
        ["Año", "Tipo", "r antes", "r tras", "Δr"])
    self.tabla_sugerencias.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch)
    self.tabla_sugerencias.setSelectionBehavior(
        QAbstractItemView.SelectionBehavior.SelectRows)
    self.tabla_sugerencias.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection)
    self.tabla_sugerencias.itemSelectionChanged.connect(
        self._on_seleccion_sugerencia)
    self.tabla_sugerencias.setMaximumHeight(200)
    self.tabla_sugerencias.setMinimumHeight(120)
    self.sec_sug.agregar_widget(self.tabla_sugerencias)

    # Indicador de prueba en curso
    self.lbl_prueba = QLabel("")
    self.lbl_prueba.setWordWrap(True)
    self.lbl_prueba.setTextFormat(Qt.TextFormat.RichText)
    self.lbl_prueba.setStyleSheet(
        "QLabel{font-size:11px; padding:4px 6px; color:#e67e22; "
        "font-weight:bold;}")
    self.lbl_prueba.setVisible(False)
    self.sec_sug.agregar_widget(self.lbl_prueba)

    # Paso 1: probar la corrección (sin tocar la serie real)
    self.btn_probar = QPushButton("🧪 Probar corrección seleccionada")
    self.btn_probar.setStyleSheet(
        "background-color:#5bc0de; color:white; font-weight:bold;")
    self.btn_probar.setToolTip(
        "Aplica la corrección de forma temporal para ver cómo queda la\n"
        "correlación, SIN modificar todavía la serie real.")
    self.btn_probar.setEnabled(False)
    self.btn_probar.clicked.connect(self.probar_correccion_seleccionada)
    self.sec_sug.agregar_widget(self.btn_probar)

    # Paso 2: aplicar a la serie real (con confirmación de qué cambia)
    self.btn_aplicar = QPushButton("✅ Aplicar a serie real")
    self.btn_aplicar.setStyleSheet(
        "background-color: #5cb85c; color: white; font-weight: bold;")
    self.btn_aplicar.setEnabled(False)
    self.btn_aplicar.setToolTip(
        "Confirma qué datos se modifican y guarda el cambio en la serie "
        "real.")
    self.btn_aplicar.clicked.connect(self.aplicar_correccion_seleccionada)
    self.sec_sug.agregar_widget(self.btn_aplicar)

    # Descartar la prueba (revierte a como estaba)
    self.btn_descartar_prueba = QPushButton("↺ Descartar prueba")
    self.btn_descartar_prueba.setStyleSheet(
        "QPushButton{background-color:#6c757d; color:white; padding:4px;}"
        "QPushButton:hover{background-color:#7d868e;}")
    self.btn_descartar_prueba.setEnabled(False)
    self.btn_descartar_prueba.clicked.connect(self._descartar_prueba)
    self.sec_sug.agregar_widget(self.btn_descartar_prueba)

    # Botón para restablecer la serie corregida a sus valores originales,
    # disponible aquí (no solo en el simulador manual).
    self.btn_restablecer_sug = QPushButton("🔄 Restablecer valores originales")
    self.btn_restablecer_sug.setStyleSheet(
        "QPushButton{background-color:#6c757d; color:white; "
        "padding:4px;}"
        "QPushButton:hover{background-color:#7d868e;}")
    self.btn_restablecer_sug.clicked.connect(self.restaurar_original_sugerencias)
    self.sec_sug.agregar_widget(self.btn_restablecer_sug)
    panel_izq.addWidget(self.sec_sug)

    # ── SECCIÓN COLAPSABLE: Simulador manual ──
    # Va al final porque se usa poco; las correcciones normales se hacen
    # desde Sugerencias (que abre el editor con conservación de ancho).
    sec_sim = SeccionColapsable("📝 Simulador Manual", expandida=False)
    fila = QHBoxLayout()
    fila.addWidget(QLabel("Año:"))
    self.spin_edit_year = SpinBoxFlechas()
    self.spin_edit_year.setRange(-10000, 5000)
    self.spin_edit_year.setValue(1900)
    fila.addWidget(self.spin_edit_year)
    sec_sim.agregar_layout(fila)

    fila2 = QHBoxLayout()
    btn_ins = QPushButton("➕ Insertar")
    btn_ins.setStyleSheet("background-color: #5bc0de; color: white;")
    btn_ins.clicked.connect(self.simular_insertar)
    fila2.addWidget(btn_ins)
    btn_del = QPushButton("➖ Borrar")
    btn_del.setStyleSheet("background-color: #d9534f; color: white;")
    btn_del.clicked.connect(self.simular_borrar)
    fila2.addWidget(btn_del)
    sec_sim.agregar_layout(fila2)
    btn_rst = QPushButton("🔄 Restaurar Original")
    btn_rst.clicked.connect(self.restaurar_serie)
    sec_sim.agregar_widget(btn_rst)
    panel_izq.addWidget(sec_sim)

    panel_izq.addStretch()
    scroll.setWidget(widget_izq)

    # ═══════════════════════════════════════════════════════════════
    # PANEL DERECHO: Gráficos
    # ═══════════════════════════════════════════════════════════════
    splitter_der = QSplitter(Qt.Orientation.Vertical)

    self.grafico = pg.PlotWidget(title="Series de Ancho de Anillo")
    _agregar_hover_anio(self.grafico)
    self.grafico.showGrid(x=True, y=True, alpha=0.3)
    self.grafico.addLegend()
    _gr.aplicar_a_pyqtgraph(self.grafico)
    _cont_grafico = QWidget()
    _lay_grafico = QVBoxLayout(_cont_grafico)
    _lay_grafico.setContentsMargins(0, 0, 0, 0)
    _lay_grafico.setSpacing(2)
    _lay_grafico.addWidget(self.grafico, 1)

    # Fila de controles del gráfico: zoom + selector de tipo de gráfico.
    _fila_ctrl_graf = QHBoxLayout()
    _fila_ctrl_graf.setContentsMargins(0, 0, 0, 0)
    _fila_ctrl_graf.setSpacing(6)
    _barra_sup = _crear_barra_zoom(self.grafico, nombre_exportar="series")
    _fila_ctrl_graf.addWidget(_barra_sup)

    # Modo barras: dibuja cada serie como barras que salen de su MEDIA
    # (hacia arriba si el año fue de crecimiento sobre la media, hacia
    # abajo si fue bajo la media). Es la vista clásica de desviaciones,
    # muy útil para ver años característicos y comparar con COFECHA.
    self.btn_grafico_barras = QPushButton("📊 Barras")
    self.btn_grafico_barras.setCheckable(True)
    self.btn_grafico_barras.setToolTip(
        "Alterna entre gráfico de LÍNEAS y gráfico de BARRAS.\n\n"
        "En modo barras, la MEDIA de cada serie es el eje central:\n"
        "las barras suben sobre la media (años buenos, verde) y bajan\n"
        "bajo la media (años malos, rojo). Con varias series marcadas,\n"
        "las barras se dibujan lado a lado por año."
    )
    self.btn_grafico_barras.toggled.connect(self.graficar_series)

    # El botón de barras va junto a «Ver todo», que es donde se
    # esperan los controles de ESTE gráfico. La fila que ocupaba antes
    # queda libre para los controles de los gráficos de abajo.
    _barra_sup.layout().insertWidget(
        _barra_sup.layout().count() - 1, self.btn_grafico_barras)
    _fila_ctrl_graf.addStretch()

    _cont_ctrl_graf = QWidget()
    _cont_ctrl_graf.setLayout(_fila_ctrl_graf)
    _lay_grafico.addWidget(_cont_ctrl_graf)
    splitter_der.addWidget(_cont_grafico)

    contenedor_offset = QWidget()
    layout_offset = QVBoxLayout(contenedor_offset)
    layout_offset.setContentsMargins(0, 0, 0, 0)
    layout_offset.setSpacing(2)

    self.grafico_offset = pg.PlotWidget(
        title="Correlación móvil (r) entre la serie y la referencia, por ventana")
    self.grafico_offset.showGrid(x=True, y=True, alpha=0.3)
    self.grafico_offset.setYRange(-1.05, 1.05)
    self.grafico_offset.setLabel("left", "r (correlación por ventana)")
    self.grafico_offset.setLabel("bottom", "Año (centro de la ventana)")
    self.grafico_offset.addLegend(offset=(10, 10))
    self._texto_hover = pg.TextItem(fill=(40, 40, 40, 220), color=(255, 255, 255))
    self._texto_hover.hide()
    self.grafico_offset.addItem(self._texto_hover)
    self.grafico_offset.scene().sigMouseMoved.connect(self._on_mouse_movido)
    _agregar_hover_anio(self.grafico_offset)
    layout_offset.addWidget(self.grafico_offset, 1)
    # Controles de zoom propios de ESTA pestaña: cada gráfico de abajo se
    # maneja por su cuenta, así se puede dejar uno encuadrado en un tramo
    # mientras se explora el otro.
    layout_offset.addWidget(_crear_barra_zoom(self.grafico_offset))

    self.lbl_stats = QLabel("")
    self.lbl_stats.setWordWrap(False)
    self.lbl_stats.setTextFormat(Qt.TextFormat.RichText)
    self.lbl_stats.setMinimumHeight(38)
    # Fondo oscuro fijo: este label es un overlay sobre el gráfico
    # de pyqtgraph (que es negro siempre), y el HTML interno usa
    # colores #888/#aaa/etc que requieren fondo oscuro para verse.
    self.lbl_stats.setStyleSheet(
        "QLabel{background-color:#1a1a1a; color:#e0e0e0; "
        "border:1px solid #444; border-radius:4px; padding:8px 12px;}"
    )
    self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignVCenter |
                                Qt.AlignmentFlag.AlignLeft)
    self.lbl_stats.setToolTip(TOOLTIP_STATS)
    self.lbl_stats.setVisible(False)
    layout_offset.addWidget(self.lbl_stats)

    # ── Panel inferior con pestañas ────────────────────────────────
    # Antes este panel mostraba solo la correlación móvil. El informe de
    # co-datación y el perfil del quiebre se calculaban pero no se veían
    # en ninguna parte: la explicación en prosa y el gráfico que muestra
    # si el año está determinado o es una meseta quedaban dentro de la
    # estructura de datos, invisibles. Van acá, junto al gráfico que ya
    # había, para que el usuario alterne entre los tres sin perder nada.
    self.tabs_inferior = QTabWidget()
    self.tabs_inferior.addTab(contenedor_offset, "Correlación móvil")

    self.txt_informe = QPlainTextEdit()
    self.txt_informe.setReadOnly(True)
    self.txt_informe.setPlaceholderText(
        "Acá aparece el informe de co-datación cuando se busca una "
        "corrección:\n\n"
        "  · qué tramo de la serie correlaciona bien y con qué r\n"
        "  · dónde baja la correlación\n"
        "  · cuántos anillos faltan o sobran, y entre qué años\n"
        "  · los años concretos que conviene revisar bajo la lupa")
    self.txt_informe.setStyleSheet(
        "QPlainTextEdit{background-color:#1a1a1a; color:#e0e0e0;"
        " border:1px solid #444; padding:8px;}")
    f_inf = QFont("Consolas" if sys.platform.startswith("win")
                  else "Monospace")
    f_inf.setStyleHint(QFont.StyleHint.TypeWriter)
    f_inf.setPointSize(10)
    self.txt_informe.setFont(f_inf)

    # Controles de letra: no todo el mundo lee cómodo el mismo cuerpo, y
    # la monoespaciada alinea las tablas pero cansa en prosa larga.
    _cont_inf = QWidget()
    _lay_inf = QVBoxLayout(_cont_inf)
    _lay_inf.setContentsMargins(0, 0, 0, 0)
    _lay_inf.setSpacing(2)
    _lay_inf.addWidget(self.txt_informe, 1)

    _fila_letra = QHBoxLayout()
    _fila_letra.setContentsMargins(4, 0, 4, 0)
    _fila_letra.addWidget(QLabel("Letra:"))
    self.combo_fuente_informe = QComboBox()
    for etq, fam in (("Monoespaciada", "__mono__"),
                     ("Garamond", "Garamond"),
                     ("Arial", "Arial"),
                     ("Verdana", "Verdana"),
                     ("Georgia", "Georgia"),
                     ("Times New Roman", "Times New Roman")):
        self.combo_fuente_informe.addItem(etq, fam)
    self.combo_fuente_informe.setToolTip(
        "La monoespaciada mantiene alineadas las tablas del informe.\n"
        "Las demás se leen mejor en la prosa, pero descuadran columnas.")
    self.combo_fuente_informe.currentIndexChanged.connect(
        self._aplicar_fuente_informe)
    self.combo_fuente_informe.currentIndexChanged.connect(
        self._guardar_pref_fuente)
    _fila_letra.addWidget(self.combo_fuente_informe)

    _fila_letra.addWidget(QLabel("Tamaño:"))
    self.spin_fuente_informe = QSpinBox()
    self.spin_fuente_informe.setRange(7, 24)
    self.spin_fuente_informe.setValue(10)
    self.spin_fuente_informe.setSuffix(" pt")
    self.spin_fuente_informe.valueChanged.connect(
        self._aplicar_fuente_informe)
    self.spin_fuente_informe.valueChanged.connect(
        self._guardar_pref_fuente)
    _fila_letra.addWidget(self.spin_fuente_informe)

    btn_copiar_inf = QPushButton("Copiar")
    btn_copiar_inf.setToolTip("Copia el informe completo al portapapeles.")
    btn_copiar_inf.clicked.connect(
        lambda: QApplication.clipboard().setText(
            self.txt_informe.toPlainText()))
    _fila_letra.addWidget(btn_copiar_inf)
    _fila_letra.addStretch()

    _cw = QWidget()
    _cw.setLayout(_fila_letra)
    _lay_inf.addWidget(_cw)
    self.tabs_inferior.addTab(_cont_inf, "Informe")
    self._restaurar_pref_fuente()

    self.grafico_perfil = pg.PlotWidget(
        title="¿En qué año se rompe el fechado? "
              "Correlación de la serie completa si el error estuviera "
              "en cada año")
    self.grafico_perfil.showGrid(x=True, y=True, alpha=0.3)
    self.grafico_perfil.setLabel(
        "left", "r de TODA la serie si el error estuviera en ese año")
    self.grafico_perfil.setLabel(
        "bottom", "Año donde se probó poner el error")
    self.grafico_perfil.addLegend(offset=(10, 10))
    _agregar_hover_anio(self.grafico_perfil)
    _cont_perfil = QWidget()
    _lay_perfil = QVBoxLayout(_cont_perfil)
    _lay_perfil.setContentsMargins(0, 0, 0, 0)
    _lay_perfil.setSpacing(2)

    # Gráfico y explicación lado a lado, con divisor movible: el perfil no
    # se entiende solo mirándolo, y una leyenda no alcanza para explicar
    # que cada punto es un experimento distinto de datación.
    _div_perfil = QSplitter(Qt.Orientation.Horizontal)
    _div_perfil.addWidget(self.grafico_perfil)

    self.txt_ayuda_perfil = QTextBrowser()
    self.txt_ayuda_perfil.setOpenExternalLinks(False)
    self.txt_ayuda_perfil.setHtml(
        "<div style='font-size:12px; line-height:1.35;'>"
        "<b>Qué estás viendo</b><br>"
        "Cada punto del gráfico es un <i>experimento</i>: el programa "
        "supone que el error de fechado está en ese año, aplica la "
        "corrección, y mide cómo queda <b>la serie completa</b>.<br><br>"
        "No es la correlación de un tramo. Es la de toda la serie, "
        "partida en ese año.<br><br>"
        "<b>Cómo se lee la forma</b><br>"
        "<span style='color:#5cb85c;'>▲ Pico angosto</span> — un solo año "
        "funciona. El fechado está determinado.<br>"
        "<span style='color:#e0a030;'>▬ Meseta ancha</span> — muchos años "
        "funcionan igual de bien. Elegir uno sería falsa precisión: hay "
        "que revisar todos los candidatos.<br>"
        "<span style='color:#d9534f;'>▼ Todo bajo</span> — si el mejor "
        "pico no llega a 0,3, ninguna corrección arregla esta serie. El "
        "problema es otro.<br><br>"
        "<b>Los colores</b><br>"
        "<span style='color:#4aa3dc;'>━ Curva azul</span>: la correlación "
        "de cada hipótesis.<br>"
        "<span style='color:#4aa3dc;'>▨ Franja azul</span>: la zona "
        "compatible, los años que no se distinguen del mejor.<br>"
        "<span style='color:#e04040;'>┃ Línea roja</span>: el año más "
        "probable.<br>"
        "<span style='color:#e0a030;'>┆ Punteadas</span>: los otros años "
        "a revisar, ordenados por lo estrecho que es ese anillo en la "
        "cronología.<br><br>"
        "<b>Ojo</b><br>"
        "La altura del pico dice si vale la pena; el ancho dice cuánta "
        "confianza tienes en el año. Son dos cosas distintas."
        "</div>")
    self.txt_ayuda_perfil.setStyleSheet(
        "QTextBrowser{background-color:#1a1a1a; color:#d8d8d8;"
        " border:1px solid #444; padding:8px;}")
    _div_perfil.addWidget(self.txt_ayuda_perfil)
    _div_perfil.setStretchFactor(0, 3)
    _div_perfil.setStretchFactor(1, 1)
    _div_perfil.setSizes([700, 260])
    _lay_perfil.addWidget(_div_perfil, 1)
    _lay_perfil.addWidget(_crear_barra_zoom(self.grafico_perfil))
    self.tabs_inferior.addTab(_cont_perfil, "Perfil del quiebre")

    splitter_der.addWidget(self.tabs_inferior)

    splitter_principal.addWidget(scroll)
    splitter_principal.addWidget(splitter_der)
    splitter_principal.setStretchFactor(0, 1)
    splitter_principal.setStretchFactor(1, 4)
    splitter_principal.setSizes([280, 1120])
    layout_principal.addWidget(splitter_principal)

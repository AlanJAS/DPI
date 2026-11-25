"""
modulo_codatacion.py — Panel de Co-datación Visual

Permite comparar series dendrocronológicas, detectar anillos faltantes o
sobrantes mediante búsqueda exhaustiva, y aplicar correcciones en memoria.
"""

import modulo_codatacion_ui

import os
import sys
import datetime
import logging
import hashlib
import numpy as np
import pandas as pd
import pyqtgraph as pg
from modulo_dialogos_archivo import ultima_carpeta
from modulo_widgets import (
    _ensanchar_dialogo, _agregar_hover_anio, _crear_barra_zoom,
    SpinBoxFlechas, SeccionColapsable,
)
from modulo_modelo_series import ModeloSeries
import modulo_transformacion as _tr
import modulo_estadistica as _est
from modulo_estadistica import (
    _sensibilidad_media,
    _autocorrelacion_ar1,
    gleichlaufigkeit,
    glk_significance,
    _filtro_hollstein,
    t_baillie_pilcher,
    estadisticos_cofechado,
    calcular_eps_rbar_movil,
    calcular_rbar,
    calcular_eps,
    calcular_sss,
    _correlacion_por_desfase,
    _estadisticos_por_desfase,
    _r_movil,
    _stats_movil,
)
import modulo_quiebres as _qb
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QSplitter,
    QFileDialog, QMessageBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog,
    QFormLayout, QComboBox, QCheckBox, QGroupBox,
    QDialogButtonBox, QApplication, QProgressDialog, QScrollArea,
    QFrame, QTabWidget, QPlainTextEdit, QTextBrowser,
)
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut, QPalette
from PyQt6.QtCore import Qt, QSettings, QEvent

from estilos import SECUNDARIO_QSS, color_secundario
import estilos_graficos as _gr
import json_seguro as _js
from constantes import (
    TUCSON_VALOR_FIN, TUCSON_VALOR_FALTANTE, TUCSON_MAX_CHARS_ID, TUCSON_DIVISOR,
    OVERLAP_MINIMO_ANALISIS, OVERLAP_MINIMO_GRAFICO, OVERLAP_MINIMO_FLOTANTE, UMBRAL_ANCLA_DEFECTO,
    VENTANA_COFECHADO_DEFECTO, COLORES_SERIES,
)

logger = logging.getLogger(__name__)

from modulo_datacion import (
    score_compuesto,
    _serie_transformada_para_comparar,
    alineamiento_optimo_anillos,
    _diff_log,
    aplicar_correccion,
    _plausibilidad_anillo_estrecho,
    puntaje_consistencia,
    _texto_correccion,
    _buscar_y_priorizar,
    diagnosticar_datacion,
    buscar_correcciones,
    aplicar_modo_cofecha,
    _glk_np,
    _tbp_np,
    _r_pearson,
    MAX_CORRECCION,
    MIN_OVERLAP_DEFAULT,
)

# Extensiones de planilla que se leen/escriben con el motor de Excel de
# pandas. Incluye .ods (LibreOffice / OpenDocument), que necesita el módulo
# 'odfpy'. Se usa en todo el módulo para no repetir la lista y para que un
# .ods nunca caiga por error al parser de texto (CSV), que devolvería basura.
from modulo_formatos import (
    EXTS_PLANILLA,
    _es_planilla,
    _leer_planilla,
    _escribir_excel,
    _asegurar_extension,
)


from modulo_cronologia import (
    agrupar_por_arbol,
    rbar_entre_arboles,
)


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


# =============================================================================
# LECTORES DE FORMATO DE ARCHIVO
# =============================================================================

from modulo_formatos import (
    detectar_precision_tucson,
    leer_archivo_tucson,
    leer_tucson_multi,
    leer_formato_compacto,
    leer_dendro_auto,
    leer_wid,
    leer_tabular,
    _indexar_columna_multi,
    _leer_crudo_tabular,
    leer_columna_multi,
    leer_columna_multi_hojas,
)


# =============================================================================
# CRONOLOGÍA: NORMALIZACIÓN Y CONSTRUCCIÓN
# =============================================================================

from modulo_cronologia import (
    _biweight_mean,
    _spline_cook,
    _fit_trend,
    _detrend_serie_indice,
    _ajustar_ar_yule_walker,
    _seleccionar_orden_ar,
    _ajustar_ar_burg,
    _residualizar_indice,
    rigidez_efectiva,
    estabilizar_varianza,
    detrendar_para_cronologia,
    orden_ar_agrupado,
    _normalizar_serie_para_tipo,
    diagnosticar_curva,
    detectar_series_problematicas,
    elegir_metodo_para_grupo,
    RIGIDEZ_SPLINE_DEFECTO,
    ORDEN_AR_MAXIMO,
    METODOS_DETREND,
    solveh_banded,
)


from modulo_cronologia import (
    _construir_cronologia_desde_series,
)


from modulo_formatos import (
    _ruta_metadatos_cronologia,
    _restaurar_claves_anio,
    _guardar_metadatos_cronologia,
    _cargar_metadatos_cronologia,
    escribir_tucson,
    _exportar_cronologia_df,
    _leer_cronologia_guardada,
    _CAMPOS_POR_ANIO,
)


# =============================================================================
# PANEL DE CO-DATACIÓN
# =============================================================================


from modulo_codatacion_util import (
    _ultima_carpeta,
    _color_r,
    _color_glk,
    _color_tbp,
    _color_compuesto,
    formato_stats_hover_html,
    formato_stats_global_html,
    formato_estadisticos,
    _html_curvas_negativas,
    _mostrar_dialogo_eps_rbar,
)

from modulo_codatacion_dialogos import (
    DialogoSeleccionCronologias,
    DialogoCofecha,
    DialogoEditarAnillos,
    DialogoAlineamientoAnillos,
    DialogoCurvasNegativas,
)

from modulo_codatacion_comparacion import (
    VentanaTablaOffset,
    DialogoComparacionMultiple,
)

from modulo_skeleton_plot import (
    VentanaSkeletonPlot,
)

from modulo_ventana_cronologia import (
    VentanaCronologia,
)


class PanelCodatacion(QWidget):
    """Panel principal de co-datación visual."""

    def __init__(self, ventana_padre: QWidget):
        super().__init__()
        self._ventana_padre = ventana_padre

        self.modelo_series = ModeloSeries()
        self.series_originales = self.modelo_series.originales
        self.series_datos = self.modelo_series.datos

        # Datos del análisis de offset (analizar_offset)
        self._shifts_actuales: list[int] = []
        self._r_actuales: list[float] = []
        self._glk_actuales: list[float] = []
        self._tbp_actuales: list[float] = []
        self._n_actuales: list[int] = []

        # Datos de la correlación móvil (verificar_datacion / buscar_errores)
        self._stats_movil_years: list[float] = []
        self._stats_movil_r: list[float] = []
        self._stats_movil_glk: list[float] = []
        self._stats_movil_tbp: list[float] = []
        self._stats_movil_n: list[int] = []
        self._mitad_ventana_actual: int = 15

        # Estado del motor de sugerencias
        self._sugerencias: list[dict] = []
        self._sugerencias_es_marginal: bool = False
        self._nombre_referencia: str = ""
        self._nombre_problema: str = ""
        self._item_preview = None
        self._stats_actuales: dict | None = None

        # El modelo conserva el respaldo; aquí solo queda la sugerencia visual.
        self._prueba_sug: dict | None = None

        # Cronología activa
        self.cronologia_activa: pd.DataFrame | None = None
        self.meta_cronologia: dict | None = None
        self._ventana_cronologia = None
        self._nombre_cronologia_activa: str = ""

        # Parámetros del modo COFECHA
        self._modo_cofecha_params: dict = {
            "rigidez_spline": 32,
            "aplicar_log": True,
            "aplicar_ar": True,
            "aplicar_first_diff": False,
        }

        self._construir_ui()
        self._sincronizar_fondo_con_tema_app()

    # -------------------------------------------------------------------------
    # CONSTRUCCIÓN DE LA INTERFAZ
    # -------------------------------------------------------------------------

    def _construir_ui(self):
        return modulo_codatacion_ui._construir_ui(self)

    # -------------------------------------------------------------------------
    # SINCRONIZACIÓN DE FONDO CON EL TEMA DE LA APP
    # -------------------------------------------------------------------------

    def _sincronizar_fondo_con_tema_app(self):
        """Aplica el fondo correcto al QWidget contenedor del panel según el
        tema activo de la aplicación.

        El stylesheet global de la app (estilos.py) define backgrounds para
        QMainWindow / QDialog / QListView / QSpinBox / etc., pero NO para
        QWidget genérico. Como el contenedor del scroll del panel es un
        QWidget plano, sin esto Qt lo pinta con palette(window) del sistema
        — que en Linux/GTK puede ser gris claro incluso con el tema oscuro
        de la app activo. Resultado: labels con texto blanco quedan invisibles
        sobre fondo gris claro.

        Detectamos el tema inspeccionando el stylesheet global. ESTILO_OSCURO
        contiene "background-color: #2b2b2b" y ESTILO_CLARO contiene
        "background-color: #f0f0f0" — ambos definidos en estilos.py.
        """
        # Los gráficos van primero, antes del `return` de más abajo: pyqtgraph
        # pinta con sus propios colores y no se entera del cambio de tema por
        # su cuenta, así que tienen que repintarse pase lo que pase con el
        # stylesheet. Se recorren todos (principal, correlación móvil, perfil).
        _gr.aplicar_a_todos(self)

        ss_app = QApplication.instance().styleSheet() or ""

        # Marcador robusto: el QMainWindow en ESTILO_OSCURO tiene #2b2b2b,
        # en ESTILO_CLARO tiene #f0f0f0. Si ninguno está, dejamos sin
        # estilizar (Qt usa palette del sistema).
        if "#2b2b2b" in ss_app:
            fondo = "#2b2b2b"
        elif "#f0f0f0" in ss_app:
            fondo = "#f0f0f0"
        else:
            return  # sin stylesheet reconocible, no tocar nada

        if hasattr(self, "_widget_izq_panel"):
            # Solo el QWidget contenedor — los descendientes con estilo propio
            # (QSpinBox, QListWidget, QPushButton, etc.) mantienen sus colores
            # del stylesheet global porque su selector específico vence al
            # genérico QWidget. Los QLabel también: el global tiene
            # "QLabel { background: transparent; }" que vence a este.
            self._widget_izq_panel.setStyleSheet(
                f"QWidget {{ background-color: {fondo}; }}"
            )

    def changeEvent(self, event):
        """Re-sincroniza el fondo del panel en caliente cuando la app
        cambia su stylesheet global (toggle de tema oscuro/claro).

        Cuando el usuario activa el toggle de tema, la app llama a
        QApplication.setStyleSheet(NUEVO_ESTILO). Eso propaga un evento
        QEvent.StyleChange a todos los widgets visibles e invisibles.
        Aprovechamos ese evento para re-aplicar el fondo apropiado al
        contenedor del scroll sin requerir reinicio.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.StyleChange:
            self._sincronizar_fondo_con_tema_app()

    # -------------------------------------------------------------------------
    # CARGA DE ARCHIVOS
    # -------------------------------------------------------------------------

    def cargar_archivos_rwl(self):
        """Carga uno o más archivos, detectando formato automáticamente."""
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar Series", _ultima_carpeta(),
            "Series compatibles (*.rwl *.txt *.wid *.csv *.tsv *.xlsx *.xls *.ods *.cat *.cmp);;"
            "Todos (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not rutas:
            return
        _ultima_carpeta(rutas[0])

        n_agregadas = 0
        n_duplicadas = 0
        errores: list[str] = []

        for ruta in rutas:
            ext = os.path.splitext(ruta)[1].lower()
            base_nombre = os.path.splitext(os.path.basename(ruta))[0]

            try:
                with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
                    primeras = f.read(500)

                if "=N" in primeras and "=I" in primeras:
                    series_extraidas = leer_formato_compacto(ruta)
                elif ext == ".wid":
                    df, sid = leer_wid(ruta)
                    series_extraidas = {f"🌲{sid}": df}
                elif ext in (".rwl", ".txt"):
                    primera_real = ""
                    try:
                        with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
                            for linea in f:
                                ln = linea.rstrip("\r\n")
                                if not ln or ln.startswith("#"):
                                    continue
                                primera_real = ln
                                break
                    except Exception:
                        primera_real = ""

                    if "\t" in primera_real:
                        series_extraidas = self._leer_como_columnas_o_tabular(ruta, base_nombre)
                    else:
                        try:
                            series_extraidas = leer_tucson_multi(ruta)
                        except Exception:
                            series_extraidas = self._leer_como_columnas_o_tabular(ruta, base_nombre)
                elif ext in (".csv", ".tsv") or _es_planilla(ext):
                    series_extraidas = self._leer_como_columnas_o_tabular(ruta, base_nombre)
                else:
                    df, sid = leer_tabular(ruta)
                    series_extraidas = {sid: df}

                for id_serie, df_serie in series_extraidas.items():
                    if id_serie in self.series_datos:
                        n_duplicadas += 1
                        continue
                    self.modelo_series.registrar(id_serie, df_serie)
                    self._series_modificadas(regraficar=False)
                    item = QListWidgetItem(id_serie)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self.lista_series.addItem(item)
                    n_agregadas += 1

            except (ValueError, OSError) as exc:
                logger.warning("Error al cargar %s: %s", ruta, exc)
                errores.append(f"{os.path.basename(ruta)}: {exc}")
                continue

        self.graficar_series()

        if n_agregadas == 0 and not errores:
            QMessageBox.information(
                self, "Sin novedades",
                f"Las {n_duplicadas} series del archivo ya estaban cargadas.")
        elif errores:
            msg = f"Se agregaron {n_agregadas} serie(s)."
            if n_duplicadas:
                msg += f"\n{n_duplicadas} duplicada(s) omitida(s)."
            msg += "\n\nErrores:\n" + "\n".join(errores)
            QMessageBox.warning(self, "Carga con errores", msg)

    def _leer_como_columnas_o_tabular(self, ruta: str, base_nombre: str) -> dict:
        from modulo_formatos import leer_como_columnas_o_tabular
        return leer_como_columnas_o_tabular(ruta, base_nombre)

    def cargar_cronologias_externas(self):
        """Carga cronologías externas con prefijo 📚."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Cargar cronología(s) externa(s)", _ultima_carpeta(),
            "Cronologías y series (*.rwl *.txt *.crn *.wid *.csv *.tsv "
            "*.xlsx *.xls *.ods *.cat *.cmp);;Todos (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
        _ultima_carpeta(ruta)

        ext = os.path.splitext(ruta)[1].lower()
        try:
            # Detectar formato compacto (solo en archivos de texto: una
            # planilla .ods/.xlsx es un ZIP binario y leerla como texto puede
            # dar falsos positivos).
            primeras = ""
            if not _es_planilla(ext):
                with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
                    primeras = f.read(500)
            if "=N" in primeras and "=I" in primeras:
                series = leer_formato_compacto(ruta)
                self._procesar_tucson_como_crono(series, ruta)
                return

            # WID directo
            if ext == ".wid":
                df, sid = leer_wid(ruta)
                self._agregar_crono(f"📚 {sid}", df, ruta)
                return

            # Tucson (.rwl/.txt SIN tabs)
            if ext in (".rwl", ".txt"):
                primera_real = ""
                try:
                    with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
                        for linea in f:
                            ln = linea.rstrip("\r\n")
                            if not ln or ln.startswith("#"):
                                continue
                            primera_real = ln
                            break
                except Exception:
                    primera_real = ""
                if "\t" not in primera_real:
                    try:
                        series = leer_tucson_multi(ruta)
                        if series:
                            self._procesar_tucson_como_crono(series, ruta)
                            return
                    except Exception:
                        pass

            # Multi-columna o tabular
            try:
                # Leer TODAS las hojas (un .ods/.xlsx puede traer una
                # cronología por hoja; pandas solo lee la primera por defecto).
                hojas = leer_columna_multi_hojas(ruta)
                base_nombre = os.path.splitext(os.path.basename(ruta))[0]

                # Detectar columnas auxiliares y descartarlas.
                # Una cronología exportada típicamente trae el VALOR del
                # índice + columnas auxiliares (tamaño de muestra, EPS,
                # Rbar, desviación estándar, etc). Antes cada columna se
                # cargaba como una cronología separada, por eso el usuario
                # veía aparecer 2 o más cronologías al abrir UN archivo.
                # Acá filtramos por nombre los auxiliares conocidos para
                # quedarnos solo con las columnas que son valores de
                # cronología real.
                AUX_COLUMNAS = {
                    # Tamaño de muestra
                    "n", "n_series", "n_samples", "sample_size", "samples",
                    "depth", "count", "cantidad",
                    # Dispersión
                    "sd", "std", "stdev", "stderr", "se", "desv_std",
                    "desviacion", "desviación",
                    # Estadísticos de calidad
                    "rbar", "r_bar", "eps", "snr",
                    # Año (debería estar como índice pero por si acaso)
                    "anio", "año", "year",
                }

                # Armar la lista de candidatos: cada par (hoja, columna) que
                # tenga datos es una cronología potencial.
                candidatos = []  # [(etiqueta, nombre_crono, df_serie)]
                for nombre_hoja, df_multi in hojas.items():
                    cols_validas = [
                        c for c in df_multi.columns
                        if str(c).strip().lower() not in AUX_COLUMNAS
                    ]
                    # Si el filtro quitó todo (raro), no aplicamos el filtro
                    if not cols_validas:
                        cols_validas = list(df_multi.columns)

                    for col in cols_validas:
                        df_serie = pd.DataFrame(
                            {"Ancho_mm": pd.to_numeric(df_multi[col],
                                                       errors="coerce")},
                            index=df_multi.index,
                        ).dropna()
                        if df_serie.empty:
                            continue

                        # Nombre único por cronología. Antes todas las
                        # columnas se agregaban con el MISMO nombre
                        # (el del archivo), así que chocaban entre sí.
                        # Solo se agrega la hoja si hay más de una, y la
                        # columna si hay más de una, para no ensuciar el
                        # nombre con partes redundantes.
                        partes = [base_nombre]
                        if nombre_hoja and len(hojas) > 1:
                            partes.append(str(nombre_hoja))
                        if len(cols_validas) > 1:
                            partes.append(str(col))
                        nombre_crono = "_".join(partes)

                        etiqueta = nombre_crono
                        if len(df_serie):
                            etiqueta += (f"   ({df_serie.index.min()}–"
                                         f"{df_serie.index.max()}, "
                                         f"{len(df_serie)} años)")
                        candidatos.append((etiqueta, nombre_crono, df_serie))

                if not candidatos:
                    raise ValueError("No se encontraron cronologías en el archivo.")

                # Con varias cronologías, preguntar cuáles cargar (todas
                # marcadas por defecto). Con una sola, cargarla directo.
                if len(candidatos) > 1:
                    dlg = DialogoSeleccionCronologias(
                        [c[0] for c in candidatos], parent=self)
                    if dlg.exec() != QDialog.DialogCode.Accepted:
                        return
                    elegidas = set(dlg.seleccionadas())
                    candidatos = [c for c in candidatos if c[0] in elegidas]
                    if not candidatos:
                        return
                elif len(candidatos) == 1:
                    # Una sola: usar el nombre del archivo tal cual
                    etiqueta, _nombre, df_serie = candidatos[0]
                    candidatos = [(etiqueta, base_nombre, df_serie)]

                for _etiqueta, nombre_crono, df_serie in candidatos:
                    self._agregar_crono(f"📚 {nombre_crono}", df_serie, ruta)
                return
            except Exception:
                pass

            df, sid = leer_tabular(ruta)
            self._agregar_crono(f"📚 {sid}", df, ruta)

        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar la cronología:\n{exc}")

        self.graficar_series()

    def _procesar_tucson_como_crono(self, series: dict, ruta: str):
        """Procesa series Tucson de un archivo:
        • 1 serie → la carga directamente como 📚
        • N series → auto-genera cronología (residual+spline+biweight), la
          activa como 📚 y NO carga las series individuales
        """
        if not series:
            return

        if len(series) == 1:
            sid, df = next(iter(series.items()))
            self._agregar_crono(f"📚 {sid}", df, ruta)
            self.graficar_series()
            return

        # Múltiples series → auto-cronología con diálogo de progreso
        nombres = list(series.keys())

        progreso = QProgressDialog(
            f"Generando cronología desde {len(nombres)} series...",
            None, 0, 100, self
        )
        progreso.setWindowTitle("Auto-Cronología")
        progreso.setWindowModality(Qt.WindowModality.WindowModal)
        progreso.setMinimumDuration(0)
        progreso.setCancelButton(None)  # no cancelable, evita estados inconsistentes
        progreso.setValue(5)
        QApplication.processEvents()

        try:
            progreso.setLabelText("Estandarizando series (spline + AR removal)...")
            QApplication.processEvents()
            df_crono, meta = _construir_cronologia_desde_series(
                series, nombres,
                tipo_cronologia="residual",
                metodo_estandarizacion="spline",
                agregacion="biweight",
            )
            progreso.setValue(30)
            QApplication.processEvents()
        except Exception as exc:
            progreso.close()
            QMessageBox.warning(
                self, "Error al generar cronología",
                f"No se pudo generar cronología automática:\n{exc}\n\n"
                "Las series individuales no fueron cargadas."
            )
            return

        nombre_base = os.path.splitext(os.path.basename(ruta))[0]
        nombre = f"{nombre_base}_auto"
        meta["nombre"] = nombre

        # Rbar y EPS ya vienen calculados desde dentro de
        # _construir_cronologia_desde_series sobre las series DETRENDADAS
        # (comparable con ARSTAN "all possible series rbar"). Antes acá
        # se sobrescribían usando series raw, lo que inflaba el Rbar.
        progreso.setValue(50)
        QApplication.processEvents()

        # EPS / Rbar móvil con callback
        progreso.setLabelText("Calculando EPS y Rbar móvil...")
        QApplication.processEvents()

        def _cb_progreso(pct):
            # mapear 0..100 a 50..95
            progreso.setValue(50 + int(pct * 0.45))
            QApplication.processEvents()

        try:
            eps_df = calcular_eps_rbar_movil(
                series, nombres, window=15,
                paso=max(1, len(df_crono) // 200),
                progreso=_cb_progreso,
            )
            if not eps_df.empty:
                meta["EPS_movil"] = eps_df["EPS"].dropna().to_dict()
                meta["Rbar_movil"] = eps_df["Rbar"].dropna().to_dict()
        except Exception as exc:
            logger.warning("EPS/Rbar móvil falló: %s", exc)

        progreso.setLabelText("Activando cronología...")
        progreso.setValue(95)
        QApplication.processEvents()

        # Activar como cronología, garantizando el cierre del diálogo de
        # progreso pase lo que pase (así no queda una ventana "pegada" que
        # parece que nunca termina).
        try:
            self.set_cronologia_activa(df_crono, meta, nombre)
            progreso.setValue(100)
        finally:
            progreso.close()

        # Rbar y EPS para el mensaje: vienen calculados dentro de
        # _construir_cronologia_desde_series y quedan en meta.
        rbar = meta.get("Rbar", float("nan"))
        eps_val = meta.get("EPS", float("nan"))
        rbar_txt = f"{rbar:.3f}" if np.isfinite(rbar) else "—"
        eps_txt = f"{eps_val:.3f}" if np.isfinite(eps_val) else "—"

        QMessageBox.information(
            self, "✅ Cronología generada automáticamente",
            f"Se generó la cronología '{nombre}' a partir de "
            f"{len(nombres)} serie(s) del archivo.\n\n"
            f"  • Años: {len(df_crono)}\n"
            f"  • Tipo: residual (spline 32 años + AR removal)\n"
            f"  • Agregación: biweight\n"
            f"  • Rbar: {rbar_txt}    EPS: {eps_txt}\n\n"
            f"La cronología aparece en la lista con 📚 y está lista para "
            f"cofechado.\n\n"
            f"Si quieres ajustar parámetros (tipo, método, estandarización), "
            f"usa la pestaña 🧭 Cronología."
        )

    def _agregar_crono(self, nombre: str, df: pd.DataFrame, ruta: str):
        """Agrega una cronología 📚 a la lista y la marca como activa.

        La cronología recién cargada queda como `cronologia_activa` para que
        el botón "Series múltiples vs Crono" la encuentre disponible
        inmediatamente. Si ya había una activa anterior, la sobrescribe (el
        usuario puede tener varias en la lista pero solo una "activa" para
        comparaciones).

        Meta mínima: tipo "raw" porque las cronologías cargadas externamente
        ya vienen en su forma final (no se les aplica más transformación).
        """
        if nombre in self.series_datos:
            return
        self.modelo_series.registrar(nombre, df)
        self._series_modificadas(regraficar=False)
        item = QListWidgetItem(nombre)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        self.lista_series.addItem(item)

        # Marcar automáticamente como cronología activa SIN volver a
        # agregarla a la lista (ya la agregamos arriba). El flag
        # agregar_a_lista=False evita la duplicación: antes la cronología
        # aparecía dos veces (una por este método y otra porque
        # set_cronologia_activa también la agregaba).
        meta = {
            "tipo_cronologia": "raw",
            "columna_valor": "Ancho_mm",
            "metodo_estandarizacion": "spline",
        }
        nombre_limpio = nombre.replace("📚 ", "").strip()
        self.set_cronologia_activa(df, meta, nombre_limpio, agregar_a_lista=False)


    # -------------------------------------------------------------------------
    # GESTIÓN DE LA LISTA DE SERIES
    # -------------------------------------------------------------------------

    def _anclaje_actual(self) -> str:
        """Extremo fijo al corregir anillos ('corteza' o 'medula')."""
        combo = getattr(self, "combo_anclaje", None)
        if combo is None:
            return "corteza"
        return combo.currentData() or "corteza"

    def _ordenar_ref_problema(self, n1: str, n2: str) -> tuple[str, str]:
        """Devuelve (referencia, problema) para un par de series.

        La CRONOLOGÍA siempre es la referencia: es el patrón contra el que se
        data y nunca se le insertan ni quitan anillos. Si ninguna lo es (o lo
        son ambas), se usa la más larga como referencia.
        """
        c1 = n1.startswith("📚")
        c2 = n2.startswith("📚")
        if c1 and not c2:
            return n1, n2
        if c2 and not c1:
            return n2, n1
        try:
            if len(self.series_datos[n1]) >= len(self.series_datos[n2]):
                return n1, n2
        except Exception:
            pass
        return n2, n1

    def _serie_seleccionada(self) -> str | None:
        """Devuelve la serie SELECCIONADA (fila resaltada en azul), o None.

        Separación de responsabilidades en la lista de series:
          • La CASILLA (☑) controla qué series se DIBUJAN en el gráfico.
          • La SELECCIÓN (fila azul) es sobre qué serie ACTÚAN los botones
            (editar, restaurar, insertar/borrar anillo, año base, etc.).

        Antes las acciones usaban las casillas y exigían exactamente UNA
        marcada; al comparar una serie con su cronología (lo normal) hay dos
        marcadas, así que los botones no hacían nada y solo avisaban.
        """
        item = self.lista_series.currentItem()
        if item is None:
            return None
        nombre = item.text()
        return nombre if nombre in self.series_datos else None

    def _serie_para_accion(self, accion: str = "editar") -> str | None:
        """Serie sobre la que actuar, con aviso claro si no hay selección.

        Respaldo: si no hay fila seleccionada pero hay exactamente UNA casilla
        marcada, se usa esa (comportamiento antiguo) para no romper la
        costumbre de quien ya trabajaba así.
        """
        nombre = self._serie_seleccionada()
        if nombre is not None:
            return nombre
        marcadas = self._series_marcadas()
        if len(marcadas) == 1:
            return marcadas[0]
        QMessageBox.warning(
            self, "Atención",
            f"Selecciona (haz clic sobre) la serie que quieres {accion}.\n\n"
            "La casilla ☑ solo controla qué series se dibujan en el gráfico; "
            "la fila resaltada en azul es la que se edita.")
        return None
    def _series_marcadas(self) -> list[str]:
        return [
            self.lista_series.item(i).text()
            for i in range(self.lista_series.count())
            if self.lista_series.item(i).checkState() == Qt.CheckState.Checked
        ]

    def toggle_seleccion(self):
        todas = all(
            self.lista_series.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.lista_series.count())
        )
        estado = Qt.CheckState.Unchecked if todas else Qt.CheckState.Checked
        self.lista_series.blockSignals(True)
        for i in range(self.lista_series.count()):
            self.lista_series.item(i).setCheckState(estado)
        self.lista_series.blockSignals(False)
        self.graficar_series()

    def eliminar_series(self):
        """Elimina las series seleccionadas (múltiples permitidas)."""
        items = self.lista_series.selectedItems()
        if not items:
            return

        self._descartar_prueba(silencioso=True)
        nombres_a_eliminar = [item.text() for item in items]
        nombres_set = set(nombres_a_eliminar)

        for nombre in nombres_a_eliminar:
            self.modelo_series.eliminar(nombre)
        self._series_modificadas(regraficar=False)

        for i in range(self.lista_series.count() - 1, -1, -1):
            if self.lista_series.item(i).text() in nombres_set:
                self.lista_series.takeItem(i)

        if self._nombre_referencia in nombres_set:
            self._nombre_referencia = ""
        if self._nombre_problema in nombres_set:
            self._nombre_problema = ""

        if (self._nombre_cronologia_activa and
                f"📚 {self._nombre_cronologia_activa}" in nombres_set):
            self.cronologia_activa = None
            self.meta_cronologia = None
            self._nombre_cronologia_activa = ""
            self.lbl_info_crono.setVisible(False)
            self.btn_eps_crono.setEnabled(False)

        self.graficar_series()

        necesita_limpiar = (
            not self._nombre_referencia or not self._nombre_problema or
            self._nombre_referencia not in self.series_datos or
            self._nombre_problema not in self.series_datos
        )
        if necesita_limpiar:
            self.grafico_offset.clear()
            self._shifts_actuales.clear()
            self._r_actuales.clear()
            self._glk_actuales.clear()
            self._tbp_actuales.clear()
            self._n_actuales.clear()
            self._stats_movil_years.clear()
            self._stats_movil_r.clear()
            self._stats_movil_glk.clear()
            self._stats_movil_tbp.clear()
            self._stats_movil_n.clear()
            self._sugerencias = []
            self.tabla_sugerencias.setRowCount(0)
            self.btn_aplicar.setEnabled(False)
            self.lbl_stats.setVisible(False)
            self.btn_ver_tabla_off.setEnabled(False)

    def editar_anio_serie(self):
        """Cambia el año base de la serie seleccionada.

        Muestra un diálogo con DOS spinboxes:
          • Año del primer anillo (MÉDULA) ← campo principal, foco por defecto
          • Año del último anillo (CORTEZA)
        Al cambiar uno, el otro se ajusta automáticamente. El usuario edita
        el que tenga datos confiables (típicamente médula para series flotantes,
        corteza para muestras con corteza preservada).
        """
        items = self.lista_series.selectedItems()
        if not items:
            QMessageBox.warning(self, "Atención",
                                "Selecciona una serie (haz clic sobre su nombre).")
            return
        if len(items) > 1:
            QMessageBox.warning(self, "Atención", "Edita una sola serie a la vez.")
            return

        nombre = items[0].text()
        self._descartar_prueba(silencioso=True)
        df = self.series_datos.get(nombre)
        if df is None or df.empty:
            return

        n_anios = len(df)
        anio_medula_actual = int(df.index.min())
        anio_corteza_actual = int(df.index.max())

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Editar año base — {nombre}")
        dlg.setMinimumWidth(440)
        v = QVBoxLayout(dlg)

        info = QLabel(
            f"<b>Serie:</b> {nombre}<br>"
            f"<b>Rango actual:</b> {anio_medula_actual} → {anio_corteza_actual} "
            f"<span style='color:{color_secundario()};'>({n_anios} años)</span>"
        )
        v.addWidget(info)

        hint = QLabel(
            f"<span style='color:{color_secundario()}; font-size:11px;'>"
            "Edita el campo que conozcas con certeza. El otro se "
            "ajusta automáticamente. Para series flotantes lo habitual "
            "es anclar el primer año (médula); para muestras con corteza "
            "preservada se ancla el último año."
            "</span>"
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        form = QFormLayout()
        spin_medula = SpinBoxFlechas()
        spin_medula.setRange(-10000, 5000)
        spin_medula.setValue(anio_medula_actual)
        spin_medula.setStyleSheet("QSpinBox{font-weight:bold; color:#5cb85c;}")
        form.addRow("🌱 <b>Primer año (MÉDULA):</b>", spin_medula)

        spin_corteza = SpinBoxFlechas()
        spin_corteza.setRange(-10000, 5000)
        spin_corteza.setValue(anio_corteza_actual)
        spin_corteza.setStyleSheet("QSpinBox{color:#f0ad4e;}")
        form.addRow("🪵 Último año (CORTEZA):", spin_corteza)
        v.addLayout(form)

        # Vinculación: cuando cambia uno, el otro se ajusta
        _bloqueado = [False]

        def _sync_desde_medula():
            if _bloqueado[0]:
                return
            _bloqueado[0] = True
            spin_corteza.setValue(spin_medula.value() + n_anios - 1)
            _bloqueado[0] = False

        def _sync_desde_corteza():
            if _bloqueado[0]:
                return
            _bloqueado[0] = True
            spin_medula.setValue(spin_corteza.value() - n_anios + 1)
            _bloqueado[0] = False

        spin_medula.valueChanged.connect(_sync_desde_medula)
        spin_corteza.valueChanged.connect(_sync_desde_corteza)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        # Foco en MÉDULA por default
        spin_medula.setFocus()
        spin_medula.selectAll()

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        nuevo_medula = spin_medula.value()
        delta = nuevo_medula - anio_medula_actual
        if delta == 0:
            return

        nuevo_idx = df.index + delta
        df_nuevo = df.copy()
        df_nuevo.index = nuevo_idx
        df_nuevo.sort_index(inplace=True)

        self.modelo_series.actualizar(nombre, df_nuevo)
        self._series_modificadas()
        QMessageBox.information(
            self, "Año actualizado",
            f"Serie '{nombre}' desplazada {delta:+d} años.\n"
            f"Ahora va de {int(df_nuevo.index.min())} a {int(df_nuevo.index.max())}."
        )

    def _exportar_una_serie(self, nombre: str):
        """Exporta UNA serie por nombre (usado al exportar varias a la vez)."""
        prev = self.lista_series.currentItem()
        for i in range(self.lista_series.count()):
            it = self.lista_series.item(i)
            if it.text() == nombre:
                self.lista_series.setCurrentItem(it)
                break
        try:
            self._exportar_serie_por_nombre(nombre)
        finally:
            if prev is not None:
                self.lista_series.setCurrentItem(prev)

    def exportar_serie_codatada(self):
        """Exporta la serie marcada con formato según extensión.

        Si el modo COFECHA está activo y aplica a este tipo (serie o
        cronología), ofrece guardar la serie ESTANDARIZADA (la misma
        transformación que se usa para las correlaciones) en vez de los
        datos crudos. Así el usuario puede subir una serie, activar el modo
        COFECHA y guardar la versión estandarizada directamente.
        """
        # Exporta la(s) serie(s) SELECCIONADA(S) (filas resaltadas), no las
        # marcadas con casilla: la casilla es solo para elegir qué se grafica.
        seleccionadas = [it.text() for it in self.lista_series.selectedItems()
                         if it.text() in self.series_datos]
        if not seleccionadas:
            nombre_unico = self._serie_para_accion("exportar")
            if nombre_unico is None:
                return
            seleccionadas = [nombre_unico]

        if len(seleccionadas) > 1:
            resp = QMessageBox.question(
                self, "Varias series seleccionadas",
                f"Hay {len(seleccionadas)} series seleccionadas.\n\n"
                "¿Exportarlas todas? Se pedirá una ubicación por cada una.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if resp != QMessageBox.StandardButton.Yes:
                return
            for nom in seleccionadas:
                self._exportar_una_serie(nom)
            return

        self._exportar_serie_por_nombre(seleccionadas[0])

    def _exportar_serie_por_nombre(self, nombre: str):
        """Cuerpo real de la exportación, para una serie ya elegida."""
        df = self.series_datos.get(nombre)
        if df is None or df.empty:
            QMessageBox.warning(self, "Sin datos",
                                f"'{nombre}' no tiene datos para exportar.")
            return
        es_crono = nombre.startswith("📚 ")

        # ¿El modo COFECHA aplica a este tipo (serie/cronología)?
        cofecha_aplica = (
            self.btn_modo_cofecha.isChecked() and (
                (es_crono and self.chk_cof_crono.isChecked()) or
                (not es_crono and self.chk_cof_serie.isChecked())
            )
        )

        exportar_std = False
        if cofecha_aplica:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Modo COFECHA activo")
            box.setText(
                f"El modo COFECHA está activo para esta {'cronología' if es_crono else 'serie'}.\n\n"
                f"¿Qué quieres guardar de '{nombre}'?")
            b_std = box.addButton("Estandarizada (COFECHA)",
                                  QMessageBox.ButtonRole.YesRole)
            box.addButton("Datos originales", QMessageBox.ButtonRole.NoRole)
            b_cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is b_cancel:
                return
            exportar_std = box.clickedButton() is b_std

        # ── Exportar ESTANDARIZADA (índice residual COFECHA, 2 columnas) ──
        if exportar_std:
            serie_std = aplicar_modo_cofecha(
                df["Ancho_mm"], **self._modo_cofecha_params)
            nombre_limpio = nombre.replace("📚 ", "").strip()
            self._guardar_serie_2col(
                serie_std, f"{nombre_limpio}_cofecha",
                "Exportar serie estandarizada (COFECHA)",
                estandarizada=True)
            return

        # ── Cronologías → formato 2-columnas con coma decimal ──
        if es_crono:
            nombre_limpio = nombre.replace("📚 ", "").strip()
            # Añadir el tipo de cronología al nombre de archivo por defecto
            # (RES/STD/RAW) para que quede claro qué se guardó. Se usa el tipo
            # de la cronología ACTIVA si el nombre coincide; si no, el de la
            # metadata disponible.
            tipo_c = ""
            if nombre_limpio == self._nombre_cronologia_activa:
                tipo_c = (self.meta_cronologia or {}).get("tipo_cronologia", "")
            tag = {"residual": "RES", "standard": "STD",
                   "raw": "RAW"}.get((tipo_c or "").lower(), "")
            nombre_archivo = f"{nombre_limpio}_{tag}" if tag else nombre_limpio
            self._guardar_serie_2col(
                pd.to_numeric(df["Ancho_mm"], errors="coerce"),
                nombre_archivo, "Exportar cronología", estandarizada=False)
            return

        # ── Series normales → exportador Tucson (anchos crudos en mm) ──
        mediciones = [{"anio": int(idx), "ancho_mm": float(val)}
                      for idx, val in df["Ancho_mm"].items()]
        exp = getattr(self._ventana_padre, "exportador", None)
        if exp:
            exp.exportar_datos(nombre, mediciones)
        else:
            QMessageBox.information(self, "Sin exportador",
                                    "No hay un exportador disponible.")

    def _guardar_serie_2col(self, serie, nombre_archivo, titulo,
                             estandarizada=False):
        """Guarda una serie en formato 2 columnas (Año, Valor) con coma
        decimal. Usado para cronologías y para series estandarizadas
        COFECHA (que son índices residuales adimensionales, no anchos en
        mm, por lo que NO van por el exportador Tucson)."""
        ruta_default = os.path.join(_ultima_carpeta(), f"{nombre_archivo}.txt")
        ruta, fmt = QFileDialog.getSaveFileName(
            self, titulo, ruta_default,
            "Texto separado por tabulaciones (*.txt);;"
            "Tucson (*.rwl);;"
            "CSV separado por punto y coma (*.csv);;"
            "Excel (*.xlsx);;LibreOffice (*.ods)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return
        ruta = _asegurar_extension(ruta, fmt)
        _ultima_carpeta(ruta)
        from modulo_formatos import exportar_serie_2col
        try:
            n_anios = exportar_serie_2col(serie, ruta, nombre_archivo)
            if estandarizada:
                nota = ("Valores ESTANDARIZADOS por modo COFECHA "
                        "(índice residual adimensional, no anchos en mm).")
            else:
                nota = "Formato 2 columnas (Año, Valor) con coma decimal."
            QMessageBox.information(
                self, "✅ Serie exportada",
                f"Archivo guardado:\n{ruta}\n\n{nota}\n"
                f"Años: {n_anios}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{exc}")

    # -------------------------------------------------------------------------
    # SIMULADOR MANUAL
    # -------------------------------------------------------------------------

    def simular_insertar(self):
        self._simular_correccion(1)

    def simular_borrar(self):
        self._simular_correccion(-1)

    def _simular_correccion(self, delta):
        nombre = self._serie_para_accion("editar")
        if nombre is None:
            return
        self._descartar_prueba(silencioso=True)
        anio = self.spin_edit_year.value()
        corregido = aplicar_correccion(
            self.series_datos[nombre], anio, delta, anclaje=self._anclaje_actual())
        try:
            self.modelo_series.actualizar(nombre, corregido)
        except (ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "Corrección inválida", str(exc))
            return
        self._series_modificadas()

    def abrir_skeleton_plot(self):
        """Va a la pestaña Skeleton, importa las series de Co-Datación y, si
        hay exactamente dos marcadas, las fija como referencia y flotante.

        `ir_a_skeleton` lo conecta main_anillos: recibe (ref_nombre_o_None,
        flo_nombre_o_None) para preseleccionar el par (o None para solo ir e
        importar)."""
        marcadas = self._series_marcadas()
        ref_nombre = flo_nombre = None
        if len(marcadas) == 2:
            cronos = [n for n in marcadas if n.startswith("📚")]
            if cronos:
                ref_nombre = cronos[0]
                flo_nombre = [n for n in marcadas if n != ref_nombre][0]
            else:
                ref_nombre, flo_nombre = marcadas[0], marcadas[1]

        cb = getattr(self, "ir_a_skeleton", None)
        if callable(cb):
            cb(ref_nombre, flo_nombre)
        else:
            QMessageBox.information(
                self, "Skeleton",
                "Abre la pestaña Skeleton e importa las series desde allí.")

    def restaurar_serie(self):
        nombre = self._serie_para_accion("restaurar")
        if nombre is None:
            return
        if nombre not in self.series_originales:
            QMessageBox.information(
                self, "Sin original",
                f"'{nombre}' no tiene una copia original guardada "
                "(no se le han aplicado correcciones).")
            return
        self._descartar_prueba(silencioso=True)
        self.modelo_series.restablecer(nombre)
        self._series_modificadas()
        QMessageBox.information(
            self, "Restaurada",
            f"'{nombre}' volvió a sus valores originales.")

    def restaurar_original_sugerencias(self):
        """Restablece a sus valores originales la serie que se está
        corrigiendo (la del cofechado/sugerencias). Si no hay una serie
        problema definida, usa la serie marcada."""
        nombre = getattr(self, "_nombre_problema", None)
        if not nombre or nombre not in self.series_datos:
            marcadas = self._series_marcadas()
            nombre = marcadas[0] if len(marcadas) == 1 else None
        if not nombre or nombre not in self.series_originales:
            QMessageBox.warning(
                self, "Sin original",
                "No hay una serie con valores originales para restablecer.\n"
                "Cofecha o selecciona una serie primero.")
            return
        resp = QMessageBox.question(
            self, "Restablecer valores originales",
            f"¿Restablecer '{nombre}' a sus valores originales?\n\n"
            "Se descartarán todas las correcciones de anillos aplicadas a "
            "esta serie.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._descartar_prueba(silencioso=True)
        self.modelo_series.restablecer(nombre)
        self._series_modificadas(regraficar=False)
        self._limpiar_preview()
        self._sugerencias.clear()
        self.tabla_sugerencias.setRowCount(0)
        self.btn_aplicar.setEnabled(False)
        self.graficar_series()
        self.buscar_errores()

    # -------------------------------------------------------------------------
    # VISUALIZACIÓN DE SERIES
    # -------------------------------------------------------------------------

    def _anotar_anios_en_lista(self):
        """Recorre todas las series de la lista y anota en cada item su
        rango de años como tooltip. Si el último año de una serie supera
        el año actual (presente), marca el item con color de advertencia
        y un símbolo ⚠️ en el tooltip.

        Esto es importante sobre todo para series flotantes: cuando se les
        asigna un año de inicio, el último año puede quedar más allá del
        presente, lo que es físicamente imposible (un árbol no tiene
        anillos en el futuro) y delata un año de inicio mal asignado.
        """
        import datetime
        anio_actual = datetime.datetime.now().year

        # Colores de advertencia según el tema (claro/oscuro). Usamos un
        # naranja/rojo que contraste en ambos.
        COLOR_ADVERTENCIA = QColor("#e67e22")  # naranja
        # Color de texto normal heredado del tema actual de la lista
        COLOR_NORMAL = self.lista_series.palette().color(
            QPalette.ColorRole.Text)

        for i in range(self.lista_series.count()):
            item = self.lista_series.item(i)
            nombre = item.text()
            df = self.series_datos.get(nombre)
            if df is None or df.empty:
                item.setToolTip("Serie sin datos")
                continue

            try:
                anio_min = int(df.index.min())
                anio_max = int(df.index.max())
            except (ValueError, TypeError):
                item.setToolTip("Rango de años no disponible")
                continue

            n_anios = anio_max - anio_min + 1
            tooltip = (f"Años: {anio_min} – {anio_max}  ({n_anios} años)")

            # Para la cronología activa (📚), anteponer su tipo (RES/STD/RAW)
            # para que el usuario sepa en qué espacio está.
            if (nombre.startswith("📚") and
                    nombre.replace("📚 ", "").strip() == self._nombre_cronologia_activa):
                tag = getattr(self, "_tag_tipo_cronologia", "") or {
                    "residual": "RES", "standard": "STD", "raw": "RAW"}.get(
                    ((self.meta_cronologia or {}).get("tipo_cronologia") or "").lower(), "")
                if tag:
                    nombre_tipo = {"RES": "residual", "STD": "standard",
                                   "RAW": "cruda"}.get(tag, "")
                    tooltip = (f"Cronología · tipo {tag} ({nombre_tipo})\n"
                               + tooltip)

            if anio_max > anio_actual:
                # El último año supera el presente → advertencia
                exceso = anio_max - anio_actual
                tooltip += (
                    f"\n\n⚠️ El último año ({anio_max}) supera el año actual "
                    f"({anio_actual}) por {exceso} año(s).\n"
                    f"Si es una serie flotante, revisa el año de inicio "
                    f"asignado: probablemente está corrido hacia el futuro."
                )
                item.setForeground(COLOR_ADVERTENCIA)
            else:
                # Restaurar color normal del tema
                item.setForeground(COLOR_NORMAL)

            item.setToolTip(tooltip)

    def _series_modificadas(self, *, regraficar=True):
        """Invalida resultados de comparación tras cambiar datos o cronología."""
        self._cache_comparacion = None
        if regraficar:
            self.graficar_series()

    def graficar_series(self):
        """Redibuja el gráfico principal con las series marcadas.

        Si el Modo COFECHA está activo, grafica las series TRANSFORMADAS
        (spline + log + AR(1) según configuración) en vez del ancho crudo,
        respetando los checkboxes 'Aplicar a: Serie / Cronología'. Esto
        permite ver las series detrendadas superpuestas, que es mucho más
        informativo para cofechar que el ancho crudo (donde la tendencia
        de crecimiento por edad domina y oculta la señal común).
        """
        # Anotar el rango de años de cada serie en la lista (tooltip +
        # aviso si el último año supera el presente).
        self._anotar_anios_en_lista()

        self.grafico.clear()

        # Recrear la leyenda en cada repintado. En algunas versiones de
        # pyqtgraph, clear() NO borra la leyenda, y ésta acumula los códigos
        # de todas las series dibujadas (una "ventana" de leyenda que persiste
        # y crece). Recrearla garantiza que solo muestre las series actuales.
        if self.grafico.plotItem.legend is not None:
            try:
                self.grafico.plotItem.legend.scene().removeItem(
                    self.grafico.plotItem.legend)
            except Exception:
                pass
            self.grafico.plotItem.legend = None
        self.grafico.addLegend()

        modo_cofecha = self.btn_modo_cofecha.isChecked()
        modo_barras = (hasattr(self, "btn_grafico_barras") and
                       self.btn_grafico_barras.isChecked())
        graficadas = 0
        series_a_dibujar = []  # [(nombre, valores, color)] usado en modo barras
        for i in range(self.lista_series.count()):
            item = self.lista_series.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            nombre = item.text()
            if nombre not in self.series_datos:
                continue
            df = self.series_datos[nombre]
            serie_mm = pd.to_numeric(df["Ancho_mm"], errors="coerce")

            # Decidir si transformar esta serie según el modo y los checkboxes
            es_crono = nombre.startswith("📚")
            transformar = modo_cofecha and (
                (es_crono and self.chk_cof_crono.isChecked()) or
                (not es_crono and self.chk_cof_serie.isChecked())
            )
            if transformar:
                try:
                    # Usar la MISMA transformación que la correlación para que
                    # la serie quede en el espacio de la cronología activa
                    # (índice residual, media ~1) y se pueda superponer
                    # visualmente con la cronología. Antes se usaba
                    # aplicar_modo_cofecha (log, media 0) y los gráficos
                    # quedaban en escalas distintas (crono en 1, serie en 0).
                    valores = self._transformar_para_correlacion(
                        serie_mm, es_crono)
                except Exception:
                    valores = serie_mm
            else:
                valores = serie_mm

            valores = valores.dropna()
            if valores.empty:
                continue

            color = COLORES_SERIES[graficadas % len(COLORES_SERIES)]
            if modo_barras:
                # Se acumulan para dibujarlas después: hay que saber cuántas
                # series hay para repartir el ancho de las barras por año.
                series_a_dibujar.append((nombre, valores, color))
            else:
                self.grafico.plot(
                    valores.index.to_numpy(dtype=float),
                    valores.to_numpy(dtype=float),
                    pen=pg.mkPen(color, width=2),
                    name=nombre,
                )
            graficadas += 1

        if modo_barras and series_a_dibujar:
            self._dibujar_barras_desviacion(series_a_dibujar)

        # Actualizar etiqueta del eje Y según el modo
        if modo_cofecha:
            self.grafico.setLabel("left", "Índice estandarizado (media ~1)")
        else:
            self.grafico.setLabel("left", "Ancho de anillo (mm)")

    def _dibujar_barras_desviacion(self, series: list):
        """Dibuja las series como barras que salen de su MEDIA.

        La media de cada serie es el eje central: la barra sube cuando el
        año está sobre la media y baja cuando está bajo la media. Con varias
        series marcadas, las barras del mismo año se reparten lado a lado
        para que no se tapen.
        """
        n = len(series)
        # Ancho total ocupado por año (0.8 deja aire entre años).
        ancho_total = 0.8
        ancho_barra = ancho_total / n
        # Desplazamiento para centrar el grupo de barras en el año.
        offset_base = -ancho_total / 2 + ancho_barra / 2

        for k, (nombre, valores, color) in enumerate(series):
            anios = valores.index.to_numpy(dtype=float)
            vals = valores.to_numpy(dtype=float)
            media = float(np.nanmean(vals))
            desv = vals - media

            # Verde sobre la media, rojo bajo la media. Con una sola serie se
            # usa ese código de color (más legible); con varias se usa el
            # color de la serie para poder distinguirlas entre sí.
            if n == 1:
                brushes = ["#c0392b" if d < 0 else "#27ae60" for d in desv]
            else:
                brushes = [color] * len(desv)

            x = anios + (offset_base + k * ancho_barra)
            barras = pg.BarGraphItem(
                x=x, height=desv, width=ancho_barra * 0.9, y0=media,
                brushes=brushes, pen=pg.mkPen(None),
            )
            self.grafico.addItem(barras)

            # Línea de la media (el "eje" de la serie), punteada en su color.
            linea = pg.InfiniteLine(
                pos=media, angle=0,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
            )
            self.grafico.addItem(linea)

            # Entrada de leyenda (BarGraphItem no la agrega solo).
            try:
                muestra = pg.PlotDataItem(pen=pg.mkPen(color, width=6))
                self.grafico.plotItem.legend.addItem(muestra, nombre)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # CRONOLOGÍA ACTIVA
    # -------------------------------------------------------------------------

    def abrir_ventana_cronologia(self):
        """Cambia a la pestaña de Cronología (antes abría una ventana
        flotante; ahora la cronología es una pestaña propia)."""
        vp = getattr(self, "_ventana_padre", None)
        if vp is not None and hasattr(vp, "ir_a_pestana_cronologia"):
            vp.ir_a_pestana_cronologia()
        elif self._ventana_cronologia is not None:
            # Respaldo: si no hay ventana principal con pestañas, mostrar
            # como ventana flotante (compatibilidad).
            self._ventana_cronologia.show()
            self._ventana_cronologia.raise_()

    def set_cronologia_activa(self, df: pd.DataFrame, meta: dict, nombre: str,
                               agregar_a_lista: bool = True):
        """Setea la cronología activa para cofechado.

        Parámetro `agregar_a_lista`:
          - True (default): agrega la cronología a la lista de series con
            prefijo 📚 (comportamiento usado cuando se genera una
            cronología desde la VentanaCronologia, que NO la tiene aún
            en la lista).
          - False: NO toca la lista — solo marca la cronología como activa
            y actualiza la etiqueta informativa. Se usa desde
            `_agregar_crono`, que YA agregó la cronología a la lista. Sin
            este flag, la cronología aparecía DUPLICADA: una vez por
            `_agregar_crono` y otra por esta función.
        """
        self._descartar_prueba(silencioso=True)
        self.cronologia_activa = df.copy()
        self.meta_cronologia = dict(meta) if meta else {}
        self._nombre_cronologia_activa = nombre or "Cronología"
        self._series_modificadas(regraficar=False)

        if agregar_a_lista:
            # Agregar a la lista como 📚
            nombre_lista = f"📚 {self._nombre_cronologia_activa}"
            col_val = self.meta_cronologia.get("columna_valor", df.columns[0])
            if col_val not in df.columns:
                col_val = df.columns[0]
            df_serie = pd.DataFrame({"Ancho_mm": df[col_val]}, index=df.index)
            df_serie = df_serie.dropna()

            existe = nombre_lista in self.series_datos
            self.modelo_series.registrar(nombre_lista, df_serie)
            if not existe:
                item = QListWidgetItem(nombre_lista)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.lista_series.addItem(item)

        # Mostrar info de cronología (siempre, sin importar agregar_a_lista)
        n_anios = len(df)
        n_series = self.meta_cronologia.get("n_series", 0)
        rbar = self.meta_cronologia.get("Rbar", float("nan"))
        eps = self.meta_cronologia.get("EPS", float("nan"))

        # Etiqueta corta del tipo de cronología: RES (residual), STD
        # (standard) o RAW (cruda). Se muestra al usuario para que sepa en qué
        # espacio está la cronología (una RES vive en torno a media 1).
        tipo_crono = (self.meta_cronologia.get("tipo_cronologia") or "raw").lower()
        tag_tipo = {"residual": "RES", "standard": "STD", "raw": "RAW"}.get(
            tipo_crono, tipo_crono.upper()[:3])
        nombre_tipo = {"RES": "residual", "STD": "standard",
                       "RAW": "cruda"}.get(tag_tipo, tipo_crono)
        self._tag_tipo_cronologia = tag_tipo

        info = f"📚 <b>{self._nombre_cronologia_activa}</b> [{tag_tipo}] — {n_anios} años"
        if n_series:
            info += f", {n_series} series"
        if np.isfinite(rbar):
            info += f", Rbar={rbar:.3f}"
        if np.isfinite(eps):
            info += f", EPS={eps:.3f}"
        self.lbl_info_crono.setText(info)
        # NO se hace visible: este QLabel quedó vestigial al mover la sección
        # de Cronología a su propia pestaña. Antes se hacía setVisible(True),
        # pero como el label no está en ningún layout (sin padre visible), Qt
        # lo mostraba como una ventana suelta transparente titulada
        # "run_dpi.py" detrás del programa. Se mantiene oculto.

        # Habilitar botón EPS si hay datos móviles
        tiene_eps_movil = bool(self.meta_cronologia.get("EPS_movil"))
        self.btn_eps_crono.setEnabled(tiene_eps_movil)

        self.graficar_series()

    def _mostrar_eps_cronologia_activa(self):
        """Muestra el diálogo de EPS/Rbar móvil de la cronología activa."""
        _mostrar_dialogo_eps_rbar(
            self, self.meta_cronologia or {}, self._nombre_cronologia_activa
        )

    # -------------------------------------------------------------------------
    # MODO COFECHA
    # -------------------------------------------------------------------------

    def _on_modo_cofecha_toggled(self, activo: bool):
        """Al activar/desactivar el Modo COFECHA, actualiza el texto del
        botón y redibuja el gráfico para mostrar las series transformadas
        (si activo) o el ancho crudo (si inactivo)."""
        self.btn_modo_cofecha.setText(
            "🎯 Modo COFECHA ACTIVO" if activo else "🎯 Activar Modo COFECHA")
        self.graficar_series()

    def _on_cofecha_aplicar_cambiado(self, _checked: bool):
        """Al cambiar los checkboxes 'Aplicar a: Serie/Cronología',
        redibuja solo si el modo COFECHA está activo (si no, no tiene
        efecto visible)."""
        if self.btn_modo_cofecha.isChecked():
            self.graficar_series()

    def _configurar_modo_cofecha(self):
        """Abre el diálogo de configuración del modo COFECHA."""
        dlg = DialogoCofecha(self, self._modo_cofecha_params)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._modo_cofecha_params = dlg.get_params()
            # Si el modo está activo, redibujar con los nuevos parámetros
            if self.btn_modo_cofecha.isChecked():
                self.graficar_series()

    # -------------------------------------------------------------------------
    # TRANSFORMACIÓN PARA CORRELACIÓN
    # -------------------------------------------------------------------------

    def _transformar_para_correlacion(self, serie_mm: pd.Series, es_crono: bool) -> pd.Series:
        """Transformación para calcular la r de correlación, gobernada por el
        botón modo COFECHA.

        Punto CLAVE (corrige un bug grave): para que la r coincida con COFECHA,
        la serie y la cronología deben quedar en el MISMO espacio. Una
        cronología residual se construyó con spline+AR (sin log); si a la
        serie se le aplicaba `aplicar_modo_cofecha` (spline+LOG+AR), quedaban
        en espacios distintos y la r se desplomaba (p. ej. 0.90 → 0.51, o peor
        con datos reales). La solución es estandarizar la SERIE cruda con el
        MISMO método que usó la cronología activa, y NO re-procesar la
        cronología (ya está estandarizada).

        - Modo COFECHA apagado: sin transformación (la serie tal como se subió).
        - Modo COFECHA encendido:
            • Cronología (es_crono=True): se usa tal cual (ya estandarizada;
              re-procesarla la dañaría). El checkbox 'Cronología' fuerza a
              estandarizarla igual, para el caso de una cronología cargada
              SIN estandarizar (anchos crudos en mm).
            • Serie cruda (es_crono=False): se estandariza con el método de la
              cronología activa (residual/standard + spline), quedando en su
              mismo espacio. Si no hay cronología activa comparable, se usa la
              estandarización COFECHA clásica (simétrica entre dos series).
          El checkbox 'Serie' permite desactivar la estandarización de la
          serie (usarla cruda) si el usuario ya la subió estandarizada.
        """
        s_raw = pd.to_numeric(serie_mm, errors="coerce").astype(float).dropna()
        if not self.btn_modo_cofecha.isChecked():
            return s_raw

        if es_crono:
            # Por defecto la cronología ya vive en su espacio estandarizado
            # (índice residual/standard), así que NO se re-procesa: aplicarle
            # spline+log+AR encima la dañaría y desplomaría la r.
            #
            # El checkbox 'Cronología' es la salida de escape para el caso en
            # que la cronología cargada NO esté estandarizada (p. ej. una
            # cronología de anchos crudos en mm): ahí sí hay que estandarizarla
            # para poder compararla. Por eso el valor por defecto es apagado.
            if not self.chk_cof_crono.isChecked():
                return s_raw
            try:
                res = aplicar_modo_cofecha(serie_mm, **self._modo_cofecha_params)
                if res is not None and not res.empty:
                    return res
            except Exception:
                pass
            return s_raw

        # Serie cruda: solo estandarizar si el checkbox 'Serie' está activo.
        if not self.chk_cof_serie.isChecked():
            return s_raw

        meta = self.meta_cronologia or {}
        tipo = (meta.get("tipo_cronologia") or "").lower()
        metodo = meta.get("metodo_estandarizacion") or "spline"

        # Si el tipo no está en la metadata (p. ej. una cronología cargada
        # desde un archivo plano sin encabezado de tipo), inferirlo del espacio
        # de la cronología activa. Una cronología residual/standard vive en
        # torno a media 1 (índice adimensional); una serie COFECHA clásica vive
        # en torno a 0 (log-residual). Sin esta inferencia, la serie se
        # transformaba con log-COFECHA (media 0) contra una cronología en media
        # 1 —espacios distintos— y la r se desplomaba a casi 0.
        if tipo not in ("residual", "standard") and self.cronologia_activa is not None:
            try:
                mcol = meta.get("columna_valor")
                dfc = self.cronologia_activa
                if not mcol or mcol not in dfc.columns:
                    mcol = dfc.columns[0]
                media_crono = float(
                    pd.to_numeric(dfc[mcol], errors="coerce").dropna().mean())
                if 0.5 < media_crono < 1.5:
                    tipo = "residual"
            except Exception:
                pass

        if tipo in ("residual", "standard"):
            try:
                aplicar_log = bool(meta.get("aplicar_log", False))
                res = _normalizar_serie_para_tipo(
                    serie_mm, tipo, metodo, aplicar_log=aplicar_log)
                if res is not None and not res.empty:
                    return res
            except Exception:
                pass
        # Sin cronología activa comparable: COFECHA clásico (simétrico).
        return aplicar_modo_cofecha(serie_mm, **self._modo_cofecha_params)

    def _serie_para_glk(self, serie_mm: pd.Series, es_crono: bool) -> pd.Series:
        """Serie para calcular GLK y t-BP.

        GLK y t-BP diferencian internamente (GLK usa el signo de la primera
        diferencia; t-BP aplica el filtro de Hollstein = diff-log), así que se
        calculan sobre los datos CRUDOS y no necesitan la estandarización
        COFECHA. Esto los mantiene estables y comparables con el uso clásico.
        """
        return pd.to_numeric(serie_mm, errors="coerce").astype(float).dropna()

    def _preparar_diferencias_log(self, n1: str, n2: str):
        """Prepara las series transformadas de un par para cofechado."""
        df1 = self.series_datos[n1]
        df2 = self.series_datos[n2]
        es_crono_1 = n1.startswith("📚")
        es_crono_2 = n2.startswith("📚")

        # El leave-one-out vive ahora en la pestaña COFECHA, donde todas las
        # series miembro están cargadas y puede aplicarse siempre. Acá se
        # comparan las series tal cual.
        s1 = df1["Ancho_mm"]
        s2 = df2["Ancho_mm"]
        d1 = self._transformar_para_correlacion(s1, es_crono_1)
        d2 = self._transformar_para_correlacion(s2, es_crono_2)
        return d1, d2, n1, n2

    def _fmt_r(self, r: float) -> str:
        if not np.isfinite(r):
            return "—"
        return f"{r:.3f}"


    # -------------------------------------------------------------------------
    # ANÁLISIS DE OFFSET (BÚSQUEDA DE DESFASE)
    # -------------------------------------------------------------------------

    def analizar_offset(self):
        """Análisis de desfase: r/GLK/t-BP por cada shift posible."""
        marcadas = self._series_marcadas()
        if len(marcadas) != 2:
            return QMessageBox.warning(self, "Atención", "Marque EXACTAMENTE dos series.")

        # Determinar cuál es la SERIE (se mueve) y cuál la CRONOLOGÍA (fija,
        # referencia). Se distinguen por el prefijo 📚 de las cronologías.
        # El desfase se aplica siempre a la SERIE para alinearla con la
        # cronología. Si ninguna o ambas son cronología, se respeta el
        # orden de marcado (la primera se mueve).
        cronos = [m for m in marcadas if m.startswith("📚")]
        series = [m for m in marcadas if not m.startswith("📚")]
        if len(cronos) == 1 and len(series) == 1:
            mover, referencia = series[0], cronos[0]
        else:
            mover, referencia = marcadas[0], marcadas[1]

        # Limpiar modo de la curva de cofechado
        self._stats_movil_years = []
        self._stats_movil_r = []
        self._stats_movil_glk = []
        self._stats_movil_tbp = []
        self._stats_movil_n = []

        self.grafico_offset.clear()
        self.grafico_offset.setTitle("Procesando…")
        self.grafico_offset.addItem(self._texto_hover)
        self._texto_hover.hide()

        # m_diff = serie que se MUEVE; t_diff = cronología/referencia FIJA
        m_diff, t_diff, n_m, n_t = self._preparar_diferencias_log(mover, referencia)

        if (len(m_diff) < OVERLAP_MINIMO_ANALISIS or
                len(t_diff) < OVERLAP_MINIMO_ANALISIS):
            return self.grafico_offset.setTitle(
                f"Error: Se requieren >{OVERLAP_MINIMO_ANALISIS} años.")

        serie_a_raw = pd.to_numeric(
            self.series_datos[n_m]["Ancho_mm"], errors="coerce").dropna()
        serie_b_raw = pd.to_numeric(
            self.series_datos[n_t]["Ancho_mm"], errors="coerce").dropna()

        # Series para GLK/t-BP respetando el modo COFECHA (transformadas si
        # está activo; crudas si no). Así estos estadísticos también miran
        # el botón modo COFECHA, igual que r.
        serie_a_glk = self._serie_para_glk(
            self.series_datos[n_m]["Ancho_mm"], es_crono=n_m.startswith("📚"))
        serie_b_glk = self._serie_para_glk(
            self.series_datos[n_t]["Ancho_mm"], es_crono=n_t.startswith("📚"))

        # Guardar para la tabla de detalle (año de término, alineamiento,
        # aplicar desfase). n_m es la primera serie marcada (la que se data).
        self._offset_nombre_a = n_m
        self._offset_serie_a_raw = serie_a_raw
        self._offset_serie_b_raw = serie_b_raw

        # Convención de desfase: el shift se aplica a la PRIMERA serie
        # marcada (m_diff, la que se está datando) para alinearla con la
        # SEGUNDA (t_diff, la referencia). Así un desfase positivo significa
        # "sumar estos años a la primera serie para posicionarla", igual que
        # en 'Series múltiples vs Crono'. Antes se desplazaba la segunda
        # serie, lo que daba desfases negativos para series flotantes y
        # resultaba confuso e inconsistente entre los dos análisis.
        s_min = int(t_diff.index.min() - m_diff.index.max() + OVERLAP_MINIMO_ANALISIS - 1)
        s_max = int(t_diff.index.max() - m_diff.index.min() - OVERLAP_MINIMO_ANALISIS + 1)

        self._shifts_actuales = []
        self._r_actuales = []
        self._glk_actuales = []
        self._tbp_actuales = []
        self._n_actuales = []

        for shift in range(s_min, s_max + 1):
            # m_diff desplazada (+shift) se alinea con t_diff
            overlap = (m_diff.index + shift).intersection(t_diff.index)
            # Solape mínimo alto: ver OVERLAP_MINIMO_FLOTANTE. Sin esto las
            # posiciones de los extremos, con diez o veinte años de solape,
            # ganan por azar y tapan el desfase verdadero.
            if len(overlap) < min(OVERLAP_MINIMO_FLOTANTE,
                                  max(len(m_diff), len(t_diff))):
                continue
            r = _r_pearson(m_diff.loc[overlap - shift].values,
                           t_diff.loc[overlap].values)
            if np.isnan(r):
                continue

            # GLK y t-BP sobre la serie para GLK (transformada COFECHA si
            # está activo, cruda si no): se desplaza la PRIMERA serie (a)
            a_glk_shift = serie_a_glk.copy()
            a_glk_shift.index = a_glk_shift.index + shift
            overlap_glk = a_glk_shift.index.intersection(serie_b_glk.index)
            n_ov = len(overlap_glk)
            if n_ov >= OVERLAP_MINIMO_ANALISIS:
                a_o = a_glk_shift.loc[overlap_glk]
                b_o = serie_b_glk.loc[overlap_glk]
                glk, _ = gleichlaufigkeit(a_o, b_o, min_overlap=OVERLAP_MINIMO_ANALISIS)
                t_bp, _, _ = t_baillie_pilcher(a_o, b_o, min_overlap=OVERLAP_MINIMO_ANALISIS)
            else:
                glk = float("nan")
                t_bp = float("nan")

            self._shifts_actuales.append(shift)
            self._r_actuales.append(r)
            self._glk_actuales.append(glk)
            self._tbp_actuales.append(t_bp)
            self._n_actuales.append(n_ov)

        if not self._shifts_actuales:
            return self.grafico_offset.setTitle("Sin coincidencias suficientes.")

        self._redibujar_offset()
        self.btn_ver_tabla_off.setEnabled(True)

    def _redibujar_offset(self):
        """Redibuja las barras de offset con la métrica seleccionada en el combo."""
        if not self._shifts_actuales:
            return

        metrica_txt = self.combo_metrica_offset.currentText()

        if metrica_txt.startswith("🎯"):
            vals = [score_compuesto(r, g, t)
                    for r, g, t in zip(self._r_actuales, self._glk_actuales, self._tbp_actuales)]
            metric_name = "Puntaje compuesto"
            color_func = _color_compuesto
            umbrales_html = (
                "<b>Puntaje compuesto</b> = ∛(r × GLK_norm × t-BP_norm) preserva signo: "
                "<span style='color:#dc3545;'>&lt;-0.20 anti-correlación</span> · "
                "<span style='color:#fd7e14;'>-0.20–+0.20 ambiguo</span> · "
                "<span style='color:#ffc107;'>+0.20–+0.40 débil</span> · "
                "<span style='color:#5cb85c;'>+0.40–+0.60 bueno</span> · "
                "<span style='color:#28a745;'>&gt;+0.60 confiable</span>"
            )
            y_range = (-1.05, 1.05)
        elif metrica_txt.startswith("t-BP"):
            vals = list(self._tbp_actuales)
            metric_name = "t-BP"
            color_func = _color_tbp
            umbrales_html = (
                "<b>Umbrales t-BP</b> (Baillie & Pilcher 1973): "
                "<span style='color:#dc3545;'>&lt;3 dudoso</span> · "
                "<span style='color:#fd7e14;'>3–4 débil</span> · "
                "<span style='color:#ffc107;'>4–6 aceptable</span> · "
                "<span style='color:#5cb85c;'>&gt;6 confiable</span>"
            )
            vals_validos = [v for v in vals if np.isfinite(v)]
            y_max = (max(vals_validos) * 1.15) if vals_validos else 10.0
            y_range = (-1.0, max(8.0, y_max))
        elif metrica_txt.startswith("GLK"):
            vals = list(self._glk_actuales)
            metric_name = "GLK"
            color_func = _color_glk
            umbrales_html = (
                "<b>Umbrales GLK</b> (Eckstein 1969): "
                "<span style='color:#dc3545;'>&lt;0.60 azar</span> · "
                "<span style='color:#fd7e14;'>0.60–0.65 débil</span> · "
                "<span style='color:#ffc107;'>0.65–0.70 aceptable</span> · "
                "<span style='color:#5cb85c;'>&gt;0.70 confiable</span>"
            )
            y_range = (0.30, 1.0)
        else:
            vals = list(self._r_actuales)
            metric_name = "r"
            color_func = _color_r
            umbrales_html = (
                "<b>Umbrales r</b> (Pearson, post-AR): "
                "<span style='color:#dc3545;'>&lt;0.20 azar</span> · "
                "<span style='color:#fd7e14;'>0.20–0.35 débil</span> · "
                "<span style='color:#ffc107;'>0.35–0.50 aceptable</span> · "
                "<span style='color:#5cb85c;'>&gt;0.50 confiable</span>"
            )
            y_range = (-1.05, 1.05)

        self.grafico_offset.clear()
        self.grafico_offset.addItem(self._texto_hover)
        self._texto_hover.hide()

        self.grafico_offset.addItem(pg.InfiniteLine(
            pos=0, angle=0, pen=pg.mkPen("#aaaaaa", width=1)))

        for shift, val in zip(self._shifts_actuales, vals):
            if not np.isfinite(val):
                continue
            self.grafico_offset.addItem(pg.BarGraphItem(
                x=[shift], height=[val], width=1.0,
                brush=color_func(val), pen=pg.mkPen(None)
            ))

        vals_para_max = [v if np.isfinite(v) else -np.inf for v in vals]
        if max(vals_para_max) > -np.inf:
            idx_max = int(np.argmax(vals_para_max))
            best_shift = self._shifts_actuales[idx_max]
            best_val = vals[idx_max]
            self.grafico_offset.addItem(pg.BarGraphItem(
                x=[best_shift], height=[best_val], width=1.0,
                brush=color_func(best_val),
                pen=pg.mkPen("white", width=2)
            ))

            def _f(v, dec=2):
                return "—" if not np.isfinite(v) else f"{v:.{dec}f}"

            self.grafico_offset.setTitle(
                f"Análisis de desfase — métrica: <b>{metric_name}</b>  "
                f"|  mejor: shift {best_shift:+d}, {metric_name}={_f(best_val)}"
            )
        else:
            self.grafico_offset.setTitle(f"Análisis de desfase — métrica: <b>{metric_name}</b>")

        self.grafico_offset.setYRange(*y_range)
        self.grafico_offset.setXRange(
            min(self._shifts_actuales) - 2, max(self._shifts_actuales) + 2)

        self.lbl_stats.setText(
            f"<div style='font-size:11px; line-height:1.5;'>"
            f"{umbrales_html}<br>"
            f"<span style='color:{color_secundario()};'>"
            f"💡 Pasá el mouse sobre las barras para ver r/GLK/t-BP/n de cada shift. "
            f"La fecha verdadera es donde las TRES métricas son altas simultáneamente — "
            f"si solo una es alta, suele ser coincidencia.</span>"
            f"</div>"
        )
        self.lbl_stats.setVisible(True)

    # ── Comparación múltiple directa contra cronología ────────────────────

    def aplicar_desfase_a_serie(self, nombre: str, shift: int,
                                 regraficar: bool = True) -> bool:
        """Re-data UNA serie sumando `shift` a su índice de años.

        Reutilizable desde la tabla de comparación múltiple y desde la
        ventana de detalle. Conserva los datos originales,
        invalida la caché de comparación y (opcionalmente) regrafica.

        Devuelve True si aplicó algún cambio.
        """
        self._descartar_prueba(silencioso=True)
        if not self.modelo_series.desplazar(nombre, shift):
            return False
        self._series_modificadas(regraficar=regraficar)
        return True

    def reemplazar_serie(self, nombre: str, df_nuevo: pd.DataFrame,
                          regraficar: bool = True):
        """Reemplaza por completo los datos de una serie (usado por el
        editor de anillos, que cambia anchos y/o cantidad de anillos).
        Invalida la caché de comparación y regrafica."""
        self._descartar_prueba(silencioso=True)
        self.modelo_series.actualizar(nombre, df_nuevo)
        self._series_modificadas(regraficar=regraficar)

    def _abrir_editor_anillos_marcada(self):
        """Abre el editor de anillos para la serie marcada (exactamente
        una). Accesible directamente desde el panel principal."""
        nombre = self._serie_para_accion("editar")
        if nombre is None:
            return
        self._descartar_prueba(silencioso=True)
        # No se editan anchos de una cronología
        if nombre.startswith("📚"):
            QMessageBox.information(
                self, "Selecciona una serie",
                "La selección es una cronología (📚) y no se editan sus "
                "anchos.\n\nSelecciona una serie de medición.")
            return
        df = self.series_datos.get(nombre)
        if df is None or df.empty:
            QMessageBox.warning(self, "Sin datos",
                                "La serie seleccionada no tiene datos.")
            return
        dlg = DialogoEditarAnillos(df, nombre, self, parent=self)
        dlg.exec()

    def comparar_series_marcadas_vs_crono(self):
        """Compara las series marcadas (1 o varias) contra la cronología
        activa. Lanzada desde el botón "Series múltiples vs Crono" del
        panel principal — el usuario no tiene que abrir la ventana de
        cronología para usar esta funcionalidad.

        Flujo:
          1. Si NO hay cronología cargada: avisa al usuario que primero
             cargue/genere una.
          2. Si hay 0 series marcadas: aviso.
          3. Si hay 1+ series marcadas: ejecuta el cálculo en lote y
             abre `DialogoComparacionMultiple` con los resultados.

        RANGO DE DESFASE DINÁMICO POR SERIE:
        En vez de usar un max_shift fijo, el rango se calcula por serie
        según los años que cubre. Esto permite que el mismo botón funcione
        con dos tipos de series:

          - Series FECHADAS (años calendar 1500-2020 por ejemplo): el
            rango natural es estrecho, solo hay overlap cerca de shift=0.
            El cálculo es rápido y detecta errores de datación pequeños
            (anillos faltantes/extra).

          - Series FLOTANTES (años arbitrarios 0-200 por ejemplo): el
            rango natural cubre TODA la cronología. Encuentra la posición
            donde encaja la serie. Más lento pero necesario — antes el
            límite fijo de 10 hacía que estas series mostraran todo en 0
            porque jamás se solapaban con la cronología.

        Fórmula:
          shift_min = c_min - s_max + min_overlap - 1
          shift_max = c_max - s_min - min_overlap + 1
        donde c_* son años de la cronología y s_* son años de la serie.
        Cualquier shift en ese rango garantiza al menos `min_overlap`
        años de solape.
        """
        # Validación 1: cronología activa
        if self.cronologia_activa is None or self.cronologia_activa.empty:
            QMessageBox.warning(
                self, "Sin cronología activa",
                "Primero carga una cronología desde el botón <b>📚 Crono</b>\n"
                "o genérala desde <b>🧭 Generar Cronología</b>.\n\n"
                "Una vez disponible podrás comparar series contra ella desde acá."
            )
            return

        # Validación 2: series marcadas
        nombres = self._series_marcadas()
        if len(nombres) < 1:
            QMessageBox.warning(
                self, "Sin series marcadas",
                "Marca al menos una serie con check en la lista\n"
                "para compararla contra la cronología."
            )
            return

        # ── Caché de resultados ───────────────────────────────────────
        # Construir una clave que represente el estado actual de la
        # comparación: series marcadas + cronología + un resumen de los
        # datos de cada una (largo, primer y último año, suma redondeada).
        # Si nada cambió desde el último cálculo, reusamos los resultados
        # guardados en vez de recalcular (que puede ser lento con series
        # flotantes y rangos de desfase amplios).
        clave_actual = self._clave_cache_comparacion(nombres)
        cache = getattr(self, "_cache_comparacion", None)
        if (cache is not None and cache.get("clave") == clave_actual
                and cache.get("resultados")):
            dlg = DialogoComparacionMultiple(
                cache["resultados"], cache["nombre_crono"], parent=self)
            dlg.exec()
            return

        # Excluir la propia cronología de la comparación si está marcada.
        # No tiene sentido comparar la cronología consigo misma — daría
        # siempre un puntaje perfecto en shift=0 y confunde el resumen.
        nombre_crono_completo = None
        for nombre in nombres:
            n_limpio = nombre.replace("📚 ", "").strip()
            if n_limpio == self._nombre_cronologia_activa:
                nombre_crono_completo = nombre
                break
        if nombre_crono_completo:
            nombres = [n for n in nombres if n != nombre_crono_completo]
            if not nombres:
                QMessageBox.warning(
                    self, "Sin series comparables",
                    "Solo marcaste la propia cronología activa. Marca otras\n"
                    "series para compararlas contra ella."
                )
                return

        MIN_OVERLAP = 20
        # Desfase máximo a explorar para series que YA están fechadas (se
        # solapan con la cronología). Suficiente para detectar errores de
        # datación reales sin barrer cientos de años innecesariamente.
        VENTANA_DESFASE_FECHADA = 50

        # Preparar la serie de la cronología (lado derecho de la comparación)
        meta = self.meta_cronologia or {}
        col_val = meta.get("columna_valor")
        if not col_val or col_val not in self.cronologia_activa.columns:
            col_val = self.cronologia_activa.columns[0]
        # CRUDA (para rangos de años, GLK/t-BP, y series guardadas)
        s_b_raw = pd.to_numeric(
            self.cronologia_activa[col_val], errors="coerce"
        ).dropna()
        if s_b_raw.empty:
            QMessageBox.warning(
                self, "Cronología sin datos válidos",
                "La cronología activa no contiene valores numéricos válidos."
            )
            return
        # ALTA FRECUENCIA para r (misma transformación que el cofechado real,
        # respetando el modo COFECHA si está activo). Evita las correlaciones
        # espurias de los anchos crudos (tendencias de edad compartidas).
        s_b_corr = self._transformar_para_correlacion(
            self.cronologia_activa[col_val], es_crono=True)
        # Serie para GLK/t-BP respetando COFECHA (transformada si COFECHA
        # activo; cruda si no).
        s_b_glk = self._serie_para_glk(
            self.cronologia_activa[col_val], es_crono=True)
        c_min_year = int(s_b_raw.index.min())
        c_max_year = int(s_b_raw.index.max())

        # Cursor de espera durante el cálculo
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        resultados = []
        nombre_crono = self._nombre_cronologia_activa or "cronología"

        try:
            for nombre in nombres:
                df_serie = self.series_datos.get(nombre)
                if df_serie is None or df_serie.empty:
                    continue

                # CRUDA (rangos de años, GLK/t-BP, gráficos, alineamiento)
                s_a_raw = pd.to_numeric(
                    df_serie["Ancho_mm"], errors="coerce").dropna()
                if s_a_raw.empty:
                    continue
                # ALTA FRECUENCIA para r
                es_crono_serie = nombre.startswith("📚")
                s_a_corr = self._transformar_para_correlacion(
                    df_serie["Ancho_mm"], es_crono_serie)
                if s_a_corr.empty:
                    continue
                # Serie para GLK/t-BP respetando COFECHA
                s_a_glk = self._serie_para_glk(
                    df_serie["Ancho_mm"], es_crono_serie)

                s_min_year = int(s_a_raw.index.min())
                s_max_year = int(s_a_raw.index.max())

                # Rango de desfase que garantiza al menos MIN_OVERLAP años
                # de solape con la cronología.
                shift_min = c_min_year - s_max_year + MIN_OVERLAP - 1
                shift_max = c_max_year - s_min_year - MIN_OVERLAP + 1

                if shift_min > shift_max:
                    resultados.append(self._resultado_sin_overlap(nombre))
                    continue
                max_shift_dinamico = max(abs(shift_min), abs(shift_max))

                # ACELERACIÓN: si la serie YA se solapa con la cronología en su
                # posición actual (serie fechada en años calendario), basta con
                # explorar desfases PEQUEÑOS para detectar errores de datación.
                # El barrido completo (±cientos de años) solo hace falta para
                # series FLOTANTES sin fecha. Con muchas series fechadas, esto
                # reduce el tiempo de más de un minuto a unos pocos segundos.
                overlap_en_0 = len(s_a_raw.index.intersection(s_b_raw.index))
                if overlap_en_0 >= MIN_OVERLAP:
                    max_shift_dinamico = min(max_shift_dinamico, VENTANA_DESFASE_FECHADA)
                else:
                    max_shift_dinamico = min(max_shift_dinamico, 5000)

                # r sobre alta frecuencia (s_*_corr); GLK/t-BP sobre
                # s_*_glk (transformada COFECHA si activo, cruda si no).
                shifts, rs, glks, tbps, ns = _estadisticos_por_desfase(
                    s_a_corr, s_b_corr, max_shift_dinamico, MIN_OVERLAP,
                    serie_a_raw=s_a_glk, serie_b_raw=s_b_glk,
                )

                if not shifts:
                    resultados.append(self._resultado_sin_overlap(nombre))
                    continue

                # Puntaje compuesto por desfase y elección del mejor
                scores = [score_compuesto(r, g, t)
                          for r, g, t in zip(rs, glks, tbps)]
                scores_validos = [
                    (i, s) for i, s in enumerate(scores) if np.isfinite(s)]
                if scores_validos:
                    idx_mejor = max(scores_validos, key=lambda x: x[1])[0]
                else:
                    idx_mejor = int(np.argmax(rs))

                # Puntaje en desfase=0 para calcular Δ
                if 0 in shifts:
                    score_shift0 = scores[shifts.index(0)]
                else:
                    score_shift0 = float("nan")

                resultados.append({
                    "nombre_serie": nombre,
                    "shifts": shifts, "rs": rs, "glks": glks,
                    "tbps": tbps, "ns": ns,
                    "mejor_shift": shifts[idx_mejor],
                    "mejor_score": scores[idx_mejor],
                    "mejor_r": rs[idx_mejor],
                    "mejor_glk": glks[idx_mejor],
                    "mejor_tbp": tbps[idx_mejor],
                    "mejor_n": ns[idx_mejor],
                    "score_shift0": score_shift0,
                    # Series CRUDAS para los gráficos de detalle y el
                    # alineamiento (que diferencia internamente).
                    "serie_a": s_a_raw,
                    "serie_b": s_b_raw,
                })

                QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()

        if not resultados:
            QMessageBox.warning(
                self, "Sin resultados",
                "No se pudo comparar ninguna de las series marcadas.\n"
                "Verifica que las series tengan datos válidos."
            )
            return

        # Guardar en caché para no recalcular si se reabre con las mismas
        # series sin cambios.
        self._cache_comparacion = {
            "clave": clave_actual,
            "resultados": resultados,
            "nombre_crono": nombre_crono,
        }

        dlg = DialogoComparacionMultiple(resultados, nombre_crono, parent=self)
        dlg.exec()

    def _clave_cache_comparacion(self, nombres: list[str]) -> tuple:
        """Identifica datos, años, columnas y metadatos de la comparación."""
        def _firma(df):
            if df is None:
                return None
            h = hashlib.blake2b(digest_size=32)
            h.update(repr((tuple(df.columns), tuple(map(str, df.dtypes)),
                           str(df.index.dtype))).encode("utf-8"))
            h.update(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
            return h.digest()

        modelo = getattr(self, "modelo_series", None)
        if modelo is None:
            # Compatibilidad con consumidores sin modelo.
            partes = [(n, _firma(self.series_datos.get(n))) for n in sorted(nombres)]
        else:
            partes = [("__series__", modelo.revision, tuple(sorted(nombres)))]
        partes.append((self._nombre_cronologia_activa,
                       _firma(self.cronologia_activa),
                       repr(self.meta_cronologia or {})))

        # Incluir el estado del modo COFECHA: afecta directamente las
        # correlaciones (transformación de las series). Sin esto, al
        # activar/desactivar COFECHA la clave no cambiaba y se devolvía el
        # resultado cacheado anterior — parecía que COFECHA "no hacía nada".
        try:
            cof = (
                bool(self.btn_modo_cofecha.isChecked()),
                bool(self.chk_cof_serie.isChecked()),
                bool(self.chk_cof_crono.isChecked()),
                tuple(sorted((self._modo_cofecha_params or {}).items())),
            )
        except Exception:
            cof = ()
        partes.append(("__cofecha__",) + cof)
        return tuple(partes)

    def _resultado_sin_overlap(self, nombre: str) -> dict:
        """Devuelve un dict de resultado en blanco para series que no
        pueden compararse (sin solape suficiente con la cronología incluso
        con el desfase máximo). Aparecen en la tabla con valores en 0/—
        para que el usuario sepa cuáles quedaron fuera."""
        return {
            "nombre_serie": nombre,
            "shifts": [], "rs": [], "glks": [],
            "tbps": [], "ns": [],
            "mejor_shift": 0,
            "mejor_score": float("nan"),
            "mejor_r": float("nan"),
            "mejor_glk": float("nan"),
            "mejor_tbp": float("nan"),
            "mejor_n": 0,
            "score_shift0": float("nan"),
        }

    def mostrar_tabla_offset(self):
        """Abre el diálogo con la tabla completa de offsets."""
        if not self._shifts_actuales:
            return
        dialogo = VentanaTablaOffset(
            self._shifts_actuales, self._r_actuales,
            self._glk_actuales, self._tbp_actuales, self._n_actuales,
            serie_a=getattr(self, "_offset_serie_a_raw", None),
            serie_b=getattr(self, "_offset_serie_b_raw", None),
            parent=self,
            nombre_serie=getattr(self, "_offset_nombre_a", None),
            panel_ref=self,
        )
        dialogo.exec()

    # -------------------------------------------------------------------------
    # COFECHADO: CORRELACIÓN MÓVIL
    # -------------------------------------------------------------------------

    def verificar_datacion(self):
        """Dibuja curva de correlación móvil y stats por ventana."""
        marcadas = self._series_marcadas()
        if len(marcadas) != 2:
            return QMessageBox.warning(self, "Atención", "Marque EXACTAMENTE dos series.")

        # Limpiar modo offset
        self._shifts_actuales = []
        self._r_actuales = []
        self._glk_actuales = []
        self._tbp_actuales = []
        self._n_actuales = []

        _ref, _prob = self._ordenar_ref_problema(marcadas[0], marcadas[1])
        m_diff, t_diff, n_m, n_t = self._preparar_diferencias_log(_ref, _prob)
        overlap = list(m_diff.index.intersection(t_diff.index))
        if len(overlap) < OVERLAP_MINIMO_ANALISIS:
            return QMessageBox.warning(self, "Error", "Las series no se solapan lo suficiente.")

        mitad = self.spin_ventana.value() // 2

        # Series para GLK/t-BP respetando el modo COFECHA (transformadas si
        # está activo; crudas si no), igual que el resto de los análisis.
        serie_a_raw = self._serie_para_glk(
            self.series_datos[n_m]["Ancho_mm"], es_crono=n_m.startswith("📚"))
        serie_b_raw = self._serie_para_glk(
            self.series_datos[n_t]["Ancho_mm"], es_crono=n_t.startswith("📚"))

        years, rs, glks, tbps, ns = _stats_movil(
            m_diff, t_diff, overlap, mitad, serie_a_raw, serie_b_raw)

        self._stats_movil_years = years
        self._stats_movil_r = rs
        self._stats_movil_glk = glks
        self._stats_movil_tbp = tbps
        self._stats_movil_n = ns
        self._mitad_ventana_actual = mitad

        r_global = _r_pearson(m_diff.loc[overlap].values, t_diff.loc[overlap].values)
        self._stats_actuales = estadisticos_cofechado(serie_a_raw, serie_b_raw)
        self._nombre_referencia = n_m
        self._nombre_problema = n_t

        self._dibujar_curva_cofechado(years, rs, overlap, r_global, n_t, [], False)

    def buscar_errores(self):
        """Busca anillos faltantes/sobrantes + calcula stats móviles."""
        self._descartar_prueba(silencioso=True)
        marcadas = self._series_marcadas()
        if len(marcadas) != 2:
            return QMessageBox.warning(self, "Atención", "Marque EXACTAMENTE dos series.")

        # Limpiar modo offset
        self._shifts_actuales = []
        self._r_actuales = []
        self._glk_actuales = []
        self._tbp_actuales = []
        self._n_actuales = []

        n1, n2 = marcadas[0], marcadas[1]
        # La CRONOLOGÍA es siempre la referencia: es el patrón contra el que se
        # data, y nunca se le insertan ni quitan anillos. Antes se elegía como
        # referencia la serie más LARGA, así que si la serie a datar era más
        # larga que la cronología (caso habitual con una cronología corta),
        # los papeles se invertían y las correcciones se probaban sobre la
        # cronología. El resultado eran sugerencias con el signo cambiado.
        self._nombre_referencia, self._nombre_problema = \
            self._ordenar_ref_problema(n1, n2)

        df_ref = self.series_datos[self._nombre_referencia]
        df_prob = self.series_datos[self._nombre_problema]
        mitad = self.spin_ventana.value() // 2
        max_c = self.spin_max_corr.value()
        self._mitad_ventana_actual = mitad

        self.grafico_offset.setTitle("Buscando correcciones…")
        QApplication.processEvents()

        self._stats_actuales = estadisticos_cofechado(
            df_ref["Ancho_mm"], df_prob["Ancho_mm"])

        ref_es_crono = self._nombre_referencia.startswith("📚")
        prob_es_crono = self._nombre_problema.startswith("📚")

        def transformar_ref(serie_mm):
            return self._transformar_para_correlacion(serie_mm, ref_es_crono)

        def transformar_prob(serie_mm):
            return self._transformar_para_correlacion(serie_mm, prob_es_crono)

        # DIAGNÓSTICO PREVIO: antes de probar correcciones a ciegas, detectar
        # qué tramo de la serie ya calza con la referencia. Ese tramo es el
        # ancla y define qué extremo debe quedar fijo; además indica si el
        # problema es un error interno o un desfase de toda la serie.
        try:
            self._diagnostico_datacion = diagnosticar_datacion(
                transformar_prob(df_prob["Ancho_mm"]),
                transformar_ref(df_ref["Ancho_mm"]))
        except Exception:
            self._diagnostico_datacion = None

        anclaje_usar = self._anclaje_actual()
        diag = self._diagnostico_datacion
        if diag and diag.get("diagnostico") == "error_interno":
            # Para BUSCAR se ancla el tramo que ya está bien fechado (mover el
            # tramo correcto sería un error), pero NO se toca la selección del
            # usuario: el selector es suyo y cambiarlo solo resulta confuso.
            # Si el anclaje recomendado difiere del elegido, se avisa en el
            # texto del diagnóstico.
            anclaje_usar = diag.get("anclaje_sugerido", anclaje_usar)

        coleccion_std = self._coleccion_para_nulo(transformar_prob)

        self._sugerencias, es_marginal = _buscar_y_priorizar(
            df_ref, df_prob, mitad, max_c,
            diagnostico=self._diagnostico_datacion,
            anclaje=anclaje_usar,
            transformar_ref=transformar_ref,
            transformar_prob=transformar_prob,
            coleccion_std=coleccion_std,
            nombre_serie=self._nombre_problema,
        )
        self._sugerencias_es_marginal = es_marginal
        self._poblar_tabla(self._sugerencias, es_marginal=es_marginal)
        self._mostrar_informe_quiebre(
            self._sugerencias,
            serie=transformar_prob(df_prob["Ancho_mm"]).dropna(),
            referencia=transformar_ref(df_ref["Ancho_mm"]).dropna())

        d_ref = transformar_ref(df_ref["Ancho_mm"])
        d_prob = transformar_prob(df_prob["Ancho_mm"])
        overlap = list(d_ref.index.intersection(d_prob.index))

        serie_a_raw = pd.to_numeric(df_ref["Ancho_mm"], errors="coerce").dropna()
        serie_b_raw = pd.to_numeric(df_prob["Ancho_mm"], errors="coerce").dropna()

        years, rs, glks, tbps, ns = _stats_movil(
            d_ref, d_prob, overlap, mitad, serie_a_raw, serie_b_raw)

        self._stats_movil_years = years
        self._stats_movil_r = rs
        self._stats_movil_glk = glks
        self._stats_movil_tbp = tbps
        self._stats_movil_n = ns

        r_global = (_r_pearson(d_ref.loc[overlap].values, d_prob.loc[overlap].values)
                    if overlap else float("nan"))
        self._dibujar_curva_cofechado(
            years, rs, overlap, r_global, self._nombre_problema,
            self._sugerencias[:10], False)

    def _dibujar_curva_cofechado(self, years, r_vals, overlap, r_global,
                                  nombre_target, marcadores, es_preview):
        """Dibuja la curva base de cofechado."""
        if not es_preview:
            self.grafico_offset.clear()
            self._item_preview = None
            self.grafico_offset.setYRange(-1.05, 1.05)
            if overlap:
                self.grafico_offset.setXRange(min(overlap) - 5, max(overlap) + 5)

            self.grafico_offset.addItem(
                pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#555555", width=1))
            )
            self.grafico_offset.addItem(
                pg.InfiniteLine(pos=UMBRAL_ANCLA_DEFECTO, angle=0,
                                pen=pg.mkPen("#5cb85c", style=Qt.PenStyle.DashLine, width=1))
            )
            self.grafico_offset.addItem(self._texto_hover)
            self._texto_hover.hide()

            if years:
                self.grafico_offset.plot(
                    years, r_vals,
                    pen=pg.mkPen("#3388FF", width=2),
                    name="r móvil actual",
                )

            for m in marcadores:
                color_hex = "#FF4444" if m["delta"] > 0 else "#FFA500"
                y_pos = m.get("r_zona_antes", 0.0)
                if np.isnan(y_pos):
                    y_pos = 0.0
                self.grafico_offset.addItem(
                    pg.ScatterPlotItem(
                        x=[m["anio"]], y=[y_pos], size=14,
                        brush=pg.mkBrush(color_hex),
                        pen=pg.mkPen("#ffffff", width=1),
                    )
                )
                signo = "+" if m["delta"] > 0 else ""
                html = (
                    f"<div style='color:{color_hex}; font-weight:bold; "
                    f"background:rgba(0,0,0,0.8); padding:3px 6px; border-radius:4px;'>"
                    f"{int(m['anio'])}<br>"
                    f"{signo}{m['delta']} anillo(s)<br>"
                    f"Δr = +{m['delta_r']:.3f}</div>"
                )
                txt = pg.TextItem(html=html, anchor=(0.5, 1.2))
                txt.setPos(m["anio"], y_pos)
                self.grafico_offset.addItem(txt)

            n_sug = len(marcadores)
            estado = "Sin sugerencias" if n_sug == 0 else f"{n_sug} sugerencia(s)"
            modo_str = " [COFECHA]" if self.btn_modo_cofecha.isChecked() else ""
            self.grafico_offset.setTitle(
                f"Cofechado{modo_str} '{nombre_target}' | "
                f"r global: {self._fmt_r(r_global)} | {estado}"
            )

            stats = getattr(self, "_stats_actuales", None)
            if stats and np.isfinite(stats.get("r", float("nan"))):
                self.lbl_stats.setText(formato_stats_global_html(stats))
                self.lbl_stats.setVisible(True)
            else:
                self.lbl_stats.setVisible(False)
        else:
            if self._item_preview is not None:
                self.grafico_offset.removeItem(self._item_preview)
            if years:
                self._item_preview = self.grafico_offset.plot(
                    years, r_vals,
                    pen=pg.mkPen("#FFA500", width=2, style=Qt.PenStyle.DashLine),
                    name="r móvil tras corrección",
                )

    def _limpiar_preview(self):
        if self._item_preview is not None:
            try:
                self.grafico_offset.removeItem(self._item_preview)
            except Exception:
                pass
            self._item_preview = None

    def _dibujar_preview(self, sug: dict):
        if not self._nombre_referencia or not self._nombre_problema:
            return
        df_ref = self.series_datos.get(self._nombre_referencia)
        df_corr = sug.get("df_corregido")
        if df_ref is None or df_corr is None:
            return

        ref_es_crono = self._nombre_referencia.startswith("📚")
        prob_es_crono = self._nombre_problema.startswith("📚")

        d_ref = self._transformar_para_correlacion(df_ref["Ancho_mm"], ref_es_crono)
        d_corr = self._transformar_para_correlacion(df_corr["Ancho_mm"], prob_es_crono)

        overlap_corr = list(d_ref.index.intersection(d_corr.index))
        mitad = self.spin_ventana.value() // 2
        years_p, r_p = _r_movil(d_ref, d_corr, overlap_corr, mitad)
        self._dibujar_curva_cofechado(years_p, r_p, overlap_corr, 0, "", [], True)

    # -------------------------------------------------------------------------
    # TABLA DE SUGERENCIAS
    # -------------------------------------------------------------------------

    def _guardar_pref_fuente(self, *_):
        """Recuerda tipo y tamaño de letra entre sesiones."""
        try:
            from PyQt6.QtCore import QSettings
            a = QSettings("MoiCedrus", "DPI")
            a.setValue("informe/fuente",
                       self.combo_fuente_informe.currentData())
            a.setValue("informe/tamano", self.spin_fuente_informe.value())
        except Exception:
            pass

    def _restaurar_pref_fuente(self):
        try:
            from PyQt6.QtCore import QSettings
            a = QSettings("MoiCedrus", "DPI")
            fam = a.value("informe/fuente", "", type=str)
            tam = a.value("informe/tamano", 0, type=int)
            if fam:
                i = self.combo_fuente_informe.findData(fam)
                if i >= 0:
                    self.combo_fuente_informe.setCurrentIndex(i)
            if tam:
                self.spin_fuente_informe.setValue(tam)
        except Exception:
            pass
        self._aplicar_fuente_informe()

    def _aplicar_fuente_informe(self, *_):
        """Cambia tipo y tamaño de letra del informe."""
        if not hasattr(self, "txt_informe"):
            return
        fam = self.combo_fuente_informe.currentData()
        if fam == "__mono__":
            f = QFont("Consolas" if sys.platform.startswith("win")
                      else "Monospace")
            f.setStyleHint(QFont.StyleHint.TypeWriter)
        else:
            f = QFont(fam)
        f.setPointSize(self.spin_fuente_informe.value())
        self.txt_informe.setFont(f)

    def _coleccion_para_nulo(self, transformar) -> dict:
        """Series fechadas que sirven de nulo para el localizador de quiebres.

        El umbral de credibilidad se MIDE sobre series ya fechadas en vez de
        inventarlo, así que hace falta reunir todas las que haya a mano. Se
        buscan en tres lugares, y se acumulan:

        1. Las cargadas en este panel con «📂 Series».
        2. Las que se usaron para construir la cronología en su pestaña. Es el
           caso más común y el que antes se perdía: quien arma la cronología y
           después cofecha contra ella ya tiene decenas de series fechadas, y
           el panel no las veía.
        3. Las cargadas expresamente como referencia con «📊 Series de
           referencia», para cuando solo se dispone de una cronología ya hecha
           y una serie por cofechar.

        Se excluyen la serie que se evalúa y la referencia, y todo lo que
        parezca una cronología, porque una cronología promediada no es una
        serie individual y su ganancia no es comparable.
        """
        fuera = {self._nombre_problema, self._nombre_referencia}
        crudas: dict = {}

        def _sumar(origen):
            for n, df in (origen or {}).items():
                if n in fuera or n in crudas or str(n).startswith("📚"):
                    continue
                try:
                    col = df["Ancho_mm"] if isinstance(df, pd.DataFrame) else df
                    if len(col.dropna()) > 40:
                        crudas[n] = col
                except Exception:
                    continue

        _sumar(getattr(self, "series_datos", None))
        vc = getattr(self, "_ventana_cronologia", None)
        if vc is not None:
            _sumar(getattr(vc, "_series_cronologia", None))
        _sumar(getattr(self, "_series_nulo", None))

        out = {}
        for n, col in crudas.items():
            try:
                t = transformar(col).dropna()
                if len(t) > 30:
                    out[n] = t
            except Exception:
                continue
        return out

    def cargar_series_referencia(self):
        """Carga series solo para que sirvan de nulo, sin meterlas en la lista.

        Pensado para el caso de tener una cronología ya construida y una sola
        serie por cofechar: sin otras series fechadas, el localizador cae a un
        nulo sintético que deja pasar bastantes más falsos positivos.
        """
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Cargar series de referencia para el contraste",
            self._ultima_carpeta_nulo(),
            "Series (*.rwl *.txt *.RWL *.TXT);;Todos (*)")
        if not rutas:
            return
        if not hasattr(self, "_series_nulo"):
            self._series_nulo = {}
        n_antes = len(self._series_nulo)
        for r in rutas:
            try:
                d = leer_tucson_multi(r)
                for k, v in d.items():
                    self._series_nulo[k] = v
            except Exception:
                try:
                    df, ide = leer_archivo_tucson(r)
                    self._series_nulo[ide] = df
                except Exception:
                    continue
        try:
            from PyQt6.QtCore import QSettings
            QSettings("MoiCedrus", "DPI").setValue(
                "codatacion/carpeta_nulo", os.path.dirname(rutas[0]))
        except Exception:
            pass
        n = len(self._series_nulo)
        QMessageBox.information(
            self, "Series de referencia",
            f"Hay {n} serie(s) de referencia cargadas "
            f"({n - n_antes} nueva(s)).\n\n"
            "No aparecen en la lista ni se cofechan: solo se usan para medir "
            "cuánto gana la búsqueda en series que ya están fechadas, y así "
            "decidir si un quiebre propuesto es real.\n\n"
            "Con nueve o más, el contraste pasa a ser el bueno.")

    def _ultima_carpeta_nulo(self) -> str:
        try:
            from PyQt6.QtCore import QSettings
            r = QSettings("MoiCedrus", "DPI").value(
                "codatacion/carpeta_nulo", "", type=str)
            return r if r and os.path.isdir(r) else ""
        except Exception:
            return ""

    def _mostrar_informe_quiebre(self, sugerencias, serie=None,
                                  referencia=None):
        """Vuelca el informe en prosa y el perfil del quiebre a sus pestañas.

        El informe viaja dentro de las sugerencias de origen "zona", pero todo
        ese cálculo vive bajo un `try` amplio en el buscador: si algo falla ahí
        —una serie muy corta, un solape insuficiente— la excepción se traga y
        las pestañas quedaban en blanco sin explicar por qué. Por eso, si no
        llega informe en las sugerencias, se calcula acá directamente con la
        serie y la referencia ya transformadas.
        """
        if not hasattr(self, "txt_informe"):
            return
        base = next((x for x in (sugerencias or [])
                     if x.get("origen") == "zona" and x.get("texto")), None)

        if base is None and serie is not None and referencia is not None:
            try:
                inf = _qb.informe_quiebre(serie, referencia, max_desfase=10,
                                          n_nulo=0)
                if inf.get("texto") and inf.get("zona"):
                    base = {"texto": inf["texto"], "zona": inf["zona"],
                            "tramos": inf.get("tramos"),
                            "perfil": inf.get("perfil")}
            except Exception as e:
                self.txt_informe.setPlainText(
                    "No se pudo generar el informe de co-datación.\n\n"
                    f"Motivo: {e}\n\n"
                    "Suele ocurrir cuando la serie o el solape con la "
                    "referencia son demasiado cortos: hacen falta al menos 15 "
                    "años a cada lado del quiebre.")
                self.grafico_perfil.clear()
                return

        # ── Texto ────────────────────────────────────────────────────
        if base is None:
            self.txt_informe.setPlainText(
                "Todavía no hay informe.\n\n"
                "Se genera al buscar correcciones sobre una serie y una "
                "referencia con solape suficiente (al menos 15 años a cada "
                "lado del posible quiebre).")
            self.grafico_perfil.clear()
            return
        L = ["INFORME DE CO-DATACIÓN", "=" * 60, ""]
        L.append(base["texto"])
        L.append("")
        tramos = base.get("tramos") or []
        if tramos:
            L.append("TRAMOS")
            L.append(f"  {'años':<16}{'n':>5}{'r':>8}{'desfase':>9}   estado")
            for t in tramos:
                r = t.get("r")
                L.append(f"  {t['inicio']}-{t['fin']:<11}{t['n']:>5}"
                         f"{(f'{r:.3f}' if r == r else '   -'):>8}"
                         f"{t['desfase']:>9}   {t['estado']}")
            L.append("")
        z = base.get("zona")
        if z:
            L.append(f"ZONA COMPATIBLE:  {z[0]} a {z[1]}"
                     f"   ({z[1] - z[0] + 1} años)")
            L.append("  La zona reúne los años cuya correlación no se distingue")
            L.append("  de la del óptimo. Contiene el año verdadero casi siempre,")
            L.append("  pero es ancha: por eso abajo van ordenados por prioridad.")
            L.append("")
        cands = [x for x in (sugerencias or []) if x.get("origen") == "zona"]
        if cands:
            L.append("AÑOS A REVISAR, por orden de probabilidad")
            L.append("  El orden usa lo estrecho que es ese año en la cronología:")
            L.append("  un anillo ausente aparece donde el árbol casi no formó leño.")
            L.append("")
            L.append(f"  {'#':>2}  {'año':>6}  {'corrección':<14}{'r resultante':>13}")
            for k, x in enumerate(cands[:10], start=1):
                L.append(f"  {k:>2}  {int(x['anio']):>6}  {x['tipo']:<14}"
                         f"{x.get('r_verificada', float('nan')):>13.3f}")
        self.txt_informe.setPlainText("\n".join(L))

        # ── Perfil ───────────────────────────────────────────────────
        self.grafico_perfil.clear()
        perfil = base.get("perfil") or []
        if not perfil:
            return
        xs = [p[0] - 1 for p in perfil]   # año de la corrección, no del quiebre
        ys = [p[1] for p in perfil]
        self.grafico_perfil.plot(
            xs, ys, pen=pg.mkPen("#4aa3dc", width=2),
            name="r si el quiebre estuviera en ese año")
        leyenda = self.grafico_perfil.addLegend(offset=(10, 10))
        if z:
            reg = pg.LinearRegionItem(values=[z[0], z[1]], movable=False,
                                      brush=(74, 163, 220, 45))
            reg.setZValue(-10)
            self.grafico_perfil.addItem(reg)
            # pyqtgraph no pone las regiones ni las líneas verticales en la
            # leyenda, así que se agregan entradas falsas con el mismo trazo:
            # sin esto el usuario ve tres colores y ningún nombre.
            leyenda.addItem(
                pg.PlotDataItem(pen=None, symbol="s", symbolSize=10,
                                symbolBrush=(74, 163, 220, 120),
                                symbolPen=None),
                f"Zona compatible ({z[0]}–{z[1]})")
        pen_cand = pg.mkPen("#e0a030", width=1, style=Qt.PenStyle.DashLine)
        pen_mejor = pg.mkPen("#e04040", width=2)
        for x in cands[1:5]:
            self.grafico_perfil.addItem(
                pg.InfiniteLine(pos=int(x["anio"]), angle=90, pen=pen_cand))
        if len(cands) > 1:
            leyenda.addItem(pg.PlotDataItem(pen=pen_cand),
                            "Otros años a revisar")
        if cands:
            self.grafico_perfil.addItem(
                pg.InfiniteLine(pos=int(cands[0]["anio"]), angle=90,
                                pen=pen_mejor))
            leyenda.addItem(pg.PlotDataItem(pen=pen_mejor),
                            f"Año más probable ({int(cands[0]['anio'])})")

    def _poblar_tabla(self, sugerencias: list[dict], es_marginal: bool = False):
        """Rellena la tabla de sugerencias.

        es_marginal=True indica que las correcciones están por debajo del umbral
        de significancia (probable ruido). Se muestran como sanity-check con
        una advertencia visible.
        """
        self.tabla_sugerencias.setRowCount(0)
        self.btn_aplicar.setEnabled(False)

        # Mensaje de estado de la sección
        # Cabecera con el DIAGNÓSTICO: qué tramo está bien fechado y de qué
        # tipo es el problema. Va antes que la lista de correcciones porque
        # cambia cómo hay que leerla.
        diag = getattr(self, "_diagnostico_datacion", None)
        cabecera = ""
        if diag:
            tipo = diag.get("diagnostico")
            msg = diag.get("mensaje", "")
            if tipo == "bien_fechada":
                cabecera = ("<span style='color:#5cb85c;'>✓ <b>Serie bien fechada</b>"
                            "</span><br><span style='font-size:9px;'>" + msg + "</span><br><br>")
            elif tipo == "desfase_global":
                cabecera = ("<span style='color:#d9534f;'>⚠️ <b>Desfase de toda la "
                            "serie</b></span><br><span style='font-size:9px;'>" + msg +
                            "<br><b>Revisa el año base antes de insertar o quitar "
                            "anillos.</b></span><br><br>")
            elif tipo == "error_interno":
                cabecera = ("<span style='color:#f0ad4e;'>🎯 <b>Error localizado</b>"
                            "</span><br><span style='font-size:9px;'>" + msg +
                            "</span><br><br>")
            elif tipo == "ambiguo":
                cabecera = (f"<span style='color:{color_secundario()};'><b>Diagnóstico no concluyente</b>"
                            "</span><br><span style='font-size:9px;'>" + msg +
                            "</span><br><br>")

        if hasattr(self, "lbl_estado_sug"):
            if not sugerencias:
                self.lbl_estado_sug.setText(
                    cabecera +
                    "<span style='color:#5cb85c;'>✓ <b>Sin correcciones sugeridas.</b></span><br>"
                    "<span style='font-size:9px;'>La serie parece estar correctamente cofechada "
                    "contra la referencia en esta ventana de análisis.</span>"
                )
                self.lbl_estado_sug.setVisible(True)
            elif es_marginal:
                self.lbl_estado_sug.setText(
                    cabecera +
                    "<span style='color:#f0ad4e;'>⚠️ <b>Sugerencias marginales</b></span> "
                    "<span style='font-size:9px;'>(Δr &lt; 0.05)</span><br>"
                    "<span style='font-size:9px;'>No hay correcciones significativas. "
                    "Estos cambios podrían ser ruido estadístico. Si la serie ya está "
                    "cofechada, probablemente no necesitas aplicar ninguno.</span>"
                )
                self.lbl_estado_sug.setVisible(True)
            else:
                n = len(sugerencias)
                self.lbl_estado_sug.setText(
                    cabecera +
                    f"<span style='color:#5cb85c;'>"
                    f"<b>{n} corrección(es) significativa(s)</b> encontrada(s).</span><br>"
                    "<span style='font-size:9px;'>Click en una fila para previsualizar "
                    "el cambio antes de aplicarlo.</span>"
                )
                self.lbl_estado_sug.setVisible(True)

        # Auto-expandir la sección si hay algo que mostrar
        if (sugerencias or es_marginal) and hasattr(self, "sec_sug"):
            self.sec_sug.expandir()

        font_bold = QFont()
        font_bold.setBold(True)

        for sug in sugerencias:
            row = self.tabla_sugerencias.rowCount()
            self.tabla_sugerencias.insertRow(row)

            delta_r = sug["delta_r"]
            if es_marginal:
                # Filas marginales: fondo gris-naranja muy tenue
                bg = QColor(240, 173, 78, 50)
            elif delta_r >= 0.10:
                bg = QColor(80, 180, 80, 120)
            elif delta_r >= 0.05:
                bg = QColor(180, 220, 80, 80)
            else:
                bg = QColor(220, 200, 80, 60)

            if sug.get("origen") in ("quiebre", "zona"):
                # Estas vienen de localizar el quiebre, no de probar
                # correcciones a ciegas: se distinguen para que el usuario
                # sepa de dónde sale el año.
                bg = (QColor(60, 160, 220, 130) if sug.get("confiable")
                      else QColor(60, 160, 220, 60))

            signo = "+" if sug["delta"] > 0 else ""
            marca = ""
            if sug.get("origen") == "quiebre":
                marca = " ◆" if sug.get("confiable") else " ◇"
            elif sug.get("origen") == "zona":
                marca = " ◇"
            valores = [
                str(int(sug["anio"])) + marca,
                f"{signo}{sug['delta']} anillo(s)",
                self._fmt_r(sug["r_antes"]),
                self._fmt_r(sug["r_tras"]),
                f"+{delta_r:.3f}",
            ]
            for col, val in enumerate(valores):
                celda = QTableWidgetItem(val)
                celda.setBackground(bg)
                celda.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 4:
                    celda.setFont(font_bold)
                self.tabla_sugerencias.setItem(row, col, celda)

    def _on_seleccion_sugerencia(self):
        fila = self.tabla_sugerencias.currentRow()
        # Cambiar de sugerencia descarta una prueba en curso (para no mezclar).
        if self.modelo_series.nombre_en_prueba is not None:
            self._descartar_prueba(silencioso=True)
        if fila < 0 or fila >= len(self._sugerencias):
            self.btn_probar.setEnabled(False)
            self.btn_aplicar.setEnabled(False)
            self._limpiar_preview()
            return
        self.btn_probar.setEnabled(True)
        # Aplicar directo también es posible sin probar, pero pedirá confirmación.
        self.btn_aplicar.setEnabled(True)
        self._dibujar_preview(self._sugerencias[fila])

    def _texto_cambio_sugerencia(self, sug, nombre):
        """Arma la descripción de QUÉ datos se modifican con una sugerencia."""
        anio = int(sug["anio"])
        delta = int(sug["delta"])
        df_act = self.series_datos.get(nombre)
        df_corr = sug.get("df_corregido")
        n0 = len(df_act) if df_act is not None else 0
        n1 = len(df_corr) if df_corr is not None else n0
        if delta > 0:
            accion = f"insertar {delta} anillo(s)"
        else:
            accion = f"eliminar {abs(delta)} anillo(s)"
        rango = ""
        if df_corr is not None and not df_corr.empty:
            rango = (f"<br>Rango resultante: <b>{int(df_corr.index.min())}–"
                     f"{int(df_corr.index.max())}</b>")
        return (
            f"Serie: <b>{nombre.replace('📚 ', '')}</b><br>"
            f"Acción: <b>{accion}</b> en el año <b>{anio}</b><br>"
            f"Anillos: <b>{n0} → {n1}</b>{rango}<br>"
            f"<span style='color:{color_secundario()};'>Los años ≤ {anio} no cambian "
            f"(médula fija).</span><br>"
            f"Correlación r: {self._fmt_r(sug['r_antes'])} → "
            f"{self._fmt_r(sug['r_tras'])} "
            f"(Δr +{sug['delta_r']:.3f})")

    def probar_correccion_seleccionada(self):
        """Aplica la corrección seleccionada de forma TEMPORAL (con respaldo)
        para ver cómo queda la serie corregida, sin tocar la serie real ni
        re-buscar (para no reiniciar la tabla)."""
        fila = self.tabla_sugerencias.currentRow()
        if fila < 0 or fila >= len(self._sugerencias):
            return
        sug = self._sugerencias[fila]
        nombre = self._nombre_problema
        df_corr = sug.get("df_corregido")
        if nombre not in self.series_datos or df_corr is None:
            QMessageBox.warning(self, "Sin serie",
                                "No se encontró la serie a corregir.")
            return
        try:
            self.modelo_series.probar_correccion(nombre, df_corr)
        except (ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "Corrección inválida", str(exc))
            return
        self._prueba_sug = dict(sug)
        self._series_modificadas(regraficar=False)

        self._marcar_prueba_ui(True)
        self.btn_aplicar.setEnabled(True)
        # Redibujar la serie corregida y su preview de correlación
        self.graficar_series()
        self._dibujar_preview(self._prueba_sug)
        self.lbl_prueba.setText(
            "● Probando corrección (sin aplicar)<br>"
            + self._texto_cambio_sugerencia(self._prueba_sug, nombre))
        self.lbl_prueba.setVisible(True)

    def _marcar_prueba_ui(self, activa: bool):
        self.btn_descartar_prueba.setEnabled(activa)
        self.btn_probar.setEnabled(not activa)
        if not activa:
            self.lbl_prueba.setVisible(False)
            self.lbl_prueba.setText("")

    def _descartar_prueba(self, silencioso: bool = False):
        """Recupera la serie anterior a la prueba, no la original importada."""
        if not self.modelo_series.descartar_correccion():
            return
        self._prueba_sug = None
        self._marcar_prueba_ui(False)
        self._series_modificadas()
        if not silencioso:
            try:
                self.buscar_errores()
            except Exception:
                pass

    def aplicar_correccion_seleccionada(self):
        """Aplica la corrección a la serie REAL, tras confirmar exactamente
        qué datos se modifican. Ofrece hacerlo conservando el ancho (editor)
        o de forma automática (ancho promedio)."""
        # Determinar la sugerencia a aplicar: la que se está probando, o la
        # seleccionada en la tabla.
        if self.modelo_series.nombre_en_prueba is not None:
            sug = self._prueba_sug
            nombre = self.modelo_series.nombre_en_prueba
        else:
            fila = self.tabla_sugerencias.currentRow()
            if fila < 0 or fila >= len(self._sugerencias):
                return
            sug = self._sugerencias[fila]
            nombre = self._nombre_problema
        if nombre not in self.series_datos:
            QMessageBox.warning(self, "Sin serie",
                                "No se encontró la serie a corregir.")
            return

        # Confirmación: mostrar QUÉ datos se modifican y CÓMO aplicarlos.
        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Icon.Question)
        caja.setWindowTitle("Confirmar corrección")
        caja.setTextFormat(Qt.TextFormat.RichText)
        caja.setText(
            "¿Aplicar esta corrección a la serie real?<br><br>"
            + self._texto_cambio_sugerencia(sug, nombre))
        btn_ancho = caja.addButton("Conservando ancho (editor)",
                                   QMessageBox.ButtonRole.AcceptRole)
        btn_auto = caja.addButton("Automático (ancho promedio)",
                                  QMessageBox.ButtonRole.AcceptRole)
        caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        # QMessageBox reparte el ancho según el TEXTO, no según los botones, así
        # que con botones de etiqueta larga estos salían cortados y no se podía
        # leer qué hacía cada uno. Se fuerza un ancho mínimo suficiente.
        _ensanchar_dialogo(caja, minimo=560)
        caja.exec()
        elegido = caja.clickedButton()
        if elegido not in (btn_ancho, btn_auto):
            return  # cancelado

        if elegido is btn_ancho:
            # El editor debe recibir la serie anterior a la prueba.
            self._descartar_prueba(silencioso=True)
            df = self.series_datos[nombre]
            dlg = DialogoEditarAnillos(df, nombre, self, parent=self,
                                       sugerencia=sug)
            dlg.exec()
        else:
            try:
                if self.modelo_series.nombre_en_prueba is not None:
                    self.modelo_series.confirmar_correccion()
                else:
                    df_corr = sug.get("df_corregido")
                    if df_corr is None:
                        raise ValueError("La sugerencia no contiene datos corregidos")
                    self.modelo_series.actualizar(nombre, df_corr)
            except (ValueError, TypeError, KeyError) as exc:
                QMessageBox.warning(self, "Corrección inválida", str(exc))
                return
            self._prueba_sug = None
            self._series_modificadas(regraficar=False)
            self._marcar_prueba_ui(False)

        # Refrescar tras aplicar
        self.spin_edit_year.setValue(int(sug["anio"]))
        for i in range(self.lista_series.count()):
            item = self.lista_series.item(i)
            if item.text() == nombre:
                self.lista_series.setCurrentItem(item)
                break
        self._limpiar_preview()
        self._sugerencias.clear()
        self.tabla_sugerencias.setRowCount(0)
        self.btn_aplicar.setEnabled(False)
        self.btn_probar.setEnabled(False)
        self.graficar_series()
        self.buscar_errores()

    # -------------------------------------------------------------------------
    # HOVER EN GRÁFICO
    # -------------------------------------------------------------------------

    def _on_mouse_movido(self, evt):
        """Hover sobre el gráfico de cofechado/offset."""
        if not self.grafico_offset.sceneBoundingRect().contains(evt):
            self._texto_hover.hide()
            self._restaurar_stats_globales()
            return

        punto = self.grafico_offset.plotItem.vb.mapSceneToView(evt)
        x_val = punto.x()

        # Modo curva de cofechado
        if self._stats_movil_years:
            years_arr = np.array(self._stats_movil_years)
            idx = int(np.argmin(np.abs(years_arr - x_val)))
            if abs(years_arr[idx] - x_val) > 5:
                self._restaurar_stats_globales()
                self._texto_hover.hide()
                return

            mitad = self._mitad_ventana_actual
            self.lbl_stats.setText(formato_stats_hover_html(
                int(self._stats_movil_years[idx]), mitad,
                self._stats_movil_r[idx],
                self._stats_movil_glk[idx],
                self._stats_movil_tbp[idx],
                self._stats_movil_n[idx],
            ))
            self.lbl_stats.setVisible(True)
            self._texto_hover.hide()
            return

        # Modo barras de offset
        if self._shifts_actuales:
            xi = int(round(x_val))
            if xi in self._shifts_actuales:
                idx = self._shifts_actuales.index(xi)
                r = self._r_actuales[idx]
                glk = self._glk_actuales[idx] if idx < len(self._glk_actuales) else float("nan")
                t_bp = self._tbp_actuales[idx] if idx < len(self._tbp_actuales) else float("nan")
                n = self._n_actuales[idx] if idx < len(self._n_actuales) else 0
                sc = score_compuesto(r, glk, t_bp)

                def _f(v, dec=2):
                    return "—" if not np.isfinite(v) else f"{v:.{dec}f}"

                html = (
                    f"<div style='background:rgba(40,40,40,230); padding:6px 10px; "
                    f"border-radius:4px; font-family:monospace; font-size:11px;'>"
                    f"<b style='color:#fff;'>Mover {xi:+d} años</b><br>"
                    f"<span style='color:#aaa;'>Puntaje:</span> "
                    f"<span style='color:{_color_compuesto(sc)}; font-weight:bold;'>{_f(sc, 2)}</span><br>"
                    f"<span style='color:#aaa;'>r:</span> "
                    f"<span style='color:{_color_r(r)}; font-weight:bold;'>{_f(r, 2)}</span><br>"
                    f"<span style='color:#aaa;'>GLK:</span> "
                    f"<span style='color:{_color_glk(glk)}; font-weight:bold;'>{_f(glk, 2)}</span><br>"
                    f"<span style='color:#aaa;'>t-BP:</span> "
                    f"<span style='color:{_color_tbp(t_bp)}; font-weight:bold;'>{_f(t_bp, 1)}</span><br>"
                    f"<span style='color:#aaa;'>n:</span> <span style='color:#ddd;'>{n}</span>"
                    f"</div>"
                )
                self._texto_hover.setHtml(html)
                self._texto_hover.setPos(punto.x(), punto.y())
                self._texto_hover.show()
            else:
                self._texto_hover.hide()
            return

        self._texto_hover.hide()

    def _restaurar_stats_globales(self):
        stats = getattr(self, "_stats_actuales", None)
        if stats and np.isfinite(stats.get("r", float("nan"))) and self._stats_movil_years:
            self.lbl_stats.setText(formato_stats_global_html(stats))
            self.lbl_stats.setVisible(True)

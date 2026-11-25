"""Compatibilidad con la API histórica de formatos."""
import os
import logging
import re
import numpy as np
import pandas as pd
import dpi.infraestructura.json_seguro as _js
from constantes import (TUCSON_VALOR_FIN, TUCSON_VALOR_FALTANTE,
                        TUCSON_MAX_CHARS_ID, TUCSON_DIVISOR, DPI_DEFECTO, MM_POR_PULGADA)
logger = logging.getLogger(__name__)
from dpi.formatos.planillas import _es_planilla, _leer_planilla, _escribir_excel, escribir_excel_merge, EXTS_PLANILLA
from dpi.formatos.pos import leer_pos, escribir_pos
from dpi.formatos.exportacion import exportar_serie_2col, asegurar_extension
from dpi.formatos.tucson import _registros_tucson, _precision_registros, detectar_precision_tucson, leer_tucson_multi, leer_archivo_tucson, _lineas_tucson, _guardar_lineas_tucson, escribir_tucson, exportar_tucson_ewlw, _escribir_tucson, _escribir_tucson_serie, escribir_tucson_merge, escribir_rwl_intensidad
from dpi.formatos.compacto import leer_formato_compacto
from dpi.formatos.deteccion import leer_dendro_auto, leer_series_auto
from dpi.formatos.wid import leer_wid
from dpi.formatos.tabular import leer_tabular, _indexar_columna_multi, _leer_crudo_tabular, leer_columna_multi, leer_columna_multi_hojas, exportar_tabular, escribir_tabla, leer_como_columnas_o_tabular
from dpi.formatos.cronologias import _ruta_metadatos_cronologia, _restaurar_claves_anio, _guardar_metadatos_cronologia, _cargar_metadatos_cronologia, _exportar_cronologia_df, _leer_cronologia_guardada, _CAMPOS_POR_ANIO

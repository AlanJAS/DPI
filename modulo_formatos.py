"""Lectura, escritura y metadatos dendrocronológicos, sin interfaz gráfica."""
import os
import logging
import re
import numpy as np
import pandas as pd
import json_seguro as _js
from constantes import (TUCSON_VALOR_FIN, TUCSON_VALOR_FALTANTE,
                        TUCSON_MAX_CHARS_ID, TUCSON_DIVISOR, DPI_DEFECTO, MM_POR_PULGADA)

logger = logging.getLogger(__name__)

from dpi.formatos.planillas import _es_planilla, _leer_planilla, _escribir_excel, escribir_excel_merge, EXTS_PLANILLA


from dpi.formatos.pos import leer_pos, escribir_pos









def asegurar_extension(ruta: str, filtro: str) -> str:
    """Garantiza que la ruta tenga una extensión coherente con el filtro
    elegido en el diálogo de guardado.

    El diálogo NO nativo de Qt no siempre agrega la extensión: si el usuario
    escribe solo el nombre, el archivo queda SIN extensión y los programas no
    lo reconocen (un .xlsx sin extensión se ve como un .zip). Esta función
    extrae las extensiones del filtro y agrega la primera si falta.
    """
    import re
    exts = re.findall(r"\*(\.[A-Za-z0-9]+)", filtro or "")
    if not exts:
        return ruta
    ruta_lower = ruta.lower()
    if any(ruta_lower.endswith(e.lower()) for e in exts):
        return ruta
    return ruta + exts[0]


from dpi.formatos.tucson import _registros_tucson, _precision_registros, detectar_precision_tucson, leer_tucson_multi, leer_archivo_tucson, _lineas_tucson, _guardar_lineas_tucson, escribir_tucson, exportar_tucson_ewlw, _escribir_tucson, _escribir_tucson_serie, escribir_tucson_merge, escribir_rwl_intensidad










from dpi.formatos.compacto import leer_formato_compacto


from dpi.formatos.deteccion import leer_dendro_auto, leer_series_auto


from dpi.formatos.wid import leer_wid


from dpi.formatos.tabular import leer_tabular, _indexar_columna_multi, _leer_crudo_tabular, leer_columna_multi, leer_columna_multi_hojas, exportar_tabular, escribir_tabla, leer_como_columnas_o_tabular










from dpi.formatos.cronologias import _ruta_metadatos_cronologia, _restaurar_claves_anio, _guardar_metadatos_cronologia, _cargar_metadatos_cronologia, _exportar_cronologia_df, _leer_cronologia_guardada, _CAMPOS_POR_ANIO


# Campos cuyo diccionario está indexado por AÑO. JSON obliga a que las claves
# sean texto, así que al releer hay que devolverlas a entero: los consumidores
# hacen `pd.Series(...)` y luego ordenan y comparan el índice como número.












def exportar_serie_2col(serie, ruta, codigo):
    """Exporta una serie de índices y devuelve el número de años escritos."""
    ext = os.path.splitext(ruta)[1].lower()
    s = pd.to_numeric(serie, errors="coerce").dropna()
    df = pd.DataFrame({"Anio": s.index.astype(int), "Valor": s.values})
    if ext == ".rwl":
        escribir_tucson(s, ruta, codigo=str(codigo))
    else:
        escribir_tabla(df, ruta)
    return len(df)

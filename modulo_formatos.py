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


def leer_dendro_auto(ruta: str):
    """Detecta formato y deriva al parser correcto.

    Acepta Tucson (.rwl/.txt), compacto, CooRecorder (.wid) y también
    formatos de COLUMNA (año + valor) en texto, CSV, Excel y ODS. Esto
    último es necesario porque las cronologías que genera DPI se exportan en
    dos columnas: sin esto no se podían volver a cargar como referencia.
    """
    ext = os.path.splitext(ruta)[1].lower()
    if ext == '.wid':
        return leer_wid(ruta)

    # Planillas: no son texto, van directo al lector tabular
    if _es_planilla(ext):
        return leer_tabular(ruta)

    with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
        primeras_lineas = f.read(500)

    if "=N" in primeras_lineas and "=I" in primeras_lineas:
        series = leer_formato_compacto(ruta)
        if len(series) != 1:
            raise ValueError("La referencia debe contener una sola serie.")
        sid, df = next(iter(series.items()))
        return df, sid

    if ext in ('.csv', '.tsv'):
        return leer_tabular(ruta)

    # .txt y .rwl pueden ser Tucson o dos columnas. Se decide mirando la
    # primera línea con datos: en Tucson el segundo campo es un año de cuatro
    # dígitos y vienen varios enteros después. Un archivo de dos columnas
    # (año + valor decimal) leído como Tucson devuelve valores absurdos, así
    # que conviene descartarlo antes de intentarlo.
    def _parece_tucson(texto: str) -> bool:
        for linea in texto.splitlines():
            campos = linea.split()
            if len(campos) < 3:
                continue
            try:
                anio = int(campos[1])
            except ValueError:
                return False  # encabezado tipo "Anio  Valor"
            if not (-12000 <= anio <= 3000):
                return False
            # En Tucson todos los valores son ENTEROS
            try:
                for v in campos[2:]:
                    int(v)
            except ValueError:
                return False
            return True
        return False

    if ext == ".rwl" or _parece_tucson(primeras_lineas):
        return leer_archivo_tucson(ruta)
    return leer_tabular(ruta)


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





















def leer_series_auto(ruta: str) -> dict:
    """Detecta archivos de series múltiples sin leer planillas como texto."""
    ext = os.path.splitext(ruta)[1].lower()
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    if _es_planilla(ext) or ext in (".csv", ".tsv"):
        return leer_como_columnas_o_tabular(ruta, nombre)
    if ext == ".wid":
        df, sid = leer_wid(ruta)
        return {f"🌲{sid}": df}
    with open(ruta, encoding="utf-8-sig", errors="replace") as archivo:
        primeras = archivo.read(500)
        archivo.seek(0)
        primera = next((ln for ln in archivo if ln.strip() and not ln.lstrip().startswith("#")), "")
    if "=N" in primeras and "=I" in primeras:
        return leer_formato_compacto(ruta)
    if ext in (".rwl", ".txt"):
        if "\t" not in primera:
            try:
                return leer_tucson_multi(ruta)
            except ValueError:
                if ext == ".rwl":
                    raise
        return leer_como_columnas_o_tabular(ruta, nombre)
    df, sid = leer_tabular(ruta)
    return {sid: df}

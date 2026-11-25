"""Operaciones extraídas sin modificar sus algoritmos."""
import os
from dpi.formatos.planillas import _es_planilla
from dpi.formatos.tucson import leer_tucson_multi, leer_archivo_tucson
from dpi.formatos.compacto import leer_formato_compacto
from dpi.formatos.wid import leer_wid
from dpi.formatos.tabular import leer_tabular, leer_como_columnas_o_tabular

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

"""Lectura, escritura y metadatos dendrocronológicos, sin interfaz gráfica."""
import os
import json
import logging
import numpy as np
import pandas as pd
import json_seguro as _js
from constantes import (TUCSON_VALOR_FIN, TUCSON_VALOR_FALTANTE,
                        TUCSON_MAX_CHARS_ID, TUCSON_DIVISOR)

logger = logging.getLogger(__name__)

EXTS_PLANILLA = (".xlsx", ".xls", ".ods")


def _es_planilla(ruta_o_ext: str) -> bool:
    """True si la ruta (o extensión) corresponde a una planilla Excel/ODS."""
    valor = (ruta_o_ext or "").lower()
    ext = valor if valor.startswith(".") else os.path.splitext(valor)[1].lower()
    return ext in EXTS_PLANILLA


def _leer_planilla(ruta: str, **kwargs):
    """Lee una planilla .xlsx/.xls/.ods con el motor adecuado.

    pandas elige el motor por extensión, pero solo si el módulo está
    instalado; si falta, el error ("Missing optional dependency 'odfpy'") no
    es accionable para el usuario. Acá damos un mensaje claro con la solución.
    """
    import importlib.util
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".ods" and importlib.util.find_spec("odf") is None:
        raise RuntimeError(
            "Para leer planillas de LibreOffice (.ods) falta el módulo "
            "'odfpy'.\n\nInstálalo con:  pip install odfpy\n\n"
            "Como alternativa, en LibreOffice usa «Archivo → Guardar como» y "
            "elige .xlsx o .csv.")
    if ext in (".xlsx", ".xls") and importlib.util.find_spec("openpyxl") is None:
        raise RuntimeError(
            "Para leer planillas de Excel (.xlsx) falta el módulo "
            "'openpyxl'.\n\nInstálalo con:  pip install openpyxl")
    return pd.read_excel(ruta, **kwargs)


def _escribir_excel(df, ruta: str, index: bool = False):
    """Escribe un DataFrame a .xlsx/.ods eligiendo un motor disponible.

    pandas necesita openpyxl o xlsxwriter para .xlsx, y odfpy para .ods. Si no
    especifica engine y ninguno está instalado, lanza "No engine for filetype".
    Aquí elegimos el primero disponible y, si falta, damos un mensaje accionable.
    """
    import importlib.util
    ext = os.path.splitext(ruta)[1].lower()

    if ext == ".ods":
        if importlib.util.find_spec("odf") is not None:
            df.to_excel(ruta, index=index, engine="odf")
            return
        raise RuntimeError(
            "Para exportar a LibreOffice (.ods) falta el módulo 'odfpy'.\n\n"
            "Instálalo con:  pip install odfpy\n\n"
            "Como alternativa, exporta en CSV o TXT, que no requieren módulos "
            "adicionales.")

    for engine in ("openpyxl", "xlsxwriter"):
        if importlib.util.find_spec(engine) is not None:
            df.to_excel(ruta, index=index, engine=engine)
            return
    raise RuntimeError(
        "Para exportar a Excel (.xlsx) falta el módulo 'openpyxl'.\n\n"
        "Instálalo con:  pip install openpyxl\n\n"
        "Como alternativa, exporta en CSV o TXT, que no requieren módulos "
        "adicionales.")


def _asegurar_extension(ruta: str, filtro: str) -> str:
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


def _registros_tucson(ruta):
    """Lee campos fijos una sola vez, conservando año y código."""
    registros = {}
    codigo = None
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            ln = linea.rstrip("\r\n")
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            try:
                anio = int(ln[8:12])
            except ValueError:
                continue
            codigo = ln[:8].strip() or codigo
            if not codigo:
                continue
            for i in range(10):
                token = ln[12 + 6*i:18 + 6*i].strip()
                if not token:
                    continue
                try:
                    valor = int(token)
                except ValueError:
                    logger.warning("Tucson: campo inválido %s, año %s", codigo, anio+i)
                    continue
                registros.setdefault(codigo, []).append((anio+i, valor))
    return registros


def _precision_registros(registros):
    return {sid: (100.0 if pares[-1][1] == 999 else
                  1000.0 if pares[-1][1] == TUCSON_VALOR_FIN else 1.0)
            for sid, pares in registros.items() if pares}


def detectar_precision_tucson(ruta: str) -> dict:
    return _precision_registros(_registros_tucson(ruta))


def leer_tucson_multi(ruta: str) -> dict[str, pd.DataFrame]:
    registros = _registros_tucson(ruta)
    precision = _precision_registros(registros)
    resultado = {}
    for sid, pares in registros.items():
        div = precision[sid]
        datos = []
        for anio, valor in pares:
            if valor == TUCSON_VALOR_FIN or (valor == 999 and div == 100.0):
                break
            if valor == TUCSON_VALOR_FALTANTE:
                continue
            datos.append((anio, valor / div))
        if not datos:
            continue
        df = pd.DataFrame(datos, columns=["Anio", "Ancho_mm"])
        if df["Anio"].duplicated().any():
            logger.warning("Tucson: años duplicados en %s; se promedian", sid)
        resultado[sid] = df.groupby("Anio").mean().sort_index()
    if not resultado:
        raise ValueError(f"No se encontraron series válidas en: {os.path.basename(ruta)}")
    return resultado


def leer_archivo_tucson(ruta: str) -> tuple[pd.DataFrame, str]:
    series = leer_tucson_multi(ruta)
    if len(series) != 1:
        raise ValueError("El archivo contiene varias series; utilice la importación múltiple.")
    sid, df = next(iter(series.items()))
    return df, sid


def leer_formato_compacto(ruta: str, divisor: float = 100.0) -> dict:
    """Lee formato compacto FORTRAN (20F4.0) de CATRAS/Heidelberg."""
    import re
    series_dict = {}
    with open(ruta, 'r', encoding='utf-8', errors='replace') as f:
        lineas = f.readlines()

    i = 0
    while i < len(lineas):
        linea = lineas[i].rstrip('\n\r')
        if not linea:
            i += 1
            continue

        if "=N" in linea and "=I" in linea:
            match_i = re.search(r'(\d+)=I', linea)
            anio_inicio = int(match_i.group(1)) if match_i else 0

            partes = linea.split('=I')
            if len(partes) > 1:
                subpartes = partes[1].strip().split()
                serie_id = subpartes[0] if subpartes else f"Serie_{len(series_dict)+1}"
            else:
                serie_id = f"Serie_{len(series_dict)+1}"

            i += 1
            valores = []
            while i < len(lineas) and "=N" not in lineas[i] and "=I" not in lineas[i]:
                linea_datos = lineas[i].rstrip('\n\r')
                for j in range(0, len(linea_datos), 4):
                    chunk = linea_datos[j:j+4]
                    if chunk.strip():
                        try:
                            valores.append(float(chunk.strip()) / divisor)
                        except ValueError:
                            pass
                i += 1

            if valores:
                anios = list(range(anio_inicio, anio_inicio + len(valores)))
                df = pd.DataFrame({"Anio": anios, "Ancho_mm": valores})
                df.set_index("Anio", inplace=True)
                series_dict[serie_id] = df
        else:
            i += 1

    return series_dict


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
        return leer_formato_compacto(ruta)

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


def leer_wid(ruta: str) -> tuple[pd.DataFrame, str]:
    """Lee CooRecorder .wid. Devuelve (DataFrame, nombre)."""
    anchos: list[float] = []
    anio_corteza: int | None = None
    nombre = os.path.splitext(os.path.basename(ruta))[0]

    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
        for linea in f:
            ln = linea.strip()
            if not ln:
                continue
            if ln.startswith("#C DATED"):
                try:
                    anio_corteza = int(ln.split()[2])
                except (IndexError, ValueError):
                    logger.warning("leer_wid: no se pudo parsear #C DATED en '%s'", ruta)
                continue
            if ln.startswith("#"):
                continue
            token = ln.replace(",", ".")
            try:
                anchos.append(float(token))
            except ValueError:
                logger.debug("leer_wid: token ignorado '%s'", ln)

    if not anchos:
        raise ValueError(f"No se encontraron datos de ancho en: {os.path.basename(ruta)}")

    n = len(anchos)
    if anio_corteza is None:
        import datetime
        anio_corteza = datetime.date.today().year
        logger.warning("leer_wid: '%s' sin #C DATED, usando año actual.", ruta)

    anio_medula = anio_corteza - n + 1
    anios = list(range(anio_medula, anio_corteza + 1))

    df = pd.DataFrame({"Ancho_mm": anchos}, index=pd.Index(anios, name="Anio"))
    df.sort_index(inplace=True)
    return df, nombre


def leer_tabular(ruta: str) -> tuple[pd.DataFrame, str]:
    """Lee CSV/TSV/TXT/Excel con detección automática de header, decimal, separador."""
    ext = os.path.splitext(ruta)[1].lower()

    def _leer_excel(con_header):
        return _leer_planilla(ruta, header=0 if con_header else None)

    def _leer_csv(con_header, decimal="."):
        try:
            return pd.read_csv(
                ruta, header=0 if con_header else None,
                sep=None, engine="python", decimal=decimal,
                encoding="utf-8", encoding_errors="replace",
            )
        except Exception:
            return pd.read_csv(
                ruta, header=0 if con_header else None,
                sep=r"[\s,;\t]+", engine="python", decimal=decimal,
                encoding="utf-8", encoding_errors="replace",
            )

    if _es_planilla(ext):
        df_sondeo = _leer_excel(con_header=False)
    else:
        df_sondeo = _leer_csv(con_header=False)

    if df_sondeo.empty or df_sondeo.shape[1] < 2:
        raise ValueError(f"El archivo debe tener al menos dos columnas: {os.path.basename(ruta)}")

    primera = df_sondeo.iloc[0]
    tiene_header = False
    for val in primera:
        s = str(val).strip().replace(",", ".")
        try:
            float(s)
        except (ValueError, TypeError):
            tiene_header = True
            break

    if _es_planilla(ext):
        df = _leer_excel(con_header=tiene_header)
    else:
        df = _leer_csv(con_header=tiene_header)

    if not tiene_header:
        df.columns = [f"col{i}" for i in range(df.shape[1])]

    if not _es_planilla(ext) and df.shape[1] >= 2:
        test_col = df.iloc[:, 1]
        if pd.to_numeric(test_col, errors="coerce").isna().all() and len(test_col):
            try:
                df = _leer_csv(con_header=tiene_header, decimal=",")
                if not tiene_header:
                    df.columns = [f"col{i}" for i in range(df.shape[1])]
            except Exception:
                pass

    cols = list(df.columns)

    nombres_anio = {"anio", "año", "year", "anios", "años", "yr"}
    year_col = None
    for c in cols:
        if str(c).strip().lower() in nombres_anio:
            year_col = c
            break

    if year_col is None:
        for c in cols:
            test = pd.to_numeric(df[c], errors="coerce").dropna()
            if len(test) > 0 and test.between(-10000, 10000).all():
                if test.std() > 1 and (test % 1 == 0).all():
                    year_col = c
                    break

    if year_col is None:
        raise ValueError(f"No se encontró columna de año en: {os.path.basename(ruta)}")

    nombres_excluidos = {
        str(year_col).strip().lower(),
        "id_serie", "id", "serie", "muestra", "sample", "code",
        "n", "sd", "se", "samp", "samp.depth", "sample.depth",
    }
    value_col = None
    for c in cols:
        if str(c).strip().lower() in nombres_excluidos:
            continue
        test = pd.to_numeric(df[c], errors="coerce")
        if test.notna().sum() > 0:
            value_col = c
            break

    if value_col is None:
        raise ValueError(f"No se encontró columna de valores en: {os.path.basename(ruta)}")

    df_out = pd.DataFrame({
        "Anio": pd.to_numeric(df[year_col], errors="coerce"),
        "Ancho_mm": pd.to_numeric(df[value_col], errors="coerce"),
    }).dropna()

    if df_out.empty:
        raise ValueError(f"No se encontraron datos válidos en: {os.path.basename(ruta)}")

    df_out["Anio"] = df_out["Anio"].astype(int)
    df_out = df_out.groupby("Anio", as_index=True).mean(numeric_only=True)
    df_out.index.name = "Anio"
    df_out.sort_index(inplace=True)

    nombre = os.path.splitext(os.path.basename(ruta))[0]
    return df_out, nombre


def _indexar_columna_multi(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Toma una tabla cruda (año + N columnas de valor) y la devuelve indexada
    por año, con las columnas convertidas a numérico y sin las auxiliares."""
    if df_raw.shape[1] < 2:
        raise ValueError("El archivo debe tener al menos dos columnas (año + valor[es]).")

    df_raw = df_raw.copy()
    cols = list(df_raw.columns)
    year_col = None
    for c in cols:
        if str(c).lower() in ("anio", "año", "year", "anios", "años"):
            year_col = c
            break
    if year_col is None:
        year_col = cols[0]

    df_raw[year_col] = pd.to_numeric(df_raw[year_col], errors="coerce")
    df_raw = df_raw.dropna(subset=[year_col])
    df_raw[year_col] = df_raw[year_col].astype(int)
    df_raw.set_index(year_col, inplace=True)
    df_raw.index.name = "Anio"
    df_raw.sort_index(inplace=True)

    for c in df_raw.columns:
        df_raw[c] = pd.to_numeric(df_raw[c], errors="coerce")

    cols_valor = [c for c in df_raw.columns
                  if str(c).strip().lower() not in (
                      "n", "sd", "se", "samp", "samp.depth", "sample.depth",
                      "id_serie", "id", "serie", "muestra", "sample", "code"
                  )]
    if not cols_valor:
        raise ValueError("No se encontraron columnas de valores (todo es N/SD).")

    return df_raw[cols_valor]


def _leer_crudo_tabular(ruta: str) -> pd.DataFrame:
    """Lee la tabla cruda de un archivo (primera hoja si es planilla)."""
    ext = os.path.splitext(ruta)[1].lower()

    if _es_planilla(ext):
        return _leer_planilla(ruta)

    try:
        df_raw = pd.read_csv(ruta, sep=None, engine="python",
                             encoding="utf-8", encoding_errors="replace")
    except Exception:
        df_raw = pd.read_csv(ruta, sep=r"[\s,;\t]+", engine="python",
                             encoding="utf-8", encoding_errors="replace")

    if df_raw.shape[1] >= 2:
        test = pd.to_numeric(df_raw.iloc[1:, 1], errors="coerce")
        if test.isna().all() and len(test) > 0:
            try:
                df_raw = pd.read_csv(ruta, sep=None, engine="python", decimal=",",
                                     encoding="utf-8", encoding_errors="replace")
            except Exception:
                pass
    return df_raw


def leer_columna_multi(ruta: str) -> pd.DataFrame:
    """Lee archivo con N columnas de valor, devuelve DataFrame con índice año."""
    return _indexar_columna_multi(_leer_crudo_tabular(ruta))


def leer_columna_multi_hojas(ruta: str) -> dict[str, pd.DataFrame]:
    """Igual que `leer_columna_multi` pero devuelve TODAS las hojas.

    pandas lee solo la primera hoja por defecto, así que un .ods/.xlsx con
    varias cronologías en hojas distintas mostraba solo una. Devuelve un dict
    {nombre_hoja: df_indexado}; para archivos de texto devuelve una sola
    entrada con clave "".
    """
    if not _es_planilla(ruta):
        return {"": leer_columna_multi(ruta)}

    hojas = _leer_planilla(ruta, sheet_name=None)  # dict {hoja: df}
    if not isinstance(hojas, dict):
        hojas = {"": hojas}

    salida = {}
    for nombre_hoja, df_hoja in hojas.items():
        try:
            df_idx = _indexar_columna_multi(df_hoja)
        except Exception:
            continue  # hoja sin formato de cronología (notas, etc.)
        if not df_idx.empty:
            salida[str(nombre_hoja)] = df_idx
    if not salida:
        raise ValueError("Ninguna hoja tiene formato de cronología (año + valores).")
    return salida


def _ruta_metadatos_cronologia(ruta: str) -> str:
    base = os.path.basename(ruta)
    carpeta = os.path.dirname(ruta)
    return os.path.join(carpeta, f".{os.path.splitext(base)[0]}.json")


# Campos cuyo diccionario está indexado por AÑO. JSON obliga a que las claves
# sean texto, así que al releer hay que devolverlas a entero: los consumidores
# hacen `pd.Series(...)` y luego ordenan y comparan el índice como número.
_CAMPOS_POR_ANIO = ("sample_depth", "EPS_movil", "Rbar_movil")


def _restaurar_claves_anio(meta: dict) -> dict:
    for campo in _CAMPOS_POR_ANIO:
        if isinstance(meta.get(campo), dict):
            meta[campo] = _js.restaurar_claves_int(meta[campo])
    return meta


def _guardar_metadatos_cronologia(ruta: str, meta: dict):
    """Escribe el .json de metadatos, saneando tipos y de forma atómica."""
    _js.guardar_json(_ruta_metadatos_cronologia(ruta), meta)


def _cargar_metadatos_cronologia(ruta: str) -> dict | None:
    meta_path = _ruta_metadatos_cronologia(ruta)
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return _restaurar_claves_anio(json.load(f))
    except Exception:
        logger.exception("No se pudo leer el metadato %s", meta_path)
        return None


def _lineas_tucson(serie, codigo, factor=1000.0):
    """Generador común: campos fijos, años reales y terminador inequívoco."""
    if factor not in (100.0, 1000.0):
        raise ValueError("Tucson: factor debe ser 100 o 1000.")
    codigo = str(codigo)[:TUCSON_MAX_CHARS_ID]
    if not codigo.strip() or not codigo.isascii() or any(c in codigo for c in "\r\n\t"):
        raise ValueError("Código Tucson inválido.")
    if serie.empty or serie.index.has_duplicates:
        raise ValueError("Tucson: serie vacía o años duplicados.")
    datos = {}
    fin = 999 if factor == 100 else TUCSON_VALOR_FIN
    for anio, valor in serie.items():
        y = int(anio)
        if float(anio) != y or not -999 <= y <= 9999:
            raise ValueError(f"Año Tucson inválido: {anio}")
        if pd.isna(valor):
            v = TUCSON_VALOR_FALTANTE
        else:
            v = int(round(float(valor) * factor))
            if v in (fin, TUCSON_VALOR_FIN, TUCSON_VALOR_FALTANTE) or len(str(v)) > 6:
                raise ValueError(f"Valor Tucson reservado o fuera de rango: {valor} ({y})")
        datos[y] = v
    inicio, ultimo = min(datos), max(datos)
    lineas = []
    y = inicio
    while y <= ultimo:
        n = min(10-y%10, ultimo-y+1)
        valores = [datos.get(k, TUCSON_VALOR_FALTANTE) for k in range(y,y+n)]
        lineas.append(f"{codigo:8s}{y:4d}" + "".join(f"{v:6d}" for v in valores))
        y += n
    if (len(lineas[-1])-12)//6 < 10 and y%10:
        lineas[-1] += f"{fin:6d}"
    else:
        if y > 9999:
            raise ValueError("Tucson: año del terminador fuera de rango.")
        lineas.append(f"{codigo:8s}{y:4d}{fin:6d}")
    return lineas


def _guardar_lineas_tucson(ruta, lineas):
    with open(ruta, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lineas) + "\n")


def escribir_tucson(serie: pd.Series, ruta: str, codigo: str = "CRONO",
                     factor: float = 1000.0, decimales_mm: bool = True):
    _guardar_lineas_tucson(ruta, _lineas_tucson(serie, codigo, factor))


def _exportar_cronologia_df(df: pd.DataFrame, ruta: str, codigo: str = "CRONO"):
    ext = os.path.splitext(ruta)[1].lower()
    df_out = df.copy()
    df_out.index.name = "Anio"
    if ext == ".rwl":
        # Tucson: se guarda la columna de valores de la cronología
        col = df_out.columns[0]
        for c in df_out.columns:
            if str(c).strip().lower() not in ("n", "sd", "se", "eps", "rbar"):
                col = c
                break
        escribir_tucson(pd.to_numeric(df_out[col], errors="coerce"),
                        ruta, codigo=codigo)
        return
    if _es_planilla(ext):
        _escribir_excel(df_out, ruta, index=True)
    elif ext == ".csv":
        df_out.to_csv(ruta, index=True)
    else:
        df_out.to_csv(ruta, index=True, sep="\t")


def _leer_cronologia_guardada(ruta: str) -> tuple[pd.DataFrame, dict]:
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".rwl":
        df, _ = leer_archivo_tucson(ruta)
        df = df.reset_index()
    elif _es_planilla(ext):
        df = _leer_planilla(ruta)
    elif ext == ".csv":
        df = pd.read_csv(ruta)
        if df.shape[1] < 2:
            df = pd.read_csv(ruta, sep=";", decimal=",")
    else:
        try:
            df = pd.read_csv(ruta, sep="\t")
            test_col = df.iloc[:, 1] if df.shape[1] > 1 else pd.Series()
            if pd.to_numeric(test_col, errors="coerce").isna().all() and len(test_col) > 0:
                df = pd.read_csv(ruta, sep="\t", decimal=",")
        except Exception:
            try:
                df = pd.read_csv(ruta, sep=None, engine="python", decimal=",")
            except Exception:
                df = pd.read_csv(ruta, sep=None, engine="python")

    if df.shape[1] < 2:
        raise ValueError("La cronología debe tener al menos dos columnas.")

    cols = list(df.columns)
    year_col = None
    for c in cols:
        if c.lower() in ("anio", "año", "year"):
            year_col = c
            break
    if year_col is None:
        year_col = cols[0]

    df[year_col] = pd.to_numeric(df[year_col], errors="coerce")
    df = df.dropna(subset=[year_col])
    df[year_col] = df[year_col].astype(int)
    df.set_index(year_col, inplace=True)
    df.index.name = "Anio"
    df.sort_index(inplace=True)

    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    value_cols = [c for c in df.columns if c.lower() not in ("n", "sd", "se")]

    meta = _cargar_metadatos_cronologia(ruta) or {}
    nombre = meta.get("nombre") or os.path.splitext(os.path.basename(ruta))[0]

    if not meta:
        cols_lower = {c.lower(): c for c in value_cols}
        columnas_disponibles = []
        for t in ["Raw", "Standard", "Residual"]:
            if t.lower() in cols_lower or t in df.columns:
                columnas_disponibles.append(t)

        if len(columnas_disponibles) > 1:
            tipo = "todas"
            col_valor = columnas_disponibles[0]
        elif len(columnas_disponibles) == 1:
            tipo = columnas_disponibles[0].lower()
            col_valor = columnas_disponibles[0]
        else:
            tipo = "raw"
            col_valor = value_cols[0] if value_cols else df.columns[0]

        meta = {
            "nombre": nombre, "tipo_cronologia": tipo,
            "metodo_estandarizacion": "desconocido", "agregacion": "desconocido",
            "series_usadas": [], "n_series": 0,
            "n_anios": int(len(df)),
            "columna_valor": col_valor,
            "columnas_disponibles": columnas_disponibles if len(columnas_disponibles) > 1 else [],
        }

    meta.setdefault("nombre", nombre)
    meta.setdefault("n_anios", int(len(df)))

    col_val = meta.get("columna_valor", "")
    if col_val not in df.columns:
        for c in df.columns:
            if c.lower() == col_val.lower():
                meta["columna_valor"] = c
                break
        else:
            meta["columna_valor"] = value_cols[0] if value_cols else df.columns[0]

    return df, meta


def _exportar_tabular(id_serie: str, anios: list, anchos: list, ruta: str,
                       formato: str, anchos_ewlw: list | None = None):
    """Exporta a CSV o Excel. Si anchos_ewlw está presente, agrega columnas EW_mm y LW_mm."""
    data = {"ID_Serie": id_serie, "Anio": anios, "Ancho_mm": anchos}
    if anchos_ewlw and len(anchos_ewlw) == len(anios):
        # Columnas separadas: NaN para anillos sin EW/LW detectado
        ew_col = [(t[1] if t[1] is not None else float("nan"))
                  for t in anchos_ewlw]
        lw_col = [(t[2] if t[2] is not None else float("nan"))
                  for t in anchos_ewlw]
        data["EW_mm"] = ew_col
        data["LW_mm"] = lw_col
    df = pd.DataFrame(data)
    if formato == "csv":
        df.to_csv(ruta, index=False)
    else:
        _escribir_excel(df, ruta)

def _exportar_tucson_ewlw(id_serie: str, anios: list,
                            anchos_ewlw: list, ruta_base: str):
    if not anios or len(anchos_ewlw) != len(anios):
        raise ValueError("EW/LW: cantidad de años y mediciones incompatible.")
    base, ext = os.path.splitext(ruta_base)
    ext = ext or ".rwl"
    salidas = []
    for sufijo, columna in (("_EW", 1), ("_LW", 2)):
        valores = [t[columna] if t[1] is not None and t[2] is not None else np.nan
                   for t in anchos_ewlw]
        codigo = id_serie[:TUCSON_MAX_CHARS_ID-len(sufijo)] + sufijo
        salidas.append((base+sufijo+ext, _lineas_tucson(pd.Series(valores, index=anios), codigo)))
    for ruta, lineas in salidas:
        _guardar_lineas_tucson(ruta, lineas)


def _escribir_tucson(codigo: str, anio_inicio: int, mediciones: list[int], ruta: str,
                     *, anios=None):
    if not ruta.lower().endswith((".txt", ".rwl")):
        ruta += ".txt"
    if anios is None:
        anios = range(anio_inicio, anio_inicio+len(mediciones))
    serie = pd.Series(mediciones, index=anios, dtype=float) / 1000.0
    escribir_tucson(serie, ruta, codigo)


def _escribir_tucson_serie(codigo: str, anio_inicio: int,
                            mediciones_mm: list[float], buffer: list[str]) -> None:
    serie = pd.Series(mediciones_mm, index=range(anio_inicio, anio_inicio+len(mediciones_mm)))
    buffer.extend(_lineas_tucson(serie, codigo))


def escribir_tucson_merge(series_dict: dict[str, pd.DataFrame], ruta: str) -> None:
    if not ruta.lower().endswith((".rwl", ".txt")):
        ruta += ".rwl"
    buffer = []
    codigos = set()
    for sid, df in series_dict.items():
        codigo = str(sid)[:TUCSON_MAX_CHARS_ID].strip()
        if codigo in codigos:
            raise ValueError(f"Identificadores Tucson coincidentes: {codigo}")
        codigos.add(codigo)
        df = df.set_index("Anio") if "Anio" in df.columns else df
        buffer.extend(_lineas_tucson(df["Ancho_mm"], codigo))
    if not buffer:
        raise ValueError("No hay series para exportar.")
    _guardar_lineas_tucson(ruta, buffer)


def escribir_excel_merge(series_dict: dict[str, pd.DataFrame], ruta: str) -> None:
    """Escribe TODAS las series en UNA hoja Excel.

    Estructura:
      - Columna A: Año
      - Columnas B, C, D, ...: una por serie (header = ID de la serie)
      - Celdas: ancho en mm; vacías donde la serie no tiene dato para
        ese año

    Este formato es el preferido del usuario porque facilita análisis
    posterior (importar a R, hacer cofechado, etc.) sin tener que
    deshacer la separación por hojas.
    """
    if not ruta.lower().endswith((".xlsx", ".xls")):
        ruta += ".xlsx"

    # Construir DataFrame combinado con Año como index, una columna por serie
    series_alineadas: dict[str, pd.Series] = {}
    for sid, df in series_dict.items():
        if "Anio" in df.columns:
            df_local = df.set_index("Anio")
        else:
            df_local = df
        s = df_local["Ancho_mm"].copy()
        s.name = sid
        series_alineadas[sid] = s

    combinado = pd.DataFrame(series_alineadas)
    combinado.sort_index(inplace=True)
    combinado.index.name = "Anio"

    # Exportar: incluir el index (Año) como primera columna
    combinado.to_excel(ruta, sheet_name="Series", index=True)

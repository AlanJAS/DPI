"""Núcleo de datación dendrocronológica, independiente de la interfaz Qt."""
import logging
import numpy as np
import pandas as pd
import modulo_estadistica as _est
import modulo_quiebres as _qb
from modulo_estadistica import _r_movil
from modulo_cronologia import _normalizar_serie_para_tipo
from constantes import OVERLAP_MINIMO_ANALISIS, OVERLAP_MINIMO_GRAFICO

logger = logging.getLogger(__name__)
MAX_CORRECCION = 3
MIN_OVERLAP_DEFAULT = 10


def score_compuesto(r: float, glk: float, t_bp: float) -> float:
    """Media geométrica con signo de r, GLK y t-BP normalizados a [-1, 1].

    Resultado en [-1, +1]:
      • cerca de +1  →  las tres métricas indican correlación fuerte
      • cerca de  0  →  ambiguo / al menos una métrica plana
      • cerca de -1  →  las tres indican ANTI-correlación
                        (señal de que el cofechado está completamente desfasado:
                         el patrón coincide pero invertido)

    Normalización: r ∈ [-1,1] directo, GLK mapeado desde [0,1] a [-1,1] con
    pivote en 0.5, t-BP saturado en ±10. Se usa raíz cúbica (np.cbrt) que
    preserva signo, a diferencia de la potencia 1/3 que en Python devuelve
    complejos para negativos.
    """
    if not (np.isfinite(r) and np.isfinite(glk) and np.isfinite(t_bp)):
        return float("nan")
    r_norm = max(-1.0, min(1.0, r))
    glk_norm = max(-1.0, min(1.0, 2.0 * (glk - 0.5)))
    tbp_norm = max(-1.0, min(1.0, t_bp / 10.0))
    producto = r_norm * glk_norm * tbp_norm
    return float(np.cbrt(producto))


def _serie_transformada_para_comparar(df: pd.DataFrame, meta: dict) -> pd.Series:
    tipo = (meta.get("tipo_cronologia") or "raw").lower()
    metodo = meta.get("metodo_estandarizacion", "spline")
    return _normalizar_serie_para_tipo(df["Ancho_mm"], tipo, metodo)


_glk_np = _est.glk_alineado


_tbp_np = _est.tbp_alineado


def alineamiento_optimo_anillos(serie_a, serie_b, shift_base,
                                 max_correcciones=10, penalizacion=3.0):
    """Alineamiento óptimo serie↔cronología por programación dinámica.

    A diferencia del cofechado por ventanas fijas (COFECHA), este método
    descompone la serie completa buscando el alineamiento globalmente
    óptimo que permite insertar anillos faltantes y eliminar anillos
    sobrantes en CUALQUIER posición, con una penalización por cada
    corrección.

    Modelo:
      - Se recorre la serie año a año (sobre primeras diferencias, que es
        la señal de cofechado).
      - En cada año la serie tiene un "desfase acumulado" respecto a la
        cronología.
      - De un año al siguiente, el desfase puede mantenerse (año normal),
        +1 (anillo faltante → hay que insertar uno) o −1 (anillo sobrante
        → hay que eliminar uno).
      - Cada cambio de desfase cuesta `penalizacion`.
      - Se maximiza la concordancia total (acuerdo de signo de las
        primeras diferencias, equivalente a GLK punto a punto) menos las
        penalizaciones.

    Implementación: programación dinámica O(n·S·3) donde S = 2·max_corr+1.
    Garantiza el óptimo global (no es heurístico como las ventanas).

    Parámetros:
      shift_base: desfase global de partida (centro de la banda de búsqueda)
      max_correcciones: máximo de anillos a corregir acumulados (banda ±)
      penalizacion: costo por corrección. Bajo = exploratorio (propone más
                    correcciones); alto = conservador (solo las muy claras).

    Devuelve dict con:
      "segmentos": lista de tramos de desfase constante, cada uno con
                   rango de años de la serie, rango calendario, corrección
                   neta vs base, n años, r y GLK del tramo.
      "correcciones": lista de puntos donde cambia el desfase (año
                      calendario aproximado y tipo: faltante/sobrante).
      "shift_base": el desfase base usado.
    Devuelve None si no hay datos suficientes.
    """
    a = pd.to_numeric(serie_a, errors="coerce").dropna().sort_index()
    b = pd.to_numeric(serie_b, errors="coerce").dropna().sort_index()
    if len(a) < 10 or len(b) < 10:
        return None

    da = _est.diferencias_anuales(a)
    db = _est.diferencias_anuales(b)
    sa = np.sign(da.to_numpy())
    years_a = da.index.to_numpy().astype(int)
    sb_by_year = {int(y): np.sign(v)
                  for y, v in zip(db.index.to_numpy(), db.to_numpy())}
    da_by_year = {int(y): float(v)
                  for y, v in zip(da.index.to_numpy(), da.to_numpy())}
    db_by_year = {int(y): float(v)
                  for y, v in zip(db.index.to_numpy(), db.to_numpy())}

    n = len(years_a)
    if n == 0 or db.empty:
        return None
    shifts = list(range(int(shift_base) - int(max_correcciones),
                        int(shift_base) + int(max_correcciones) + 1))
    S = len(shifts)
    NEG = -1e9
    dp = np.full((n, S), NEG)
    back = np.full((n, S), -1, dtype=int)

    def score(t, s):
        ya = years_a[t]
        cb = sb_by_year.get(ya + s)
        if cb is None or sa[t] == 0 or cb == 0:
            return 0.0
        return 1.0 if sa[t] == cb else -1.0

    # Inicialización: el primer año puede empezar en cualquier desfase de
    # la banda sin costo (la posición del extremo de médula es la hipótesis
    # de datación; las correcciones internas son las que cuestan).
    for si, s in enumerate(shifts):
        dp[0][si] = score(0, s)

    for t in range(1, n):
        prev = dp[t - 1]
        for si in range(S):
            sc = score(t, shifts[si])
            best = prev[si]       # mismo desfase (año normal)
            bptr = si
            if si - 1 >= 0 and prev[si - 1] - penalizacion > best:
                best = prev[si - 1] - penalizacion  # anillo faltante
                bptr = si - 1
            if si + 1 < S and prev[si + 1] - penalizacion > best:
                best = prev[si + 1] - penalizacion  # anillo sobrante
                bptr = si + 1
            dp[t][si] = best + sc
            back[t][si] = bptr

    end_si = int(np.argmax(dp[n - 1]))
    path = [0] * n
    si = end_si
    for t in range(n - 1, 0, -1):
        path[t] = si
        si = back[t][si]
        if si < 0:
            si = path[t]
    path[0] = si
    shift_path = [shifts[i] for i in path]

    # Construir segmentos de desfase constante
    segmentos = []
    correcciones = []
    i0 = 0
    for t in range(1, n + 1):
        if t == n or shift_path[t] != shift_path[i0]:
            s = shift_path[i0]
            ys = years_a[i0:t]
            avals, bvals, agree, tot = [], [], 0, 0
            for y in ys:
                if y in da_by_year and (y + s) in db_by_year:
                    avals.append(da_by_year[y])
                    bvals.append(db_by_year[y + s])
                    if (np.sign(da_by_year[y]) == np.sign(db_by_year[y + s])
                            and da_by_year[y] != 0):
                        agree += 1
                    tot += 1
            r = _est.pearson(avals, bvals) if len(avals) > 2 else float("nan")
            glk = agree / tot if tot else float("nan")
            segmentos.append({
                "serie_ini": int(ys[0]), "serie_fin": int(ys[-1]),
                "cal_ini": int(ys[0] + s), "cal_fin": int(ys[-1] + s),
                "shift": int(s), "correccion": int(s - shift_base),
                "n": int(len(ys)), "r": r, "glk": glk,
            })
            # Registrar el punto de corrección (transición entre segmentos)
            if t < n:
                s_next = shift_path[t]
                year_corr = int(years_a[t] + s_next)
                if s_next > s:
                    # El desfase aumenta → faltaba un anillo (insertar)
                    correcciones.append({
                        "anio_calendario": year_corr,
                        "tipo": "faltante", "delta": s_next - s,
                    })
                else:
                    correcciones.append({
                        "anio_calendario": year_corr,
                        "tipo": "sobrante", "delta": s - s_next,
                    })
            i0 = t

    return {
        "segmentos": segmentos,
        "correcciones": correcciones,
        "shift_base": int(shift_base),
    }


# =============================================================================
# MOTOR DE BÚSQUEDA EXHAUSTIVA DE CORRECCIONES
# =============================================================================

def _diff_log(serie: pd.Series) -> pd.Series:
    """Diferencias de logaritmos — transforma anchos en tasas de crecimiento."""
    return _est.diferencias_log_anuales(serie)


_r_pearson = _est.pearson


def aplicar_correccion(df: pd.DataFrame, anio: int, delta: int,
                        anclaje: str = "corteza") -> pd.DataFrame:
    """Inserta o elimina delta anillos en una posición.

    El ANCLAJE decide qué extremo de la serie se queda quieto:

    • "corteza" (por defecto): el ÚLTIMO año no se mueve y se desplazan los
      años ANTERIORES. Es lo correcto para árboles vivos fechados desde la
      corteza (se sabe con certeza el año del anillo externo). Si falta un
      anillo en 2023, al insertarlo la serie sigue terminando en 2024 y todo
      lo anterior a 2023 retrocede un año — que es justo lo que pasó en la
      madera.
        - delta > 0 (anillo faltante): los años ≤ anio se mueven −1 y se
          inserta un anillo en `anio`.
        - delta < 0 (anillo extra): se elimina `anio` y los años < anio
          se mueven +1.

    • "medula": el PRIMER año no se mueve y se desplazan los años
      posteriores. Útil para series flotantes o fechadas desde la médula.

    Antes solo existía el anclaje en médula, así que insertar un anillo
    empujaba la serie hacia el presente (una serie que terminaba en 2024
    pasaba a terminar en 2025) y obligaba a corregir el año base a mano.
    Además hacía que el buscador de correcciones propusiera años equivocados:
    para arreglar un desfase global proponía una corrección al INICIO de la
    serie en vez del anillo que realmente falta cerca de la corteza.

    Implementado con numpy (no pandas append/.loc) porque se llama cientos
    de veces por cada búsqueda de correcciones.
    """
    years = df.index.to_numpy(dtype=np.int64).copy()
    vals = pd.to_numeric(df["Ancho_mm"], errors="coerce").to_numpy(dtype=float).copy()
    placeholder = float(np.nanmean(vals)) if vals.size else 0.0
    a = int(anio)
    anclar_corteza = str(anclaje).lower().startswith("cort")

    for _ in range(abs(delta)):
        if delta > 0:
            if anclar_corteza:
                # Los años ≤ a retroceden; queda libre el año `a`
                years = np.where(years <= a, years - 1, years)
            else:
                years = np.where(years >= a, years + 1, years)
            years = np.append(years, a)
            vals = np.append(vals, placeholder)
        else:
            m = years != a
            years = years[m]
            vals = vals[m]
            if anclar_corteza:
                years = np.where(years < a, years + 1, years)
            else:
                years = np.where(years > a, years - 1, years)
    orden = np.argsort(years, kind="stable")
    return pd.DataFrame({"Ancho_mm": vals[orden]},
                        index=pd.Index(years[orden], name="Anio"))


def _plausibilidad_anillo_estrecho(ref_years: np.ndarray, ref_vals: np.ndarray,
                                    anio: int, delta: int,
                                    peso: float = 0.6) -> float:
    """Cuán creíble es que falte (o sobre) un anillo en `anio`.

    Los anillos que se omiten al fechar una muestra son los ESTRECHOS: en un
    año malo el anillo puede ser casi invisible o localmente ausente. Los
    anillos anchos prácticamente nunca se pasan por alto.

    Se mide cuán bajo está ese año en la REFERENCIA (la cronología, ya
    estandarizada, media ~1) usando su posición en desviaciones típicas, y se
    devuelve un factor:
        > 1  año estrecho  → candidato más creíble
        < 1  año ancho     → candidato menos creíble
    `peso` gradúa cuánto influye (0 = solo estadística, como antes).

    Para anillos SOBRANTES (delta<0) el razonamiento se invierte solo en
    parte: un falso anillo suele aparecer dentro de un año ancho (banda de
    madera tardía intermedia), así que ahí se premia lo ancho.
    """
    if ref_vals.size < 5:
        return 1.0
    idx = np.searchsorted(ref_years, int(anio))
    if idx < 0 or idx >= ref_years.size or int(ref_years[idx]) != int(anio):
        return 1.0  # el año no está en la referencia: sin información
    media = float(np.nanmean(ref_vals))
    sd = float(np.nanstd(ref_vals))
    if not np.isfinite(sd) or sd <= 0:
        return 1.0
    z = (float(ref_vals[idx]) - media) / sd
    # z<0 = año estrecho. Para anillo faltante premiamos z negativo.
    señal = -z if delta > 0 else z
    señal = float(np.clip(señal, -2.5, 2.5))
    return float(max(0.15, 1.0 + peso * señal / 2.5))


def puntaje_consistencia(serie_std: pd.Series, crono_std: pd.Series,
                          **kwargs) -> dict:
    """Mide si una serie YA CORREGIDA quedó limpia, no cuánto correlaciona.

    El problema que resuelve: cuando el buscador propone corregir en 1850 o en
    1858, las dos candidatas dan correlaciones globales casi iguales —
    diferencias de milésimas— porque ambas arreglan casi toda la serie. La r
    global no distingue entre ellas, y así terminan aceptándose años que están
    a cinco o diez años del verdadero.

    La pregunta cambia: en vez de «¿cuál sube más la r?», «¿cuál deja la serie
    limpia?». Se aplica cada candidata y se vuelve a correr el diagnóstico de
    tramos. Si el año es el correcto, la serie queda con un solo tramo a
    desfase 0 de punta a punta. Si el año está equivocado por ocho años, queda
    un tramo residual de ocho años desajustado, que el diagnóstico ve como un
    segundo tramo.

    La ventaja es que el criterio pasa de continuo y casi empatado a
    esencialmente binario —quedó limpia o no—, y además el tramo residual
    crece con el error, así que la señal es proporcional a la distancia.

    Devuelve:
      limpia   1 si el diagnóstico dice bien_fechada, 0 si no
      residuo  años cubiertos por tramos con desfase distinto de cero
      n_tramos cuántos tramos sólidos quedaron
      diag     el diagnóstico textual, para mostrarlo en la interfaz
    """
    try:
        d = diagnosticar_datacion(serie_std, crono_std, **kwargs)
    except Exception:
        return {"limpia": 0, "residuo": 10 ** 6, "n_tramos": 99,
                "diag": "error", "r_medio": float("nan")}

    tramos = d.get("tramos") or []
    residuo = sum(max(t["fin"] - t["inicio"], 1)
                  for t in tramos if t.get("shift", 0) != 0)
    rs = [t.get("r_medio") for t in tramos if t.get("shift", 0) == 0]
    return {
        "limpia": 1 if d.get("diagnostico") == "bien_fechada" else 0,
        "residuo": int(residuo),
        "n_tramos": len(tramos),
        "diag": d.get("diagnostico") or "",
        "r_medio": float(np.nanmean(rs)) if rs else float("nan"),
    }


def _texto_correccion(delta: int) -> str:
    """Describe la corrección con la acción, no solo con el signo.

    COFECHA escribe "+1" o "-1" y deja que el usuario deduzca si hay que
    agregar o quitar. En la práctica esa deducción se equivoca seguido, así
    que acá se nombra la acción.

    Convención, verificada con series a las que se les quitó o duplicó un
    anillo en un año conocido: delta positivo = faltan anillos, hay que
    insertar; delta negativo = sobran, hay que eliminar. Es la misma que
    COFECHA, donde un desplazamiento de +1 señala un anillo ausente.
    """
    n = abs(int(delta))
    if delta > 0:
        return f"Insertar {n}" + (" anillo" if n == 1 else " anillos")
    if delta < 0:
        return f"Eliminar {n}" + (" anillo" if n == 1 else " anillos")
    return "Sin cambio"


def _buscar_y_priorizar(ref, problema, mitad_ventana, max_corr,
                         diagnostico=None, coleccion_std=None,
                         nombre_serie=None, **kwargs):
    """Busca correcciones y las reordena según el diagnóstico previo.

    La búsqueda por correlación sola puede encabezar con una corrección del
    signo equivocado (por ejemplo, quitar un anillo cuando lo que falta es
    agregarlo): a corta distancia ambas cosas mejoran la r de forma parecida.
    El diagnóstico sí sabe qué pasa —qué tramo está bien fechado y hacia dónde
    está corrido el otro—, así que se usa para priorizar las correcciones
    COHERENTES con él: el signo correcto y cerca del año localizado.
    """
    sugerencias, es_marginal = buscar_correcciones(
        ref, problema, mitad_ventana, max_corr, **kwargs)
    if not sugerencias:
        return sugerencias, es_marginal

    # VERIFICACIÓN REAL de las mejores candidatas: en vez de confiar en la
    # métrica interna de la búsqueda (que trabaja sobre arreglos ya
    # transformados y con un relleno aproximado para el anillo nuevo), se
    # aplica cada candidata a la serie CRUDA, se vuelve a estandarizar y se
    # mide la correlación resultante. Sin esto la lista podía encabezar con
    # una corrección del signo equivocado: en una serie a la que le faltaba
    # un anillo, quitar otro daba r=0.256 mientras que insertarlo daba 0.349,
    # y aun así aparecía primero el "quitar".
    tr_ref = kwargs.get("transformar_ref")
    tr_prob = kwargs.get("transformar_prob")
    anclaje = kwargs.get("anclaje", "corteza")
    _eval_r = None
    ref_years_g = ref_vals_g = None
    _r_base_g = float("nan")
    _hay_quiebre_confiable = False
    _informe_zona = None
    if tr_ref is not None and tr_prob is not None:
        try:
            d_ref = tr_ref(ref["Ancho_mm"]).dropna()
            ref_years_g = d_ref.index.to_numpy(np.int64)
            ref_vals_g = d_ref.to_numpy(dtype=float)

            def _eval_r(df2):
                """Correlación real de una serie ya corregida contra la referencia."""
                d2 = tr_prob(df2["Ancho_mm"]).dropna()
                com = d_ref.index.intersection(d2.index)
                if len(com) < 10:
                    return -np.inf
                a = d_ref.loc[com].to_numpy(dtype=float)
                b = d2.loc[com].to_numpy(dtype=float)
                r = _est.pearson(a, b)
                return r if np.isfinite(r) else -np.inf

            def _r_real(sug):
                df2 = aplicar_correccion(problema, int(sug["anio"]),
                                         int(sug["delta"]), anclaje=anclaje)
                return _eval_r(df2)

            # Correlación SIN corregir: cualquier candidata que no la supere
            # se descarta. Una sugerencia que baja la correlación no es una
            # corrección, y ofrecerla solo confunde.
            r_base = _eval_r(problema)
            _r_base_g = r_base

            for sug in sugerencias[:12]:
                sug["r_verificada"] = _r_real(sug)
            verificadas = [s for s in sugerencias[:12]
                           if np.isfinite(s.get("r_verificada", -np.inf))
                           and (not np.isfinite(r_base)
                                or s["r_verificada"] > r_base)]
            resto = [s for s in sugerencias[12:]
                     if s.get("delta_r", 0) > 0]

            # CONSISTENCIA: se calcula para las candidatas de cabeza y se
            # guarda para mostrarla, pero NO se usa para ordenar.
            #
            # La idea era prometedora: en vez de preguntar cuál sube más la
            # correlación —criterio que empata cuando dos candidatas separadas
            # por ocho años difieren en milésimas— preguntar cuál deja la
            # serie sin tramos desajustados. Se probó de verdad, aplicando
            # cada candidata y volviendo a diagnosticar, contra el año real
            # conocido en 120 series simuladas.
            #
            # No funciona. El diagnóstico de tramos solo ve residuos de ocho
            # años o más; a cuatro años no distingue nada, y justo ahí es
            # donde la correlación tampoco decide. Peor: de vez en cuando
            # marca como sucia la candidata CORRECTA por ruido, y eso la
            # manda abajo en la lista. Medido:
            #
            #   señal fuerte (r~0.73)   exacto   error medio
            #     solo correlación        62%       0.97 años
            #     por consistencia        58%       1.33 años
            #   señal débil (r~0.35)
            #     solo correlación        32%       3.17 años
            #     por consistencia        22%       3.67 años
            #
            # Filtrar por residuo grande manteniendo el orden por r tampoco
            # aporta (62% / 1.00 años). Así que el orden sigue siendo por
            # correlación verificada, y la consistencia se muestra como
            # información de apoyo para que el usuario la juzgue.
            for sug in verificadas[:5]:
                try:
                    df2 = aplicar_correccion(problema, int(sug["anio"]),
                                             int(sug["delta"]), anclaje=anclaje)
                    sug["consistencia"] = puntaje_consistencia(
                        tr_prob(df2["Ancho_mm"]).dropna(), d_ref,
                        ventana=12, paso=2, min_overlap=6)
                except Exception:
                    pass

            def _clave(s):
                return (s.get("r_verificada", -np.inf)
                        * s.get("plausibilidad", 1.0))

            verificadas.sort(key=_clave, reverse=True)
            sugerencias = verificadas + resto

            # ── LOCALIZACIÓN POR PARTICIÓN ÓPTIMA ────────────────────
            # Reproduce el procedimiento manual: fijar el tramo que ya calza
            # con la cronología y mover solo el que falla, hasta encontrar el
            # año exacto donde se rompe la correlación.
            #
            # No es un refinamiento del buscador por correlación: es una
            # pregunta distinta. El buscador prueba correcciones y se queda
            # con la que más sube la r global, criterio que se aplana cuando
            # dos candidatas separadas por varios años difieren en milésimas.
            # Acá el AÑO DEL QUIEBRE es el parámetro que se estima, con cada
            # tramo usando todos sus datos.
            #
            # Medido en 120 series simuladas con el año conocido y el anillo
            # ausente en un año estrecho (que es donde ocurren de verdad):
            #
            #                        exacto    ±1     ±2
            #   buscador por r        20%     53%    73%
            #   partición óptima      80%     92%    97%
            #   partición, confiables 94%    100%   100%
            #
            # y el número de anillos faltantes sale correcto en el 100%.
            # Por eso estas candidatas van a la cabeza de la lista.
            # Se pide el INFORME completo, no un año único. Exigir un año
            # solo dejaba fuera cuatro de cada cinco series con error real,
            # porque el año exacto solo es afirmable en un tercio a la mitad
            # de los casos. En cambio la zona contiene el año verdadero en
            # 97-100% de las series reales probadas, y los cinco años mejor
            # ordenados de esa zona lo contienen en 67-100%.
            informe = None
            try:
                s_std = tr_prob(problema["Ancho_mm"]).dropna()
                # n_nulo=0: el nulo por rotación está mal especificado para
                # este uso (rechaza series que sí cofechan), así que no se
                # corre. El informe lo advierte en su propio texto.
                # Nulo de colección: el umbral sale de las OTRAS series
                # cargadas, que están fechadas. Es el único de los tres nulos
                # probados que controla los falsos positivos sin perder
                # detección.
                informe = _qb.informe_quiebre(
                    s_std, d_ref, max_desfase=10, n_nulo=0,
                    coleccion=coleccion_std,
                    excluir=nombre_serie)
                quiebres = _qb.mapa_de_quiebres(
                    s_std, d_ref, max_desfase=10, 
                    max_quiebres=3)
            except Exception:
                quiebres = []

            por_quiebre = []
            vistos = set()
            # ── UNA SOLA FUENTE DE VERDAD ──────────────────────────
            # El recuadro «Error localizado» venía de `_diagnosticar_datacion`,
            # un análisis por ventanas anterior e independiente, cuyo
            # `delta_sugerido` además era SIEMPRE ±1 sin importar cuántos
            # anillos. El resultado eran tres cifras distintas en la misma
            # pantalla para el mismo problema: la tabla decía +1, el recuadro
            # -2 y el informe -4.
            #
            # Ahora, cuando hay informe, el recuadro se reescribe con SUS
            # números. El diagnóstico por ventanas sigue sirviendo para decidir
            # el anclaje y para ordenar, que es donde aporta.
            if informe and informe.get("delta") and isinstance(diagnostico, dict):
                _d = int(informe["delta"])
                _n = abs(_d)
                _acc = ("INSERTAR" if _d > 0 else "ELIMINAR")
                _rg = informe.get("rango_error") or informe.get("zona")
                _cands = [str(int(a)) for a, _ in
                          (informe.get("candidatos") or [])[:5]]
                _tr = informe.get("tramos") or []
                _txt = ""
                if len(_tr) >= 2:
                    _b, _m = _tr[-1], _tr[0]
                    _txt = (f"El tramo {_b['inicio']}–{_b['fin']} calza bien "
                            f"(r≈{_b['r']:.2f}) y el tramo "
                            f"{_m['inicio']}–{_m['fin']} calza mejor desplazado "
                            f"{_m['desfase']:+d}.<br>")
                _txt += (f"<b>Hay que {_acc} {_n} anillo"
                         + ("s" if _n != 1 else "") + "</b>")
                if _rg:
                    _txt += f" <b>entre {_rg[0]} y {_rg[1]}</b>"
                if _cands:
                    _txt += ("<br><b>Años más probables</b> (estrechos en la "
                             "cronología, revísalos primero): "
                             + ", ".join(_cands))
                _txt += (". Se ancla en "
                         + ("corteza" if diagnostico.get("anclaje_sugerido",
                                                         "corteza") == "corteza"
                            else "médula")
                         + " para no mover el tramo ya fechado.")
                diagnostico["mensaje"] = _txt
                diagnostico["delta_sugerido"] = _d
                diagnostico["rango"] = _rg

            # Cada año candidato de la zona entra como una fila propia, con
            # la corrección ya aplicada, para que el usuario pueda probarlos
            # sin adivinar. Van ordenados por lo estrecho que es ese año en
            # la cronología, que es donde de verdad aparecen los ausentes.
            if informe and informe.get("candidatos") and informe.get("delta"):
                for a_cand, estrechez in informe["candidatos"]:
                    clave = (int(a_cand), int(informe["delta"]))
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    try:
                        df2 = aplicar_correccion(problema, int(a_cand),
                                                 int(informe["delta"]),
                                                 anclaje=anclaje)
                    except Exception:
                        continue
                    r_v = _eval_r(df2)
                    if not np.isfinite(r_v):
                        continue
                    por_quiebre.append({
                        "anio": int(a_cand), "delta": int(informe["delta"]),
                        "tipo": _texto_correccion(int(informe["delta"])),
                        "r_antes": float(_r_base_g), "r_tras": float(r_v),
                        "delta_r": (float(r_v - _r_base_g)
                                    if np.isfinite(_r_base_g)
                                    else float("nan")),
                        "r_zona_antes": float("nan"),
                        "r_zona_tras": float("nan"),
                        "df_corregido": df2, "r_verificada": float(r_v),
                        "plausibilidad": 1.0 + max(estrechez, 0.0),
                        "origen": "zona",
                        "confiable": False,
                        "estrechez": float(estrechez),
                        "zona": informe.get("zona"),
                        "texto": informe.get("texto"),
                        "tramos": informe.get("tramos"),
                        "perfil": informe.get("perfil"),
                    })

            # lo que venía del buscador por correlación (sin duplicar años).
            # Orden: primero lo confiable; después los años de la ZONA, que
            # heredan el delta del informe (correcto en 70-100% de los casos
            # reales); al final las candidatas crudas de la cascada, que
            # pueden proponer deltas grandes y poco creíbles.
            for q in quiebres:
                if q.get("anio") is None or not q.get("delta"):
                    continue
                clave = (int(q["anio"]), int(q["delta"]))
                if clave in vistos:
                    continue
                vistos.add(clave)
                try:
                    df2 = aplicar_correccion(problema, int(q["anio"]),
                                             int(q["delta"]), anclaje=anclaje)
                except Exception:
                    continue
                r_v = _eval_r(df2)
                if not np.isfinite(r_v):
                    continue
                por_quiebre.append({
                    "anio": int(q["anio"]), "delta": int(q["delta"]),
                    "tipo": _texto_correccion(int(q["delta"])),
                    "r_antes": float(_r_base_g),
                    "r_tras": float(r_v),
                    "delta_r": (float(r_v - _r_base_g)
                                if np.isfinite(_r_base_g) else float("nan")),
                    "r_zona_antes": float("nan"),
                    "r_zona_tras": float("nan"),
                    "df_corregido": df2,
                    "r_verificada": float(r_v),
                    "plausibilidad": (
                        _plausibilidad_anillo_estrecho(
                            ref_years_g, ref_vals_g, int(q["anio"]),
                            int(q["delta"]))
                        if ref_vals_g is not None else 1.0),
                    "origen": "quiebre",
                    "confiable": bool(q.get("confiable")),
                    "nitidez": int(q.get("nitidez", 0)),
                    "rango": q.get("rango"),
                    "perfil": q.get("perfil"),
                    "ganancia_quiebre": float(q.get("ganancia", float("nan"))),
                })

            # Primero las confiables, después el resto del quiebre, y al final
            # Dentro de la zona el orden es POR ESTRECHEZ, no por r. Es el
            # ranking que se validó: mezclarle la correlación verificada lo
            # desordena, porque entre años vecinos de la zona la r difiere en
            # milésimas y esas milésimas son ruido, mientras que lo estrecho
            # del anillo en la cronología sí informa dónde pudo faltar uno.
            por_quiebre.sort(
                key=lambda x: (
                    x["confiable"],
                    x.get("origen") == "zona",
                    (x.get("estrechez", 0.0) if x.get("origen") == "zona"
                     else x["r_verificada"])),
                reverse=True)
            claves_q = {(x["anio"], x["delta"]) for x in por_quiebre}
            sugerencias = por_quiebre + [
                x for x in sugerencias
                if (x.get("anio"), x.get("delta")) not in claves_q]

            # Fuera las candidatas que EMPEORAN la correlación. Nadie las va a
            # elegir, y llenan la tabla de ruido que estorba para encontrar
            # las que sirven.
            def _mejora(x):
                d = x.get("delta_r")
                if d is None or not np.isfinite(d):
                    a, b = x.get("r_antes"), x.get("r_tras")
                    if a is None or b is None:
                        return True          # sin dato: no se descarta
                    d = b - a
                return d > 0
            utiles = [x for x in sugerencias if _mejora(x)]
            if utiles:
                sugerencias = utiles
            _hay_quiebre_confiable = any(x["confiable"] for x in por_quiebre)
            if informe is not None:
                _informe_zona = informe
        except Exception:
            pass

    # Un quiebre CONFIABLE manda sobre el diagnóstico por ventanas. El
    # diagnóstico agrupa ventanas de largo fijo y acierta el signo con menos
    # frecuencia; dejar que filtre por su `delta_sugerido` descartaría justo
    # la candidata que las pruebas muestran correcta en el 100% de los casos.
    if _hay_quiebre_confiable:
        return sugerencias, False

    if not diagnostico:
        return sugerencias, es_marginal

    tipo = diagnostico.get("diagnostico")

    # Con un desfase de TODA la serie, proponer insertar o quitar un anillo
    # suelto es engañoso: lo que corresponde es corregir el año base. Se
    # devuelven cero sugerencias para no mandar al usuario a buscar un anillo
    # que no falta.
    if tipo == "desfase_global":
        return [], True

    if tipo == "ambiguo":
        # Sin dirección segura NO se muestra una sola opción: eso induciría a
        # buscar en la madera justo lo contrario de lo que puede haber. Se
        # ofrecen las mejores candidatas de AMBOS sentidos, alternadas, para
        # que sea la madera la que decida.
        pos = [s for s in sugerencias if s.get("delta", 0) > 0]
        neg = [s for s in sugerencias if s.get("delta", 0) < 0]
        mezcla = []
        for i in range(max(len(pos), len(neg))):
            if i < len(pos):
                mezcla.append(pos[i])
            if i < len(neg):
                mezcla.append(neg[i])
        return (mezcla or sugerencias), True

    if tipo != "error_interno":
        return sugerencias, es_marginal

    delta_ok = diagnostico.get("delta_sugerido")
    anio_ref = diagnostico.get("anio_error")
    if not delta_ok or anio_ref is None:
        return sugerencias, es_marginal

    # COHERENCIA: nunca mostrar correcciones del signo CONTRARIO al que dice
    # el diagnóstico. Si el análisis concluyó que falta un anillo, ofrecer
    # "quitar un anillo" manda al usuario a buscar justo lo opuesto de lo que
    # hay en la madera, y eso destruye la confianza en la herramienta. Es
    # preferible mostrar menos opciones —o ninguna— que opciones contrarias.
    coherentes = [s for s in sugerencias if s.get("delta") == delta_ok]

    # Si la búsqueda global no encontró ninguna del signo correcto (pasa
    # cuando la mejora no supera el umbral general), se generan candidatas
    # explícitas alrededor del año localizado y se evalúan de verdad.
    if not coherentes and _eval_r is not None:
        generadas = []
        for anio in range(int(anio_ref) - 25, int(anio_ref) + 26):
            try:
                df2 = aplicar_correccion(problema, int(anio), int(delta_ok),
                                         anclaje=anclaje)
            except Exception:
                continue
            r_v = _eval_r(df2)
            if not np.isfinite(r_v):
                continue
            if np.isfinite(_r_base_g) and r_v <= _r_base_g:
                continue  # no mejora: no se ofrece
            generadas.append({
                "anio": int(anio), "delta": int(delta_ok),
                "tipo": (f"+{delta_ok} anillo(s)" if delta_ok > 0
                         else f"{delta_ok} anillo(s)"),
                "r_antes": float("nan"), "r_tras": r_v,
                "delta_r": float("nan"), "r_zona_antes": float("nan"),
                "r_zona_tras": float("nan"), "df_corregido": df2,
                "r_verificada": r_v,
                "plausibilidad": _plausibilidad_anillo_estrecho(
                    ref_years_g, ref_vals_g, anio, delta_ok)
                if ref_vals_g is not None else 1.0,
            })
        if generadas:
            generadas.sort(key=lambda s: s["r_verificada"] * s.get("plausibilidad", 1.0),
                           reverse=True)
            coherentes = generadas[:10]
            es_marginal = True  # ninguna superó el umbral global

    def _clave(sug):
        dist = abs(int(sug.get("anio", 0)) - int(anio_ref))
        cercania = max(0.0, 1.0 - dist / 60.0)
        base = sug.get("r_verificada")
        if base is None or not np.isfinite(base):
            base = sug.get("puntaje", sug.get("delta_r", 0.0))
        return base * (0.5 + cercania) * sug.get("plausibilidad", 1.0)

    coherentes = sorted(coherentes, key=_clave, reverse=True)
    return coherentes, es_marginal


def diagnosticar_datacion(serie_std: pd.Series, crono_std: pd.Series,
                           ventana: int = 40, paso: int = 5,
                           max_shift: int = 3, min_overlap: int = 20) -> dict:
    """Determina QUÉ TRAMO de la serie está bien fechado y dónde está el error.

    Es como trabaja un dendrocronólogo: en vez de probar correcciones a ciegas
    en toda la serie, primero se busca el tramo que ya calza con la cronología
    (el ancla) y se localiza el punto donde deja de calzar.

    Para cada ventana móvil se prueba la serie desplazada en varios años y se
    ve QUÉ DESFASE gana localmente. Con eso se distinguen tres situaciones:

    • Todas las ventanas prefieren desfase 0 → la serie está bien fechada.
    • Todas prefieren el mismo desfase k ≠ 0 → la serie entera está corrida:
      no falta un anillo en medio, sino que el año base está mal (o faltan
      anillos fuera del tramo medido).
    • Unas prefieren 0 y otras k → hay un error DENTRO de la serie, justo en
      la frontera. El tramo que prefiere 0 es el que está bien fechado, y por
      tanto el que debe quedar fijo: si es el tramo reciente se ancla la
      corteza, si es el antiguo se ancla la médula.

    Devuelve un diccionario con las ventanas, los tramos detectados, el
    diagnóstico, el anclaje recomendado y el año y signo del error.
    """
    a = pd.to_numeric(serie_std, errors="coerce").dropna().sort_index()
    b = pd.to_numeric(crono_std, errors="coerce").dropna().sort_index()
    vacio = {"ventanas": [], "tramos": [], "diagnostico": "sin_datos",
             "anclaje_sugerido": "corteza", "anio_error": None,
             "delta_sugerido": 0, "shift_global": 0, "mensaje": ""}
    if a.empty or b.empty:
        return vacio

    ya = a.index.to_numpy(np.int64)
    va = a.to_numpy(dtype=float)
    yb = b.index.to_numpy(np.int64)
    vb = b.to_numpy(dtype=float)

    def _r(y_desde, y_hasta, shift):
        m = (ya >= y_desde) & (ya <= y_hasta)
        if m.sum() < min_overlap:
            return np.nan, 0
        comun, ia, ib = np.intersect1d(ya[m] + shift, yb,
                                       assume_unique=True, return_indices=True)
        if len(comun) < min_overlap:
            return np.nan, len(comun)
        x = va[m][ia]
        y = vb[ib]
        return _est.pearson(x, y), len(comun)

    ini, fin = int(ya.min()), int(ya.max())
    # VENTANAS ADAPTATIVAS: una ventana fija de 40 años deja fuera cualquier
    # serie corta (una de 18 años no se podría analizar). La ventana se ajusta
    # al largo disponible: alrededor de un tercio de la serie, entre 12 y 50
    # años, con paso proporcional.
    largo = fin - ini + 1
    ventana = int(min(max(largo // 3, 12), max(ventana, 12)))
    paso = int(min(max(ventana // 8, 1), 10))
    min_overlap = int(min(max(ventana // 2, 8), min_overlap))
    mitad = ventana // 2
    ventanas = []
    # Los centros recorren TODA la serie, incluidos los extremos: la ventana se
    # recorta contra los bordes cuando hace falta. Antes iban de ini+mitad a
    # fin−mitad, así que los primeros y últimos 25 años nunca eran centro de
    # ventana. Con un error de datación cerca del final, el tramo reciente
    # —que es justamente el que está bien fechado— casi no se medía, el
    # desfase 0 apenas aparecía y el diagnóstico lo confundía con un desfase
    # de toda la serie.
    for centro in range(ini, fin + 1, max(1, paso)):
        desde = max(ini, centro - mitad)
        hasta = min(fin, centro + mitad)
        if hasta - desde + 1 < min_overlap:
            continue
        mejores = []
        for sh in range(-max_shift, max_shift + 1):
            r, n = _r(desde, hasta, sh)
            if np.isfinite(r):
                mejores.append((r, sh, n))
        if not mejores:
            continue
        r_best, sh_best, n_best = max(mejores, key=lambda t: t[0])
        r0 = next((r for r, sh, _ in mejores if sh == 0), np.nan)
        # Solo se considera "ganador" un desfase si mejora de forma clara:
        # diferencias mínimas son ruido, no evidencia de un error de datación.
        if np.isfinite(r0) and (r_best - r0) < 0.10:
            sh_best, r_best = 0, r0
        ventanas.append({"centro": int(centro), "shift": int(sh_best),
                         "r": float(r_best), "r0": float(r0) if np.isfinite(r0) else np.nan,
                         "n": int(n_best)})

    if not ventanas:
        return vacio

    # Agrupar ventanas consecutivas con el mismo desfase ganador
    tramos = []
    for v in ventanas:
        if tramos and tramos[-1]["shift"] == v["shift"]:
            tramos[-1]["fin"] = v["centro"]
            tramos[-1]["rs"].append(v["r"])
        else:
            tramos.append({"inicio": v["centro"], "fin": v["centro"],
                           "shift": v["shift"], "rs": [v["r"]]})
    for t in tramos:
        t["r_medio"] = float(np.nanmean(t["rs"]))
        del t["rs"]

    # Descartar tramos de una sola ventana: con ventanas de pocas décadas la
    # correlación es ruidosa y aparecen desfases "ganadores" espurios. Un
    # error de datación real se manifiesta de forma sostenida en varias
    # ventanas consecutivas, no en una suelta.
    # Al menos 3 ventanas consecutivas (2 pasos de extensión): con una o dos
    # el desfase ganador es inestable, sobre todo cerca de los extremos del
    # solape, y produce diagnósticos seguros pero equivocados.
    min_extension = max(2 * paso, 1)
    solidos = [t for t in tramos if (t["fin"] - t["inicio"]) >= min_extension]
    if not solidos:
        solidos = tramos

    # Cobertura de cada desfase (en años cubiertos por sus tramos sólidos)
    cobertura = {}
    for t in solidos:
        cobertura[t["shift"]] = cobertura.get(t["shift"], 0) + \
            (t["fin"] - t["inicio"] + paso)
    total = sum(cobertura.values()) or 1

    shifts = set(cobertura)
    res = dict(vacio)
    res["ventanas"] = ventanas
    res["tramos"] = solidos

    if shifts == {0}:
        res.update(diagnostico="bien_fechada", anio_error=None, delta_sugerido=0,
                   mensaje="La serie calza con la cronología en toda su extensión.")
        return res

    # Desfase dominante distinto de cero
    no_cero = {k: v for k, v in cobertura.items() if k != 0}
    k_dom = max(no_cero, key=no_cero.get) if no_cero else 0
    frac_dom = no_cero.get(k_dom, 0) / total
    frac_cero = cobertura.get(0, 0) / total

    # Si un desfase no nulo domina de forma abrumadora y prácticamente no hay
    # tramos bien fechados, la serie ENTERA está corrida. El umbral es
    # exigente a propósito: basta con que exista un tramo sólido a desfase 0
    # para que se trate como error interno, porque ese tramo es una fecha
    # firme y lo que hay que hacer es corregir el resto respecto de él.
    hay_tramo_bueno = any(t["shift"] == 0 for t in solidos)
    if frac_dom >= 0.80 and not hay_tramo_bueno:
        res.update(diagnostico="desfase_global", shift_global=k_dom,
                   delta_sugerido=(1 if k_dom < 0 else -1),
                   anio_error=None,
                   mensaje=(f"TODA la serie calza mejor desplazada {k_dom:+d} "
                            f"año(s) ({frac_dom*100:.0f}% de las ventanas). No es "
                            "un anillo faltante en medio: el año base está mal, o "
                            "falta(n) anillo(s) fuera del tramo medido (cerca de "
                            "la corteza o de la médula)."))
        return res

    buenos = [t for t in solidos if t["shift"] == 0]
    malos = [t for t in solidos if t["shift"] == k_dom]
    if not buenos or not malos:
        res.update(diagnostico="ambiguo",
                   mensaje=("El patrón de desfases no es concluyente: la señal "
                            "común es débil o hay más de un error."))
        return res

    # Tramos más EXTENSOS de cada clase (no el de mayor desfase, que suele ser ruido)
    ancla = max(buenos, key=lambda t: (t["fin"] - t["inicio"], t["r_medio"]))
    peor = max(malos, key=lambda t: (t["fin"] - t["inicio"], t["r_medio"]))

    # CONFIANZA: la dirección del error (si falta o sobra un anillo) se deduce
    # del desfase que prefiere el tramo desajustado. Si ese tramo correlaciona
    # mal, su desfase "ganador" es poco más que ruido y la dirección puede
    # salir invertida — algo mucho peor que no opinar, porque manda a buscar
    # justo lo contrario de lo que hay en la madera. En ese caso se señala la
    # zona sospechosa sin afirmar la dirección.
    r_peor = peor.get("r_medio", 0.0)
    r_ancla = ancla.get("r_medio", 0.0)
    evidencia_debil = (not np.isfinite(r_peor) or r_peor < 0.25 or
                       (np.isfinite(r_ancla) and r_ancla > 0 and
                        r_peor < 0.55 * r_ancla))
    if evidencia_debil:
        zona = f"{peor['inicio']}–{peor['fin']}"
        res.update(diagnostico="ambiguo", anio_error=None, delta_sugerido=0,
                   mensaje=(f"El tramo {ancla['inicio']}–{ancla['fin']} calza bien "
                            f"(r≈{r_ancla:.2f}), pero el tramo {zona} tiene una "
                            f"correlación demasiado baja (r≈{r_peor:.2f}) para "
                            "determinar con seguridad si falta o sobra un anillo. "
                            "Revisa la madera en ese tramo: puede haber un anillo "
                            "ausente, un falso anillo, o simplemente poca señal "
                            "común en esos años."))
        return res

    if peor["inicio"] > ancla["fin"]:
        anio_error = int((ancla["fin"] + peor["inicio"]) // 2)
        lado = "reciente"
    else:
        anio_error = int((peor["fin"] + ancla["inicio"]) // 2)
        lado = "antiguo"

    # AFINADO POR PUNTO DE QUIEBRE: la frontera entre tramos solo da una
    # resolución del ancho de la ventana. Acá se busca el año T que mejor
    # separa "antes de T calza con desfase k" de "desde T calza con desfase 0",
    # usando TODOS los datos de cada lado (no una ventana fija). Además se
    # devuelve el INTERVALO de años compatibles: con señal común débil el dato
    # no alcanza para un año único, y dar uno solo mandaría al usuario a
    # buscar donde no es.
    k_ancla = peor["shift"]
    perfil = {}
    z = lambda r: np.arctanh(np.clip(r, -0.999, 0.999))
    min_seg = int(min(max((fin - ini + 1) // 6, 6), 15))

    def _r_seg(mask, sh):
        if mask.sum() < min_seg:
            return np.nan, 0
        com, ia, ib = np.intersect1d(ya[mask] + sh, yb,
                                     assume_unique=True, return_indices=True)
        if len(com) < min_seg:
            return np.nan, 0
        x = va[mask][ia]
        y = vb[ib]
        if np.std(x) == 0 or np.std(y) == 0:
            return np.nan, 0
        return _est.pearson(x, y), len(com)

    lo = max(int(ya.min()), int(yb.min()))
    hi = min(int(ya.max()), int(yb.max()))
    antes_es_malo = (peor["fin"] <= ancla["inicio"])
    for T in range(lo + min_seg, hi - min_seg + 1):
        if antes_es_malo:
            r1, n1 = _r_seg(ya < T, k_ancla)
            r2, n2 = _r_seg(ya >= T, 0)
        else:
            r1, n1 = _r_seg(ya < T, 0)
            r2, n2 = _r_seg(ya >= T, k_ancla)
        if not (np.isfinite(r1) and np.isfinite(r2)) or (n1 + n2) == 0:
            continue
        perfil[T] = (n1 * z(r1) + n2 * z(r2)) / (n1 + n2)

    rango = None
    candidatos = []
    if perfil:
        t_best = max(perfil, key=perfil.get)
        mx = perfil[t_best]
        # Umbral del intervalo: se calibró con series reales (ACI044B contra
        # una cronología de 169 series, r≈0.61) para que el intervalo sea
        # informativo y siga conteniendo el año verdadero.
        compatibles = [t for t, v in perfil.items() if v >= mx - 0.03]
        anio_error = int(t_best)
        if compatibles:
            # El estimador tiende a situar el quiebre uno o dos años DESPUÉS
            # del anillo que falta (el primer año mal fechado ya "arrastra" al
            # anterior), así que se garantiza un margen mínimo alrededor del
            # punto estimado para que el año verdadero quede dentro.
            rango = (min(min(compatibles), anio_error - 4),
                     max(max(compatibles), anio_error + 4))

        # LISTA CORTA DE AÑOS CONCRETOS. El intervalo por sí solo puede ser
        # ancho, y mandar al usuario a revisar 25 años de madera no sirve de
        # mucho. Pero dentro de ese intervalo no todos los años son igual de
        # probables: un anillo que se omite al fechar es casi siempre uno
        # ESTRECHO. Se combinan las dos fuentes de información —el perfil del
        # punto de quiebre y lo estrecho que es cada año en la cronología— y
        # se devuelven los pocos años que hay que mirar en la madera.
        if compatibles and vb.size > 5:
            media_c = float(np.nanmean(vb))
            sd_c = float(np.nanstd(vb)) or 1.0
            rango_perf = (max(perfil.values()) - min(perfil.values())) or 1.0
            puntuados = []
            for t in compatibles:
                pos = np.searchsorted(yb, t)
                if pos >= yb.size or int(yb[pos]) != int(t):
                    continue
                # estrechez: cuántas desviaciones bajo la media está ese año
                estrechez = (media_c - float(vb[pos])) / sd_c
                verosim = (perfil[t] - min(perfil.values())) / rango_perf
                puntuados.append((t, verosim + 0.6 * max(estrechez, 0.0),
                                  float(vb[pos])))
            puntuados.sort(key=lambda x: -x[1])
            candidatos = [{"anio": int(t), "indice_crono": round(v, 3)}
                          for t, _, v in puntuados[:5]]
    res["rango_error"] = rango
    res["candidatos"] = candidatos

    # Si el tramo bien fechado es el RECIENTE, hay que dejar fija la corteza;
    # si es el ANTIGUO, dejar fija la médula.
    centro_ancla = (ancla["inicio"] + ancla["fin"]) / 2.0
    centro_serie = (ini + fin) / 2.0
    anclaje = "corteza" if centro_ancla >= centro_serie else "medula"

    delta = 1 if k_dom < 0 else -1
    res.update(diagnostico="error_interno", anio_error=anio_error,
               delta_sugerido=delta, anclaje_sugerido=anclaje,
               shift_global=k_dom,
               mensaje=(f"El tramo {ancla['inicio']}–{ancla['fin']} calza bien "
                        f"(r≈{ancla['r_medio']:.2f}) y el tramo "
                        f"{peor['inicio']}–{peor['fin']} calza mejor desplazado "
                        f"{k_dom:+d}.<br><b>Busca el anillo "
                        + (f"entre {rango[0]} y {rango[1]}" if rango
                           else f"hacia {anio_error}")
                        + "</b>"
                        + (("<br><b>Años más probables</b> (estrechos en la "
                            "cronología, revísalos primero): "
                            + ", ".join(str(c["anio"]) for c in candidatos))
                           if candidatos else f" (lo más probable, {anio_error})")
                        + ". "
                        + ("El intervalo es amplio porque la señal común con la "
                           "cronología es débil; con una cronología de más series "
                           "se estrecha. "
                           if (rango and (rango[1] - rango[0]) > 25) else "")
                        + f"Se ancla en "
                        f"{'corteza' if anclaje == 'corteza' else 'médula'} "
                        f"para no mover el tramo ya fechado."))
    return res


def buscar_correcciones(ref, problema, mitad_ventana, max_corr=MAX_CORRECCION,
                        anclaje="corteza",
                        transformar_ref=None, transformar_prob=None,
                        delta_r_minimo: float = 0.05,
                        max_fallback: int = 3):
    """Busca correcciones que mejoran la correlación global.

    Devuelve tupla **(sugerencias, es_marginal)**:
      • Si hay correcciones con Δr ≥ delta_r_minimo: devuelve esas (hasta 15) y
        es_marginal = False.
      • Si no hay correcciones significativas pero sí hay alguna mejora positiva:
        devuelve las mejores hasta `max_fallback` y es_marginal = True. Esto
        permite mostrar un "sanity check" al usuario en lugar de una lista vacía,
        con la advertencia de que son cambios dentro del ruido estadístico.
      • Si no hay ninguna mejora positiva: devuelve ([], False).

    delta_r_minimo: filtro de ruido. 0.05 es razonable; con series ya
    correctamente cofechadas las "mejoras" suelen ser 0.01-0.04 (ruido) y
    las correcciones reales suelen estar en 0.10+.
    """
    if transformar_ref is None:
        transformar_ref = lambda s: pd.to_numeric(s, errors="coerce").astype(float).dropna()
    if transformar_prob is None:
        transformar_prob = lambda s: pd.to_numeric(s, errors="coerce").astype(float).dropna()

    d_ref = transformar_ref(ref["Ancho_mm"])
    d_prob = transformar_prob(problema["Ancho_mm"])
    overlap_base = list(d_ref.index.intersection(d_prob.index))
    if len(overlap_base) < OVERLAP_MINIMO_ANALISIS:
        return [], False

    r_global_base = _r_pearson(d_ref.loc[overlap_base].values, d_prob.loc[overlap_base].values)
    if np.isnan(r_global_base):
        return [], False

    _, r_movil_base = _r_movil(d_ref, d_prob, overlap_base, mitad_ventana)

    # OPTIMIZACIÓN CLAVE (antes el programa se colgaba): todo el bucle de
    # candidatos se hace en numpy puro. Se transforma la serie UNA sola vez
    # (fuera del bucle) y cada corrección candidata se aplica sobre los
    # arreglos ya transformados, alineando con la referencia por año con
    # np.intersect1d. Nada de spline ni construcción de DataFrames por
    # candidato (eso era lo lento).
    ref_years = d_ref.index.to_numpy(np.int64)
    ref_vals = d_ref.to_numpy(dtype=float)
    prob_years = d_prob.index.to_numpy(np.int64)
    prob_vals = d_prob.to_numpy(dtype=float)
    prob_mean = float(np.nanmean(prob_vals)) if prob_vals.size else 0.0
    ref_min, ref_max = int(ref_years.min()), int(ref_years.max())

    ob_arr = np.asarray(overlap_base, dtype=np.int64)
    base_ref_ov = d_ref.loc[overlap_base].to_numpy(dtype=float)
    base_prob_ov = d_prob.loc[overlap_base].to_numpy(dtype=float)

    _anclar_corteza = str(anclaje).lower().startswith("cort")

    def _corr_np(anio, delta):
        """Aplica la corrección sobre (prob_years, prob_vals) en numpy,
        respetando el anclaje elegido, y devuelve (años, valores) ordenados."""
        yrs = prob_years.copy()
        vals = prob_vals.copy()
        a = int(anio)
        for _ in range(abs(delta)):
            if delta > 0:
                if _anclar_corteza:
                    yrs = np.where(yrs <= a, yrs - 1, yrs)
                else:
                    yrs = np.where(yrs >= a, yrs + 1, yrs)
                yrs = np.append(yrs, a)
                vals = np.append(vals, prob_mean)
            else:
                m = yrs != a
                yrs = yrs[m]
                vals = vals[m]
                if _anclar_corteza:
                    yrs = np.where(yrs < a, yrs + 1, yrs)
                else:
                    yrs = np.where(yrs > a, yrs - 1, yrs)
        o = np.argsort(yrs, kind="stable")
        return yrs[o], vals[o]

    resultados = []
    # Limitar los años a probar a la zona que puede afectar el solape con la
    # referencia (un año posterior a ref_max no cambia la correlación).
    anios_candidatos = [int(a) for a in problema.index
                        if ref_min - max_corr <= int(a) <= ref_max]
    for anio in anios_candidatos:
        for delta in range(-max_corr, max_corr + 1):
            if delta == 0:
                continue
            cyrs, cvals = _corr_np(anio, delta)
            common, iref, icorr = np.intersect1d(
                ref_years, cyrs, assume_unique=True, return_indices=True)
            if common.size < OVERLAP_MINIMO_ANALISIS:
                continue
            a_vals = ref_vals[iref]
            b_vals = cvals[icorr]
            r_global_tras = _r_pearson(a_vals, b_vals)
            if np.isnan(r_global_tras):
                continue
            delta_r = r_global_tras - r_global_base
            if delta_r <= 0:
                continue

            zmask = np.abs(common - anio) <= mitad_ventana
            r_zona_tras = np.nan
            if int(zmask.sum()) >= OVERLAP_MINIMO_GRAFICO:
                r_zona_tras = _r_pearson(a_vals[zmask], b_vals[zmask])
            zbmask = np.abs(ob_arr - anio) <= mitad_ventana
            r_zona_antes = np.nan
            if int(zbmask.sum()) >= OVERLAP_MINIMO_GRAFICO:
                r_zona_antes = _r_pearson(base_ref_ov[zbmask], base_prob_ov[zbmask])

            # Solo para las candidatas que mejoran: la serie CRUDA corregida
            # (barata, sin spline) que se guardará para aplicarla luego.
            df_corr = aplicar_correccion(problema, anio, delta, anclaje=anclaje)

            # PLAUSIBILIDAD BIOLÓGICA: los anillos que se omiten al fechar son
            # casi siempre los ESTRECHOS (años malos), no los anchos. Cuando
            # varios años dan una mejora de correlación parecida —cosa muy
            # habitual, porque desplazar la serie un año produce mejoras
            # similares en un tramo— la estadística sola no distingue cuál es.
            # Aquí se pondera cada candidato según lo estrecho que sea ese año
            # en la REFERENCIA (la cronología): un año marcadamente bajo la
            # media es un candidato mucho más creíble para un anillo faltante.
            plaus = _plausibilidad_anillo_estrecho(
                ref_years, ref_vals, anio, delta)

            resultados.append({
                "anio": int(anio), "delta": delta,
                "tipo": f"+{delta} anillo(s)" if delta > 0 else f"{delta} anillo(s)",
                "r_antes": r_global_base, "r_tras": r_global_tras,
                "delta_r": delta_r, "r_zona_antes": r_zona_antes,
                "r_zona_tras": r_zona_tras, "df_corregido": df_corr,
                "plausibilidad": plaus,
                "puntaje": delta_r * plaus,
            })

    # Ordenar por PUNTAJE (mejora de correlación × plausibilidad del año),
    # no solo por la mejora bruta.
    resultados.sort(key=lambda x: x.get("puntaje", x["delta_r"]), reverse=True)

    # Deduplicar correcciones solapadas (cerca del mismo año con mismo signo)
    filtrados, ocupados = [], []
    for r in resultados:
        solapado = any(
            abs(r["anio"] - oc["anio"]) <= 5 and np.sign(r["delta"]) == np.sign(oc["delta"])
            for oc in ocupados)
        if not solapado:
            filtrados.append(r)
            ocupados.append(r)

    # Separar en significativas y fallback marginal
    significativas = [r for r in filtrados if r["delta_r"] >= delta_r_minimo]
    if significativas:
        return significativas[:15], False
    return filtrados[:max_fallback], True


# =============================================================================
# MODO COFECHA
# =============================================================================

def aplicar_modo_cofecha(serie_mm, rigidez_spline=32, aplicar_log=True,
                          aplicar_ar=True, aplicar_first_diff=False):
    """Spline detrending + log + AR(1). Holmes (1983)."""
    s = pd.to_numeric(serie_mm, errors="coerce").astype(float).dropna()
    if len(s) < 10:
        return s.copy()

    valores = s.to_numpy(dtype=float)

    try:
        from scipy.interpolate import UnivariateSpline
        x = np.arange(len(valores), dtype=float)
        s_factor = max(
            np.var(valores) * len(valores) * (rigidez_spline / max(len(valores), 1)) ** 1.5,
            1e-3,
        )
        spl = UnivariateSpline(x, valores, s=s_factor)
        tendencia = spl(x)
        tendencia = np.where(tendencia <= 0, np.nanmean(valores), tendencia)
        valores = valores / tendencia
    except Exception as exc:
        logger.warning("Spline COFECHA falló: %s", exc)
        valores = valores / np.mean(valores)

    if aplicar_log:
        media = np.mean(valores)
        c_const = media / 6.0 if media > 0 else 0.001
        valores = np.log(np.maximum(valores + c_const, 1e-10))

    if aplicar_ar and len(valores) > 4:
        c = valores - np.mean(valores)
        if np.std(c) > 0:
            phi = _est.pearson(c[1:], c[:-1])
            if np.isnan(phi):
                phi = 0.0
            phi = float(np.clip(phi, -0.99, 0.99))
            residuales = c.copy()
            residuales[1:] = c[1:] - phi * c[:-1]
            valores = residuales

    if aplicar_first_diff and len(valores) > 1:
        return _est.diferencias_anuales(pd.Series(valores, index=s.index))

    return pd.Series(valores, index=s.index)

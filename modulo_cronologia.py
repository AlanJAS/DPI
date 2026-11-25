"""Núcleo científico de cronologías y estandarización, sin interfaz gráfica."""

import numpy as np
import pandas as pd
from modulo_estadistica import (
    serie_anual, agrupar_por_arbol, rbar_entre_arboles, correlaciones_pares, calcular_eps, pearson,
    BIWEIGHT_C, media_biweight,
)


def _bloques_anuales(serie):
    s = serie_anual(serie)
    cortes = np.flatnonzero(np.diff(s.index.to_numpy()) != 1) + 1
    return [s.iloc[a:b] for a, b in zip([0, *cortes], [*cortes, len(s)]) if a < b]


# Adaptador histórico: el cálculo reside únicamente en modulo_estadistica.
def _biweight_mean(values, c: float = BIWEIGHT_C, minimo: int = 6) -> float:
    return media_biweight(values, c=c, minimo=minimo)


from scipy.linalg import solveh_banded


def _spline_cook(y: np.ndarray, nyrs: float = 32.0, f: float = 0.5) -> np.ndarray:
    """Spline cúbico de suavizado de Cook & Peters (1981).

    Es el spline estándar de la dendrocronología (ARSTAN, COFECHA, dplR): se
    define por su RESPUESTA DE FRECUENCIA, no por un parámetro arbitrario de
    suavizado. Con los valores por defecto, una oscilación de `nyrs` años
    conserva el 50% de su amplitud; las más rápidas se atenúan y las más
    lentas pasan casi intactas. Eso es justo lo que se quiere para quitar la
    tendencia de crecimiento por edad conservando la señal climática.

    Minimiza  Σ(yᵢ−gᵢ)² + λ·∫g″², resuelto por el algoritmo de Reinsch:
      (R + λ·QᵀQ)·c = Qᵀy   →   g = y − λ·Q·c
    con Q las segundas diferencias y R tridiagonal (2/3 en la diagonal,
    1/6 fuera). Para datos equiespaciados la respuesta es
      H(ω) = 1 / (1 + λ·48·sin⁴(ω/2)/(2+cos ω))
    y de ahí se despeja λ para que H(2π/nyrs) = f.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return np.full(n, float(np.mean(y)) if n else 0.0)

    nyrs = max(float(nyrs), 2.5)  # por debajo de ~2 años no hay señal muestreable
    f = min(max(float(f), 1e-6), 1.0 - 1e-6)
    w = 2.0 * np.pi / nyrs
    cw = np.cos(w)
    lam = (1.0 / f - 1.0) * (2.0 + cw) / (12.0 * (1.0 - cw) ** 2)

    m = n - 2
    # A = R + λ·QᵀQ: simétrica pentadiagonal (Toeplitz para paso constante)
    ab = np.zeros((3, m))
    if m > 2:
        ab[0, 2:] = lam
    if m > 1:
        ab[1, 1:] = 1.0 / 6.0 - 4.0 * lam
    ab[2, :] = 2.0 / 3.0 + 6.0 * lam

    qty = y[:-2] - 2.0 * y[1:-1] + y[2:]
    try:
        c = solveh_banded(ab, qty, lower=False)
    except Exception:
        return np.full(n, float(np.mean(y)))

    # (Q·c)ᵢ = cᵢ − 2cᵢ₋₁ + cᵢ₋₂  (c extendido con ceros en los bordes)
    cp = np.zeros(n + 2)
    cp[2:2 + m] = c
    qc = cp[2:n + 2] - 2.0 * cp[1:n + 1] + cp[0:n]
    return y - lam * qc


RIGIDEZ_SPLINE_DEFECTO = 32  # rigidez del spline de detrend (años, estilo COFECHA)


def _fit_trend(values: np.ndarray, metodo: str, ventana_mm: int | None = None,
               rigidez: int | None = None) -> np.ndarray:
    """Ajusta tendencia a la serie según el método indicado.

    Parameters
    ----------
    values : array
        Valores de la serie.
    metodo : str
        Método de ajuste: 'spline', 'negexp', 'linear', 'media_movil', 'mean'.
    ventana_mm : int, opcional
        Ventana (en años) para 'media_movil'. Si None, usa el 10% del largo
        de la serie (estilo ARSTAN). Solo aplica si metodo='media_movil'.
    """
    from scipy.interpolate import UnivariateSpline
    from scipy.optimize import curve_fit

    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    m = np.isfinite(y)
    if m.sum() < 3:
        return np.full_like(y, np.nanmean(y[m]) if m.any() else np.nan, dtype=float)

    x_fit = x[m]
    y_fit = y[m]
    metodo = (metodo or "spline").lower()

    if metodo in {"raw", "none", "ninguno"}:
        return np.full_like(y, np.nanmean(y_fit), dtype=float)
    if metodo in {"mean", "media"}:
        return np.full_like(y, np.nanmean(y_fit), dtype=float)
    if metodo in {"linear", "lineal"}:
        p = np.polyfit(x_fit, y_fit, 1)
        return np.polyval(p, x)
    if metodo in {"negexp", "negative_exponential", "exponencial", "exp"}:
        def f(t, a, b, c):
            return a * np.exp(-b * t) + c
        # Opción 1 de ARSTAN: «neg expon curve (k>0), no = opt 4».
        #
        # Verificado contra una corrida real, leyendo su tabla de ajustes por
        # serie. Dos cosas que había que entender bien:
        #
        # 1. La ASÍNTOTA debe ser POSITIVA (d > 0 en y = a·exp(−b·t) + d). Un
        #    árbol no tiende a un ancho negativo.
        # 2. Cuando el ajuste no cumple, el respaldo de ARSTAN es su OPCIÓN 4,
        #    que es «linear regression (any slope)» — NO la media horizontal,
        #    que es su opción 6. Es un detalle que se presta a confusión y
        #    cambia por completo el resultado.
        #
        # Y lo que más importa: el ajuste exponencial **falla mucho más
        # seguido de lo que uno supondría**. En la corrida de referencia falló
        # en prácticamente todas las series de la colección, así que ARSTAN
        # terminó usando regresión lineal en casi todas. Nuestro ajuste, en
        # cambio, «tenía éxito» siempre porque el optimizador empuja los
        # parámetros contra el borde y devuelve una exponencial degenerada,
        # casi plana. Por eso se rechaza explícitamente el caso b ≈ 0: una
        # exponencial que no decae es una recta disfrazada.
        a0 = max(float(np.nanmax(y_fit) - np.nanmin(y_fit)), 1e-3)
        b0 = 0.01
        c0 = max(float(np.nanmin(y_fit)), 1e-6)

        def _recta():
            p = np.polyfit(x_fit, y_fit, 1)
            return np.polyval(p, x)

        try:
            popt, _ = curve_fit(
                f, x_fit, y_fit, p0=(a0, b0, c0), maxfev=20000,
                bounds=([0.0, 0.0, 0.0], [np.inf, 10.0, np.inf]),
            )
            a_f, b_f, d_f = popt
            tend = f(x, *popt)
            # La asíntota debe ser ESTRICTAMENTE positiva: la opción de
            # ARSTAN dice «neg expon curve (k>0)», y el estricto es literal.
            #
            # El optimizador, con el límite inferior en cero, empuja la
            # asíntota contra ese borde y devuelve un ajuste que técnicamente
            # converge pero que ARSTAN rechaza. Verificado con una corrida
            # suya sobre 19 series: aceptó UNA, COS140B, con asíntota 0,693;
            # las seis que nosotros aceptábamos de más tenían todas asíntota
            # 0,000 exacto, o sea pegadas al borde.
            #
            # El umbral es relativo a la media de la serie, no absoluto,
            # porque una asíntota de 0,001 mm significa cosas distintas en
            # una serie de 0,3 mm y en una de 3 mm.
            _piso_d = 1e-4 * float(np.nanmean(y_fit)) if np.isfinite(
                np.nanmean(y_fit)) else 0.0
            if (not np.all(np.isfinite(tend)) or b_f <= 1e-4
                    or a_f <= 1e-6 or d_f <= _piso_d):
                return _recta()
            return tend
        except Exception:
            return _recta()

    if metodo in {"spline", "spl", "cubic_spline"}:
        try:
            # Spline cúbico de suavizado de Cook & Peters (1981), el estándar
            # de la dendrocronología (ARSTAN/COFECHA/dplR): definido por su
            # respuesta de frecuencia (50% a RIGIDEZ_SPLINE_DEFECTO años).
            #
            # Antes se usaba UnivariateSpline de scipy con un parámetro `s`
            # heurístico, que no equivale al spline dendrocronológico: dejaba
            # estructura distinta en los residuos y (con s = len·var·0.8)
            # podía degenerar en una cúbica que CRUZABA CERO en los extremos,
            # haciendo explotar el índice serie/tendencia.
            # La rigidez llega desde arriba: la opción 1 de la corrida.
            # Antes se usaba siempre la constante del módulo, así que cambiar
            # el spline en la interfaz no alteraba el resultado en absoluto.
            #
            # El spline se ajusta sobre el LOGARITMO del ancho y después se
            # exponencia. Así la curva es positiva por construcción y no hace
            # falta ninguna guarda.
            #
            # Ajustado en escala lineal, el spline sobrepasa hacia abajo en los
            # extremos de la serie y puede cruzar cero. La guarda que había
            # solo atrapaba los valores <= 0, así que un valor diminuto pero
            # POSITIVO pasaba y el índice explotaba: en DBC200B la tendencia
            # bajaba a 0.00094 en 2023 y el índice de ese año llegaba a 268,
            # cuando un índice normal ronda 1. Eso hundía la correlación de la
            # serie con la maestra a -0.132 donde COFECHA da +0.434.
            #
            # Medido sobre las 36 series de cos8.rwl contra la corrida real de
            # COFECHA, el cambio mejora todo a la vez:
            #
            #                        err medio  err máx  intercorrelación
            #   escala lineal          0.0646    0.566        0.425
            #   sobre el logaritmo     0.0519    0.131        0.455
            #                                            (COFECHA .463)
            #
            # y el índice máximo de toda la colección baja de 265 a 4.4.
            # Spline en ESCALA LINEAL, con piso en el 10 % de la media.
            #
            # El spline de Cook se ajusta a la serie cruda: así lo hace su
            # Fortran original (capsf.f95, que verificamos idéntico al
            # nuestro) y así lo usa COFECHA. Antes lo ajustábamos sobre el
            # logaritmo para garantizar positividad, y eso mejoraba mientras
            # el AR estaba mal puesto; corregido el AR, la escala lineal pasa
            # a ganar en todo.
            #
            # El piso resuelve el problema de la escala lineal: el spline
            # sobrepasa hacia abajo en los extremos y puede acercarse a cero,
            # disparando el índice (en DBC200B llegaba a 268 con un valor de
            # tendencia de 0,00094). Ninguna curva de crecimiento real baja al
            # 10 % de la media de su serie.
            #
            # El 10 % no es arbitrario: se barrió contra la corrida real de
            # COFECHA sobre cos8.rwl.
            #
            #   piso   maestra   error   DBC200B
            #   0.05    0.9549   0.0518    0.360   <- choca con la guarda del 5 %
            #   0.10    0.9709   0.0359    0.425
            #   0.15    0.9690   0.0381    0.421
            #   0.25    0.9647   0.0416    0.440
            #
            # Con 0.05 o menos el valor recortado queda por debajo del umbral
            # de la guarda de `_detrend_serie_indice`, que entonces descarta la
            # curva entera y usa la media: por eso esas filas coinciden con el
            # respaldo total. El 10 % deja las dos protecciones sin pisarse.
            _y = np.asarray(y_fit, dtype=float)
            _sp = np.asarray(_spline_cook(
                _y, nyrs=float(rigidez or RIGIDEZ_SPLINE_DEFECTO), f=0.5))
            _pos = _y[_y > 0]
            _piso = 0.10 * float(np.nanmean(_pos)) if _pos.size else 1e-6
            tend = np.maximum(_sp, _piso)
            if len(tend) != len(x):
                tend = np.interp(x, x_fit, tend)
            # Guarda de positividad: el crecimiento no puede ser negativo, así
            # que cualquier tramo de tendencia ≤0 (o no finito) se reemplaza por
            # la media para no hacer explotar el índice al dividir.
            media = float(np.nanmean(y_fit))
            tend = np.where(np.isfinite(tend) & (tend > 0), tend, media)
            return tend
        except Exception:
            p = np.polyfit(x_fit, y_fit, 1)
            return np.polyval(p, x)
    if metodo in {"media_movil", "moving_average", "ma"}:
        # Si el usuario especifica ventana, usar esa. Si no, default ARSTAN-like.
        if ventana_mm is not None and ventana_mm >= 3:
            w = int(ventana_mm)
        else:
            w = max(3, int(round(len(y_fit) * 0.10)))
        if w % 2 == 0:
            w += 1
        return pd.Series(y).rolling(window=w, center=True, min_periods=1).mean().to_numpy(dtype=float)
    p = np.polyfit(x_fit, y_fit, 1)
    return np.polyval(p, x)


def _detrend_serie_indice(serie_mm: pd.Series, metodo: str,
                           ventana_mm: int | None = None,
                           rigidez: int | None = None) -> pd.Series:
    bloques = _bloques_anuales(serie_mm)
    if len(bloques) > 1:
        return pd.concat([_detrend_serie_indice(b, metodo, ventana_mm=ventana_mm, rigidez=rigidez) for b in bloques])
    s = serie_anual(serie_mm)
    if s.empty:
        return s.copy()
    if (metodo or "").lower() in {"raw", "none", "ninguno"}:
        return s.copy()
    tendencia = _fit_trend(s.to_numpy(dtype=float), metodo,
                           ventana_mm=ventana_mm, rigidez=rigidez)
    tendencia = pd.Series(tendencia, index=s.index, dtype=float)
    # Guarda de positividad, al estilo de ARSTAN y dplR: si ALGÚN valor de la
    # curva sale ≤ 0 o no finito, se descarta la curva ENTERA y se usa la
    # media de la serie. Es el «dirty dog» que ARSTAN pide graficar.
    #
    # Antes se parchaban solo los años malos, y eso dejaba una serie cuyo
    # índice significa una cosa en un tramo y otra en el resto: unos años
    # divididos por su tendencia local y otros por la media global. Peor aún,
    # el parche solo atrapaba los valores ≤ 0, así que una tendencia diminuta
    # pero positiva pasaba y disparaba el índice (en DBC200B llegó a 268).
    #
    # Reemplazar la curva completa es más honesto: la serie queda
    # consistentemente sin detrending, y el diálogo de curvas negativas de la
    # pestaña de cronología avisa y deja elegir otro método.
    # El umbral no es cero sino el 5 % de la media de la serie. dplR solo
    # comprueba <= 0, pero una tendencia POSITIVA y diminuta hace el mismo
    # daño: en QLH026a el ajuste lineal nunca cruza cero y aun así produce un
    # índice de 43,5, cuando la razón entre el anillo más ancho y la media es
    # apenas 4,6. Ninguna curva de crecimiento real baja al 5 % de la media
    # de la serie, así que llegar ahí es señal de que el ajuste se rompió.
    tv = tendencia.to_numpy(dtype=float)
    media_s = float(np.nanmean(s.to_numpy(dtype=float)))
    piso = 0.05 * media_s if np.isfinite(media_s) and media_s > 0 else 0.0
    if not np.all(np.isfinite(tv)) or np.any(tv <= piso):
        tendencia = pd.Series(np.full(len(tendencia), media_s),
                              index=tendencia.index)
    idx = (s / tendencia).replace([np.inf, -np.inf], np.nan).dropna()
    return idx


ORDEN_AR_MAXIMO = 3  # orden máximo del modelo AR (COFECHA usa hasta 3)


def _ajustar_ar_yule_walker(x: np.ndarray, p: int):
    """Ajusta un AR(p) por Yule-Walker (recursión de Levinson-Durbin).

    Devuelve (coeficientes phi, varianza residual). `x` debe venir centrado.
    """
    n = len(x)
    if p <= 0:
        return np.array([]), float(np.var(x))
    # Autocovarianzas r[0..p]
    r = np.array([np.dot(x[k:], x[:n - k]) / n if k else np.dot(x, x) / n
                  for k in range(p + 1)])
    if r[0] <= 0:
        return np.zeros(p), 0.0
    phi = np.zeros(p)
    v = r[0]
    for k in range(1, p + 1):
        # Coeficiente de reflexión
        acum = r[k] - np.dot(phi[:k - 1], r[1:k][::-1]) if k > 1 else r[1]
        if v <= 0:
            break
        kappa = acum / v
        nuevo = phi[:k - 1] - kappa * phi[:k - 1][::-1] if k > 1 else np.array([])
        phi[:k - 1] = nuevo
        phi[k - 1] = kappa
        v *= (1.0 - kappa * kappa)
        if v <= 0:
            v = 1e-12
            break
    return phi[:p], float(v)


def _seleccionar_orden_ar(x: np.ndarray, max_orden: int = ORDEN_AR_MAXIMO) -> int:
    """Elige el orden del AR minimizando el AIC, como hace COFECHA.

    COFECHA ajusta modelos autorregresivos de distinto orden y se queda con
    el mejor según el criterio de Akaike (la columna 'AR()' de su salida).
    DPI usaba AR(1) fijo para todas las series, lo que dejaba autocorrelación
    sin remover en las series que necesitan orden mayor.
    """
    n = len(x)
    max_orden = int(max(0, min(max_orden, n // 10, 10)))
    if n < 20 or max_orden < 1:
        return min(1, max_orden)
    # El orden mínimo es 1, no 0: cuando el modelo autorregresivo está
    # activado, COFECHA nunca informa orden 0 — sus corridas con AR dan 1, 2
    # o 3, y solo la corrida SIN AR muestra 0. Permitir el 0 dejaba series sin
    # blanquear que en COFECHA sí lo están.
    # CRITERIO: BIC, no AIC.
    #
    # Comparado contra los órdenes AR que informa COFECHA en su Parte 7 —un
    # entero, así que la coincidencia no admite interpretación— sobre las 36
    # series de cos8.rwl:
    #
    #     BIC   33/36  (92 %)
    #     PACF  32/36  (89 %)
    #     AICc  25/36  (69 %)
    #     AIC   24/36  (67 %)
    #     FPE   24/36  (67 %)
    #
    # El BIC penaliza los parámetros con log(n) en vez de 2, así que prefiere
    # modelos más simples. Coincide con lo que se ve en COFECHA: de sus 36
    # series, 30 salen con orden 1 y solo 2 llegan a 3.
    mejor_orden, mejor_pun = 1, np.inf
    for p in range(1, max_orden + 1):
        _, v = _ajustar_ar_yule_walker(x, p)
        if not np.isfinite(v) or v <= 0:
            continue
        pun = n * np.log(v) + p * np.log(n)
        if pun < mejor_pun - 1e-9:
            mejor_pun, mejor_orden = pun, p
    return mejor_orden


def _ajustar_ar_burg(x: np.ndarray, p: int):
    """Coeficientes autorregresivos por el método de Burg.

    Es el que usa ARSTAN. Verificado despejando sus coeficientes desde los
    residuos por serie de una corrida real, sobre tres series:

        serie      ARSTAN   Yule-Walker   mín. cuad.     Burg
        COS088A    0.7893      0.7798       0.7888      0.7894
        COS088B    0.7382      0.7365       0.7455      0.7412
        COS305A    0.5083      0.5058       0.5086      0.5082

        error medio            0.00456      0.00273     0.00106

    Burg minimiza la suma de los errores de predicción hacia adelante y hacia
    atrás, en vez de resolver las ecuaciones de Yule-Walker sobre las
    autocorrelaciones muestrales. Con series cortas la diferencia se nota,
    porque Yule-Walker subestima la persistencia.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n <= p or p < 1:
        return np.zeros(max(p, 0)), float(np.var(x)) if n else 0.0
    f = x.copy()
    b = x.copy()
    a = []
    v = float(np.dot(x, x) / n)
    for m in range(p):
        num = 2.0 * float(np.dot(f[m + 1:], b[m:-1]))
        den = float(np.dot(f[m + 1:], f[m + 1:]) + np.dot(b[m:-1], b[m:-1]))
        k = num / den if den > 0 else 0.0
        a = [ai - k * aj for ai, aj in zip(a, a[::-1])] + [k] if a else [k]
        ff = f[m + 1:] - k * b[m:-1]
        bb = b[m:-1] - k * f[m + 1:]
        f = np.concatenate([f[:m + 1], ff])
        b = np.concatenate([b[:m + 1], bb])
        v *= (1.0 - k * k)
    return np.asarray(a, dtype=float), max(v, 1e-12)


def _residualizar_indice(indice: pd.Series, max_orden: int | None = None,
                          devolver_orden: bool = False, orden_fijo: int | None = None):
    """Quita la autocorrelación del índice con un modelo AR.

    El orden se elige automáticamente por AIC (como COFECHA). Antes se usaba
    siempre AR(1), lo que dejaba autocorrelación residual en las series que
    requieren orden 2 o 3.
    """
    bloques = _bloques_anuales(indice)
    if len(bloques) > 1:
        resultados = [_residualizar_indice(b, max_orden, True, orden_fijo) for b in bloques]
        resid = pd.concat([r for r, _ in resultados])
        orden = max(p for _, p in resultados)
        return (resid, orden) if devolver_orden else resid
    s = serie_anual(indice)
    if len(s) < 4:
        return (s.copy(), 0) if devolver_orden else s.copy()
    c = s - s.mean()
    x = c.to_numpy(dtype=float)
    if np.std(x) == 0:
        return (s.copy(), 0) if devolver_orden else s.copy()

    if max_orden is None:
        max_orden = ORDEN_AR_MAXIMO
    # `orden_fijo` viene del modelo AGRUPADO al modo de ARSTAN: un solo orden
    # para todas las series de la colección. Si no viene, se elige por serie.
    p = (int(orden_fijo) if orden_fijo
         else _seleccionar_orden_ar(x, max_orden))
    if p <= 0:
        resid_v = x.copy()
    else:
        # Burg, no Yule-Walker: es el estimador de ARSTAN. Ver _ajustar_ar_burg.
        phi, _ = _ajustar_ar_burg(x, p)
        # RETROPRONÓSTICO de los p valores anteriores al inicio.
        #
        # ARSTAN no deja los primeros p años sin modelar: estima los valores
        # previos con el mismo modelo AR, reflejando la serie, y así calcula
        # un residuo para TODOS los años. Verificado contra los residuos por
        # serie de una corrida real: sin retropronóstico, nuestro primer año
        # quedaba con el índice crudo (1,855 frente a su 1,327) y, peor, ese
        # valor entraba en la media de recentrado y desplazaba la serie
        # ENTERA unas tres milésimas. Con retropronóstico, los tres primeros
        # años quedan a menos de 0,007 y el resto coincide dentro del redondeo.
        prev = np.empty(p, dtype=float)
        for i in range(p):
            j = min(i, len(x) - 1)
            prev[p - 1 - i] = float(np.dot(phi[:1], [x[j]])) if p == 1 else x[j]
        ext = np.concatenate([prev, x])
        resid_v = x.copy()
        for t in range(len(x)):
            hist = ext[t:t + p][::-1]
            resid_v[t] = x[t] - float(np.dot(phi, hist))

    resid = pd.Series(resid_v, index=s.index)
    # Se devuelve el nivel de la serie ORIGINAL, no 1.0.
    #
    # Es lo que hace dplR en `ar.func`: `y <- ar1$resid + ar1$x.mean`, o sea
    # que a los residuos les suma la media de la serie de entrada. DPI sumaba
    # 1.0 fijo. Para la correlación da lo mismo —es un desplazamiento— pero
    # NO da lo mismo para el logaritmo que viene después, porque log(x + m/6)
    # no es lineal: desplazar la serie antes de aplicarlo cambia los valores
    # de forma no afín.
    #
    # Medido contra las 136 correlaciones por segmento de la Parte 5 de
    # COFECHA: el sesgo baja de -0.0206 a -0.0176 y la desviación media de
    # 0.0750 a 0.0734.
    resid = resid - resid.mean() + float(s.mean())
    return (resid, p) if devolver_orden else resid


def rigidez_efectiva(valor, n_anios: int, minima: int = 0) -> float:
    """Traduce la especificación de rigidez de ARSTAN a años.

    ARSTAN admite dos formas de pedir un spline, y la segunda no existía en DPI:

      · **Positiva** — años. `32` es un corte del 50 % a 32 años.
      · **Negativa** — PORCENTAJE DEL LARGO DE LA SERIE. `-75` es un corte al
        50 % en el 75 % del largo de cada serie, así que una serie de 400
        anillos recibe un spline de 300 años y una de 100, uno de 75.

    La forma negativa es la que permite tratar series de distinto largo de
    manera comparable: el filtro se adapta a cada una en vez de imponer el
    mismo corte a todas.

    `minima` es la rigidez mínima de ARSTAN: el spline nunca baja de ese valor.
    Sirve para no ajustar curvas muy flexibles a series cortas, que las dejaría
    con una estructura de persistencia distinta a la de las largas.
    """
    # Los métodos que no son spline no usan rigidez; se acepta None.
    if valor is None:
        return float(max(minima, 5.0)) if minima else 32.0
    v = float(valor)
    rig = (abs(v) / 100.0) * float(n_anios) if v < 0 else v
    if minima and minima > 0:
        rig = max(rig, float(minima))
    return max(rig, 5.0)


def estabilizar_varianza(idx: pd.Series, rigidez=64,
                          rigidez_minima: int = 0) -> pd.Series:
    """Estabiliza la varianza al modo de ARSTAN.

    El manual describe el procedimiento con precisión, y no es obvio: se
    normaliza la serie a media cero, se voltean las desviaciones negativas a
    positivas *anotando cuáles eran*, se ajusta un spline a esa serie de
    valores absolutos, se divide cada desviación por su valor del spline, se
    devuelven los signos y por último se suma de vuelta la media.

    Sirve cuando la varianza de una serie cambia mucho en el tiempo —algo
    propio de ciertos sitios, especies o árboles individuales—, porque si no,
    los tramos de varianza alta dominan la cronología.

    LA RIGIDEZ ES UN COMPROMISO, y por eso queda configurable. Medido sobre
    seis series largas de ciprés, como razón entre la desviación máxima y la
    mínima en ventanas de 60 años (1,00 sería varianza perfectamente estable):

        sin estabilizar   2,15
        spline 128 años   1,56
        spline  64 años   1,39   <- valor por omisión
        spline  32 años   1,29
        spline  20 años   1,25

    Más flexible estabiliza mejor, pero también aplana amplitudes que pueden
    ser reales: una década genuinamente extrema queda rebajada junto con el
    artefacto. 64 años reduce el desequilibrio a la mitad sin llegar a eso.
    """
    v = pd.to_numeric(idx, errors="coerce").dropna().astype(float)
    if len(v) < 12:
        return idx
    media = float(v.mean())
    desv = v.to_numpy() - media
    signos = np.sign(desv)
    absol = np.abs(desv)
    rig = rigidez_efectiva(rigidez, len(v), rigidez_minima)
    try:
        curva = np.asarray(_spline_cook(absol, nyrs=rig, f=0.5), dtype=float)
    except Exception:
        return idx
    # Piso proporcional: donde la curva se acerca a cero la división explota,
    # igual que en el detrending.
    piso = 0.10 * float(np.mean(absol[absol > 0])) if np.any(absol > 0) else 1e-6
    curva = np.maximum(curva, max(piso, 1e-9))
    fuera = signos * (absol / curva)
    # El manual dice «se suma de vuelta la media», pero dividir por la curva de
    # desviaciones absolutas deja la serie en unidades de esa desviación local,
    # no en unidades de índice: la desviación típica salta de ~0,23 a ~1,28.
    # Para que la cronología siga siendo comparable, se reescala al mismo
    # desvío que tenía antes. Lo que se elimina es la VARIACIÓN de la varianza
    # en el tiempo, que es el objetivo; la escala global se conserva.
    sd0 = float(np.std(desv))
    sd1 = float(np.std(fuera))
    if sd1 > 0 and sd0 > 0:
        fuera = fuera * (sd0 / sd1)
    return pd.Series(fuera + media, index=v.index)


def detrendar_para_cronologia(serie_mm: pd.Series,
                               metodo1: str = "spline",
                               rigidez1=32,
                               metodo2: str | None = None,
                               rigidez2=-128,
                               ventana_mm: int | None = None,
                               rigidez_minima: int = 0,
                               por_resta: bool = False,
                               log_previo: bool = False,
                               estabilizar: bool = False,
                               rigidez_estab=64,
                               normalizar: bool = False) -> pd.Series:
    """Detrending completo al modo de ARSTAN, incluido el DOBLE detrending.

    El doble detrending es el VALOR POR OMISIÓN de ARSTAN —su configuración
    inicial es «1 & 128»: exponencial negativa y después spline de 128 años— y
    DPI solo hacía uno. El manual explica por qué importa: la exponencial
    ajusta bien el tercio inicial de una serie, pero «hacia la mitad y el final
    puede ir muchas décadas casi enteramente por encima o por debajo del
    crecimiento real», dejando tramos largos de índices altos o bajos. El
    segundo ajuste, más rígido, corrige ese desvío sin tocar las frecuencias
    de interés.

    Orden de las operaciones, el mismo del manual:

      1. Logaritmo, sumando un sexto de la media (opcional, antes de ajustar)
      2. Primer ajuste e índices
      3. Segundo ajuste sobre esos índices e índices otra vez (opcional)
      4. Estabilización de varianza (opcional)
      5. Normalización a varianza 1 (opcional)

    `por_resta` cambia el índice de división a sustracción: ARSTAN permite las
    dos, y con series log-transformadas la resta es lo natural.
    """
    s = pd.to_numeric(serie_mm, errors="coerce").dropna().astype(float)
    if len(s) < 8:
        return s

    if log_previo:
        m = float(s.mean())
        c = m / 6.0 if m > 0 else 1e-3
        s = pd.Series(np.log(np.maximum(s.to_numpy() + c, 1e-10)), index=s.index)

    # Con la serie en logaritmos los valores pueden ser negativos con todo
    # derecho, así que la guarda de positividad de `_fit_trend` —pensada para
    # anchos en milímetros— no corresponde: descartaría curvas correctas.
    espacio_log = bool(log_previo)

    def _un_paso(x: pd.Series, metodo: str, rigidez) -> pd.Series:
        rig = rigidez_efectiva(rigidez, len(x), rigidez_minima)
        xv = x.to_numpy(dtype=float)
        if espacio_log and metodo == "spline":
            tend = np.asarray(_spline_cook(xv, nyrs=rig, f=0.5), dtype=float)
        elif espacio_log and metodo in ("media", "media_movil"):
            tend = (np.full_like(xv, float(np.nanmean(xv)))
                    if metodo == "media"
                    else np.asarray(_fit_trend(xv, metodo,
                                               ventana_mm=ventana_mm,
                                               rigidez=rig), dtype=float))
        else:
            tend = np.asarray(_fit_trend(xv, metodo, ventana_mm=ventana_mm,
                                         rigidez=rig), dtype=float)
        if por_resta:
            return pd.Series(xv - tend, index=x.index)
        piso = 0.10 * float(np.nanmean(x[x > 0])) if np.any(x > 0) else 1e-9
        return pd.Series(x.to_numpy(dtype=float) / np.maximum(tend, piso),
                         index=x.index)

    idx = _un_paso(s, metodo1, rigidez1)
    if metodo2:
        idx = _un_paso(idx, metodo2, rigidez2)

    if estabilizar:
        idx = estabilizar_varianza(idx, rigidez_estab, rigidez_minima)

    if normalizar:
        sd = float(idx.std())
        if sd > 0:
            m = float(idx.mean())
            idx = pd.Series((idx.to_numpy() - m) / sd + m, index=idx.index)
    return idx


def orden_ar_agrupado(indices: dict, pmax: int | None = None) -> tuple:
    """Orden autorregresivo AGRUPADO: uno solo para toda la colección.

    Es lo que hace ARSTAN —«series ar order 0, pooled ar order fit to all
    series»—: en vez de elegir un orden por serie, promedia las
    autocorrelaciones de la colección y ajusta sobre ellas. Agrupar mejora el
    ESTIMADOR de la autocorrelación, que es lo que aporta.

    Lo que NO cambia al agrupar es el criterio ni el tamaño de muestra, y por
    ahí se rompía. Esta función elegía el orden por el primer mínimo local del
    AIC con `n` igual a la SUMA de los largos de todas las series, y eso falla
    de dos maneras:

    **El criterio ya estaba medido y descartado.** El primer mínimo local del
    AIC es el de `chron.ars` de dplR, y contra los órdenes que informa COFECHA
    —un entero, así que no admite interpretación— acierta 81 % frente al 92 %
    del BIC, que es el que usa `_seleccionar_orden_ar`. Está en el registro de
    cambios 1.3. La función agrupada se quedó sin ese arreglo.

    **La suma de los largos no es el tamaño de muestra.** El modelo se aplica
    a series individuales, así que el orden tiene que ser el que se justifica
    para una serie del largo típico. Con `ntot` la penalización queda en torno
    a 1e-4 de `log(var)` —nula—, la traza del AIC sale monótona decreciente, el
    primer mínimo no se dispara nunca y el respaldo `argmin` devuelve el techo.
    Resultado: el orden lo decidía el TAMAÑO DE LA COLECCIÓN y no la
    persistencia de los datos. Medido sobre seis colecciones con ρ₁ entre 0,31
    y 0,36, salía 1 con 19 a 43 series y 10 con 70 a 82.

    Y lo que se modelaba pasado el retardo 1 era un artefacto: las
    autocorrelaciones parciales agrupadas son negativas y sin decaer del
    retardo 3 al 10 en las seis colecciones, que es la firma del spline, no de
    un proceso autorregresivo. Contra el piso de ruido de una serie individual
    quedan por debajo del ruido; agrupar las hacía parecer significativas.

    Con BIC sobre el largo mediano y el techo de `ORDEN_AR_MAXIMO`, el orden
    sale AR(1) en las seis, que es la moda de los órdenes por serie en todas.
    La cronología residual correlaciona 0,96 con la anterior, pero recupera
    señal: la desviación estándar sube un 8 % y el Rbar entre series también
    —0,407 a 0,448 en la colección de 82—, o sea que el AR(10) estaba quitando
    señal COMÚN, que es lo contrario de lo que busca una cronología residual.

    Nota sobre cómo se detectó: con series AR sintéticas la regla anterior
    acierta, porque ahí las parciales pasado el orden verdadero son ruido
    blanco y la traza del AIC sí da la vuelta. Degenera solo con la cola de
    parciales negativas que deja el detrending, así que hacen falta
    colecciones reales para verlo.

    Devuelve (orden, autocorrelaciones_agrupadas).
    """
    if pmax is None:
        pmax = ORDEN_AR_MAXIMO
    pmax = max(int(pmax), 1)
    num = np.zeros(pmax)
    den = np.zeros(pmax)
    largos = []
    for v in (b for serie in indices.values() for b in _bloques_anuales(serie)):
        x = v.to_numpy(dtype=float)
        if len(x) < 20:
            continue
        x = x - x.mean()
        n = len(x)
        largos.append(n)
        c0 = float(np.sum(x * x))
        if c0 <= 0:
            continue
        for k in range(1, pmax + 1):
            if n - k < 5:
                continue
            num[k - 1] += n * (float(np.sum(x[:-k] * x[k:])) / c0)
            den[k - 1] += n
    if not largos:
        return 1, np.zeros(pmax)
    rho = num / np.maximum(den, 1e-12)

    # Largo MEDIANO, no la suma: es el tamaño de la serie a la que se le va a
    # aplicar el modelo. La mediana y no la media, por las series cortas.
    n = int(np.median(largos))
    mejor_orden, mejor_pun = 1, np.inf
    for p in range(1, pmax + 1):
        R = np.array([[1.0 if i == j else rho[abs(i - j) - 1]
                       for j in range(p)] for i in range(p)])
        r = rho[:p]
        try:
            phi = np.linalg.solve(R, r)
        except Exception:
            continue
        var = 1.0 - float(np.dot(phi, r))
        if not np.isfinite(var) or var <= 0:
            continue
        pun = n * np.log(var) + p * np.log(n)      # BIC, igual que por serie
        if pun < mejor_pun - 1e-9:
            mejor_pun, mejor_orden = pun, p
    return mejor_orden, rho


def _normalizar_serie_para_tipo(serie_mm: pd.Series, tipo_cronologia: str,
                                  metodo_estandarizacion: str,
                                  ventana_mm: int | None = None,
                                  aplicar_log: bool = False,
                                  arstan: dict | None = None,
                                  orden_ar: int | None = None) -> pd.Series:
    tipo = (tipo_cronologia or "raw").lower()
    if tipo == "raw":
        return pd.to_numeric(serie_mm, errors="coerce").astype(float).dropna()

    # Camino ARSTAN: doble detrending, rigidez porcentual, estabilización de
    # varianza, normalización e índices por resta. Solo se toma si la pestaña
    # activó alguna de esas opciones; si no, sigue el camino simple de siempre.
    if arstan:
        idx = detrendar_para_cronologia(
            serie_mm,
            metodo1=arstan.get("metodo1", metodo_estandarizacion),
            rigidez1=arstan.get("rigidez1", 32),
            metodo2=arstan.get("metodo2"),
            rigidez2=arstan.get("rigidez2", -128),
            ventana_mm=ventana_mm,
            rigidez_minima=arstan.get("rigidez_minima", 0),
            por_resta=arstan.get("por_resta", False),
            log_previo=arstan.get("log_previo", False),
            estabilizar=arstan.get("estabilizar", False),
            rigidez_estab=arstan.get("rigidez_estab", 64),
            normalizar=arstan.get("normalizar", False))
        if tipo == "residual":
            return _residualizar_indice(idx)
        return idx
    idx = _detrend_serie_indice(serie_mm, metodo_estandarizacion, ventana_mm=ventana_mm)
    # Log estilo COFECHA (Holmes 1983): se aplica al índice de razón (media ~1)
    # antes del modelo autorregresivo. Comprime los anillos anchos y suele
    # subir la correlación de cofechado. Debe aplicarse por igual a la
    # cronología y a las series para que queden en el mismo espacio.
    if aplicar_log and not idx.empty:
        media = float(idx.mean())
        c_const = media / 6.0 if media > 0 else 0.001
        idx = pd.Series(
            np.log(np.maximum(idx.to_numpy(dtype=float) + c_const, 1e-10)),
            index=idx.index)
    if tipo == "residual":
        if orden_ar:
            return _residualizar_indice(idx, orden_fijo=orden_ar)
        return _residualizar_indice(idx)
    return idx


METODOS_DETREND = ("spline", "negexp", "linear", "media_movil", "media")


def diagnosticar_curva(serie_mm: pd.Series, metodo: str,
                        ventana_mm: int | None = None,
                        rigidez: int | None = None) -> dict:
    """Comprueba si la curva de ajuste cruza cero — el «dirty dog» de ARSTAN.

    Con series de caída muy fuerte, la exponencial negativa o la recta pueden
    bajar de cero. Ahí el índice queda indefinido o negativo, y dividir por un
    número cercano a cero lo dispara: medido sobre una serie real de ciprés,
    el ajuste lineal cruzaba cero en 24 de 422 años y producía un índice
    máximo de 96, cuando un índice normal ronda 1.

    DPI nunca devuelve índices negativos porque reemplaza la tendencia por la
    media de la serie donde sale <= 0. El problema no es que explote: es que
    parchaba en SILENCIO, y esos años quedan divididos por la media global en
    vez de por su tendencia local, así que su índice no significa lo mismo que
    el del resto de la serie.

    Devuelve:
      n_parches   años cuya tendencia hubo que reemplazar
      total       largo de la serie
      tramos      lista de (año inicial, año final) de los tramos parchados
      indice      la serie de índice resultante
      indice_max  máximo del índice; sobre 3 o 4 es señal de alarma
      valido      True si la curva no cruzó cero en ningún año
    """
    s = pd.to_numeric(serie_mm, errors="coerce").dropna().astype(float)
    vacio = {"n_parches": 0, "total": 0, "tramos": [], "indice": s.iloc[0:0],
             "indice_max": float("nan"), "valido": False}
    if len(s) < 8:
        return vacio
    try:
        tend = _fit_trend(s.to_numpy(dtype=float), metodo,
                          ventana_mm=ventana_mm, rigidez=rigidez)
    except Exception:
        return vacio
    tend = np.asarray(tend, dtype=float)
    # Mismo criterio que la guarda de `_detrend_serie_indice`: el 5 % de la
    # media, no el cero. Si no, el diálogo no avisaría de los casos donde la
    # curva no cruza cero pero igual dispara el índice.
    vals = s.to_numpy(dtype=float)
    med = float(np.nanmean(vals)) if len(vals) else 0.0
    piso = 0.05 * med if np.isfinite(med) and med > 0 else 0.0
    malo = ~np.isfinite(tend) | (tend <= piso)
    anios = s.index.to_numpy(np.int64)

    tramos = []
    if malo.any():
        ini = None
        for k, m in enumerate(malo):
            if m and ini is None:
                ini = k
            elif not m and ini is not None:
                tramos.append((int(anios[ini]), int(anios[k - 1])))
                ini = None
        if ini is not None:
            tramos.append((int(anios[ini]), int(anios[-1])))

    idx = _detrend_serie_indice(s, metodo, ventana_mm=ventana_mm,
                                rigidez=rigidez)
    return {
        "n_parches": int(malo.sum()), "total": int(len(s)),
        "tramos": tramos, "indice": idx,
        "indice_max": float(idx.max()) if len(idx) else float("nan"),
        "valido": not bool(malo.any()),
    }


def detectar_series_problematicas(series: dict, nombres: list,
                                   metodo: str, ventana_mm=None,
                                   rigidez=None) -> dict:
    """Series cuya curva cruza cero con el método elegido."""
    fuera = {}
    for n in nombres:
        if n not in series:
            continue
        col = series[n]["Ancho_mm"] if isinstance(series[n], pd.DataFrame) \
            else series[n]
        d = diagnosticar_curva(col, metodo, ventana_mm, rigidez)
        if d["n_parches"] > 0:
            fuera[n] = d
    return fuera


def elegir_metodo_para_grupo(series: dict, problematicas: list,
                              maestra: pd.Series,
                              metodos=METODOS_DETREND,
                              ventana_mm=None, rigidez=None) -> dict:
    """Elige UN método para todas las series con curva negativa.

    Dos etapas, y el orden importa:

    1. **Filtro duro:** se descarta cualquier método que cruce cero en alguna
       de las series del grupo. Ahí el índice no significa nada.
    2. **Entre los que sobreviven, la mediana de la correlación con la
       maestra.** No se usa el índice máximo como criterio, aunque delate bien
       los casos rotos, porque un máximo cercano a 1 se consigue de dos
       maneras opuestas: porque la curva ajusta bien, o porque ajusta DEMASIADO
       y se come toda la variabilidad. La correlación distingue esos dos casos;
       el máximo no. Tampoco sirve la sensibilidad media: medida sobre cinco
       métodos en la misma serie da 0,260 a 0,269, o sea que el método de
       estandarización no toca la alta frecuencia.

    Se elige sobre el GRUPO y no serie por serie, porque el informe tiene que
    poder decir «las N series con curva negativa se estandarizaron con X».
    Optimizar la primera serie puede castigar a las otras cinco.

    Devuelve {"metodo": str|None, "tabla": [...]} con el detalle por método.
    """
    tabla = []
    for m in metodos:
        rs, maxs, cruces = [], [], 0
        for n in problematicas:
            col = series[n]["Ancho_mm"] if isinstance(series[n], pd.DataFrame) \
                else series[n]
            d = diagnosticar_curva(col, m, ventana_mm, rigidez)
            cruces += d["n_parches"]
            idx = d["indice"]
            if idx is None or len(idx) < 10:
                continue
            maxs.append(d["indice_max"])
            com = idx.index.intersection(maestra.index)
            if len(com) >= 20:
                a = idx.loc[com].to_numpy(dtype=float)
                b = maestra.loc[com].to_numpy(dtype=float)
                if np.std(a) > 1e-12 and np.std(b) > 1e-12:
                    r = pearson(a, b)
                    if np.isfinite(r):
                        rs.append(r)
        tabla.append({
            "metodo": m, "cruces": cruces,
            "valido": cruces == 0,
            "r_mediana": float(np.median(rs)) if rs else float("nan"),
            "indice_max": float(np.max(maxs)) if maxs else float("nan"),
            "n_series": len(rs),
        })
    validos = [t for t in tabla
               if t["valido"] and np.isfinite(t["r_mediana"])]
    mejor = max(validos, key=lambda t: t["r_mediana"])["metodo"] \
        if validos else None
    tabla.sort(key=lambda t: (t["valido"],
                              t["r_mediana"] if np.isfinite(t["r_mediana"])
                              else -9), reverse=True)
    return {"metodo": mejor, "tabla": tabla}


def estandarizar_serie(serie_mm: pd.Series,
                        rigidez_spline: int = RIGIDEZ_SPLINE_DEFECTO,
                        aplicar_log: bool = True,
                        aplicar_ar: bool = True,
                        max_orden_ar: int = 3):
    """Estandariza una serie como COFECHA y devuelve (índice, orden AR).

    Pasos: spline de Cook (quita la tendencia de crecimiento) → índice de
    razón → log opcional → modelo autorregresivo.
    """
    s = pd.to_numeric(serie_mm, errors="coerce").dropna().astype(float)
    if s.empty:
        return s, 0

    idx = _detrend_serie_indice(s, "spline", rigidez=rigidez_spline)
    if idx.empty:
        return idx, 0

    # ORDEN: spline -> índice -> AR -> logaritmo.
    #
    # Es el que describe el manual de la Dendrochronology Program Library
    # (Holmes 1994): (1) spline y división, (2) "la persistencia de la serie
    # suavizada se elimina por modelado autorregresivo", (3) "se toma el
    # logaritmo de cada valor tras sumar una constante de un sexto de la
    # media". DPI aplicaba el logaritmo ANTES del AR.
    #
    # La prueba que lo zanja es el ORDEN DEL MODELO AR, que es un entero y no
    # admite interpretación. Comparado con las 36 series de cos8.rwl contra la
    # corrida real de COFECHA:
    #
    #   AR sobre el índice (manual):  25 de 36 órdenes coinciden  (69 %)
    #   AR sobre el logaritmo:        19 de 36                    (53 %)
    #
    # Y en el archivo de dos series 88B.rwl, el orden sobre el índice acierta
    # los dos (2 y 1) mientras que sobre el logaritmo falla los dos (1 y 3).
    orden = 0
    if aplicar_ar:
        idx, orden = _residualizar_indice(idx, max_orden=max_orden_ar,
                                          devolver_orden=True)

    if aplicar_log:
        media = float(idx.mean())
        c = media / 6.0 if media > 0 else 1e-3
        idx = pd.Series(
            np.log(np.maximum(idx.to_numpy(dtype=float) + c, 1e-10)),
            index=idx.index)

    return idx, orden


def _construir_cronologia_desde_series(
    series: dict[str, pd.DataFrame],
    nombres: list[str],
    tipo_cronologia: str,
    metodo_estandarizacion: str,
    agregacion: str,
    ventana_mm: int | None = None,
    aplicar_log: bool = False,
    metodo_alterno: str | None = None,
    series_alternas: list | None = None,
    metodos_por_serie: dict | None = None,
    arstan: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    if not nombres:
        raise ValueError("No hay series seleccionadas.")

    alternas = set(series_alternas or [])
    # Orden AR agrupado para la cronología residual, al modo de ARSTAN: un
    # solo orden para todas las series, elegido sobre las autocorrelaciones
    # del conjunto. Se calcula una vez y se pasa a cada serie.
    orden_pool = None
    if (tipo_cronologia or "").lower() == "residual":
        try:
            prev = {}
            for n in nombres:
                if n in series:
                    m2 = (metodo_alterno if (metodo_alterno and n in alternas)
                          else metodo_estandarizacion)
                    prev[n] = _detrend_serie_indice(
                        series[n]["Ancho_mm"], m2, ventana_mm=ventana_mm)
            if len(prev) >= 3:
                orden_pool, _rho = orden_ar_agrupado(prev)
        except Exception:
            orden_pool = None
    columnas = []
    for nombre in nombres:
        if nombre not in series:
            continue
        # Las series cuya curva cruzaba cero pueden llevar otro método, el
        # mismo para todas, elegido por el usuario o por correlación.
        # Prioridad: elección individual > método del grupo > método general.
        met = metodo_estandarizacion
        if metodo_alterno and nombre in alternas:
            met = metodo_alterno
        if metodos_por_serie and nombre in metodos_por_serie:
            met = metodos_por_serie[nombre]
        s_norm = _normalizar_serie_para_tipo(
            series[nombre]["Ancho_mm"], tipo_cronologia,
            met, ventana_mm=ventana_mm,
            aplicar_log=aplicar_log, arstan=arstan,
            orden_ar=orden_pool
        )
        s_norm.name = nombre
        columnas.append(s_norm)
    if not columnas:
        raise ValueError("No hay datos válidos para construir la cronología.")

    df = pd.concat(columnas, axis=1).sort_index()
    if df.empty:
        raise ValueError("La cronología quedó vacía.")

    agg = (agregacion or "biweight").lower()
    tipo = (tipo_cronologia or "raw").lower()

    if agg in {"biweight", "robusta", "robust"}:
        valores = pd.Series(media_biweight(df.to_numpy(dtype=float), axis=1),
                            index=df.index)
    elif agg in {"median", "mediana"}:
        valores = df.median(axis=1, skipna=True)
    else:
        valores = df.mean(axis=1, skipna=True)

    ns = df.notna().sum(axis=1)
    sds = df.std(axis=1, skipna=True, ddof=1).fillna(0.0)

    col_name = {"raw": "Raw", "residual": "Residual"}.get(tipo, "Standard")
    cron = pd.DataFrame(
        {col_name: valores, "N": ns.astype(int), "SD": sds},
        index=pd.Index(df.index.astype(int), name="Anio"),
    )
    cron = cron.dropna(subset=[col_name]).sort_index()

    # ── Rbar y EPS de PERÍODO COMPLETO sobre SERIES DETRENDADAS ──────
    # Antes calcular_rbar usaba las series RAW (Ancho_mm), lo que daba
    # valores inflados porque las tendencias decadales hacen que las
    # series brutas covaríen fuertemente a largo plazo. ARSTAN computa
    # su "all possible series rbar" sobre las series DETRENDADAS, que
    # es lo correcto: queremos la señal común año-a-año, no las
    # tendencias compartidas. Acá usamos el `df` de series detrendadas
    # que ya construimos arriba.
    # Rbar global vectorizado. Antes se recorrían todos los pares en bucles
    # de Python con pandas (.dropna/.intersection/.loc por par): con 169
    # series son 14.196 pares y era el mayor costo al generar la cronología.
    # Ahora la matriz de correlaciones se calcula de una sola vez con
    # álgebra matricial, respetando NaN y el mínimo de 10 años en común.
    rs_pairs = correlaciones_pares(df.to_numpy(dtype=float))
    rbar_completo = float(np.mean(rs_pairs)) if rs_pairs.size else float("nan")
    # Profundidad de muestreo promedio (mean number of series per year
    # with valid data) — igual que la columna "cores" de ARSTAN.
    sample_depth_mean = float(ns[ns > 0].mean()) if (ns > 0).any() else 0.0
    eps_completo = float(calcular_eps(rbar_completo, sample_depth_mean))

    meta = {
        "nombre": "",
        "tipo_cronologia": tipo,
        "metodo_estandarizacion": metodo_estandarizacion,
        "aplicar_log": bool(aplicar_log),
        "agregacion": agg,
        "series_usadas": list(nombres),
        "n_series": len(nombres),
        "n_anios": int(len(cron)),
        "creado_en": pd.Timestamp.utcnow().isoformat(),
        "columna_valor": col_name,
        # Rbar/EPS sobre series detrendadas (comparable con ARSTAN
        # "all possible series rbar")
        "Rbar": rbar_completo,
        "EPS": eps_completo,
        "sample_depth_mean": sample_depth_mean,
        # Profundidad AÑO POR AÑO, necesaria para la SSS (la media no sirve:
        # la SSS pregunta desde qué año la cronología es utilizable).
        "sample_depth": pd.Series(ns, index=df.index),
        # Sobre las series DETRENDADAS, no las crudas. Dos series brutas
        # covarían por sus tendencias de edad aunque no compartan señal
        # climática, y eso infla el Rbar dentro y entre árboles por igual.
        "rbar_arboles": rbar_entre_arboles(
            {c.name: c for c in columnas if getattr(c, "name", None)},
            [c.name for c in columnas if getattr(c, "name", None)]),
    }
    return cron, meta

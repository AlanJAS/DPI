"""Componentes de medición de DPI."""

import math
import numpy as np
from modulo_marcas_medicion import (_es_normal, _es_salto_real, _es_ewlw,
                                     _es_quiebre, _excluye_intensidad)


def _calcular_ewlw_posiciones(sig_prog, gray, coords, saltos, banda,
                              cancel_flag=None):
    """
    Detecta EW/LW procesando el perfil de intensidad gris PIXEL A PIXEL
    a lo largo de cada anillo completo. Inserta un límite en TODOS los anillos.

    Para cada anillo:
      1. Extrae el perfil continuo de intensidad gris px a px a lo largo
         del camino (promediando en banda perpendicular en cada punto).
      2. Suaviza con Savitzky-Golay.
      3. Encuentra la primera derivada más negativa.
      4. El punto de mayor oscurecimiento es el límite EW/LW.

    Corre en hilo secundario. Devuelve lista de (insert_at, px, py).
    Si cancel_flag no es None, cancela entre anillos y devuelve resultados
    parciales; al completar emite el progreso final de la ruta cancelable.
    """
    from scipy.signal import savgol_filter

    h, w = gray.shape
    n = len(coords)
    inserciones = []

    # Identificar anillos (tramos entre dos False consecutivos)
    anillos = []
    ini = 0
    for i in range(1, n):
        if _es_normal(saltos[i]):
            anillos.append(list(range(ini, i + 1)))
            ini = i
    if ini < n - 1:
        anillos.append(list(range(ini, n)))

    n_anillos = len(anillos)

    for a_num, anillo_idxs in enumerate(anillos):
        if cancel_flag is not None and cancel_flag.get("stop"):
            return inserciones

        if sig_prog is not None:
            pct = int(a_num * 100 / max(1, n_anillos))
            sig_prog.emit(pct, f"Anillo {a_num + 1}/{n_anillos}")

        if len(anillo_idxs) < 2:
            continue

        # Si ya tiene ew_lw, saltar
        if any(_es_ewlw(saltos[j])
               for j in anillo_idxs[1:] if j < len(saltos)):
            continue

        # ── Construir perfil pixel a pixel ──────────────────────────────
        # Para cada punto a lo largo del camino del anillo,
        # promediamos los valores de gris en la banda perpendicular.
        perfil_vals = []   # valor gris en cada muestra
        perfil_pos  = []   # (px, py, seg_idx) en cada muestra

        for k in range(1, len(anillo_idxs)):
            ip = anillo_idxs[k - 1]
            ic = anillo_idxs[k]
            if ic >= n:
                break
            val_k = saltos[ic] if ic < len(saltos) else False
            # Saltar quiebres y espacios (pero no ew_lw que ya filtramos)
            if _excluye_intensidad(val_k):
                continue

            x0, y0 = coords[ip]
            x1, y1 = coords[ic]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len < 1:
                continue

            ux  = (x1 - x0) / seg_len
            uy  = (y1 - y0) / seg_len
            perp_x, perp_y = -uy, ux

            # Una muestra cada pixel a lo largo del segmento
            n_s  = max(2, int(round(seg_len)))
            ts   = np.linspace(0.0, 1.0, n_s)
            xs_c = x0 + ts * (x1 - x0)   # (n_s,)
            ys_c = y0 + ts * (y1 - y0)

            # Banda perpendicular vectorizada: shape (2b+1, n_s)
            offs  = np.arange(-banda, banda + 1, dtype=np.float32)
            xs_b  = xs_c[np.newaxis, :] + offs[:, np.newaxis] * perp_x  # (2b+1, n_s)
            ys_b  = ys_c[np.newaxis, :] + offs[:, np.newaxis] * perp_y

            # Clip a los bordes de la imagen
            xs_b  = np.clip(xs_b, 0, w - 1).astype(np.int32)
            ys_b  = np.clip(ys_b, 0, h - 1).astype(np.int32)

            # Media por columna (cada columna = una posición a lo largo del camino)
            # shape (n_s,)
            vals_col = gray[ys_b, xs_b].mean(axis=0)

            for j in range(n_s):
                perfil_vals.append(float(vals_col[j]))
                perfil_pos.append((float(xs_c[j]), float(ys_c[j]), ic))

        if len(perfil_vals) < 10:
            continue

        arr = np.array(perfil_vals, dtype=np.float32)

        # Suavizado con ventana ~10% del anillo, mínimo 5 puntos
        # Ventana más grande → señal más limpia para detectar la transición
        win_ideal = max(5, int(len(arr) * 0.10))
        win = win_ideal if win_ideal % 2 == 1 else win_ideal + 1
        win = min(win, len(arr) if len(arr) % 2 == 1 else len(arr) - 1)
        arr_smooth = savgol_filter(arr, win, 2) if win >= 5 else arr.copy()

        # Algoritmo de detección EW→LW:
        # La transición es EW (claro, valor alto) → LW (oscuro, valor bajo).
        # El punto de límite es donde la pendiente negativa es máxima
        # (primera derivada más negativa = mayor tasa de oscurecimiento).
        # Usamos la primera derivada suavizada en lugar de la segunda.
        d1 = np.gradient(arr_smooth)

        # Rango de búsqueda: 15% al 95% del anillo
        m_ini = max(1, int(len(arr) * 0.15))
        m_fin = max(1, int(len(arr) * 0.05))
        if m_ini + m_fin >= len(arr):
            m_ini, m_fin = 1, 1

        d1_sub = d1[m_ini: len(arr) - m_fin]
        if len(d1_sub) == 0:
            continue

        # Mínimo de la primera derivada = punto de mayor oscurecimiento (EW→LW)
        # Si la derivada es siempre positiva (anillo monotónicamente creciente),
        # usar el umbral del 50% del rango como respaldo
        idx_min_d1 = int(np.argmin(d1_sub)) + m_ini

        # Respaldo: si la derivada en ese punto es positiva (no hay oscurecimiento),
        # usar el punto donde el perfil cruza la media del anillo
        if d1[idx_min_d1] >= 0:
            media = float(arr_smooth.mean())
            # Buscar primer cruce por debajo de la media en el rango
            sub = arr_smooth[m_ini: len(arr) - m_fin]
            cruces = np.where(np.diff(np.sign(sub - media)) < 0)[0]
            if len(cruces) > 0:
                idx_min_d1 = cruces[0] + m_ini
            else:
                idx_min_d1 = m_ini + len(sub) // 2

        px_ins, py_ins, insert_at = perfil_pos[idx_min_d1]
        inserciones.append((insert_at, px_ins, py_ins))

    # Emitir 100% al completar para que el usuario vea que el worker
    # terminó. Sin esto la barra queda pegada al 99% mientras el main
    # thread aplica los resultados, dando sensación de "crash".
    if cancel_flag is not None and sig_prog is not None:
        try:
            sig_prog.emit(100, "Procesando resultados...")
        except Exception:
            pass

    return inserciones



def _calcular_ewlw_posiciones_cancelable(sig_prog, gray, coords, saltos, banda,
                                          cancel_flag):
    """Compatibilidad con la ruta cancelable anterior."""
    return _calcular_ewlw_posiciones(
        sig_prog, gray, coords, saltos, banda, cancel_flag=cancel_flag)



def _calcular_anchos_ewlw_por_anillo(coords, saltos, ppm):
    """Calcula los anchos de earlywood (EW) y latewood (LW) para cada anillo.

    Parameters
    ----------
    coords : list[tuple[float, float]]
        Coordenadas de los puntos del camino en píxeles.
    saltos : list
        Lista paralela a coords con los flags: False/True/"espacio"/"ew_lw"/etc.
    ppm : float
        Píxeles por mm para convertir a milímetros.

    Returns
    -------
    list[tuple[float, float | None, float | None]]
        Lista de tuplas (ancho_total_mm, ew_mm, lw_mm) por anillo.
        Si el anillo no tiene límite EW/LW, ew_mm y lw_mm son None.
        El orden coincide con el de los anillos en `recalcular_todas_las_distancias`.
    """
    n = len(coords)
    anchos_anillo = []   # lista de (total_mm, ew_mm_or_None, lw_mm_or_None)
    acum = 0.0           # distancia acumulada desde el inicio del anillo actual
    acum_pre_ewlw = None # si encontramos un EW/LW, congelamos el acum acá

    for i in range(1, n):
        val = saltos[i]
        if i >= len(coords) or i - 1 >= len(coords):
            break
        d = math.hypot(
            coords[i][0] - coords[i-1][0],
            coords[i][1] - coords[i-1][1],
        ) / ppm

        if _es_salto_real(val):
            # Salto real: cierra anillo previo si quedó algo
            if acum > 0:
                if acum_pre_ewlw is not None:
                    # Había un EW/LW, pero después saltó sin completar
                    anchos_anillo.append((acum, acum_pre_ewlw, acum - acum_pre_ewlw))
                else:
                    anchos_anillo.append((acum, None, None))
            acum = 0.0
            acum_pre_ewlw = None
        elif _es_quiebre(val):
            # No suma, no cierra
            pass
        elif _es_ewlw(val):
            # Suma y marca el split: el acum hasta acá es el EW
            acum += d
            acum_pre_ewlw = acum
        else:
            # val is False: límite normal — suma y cierra el anillo
            acum += d
            if acum_pre_ewlw is not None:
                ew = acum_pre_ewlw
                lw = acum - acum_pre_ewlw
                anchos_anillo.append((acum, ew, lw))
            else:
                anchos_anillo.append((acum, None, None))
            acum = 0.0
            acum_pre_ewlw = None

    # Último anillo sin cerrar
    if acum > 0:
        if acum_pre_ewlw is not None:
            anchos_anillo.append((acum, acum_pre_ewlw, acum - acum_pre_ewlw))
        else:
            anchos_anillo.append((acum, None, None))

    return anchos_anillo


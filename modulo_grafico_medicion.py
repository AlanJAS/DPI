"""Preparación estadística de gráficos de medición sin Qt."""
import numpy as np
import pandas as pd
import modulo_transformacion as _tr

def correlacion_deslizante(anios_a, anchos_a, anios_b, anchos_b, ventana: int, metodo):
    """
    Correlación deslizante estilo COFECHA.

    Calcula r de Pearson (sobre diff-log) en cada ventana de `ventana` años,
    avanzando de la mitad de la ventana en la mitad (solapamiento 50%).
    Cuando la serie tiene menos de `ventana` años, usa todos los años
    disponibles como única ventana (ventana creciente al inicio).

    Devuelve dos listas paralelas: (años_centro, r_vals).
    Los años_centro son el año central de cada ventana.
    """
    if ventana < 2:
        raise ValueError("Ventana demasiado corta")
    MIN_VENTANA = 10
    if len(anios_a) < MIN_VENTANA or len(anios_b) < MIN_VENTANA:
        return [], []

    da = _tr.transformar(pd.Series(anchos_a, index=anios_a).clip(lower=0.01), metodo)
    db = _tr.transformar(pd.Series(anchos_b, index=anios_b).clip(lower=0.01), metodo)
    overlap = sorted(da.index.intersection(db.index))
    n_ov = len(overlap)
    if n_ov < MIN_VENTANA:
        return [], []

    años_centro, r_vals = [], []
    paso = max(1, ventana // 2)   # solapamiento = mitad de la ventana

    if n_ov <= ventana:
        # Serie corta: una sola ventana con todo el solapamiento disponible
        a_seg = da.loc[overlap].values
        b_seg = db.loc[overlap].values
        if np.std(a_seg) > 1e-9 and np.std(b_seg) > 1e-9:
            r = float(np.corrcoef(a_seg, b_seg)[0, 1])
            if not np.isnan(r):
                centro = overlap[n_ov // 2]
                años_centro.append(centro)
                r_vals.append(r)
    else:
        # Ventana deslizante con paso = ventana/2
        k = 0
        while k + ventana <= n_ov:
            seg = overlap[k: k + ventana]
            a_seg = da.loc[seg].values
            b_seg = db.loc[seg].values
            if np.std(a_seg) > 1e-9 and np.std(b_seg) > 1e-9:
                r = float(np.corrcoef(a_seg, b_seg)[0, 1])
                if not np.isnan(r):
                    centro = seg[ventana // 2]
                    años_centro.append(centro)
                    r_vals.append(r)
            k += paso

    return años_centro, r_vals

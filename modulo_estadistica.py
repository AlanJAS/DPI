"""Estadística dendrocronológica común, sin dependencias de Qt."""
import numpy as np
import pandas as pd


def pearson(a, b, *, tolerancia=0.0):
    """Pearson sobre pares alineados; NaN si no es calculable."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.ndim != 1 or a.shape != b.shape or a.size < 2:
        return float("nan")
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return float("nan")
    sa, sb = np.std(a), np.std(b)
    if sa == 0 or sb == 0 or sa < tolerancia or sb < tolerancia:
        return float("nan")
    r = float(np.corrcoef(a, b)[0, 1])
    return r if np.isfinite(r) else float("nan")


def glk_alineado(a, b, min_overlap=10):
    """GLK sobre observaciones alineadas (convención de empates de DPI)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape or a.size < max(2, min_overlap):
        return float("nan")
    da, db = np.sign(np.diff(a)), np.sign(np.diff(b))
    return float(1.0 - np.mean(np.abs(da - db)) / 2.0)


def t_desde_r(r, n):
    """Conserva la convención histórica de DPI para correlaciones perfectas."""
    if n < 3 or not np.isfinite(r) or abs(r) >= 1.0:
        return float("nan")
    return float(r * np.sqrt(n - 2) / np.sqrt(1.0 - r * r))


def tbp_filtrado(a, b, min_overlap=20):
    """t-BP y r a partir de diferencias logarítmicas ya alineadas."""
    n = len(a)
    if n < min_overlap:
        return float("nan"), float("nan"), n
    r = pearson(a, b)
    return t_desde_r(r, n), r, n


def tbp_alineado(a, b, min_overlap=20):
    """Ruta rápida histórica: filtrar pares positivos antes de diferenciar."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    m = (a > 0) & (b > 0)
    ha = 100.0 * np.diff(np.log(a[m]))
    hb = 100.0 * np.diff(np.log(b[m]))
    return tbp_filtrado(ha, hb, min_overlap)[0]

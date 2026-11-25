"""Preparación de una serie para las métricas de comparación."""
import pandas as pd
from dpi.ciencia.comparacion_nucleo import SeriePreparada

def preparar_serie(datos, transformar, para_glk):
    cruda = pd.to_numeric(datos, errors="coerce").dropna()
    if cruda.empty:
        return SeriePreparada(cruda, cruda, cruda)
    return SeriePreparada(cruda, transformar(datos), para_glk(datos))

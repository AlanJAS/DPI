"""Importación de series sin dependencia de widgets."""
from dpi.formatos.deteccion import leer_series_auto


def importar_archivo(modelo, ruta):
    """Registra un archivo completo o no modifica el modelo."""
    return modelo.registrar_lote(leer_series_auto(ruta))

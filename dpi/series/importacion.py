"""Importación de series sin dependencia de widgets."""
from dpi.formatos.deteccion import leer_series_auto

def importar_archivo(modelo, ruta):
    """Genera (nombre, agregado) tras registrar cada serie, sin sobrescribir."""
    for nombre, datos in leer_series_auto(ruta).items():
        if nombre in modelo.datos:
            yield nombre, False
            continue
        modelo.registrar(nombre, datos)
        yield nombre, True

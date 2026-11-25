"""Preferencias de carpetas de los diálogos de archivos."""
import os
from PyQt6.QtCore import QSettings


def ultima_carpeta(clave: str, nueva_ruta: str | None = None) -> str:
    cfg = QSettings("MoiCedrus", "DPI")
    if nueva_ruta is not None:
        carpeta = os.path.dirname(nueva_ruta)
        cfg.setValue(clave, carpeta)
        return carpeta
    return cfg.value(clave, "")

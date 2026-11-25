"""Compatibilidad: la implementación reside en dpi.medicion.intensidad."""
import sys as _sys
import dpi.medicion.intensidad as _modulo
_sys.modules[__name__] = _modulo

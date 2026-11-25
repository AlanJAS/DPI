"""Compatibilidad: la implementación reside en dpi.medicion.datos."""
import sys as _sys
import dpi.medicion.datos as _modulo
_sys.modules[__name__] = _modulo

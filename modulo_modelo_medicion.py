"""Compatibilidad: la implementación reside en dpi.medicion.modelo."""
import sys as _sys
import dpi.medicion.modelo as _modulo
_sys.modules[__name__] = _modulo

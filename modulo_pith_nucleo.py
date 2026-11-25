"""Compatibilidad: la implementación reside en dpi.medicion.pith."""
import sys as _sys
import dpi.medicion.pith as _modulo
_sys.modules[__name__] = _modulo

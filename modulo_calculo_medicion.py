"""Compatibilidad: la implementación reside en dpi.medicion.calculo."""
import sys as _sys
import dpi.medicion.calculo as _modulo
_sys.modules[__name__] = _modulo

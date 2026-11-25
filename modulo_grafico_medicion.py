"""Compatibilidad: la implementación reside en dpi.medicion.grafico."""
import sys as _sys
import dpi.medicion.grafico as _modulo
_sys.modules[__name__] = _modulo

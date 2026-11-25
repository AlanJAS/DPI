"""Compatibilidad: la implementación reside en dpi.medicion.autodeteccion."""
import sys as _sys
import dpi.medicion.autodeteccion as _modulo
_sys.modules[__name__] = _modulo

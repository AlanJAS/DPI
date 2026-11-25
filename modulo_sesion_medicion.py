"""Compatibilidad: la implementación reside en dpi.medicion.sesion."""
import sys as _sys
import dpi.medicion.sesion as _modulo
_sys.modules[__name__] = _modulo

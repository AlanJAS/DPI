"""Compatibilidad: la implementación reside en dpi.medicion.marcas."""
import sys as _sys
import dpi.medicion.marcas as _modulo
_sys.modules[__name__] = _modulo

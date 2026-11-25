"""Compatibilidad: la implementación reside en dpi.series.modelo."""
import sys as _sys
import dpi.series.modelo as _modulo
_sys.modules[__name__] = _modulo

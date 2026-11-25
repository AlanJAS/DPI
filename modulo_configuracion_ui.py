"""Compatibilidad: la implementación reside en dpi.ui.configuracion."""
import sys as _sys
import dpi.ui.configuracion as _modulo
_sys.modules[__name__] = _modulo

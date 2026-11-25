"""Compatibilidad: la implementación reside en dpi.infraestructura.imagen."""
import sys as _sys
import dpi.infraestructura.imagen as _modulo
_sys.modules[__name__] = _modulo

"""Compatibilidad: la implementación reside en dpi.infraestructura.json_seguro."""
import sys as _sys
import dpi.infraestructura.json_seguro as _modulo
_sys.modules[__name__] = _modulo

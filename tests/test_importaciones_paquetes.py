"""La aplicación usa los paquetes canónicos, no los adaptadores históricos."""
import ast
from pathlib import Path
import unittest

RAIZ = Path(__file__).resolve().parents[1]

class ImportacionesPaquetes(unittest.TestCase):
    def test_importaciones_canonicas(self):
        adaptadores = {p.stem for p in RAIZ.glob("*.py")
                       if "_sys.modules[__name__] = _modulo" in p.read_text(encoding="utf-8")}
        for p in [*RAIZ.glob("*.py"), * (RAIZ / "dpi").rglob("*.py")]:
            if p.stem in adaptadores:
                continue
            for nodo in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                nombres = ([a.name for a in nodo.names] if isinstance(nodo, ast.Import)
                           else [nodo.module] if isinstance(nodo, ast.ImportFrom) else [])
                for nombre in nombres:
                    self.assertNotIn(nombre, adaptadores, (p, nombre))

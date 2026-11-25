"""Comprueba dependencias locales directas y transitivas sin cargar Qt."""
import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def importaciones(ruta):
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            yield from (a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            yield nodo.module
            for alias in nodo.names:
                yield nodo.module + "." + alias.name


class DependenciasCientificas(unittest.TestCase):
    def test_importaciones_sin_interfaz(self):
        pendientes = [p for paquete in ("ciencia", "medicion", "series", "formatos", "infraestructura")
                      for p in (RAIZ / "dpi" / paquete).rglob("*.py")]
        visitados = set()
        while pendientes:
            ruta = pendientes.pop()
            if ruta in visitados:
                continue
            visitados.add(ruta)
            for nombre in importaciones(ruta):
                self.assertFalse(nombre.startswith(("PyQt", "PySide", "pyqtgraph", "tkinter", "dpi.ui"))
                                 or nombre.endswith("_ui"), (ruta, nombre))
                local = RAIZ / (nombre.replace(".", "/") + ".py")
                if local.is_file():
                    pendientes.append(local)

"""Reglas de dependencias para los módulos que no necesitan Qt."""
import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NUCLEOS = (
    'modulo_calculo_medicion', 'modulo_modelo_medicion', 'modulo_modelo_series',
    'modulo_estadistica', 'modulo_cronologia', 'modulo_datacion', 'modulo_quiebres',
    'modulo_cofecha', 'modulo_cofecha_nucleo', 'modulo_comparacion_nucleo',
    'modulo_pith_nucleo', 'modulo_intensidad_nucleo', 'modulo_indice_anual',
    'modulo_grafico_medicion', 'modulo_datos_medicion',
)

class DependenciasCientificas(unittest.TestCase):
    def test_importaciones_sin_interfaz(self):
        for modulo in NUCLEOS:
            with self.subTest(modulo=modulo):
                arbol = ast.parse((RAIZ / (modulo + '.py')).read_text(encoding='utf-8'))
                for nodo in ast.walk(arbol):
                    if isinstance(nodo, ast.Import):
                        nombres = [a.name for a in nodo.names]
                    elif isinstance(nodo, ast.ImportFrom):
                        nombres = [nodo.module or '']
                    else:
                        continue
                    for nombre in nombres:
                        self.assertFalse(nombre.startswith(('PyQt', 'PySide', 'pyqtgraph', 'tkinter')) or nombre.endswith('_ui'), (modulo, nombre))

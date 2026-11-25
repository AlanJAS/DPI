import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np
import pandas as pd
from modulo_estadistica import correlaciones_pares


class Estabilidad(unittest.TestCase):
    def test_desplazamiento(self):
        x = np.arange(30, dtype=float)
        np.testing.assert_allclose(correlaciones_pares(np.c_[1e12+x, 1e12-x]), [-1])

    def test_no_finitos_y_constantes(self):
        x = np.arange(30, dtype=float)
        y = x.copy(); y[3] = np.inf
        np.testing.assert_allclose(correlaciones_pares(np.c_[x, y, np.ones(30)]), [1])

    def test_solape_local(self):
        x = np.r_[1e15, np.arange(20.)]
        y = np.r_[np.nan, np.arange(20.)]
        np.testing.assert_allclose(correlaciones_pares(np.c_[x, y]), [1])

    def test_cache(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'modulo_codatacion.py').read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_clave_cache_comparacion')
        ns = dict(pd=pd, hashlib=hashlib)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<cache>', 'exec'), ns)
        firma = ns[node.name]
        df = pd.DataFrame({'Ancho_mm': [1., 2., 3.]}, index=[2000, 2001, 2002])
        obj = SimpleNamespace(series_datos={'a': df}, cronologia_activa=df.copy(), _nombre_cronologia_activa='c', meta_cronologia={})
        inicial = firma(obj, ['a'])
        self.assertEqual(inicial, firma(obj, ['a']))
        df.iloc[:, 0] = [3., 2., 1.]
        self.assertNotEqual(inicial, firma(obj, ['a']))
        inicial = firma(obj, ['a'])
        obj.meta_cronologia['columna_valor'] = 'Ancho_mm'
        self.assertNotEqual(inicial, firma(obj, ['a']))

import json
import unittest

from modulo_modelo_medicion import ModeloMedicion, TipoMarca
from modulo_marcas_medicion import (
    MODO_MEDIR, MODO_PITH, _es_normal, _es_salto_real,
    _es_espacio, _es_ewlw, _es_quiebre_ini, _es_amarillo,
    _es_quiebre, _excluye_intensidad,
)


class TestMarcasMedicion(unittest.TestCase):
    def test_clasificacion(self):
        # normal, salto, espacio, EW/LW, inicio de quiebre
        casos = [
            (TipoMarca.NORMAL, (True, False, False, False, False, False, False, False)),
            (TipoMarca.SALTO, (False, True, False, False, False, True, False, True)),
            (TipoMarca.ESPACIO, (False, False, True, False, False, True, True, True)),
            (TipoMarca.EW_LW, (False, False, False, True, False, False, False, False)),
            (TipoMarca.QUIEBRE_INI, (False, False, False, False, True, False, True, True)),
        ]
        funciones = (_es_normal, _es_salto_real, _es_espacio, _es_ewlw,
                     _es_quiebre_ini, _es_amarillo, _es_quiebre, _excluye_intensidad)
        for marca, esperado in casos:
            for valor in (marca, marca.value):
                with self.subTest(valor=valor):
                    self.assertEqual(tuple(f(valor) for f in funciones), esperado)
        for valor in (None, 0, 1, 'desconocida'):
            self.assertFalse(any(f(valor) for f in funciones))

    def test_formato_historico(self):
        modelo = ModeloMedicion()
        marcas = list(TipoMarca)
        for i, marca in enumerate(marcas):
            modelo.agregar((i, 0), marca)
        valores = [False, True, 'espacio', 'ew_lw', 'quiebre_ini']
        self.assertEqual(json.loads(json.dumps(list(modelo.marcas))), valores)
        self.assertEqual([p.tipo for p in modelo.captura()], marcas)
        modelo.agregar((5, 0))
        self.assertIs(modelo.captura()[-1].tipo, TipoMarca.NORMAL)

    def test_modos(self):
        self.assertEqual(MODO_MEDIR)
        self.assertEqual(MODO_MEDIR, 1)
        self.assertEqual(MODO_PITH, 9)

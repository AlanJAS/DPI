import unittest
from modulo_modelo_medicion import ModeloSesionMedicion, RadioMedicion, PuntoMedicion
class Sesion(unittest.TestCase):
    def test_propietario(self):
        m = ModeloSesionMedicion()
        r = RadioMedicion('R', (PuntoMedicion((0,0)), PuntoMedicion((1,0))), 2000, 2000, 0)
        m.guardar_radio('R', r)
        with self.assertRaises(TypeError):
            m.radios['R'] = r
        with self.assertRaises(ValueError):
            m.guardar_radio('R', r)
        m.activo.agregar((3,4))
        self.assertEqual(len(m.radios['R'].puntos), 2)
        self.assertIs(m.eliminar_radio('R'), r)
        m.cargar_radios({'R': r})
        self.assertIs(m.radios['R'], r)

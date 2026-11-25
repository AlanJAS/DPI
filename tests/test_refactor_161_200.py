import unittest



class ImportacionAtomica(unittest.TestCase):
    def test_lote_invalido(self):
        import pandas as pd
        from dpi.series.modelo import ModeloSeries
        m = ModeloSeries()
        with self.assertRaises(ValueError):
            m.registrar_lote({'A': pd.DataFrame({'Ancho_mm':[1]}, index=[2000]), 'B': pd.DataFrame()})
        self.assertEqual(len(m.datos), 0)
        self.assertEqual(m.revision, 0)


class CacheGeometria(unittest.TestCase):
    def test_cambio_escala_y_marcas(self):
        from dpi.medicion.calculo import anchos_anillos
        self.assertEqual(anchos_anillos([(0,0),(4,0)], [False,False], 2), [2.])
        self.assertEqual(anchos_anillos([(0,0),(4,0)], [False,False], 4), [1.])
        self.assertEqual(anchos_anillos([(0,0),(4,0)], [False,True], 2), [])

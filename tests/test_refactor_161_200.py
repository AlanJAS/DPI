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

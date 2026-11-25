"""Estado de series de co-datación, independiente de Qt."""
import pandas as pd


class ModeloSeries:
    """Conserva datos editables y originales independientes.

    Los diccionarios se mantienen accesibles para los consumidores históricos.
    """
    def __init__(self):
        self.datos: dict[str, pd.DataFrame] = {}
        self.originales: dict[str, pd.DataFrame] = {}

    def registrar(self, nombre, df):
        if not isinstance(df, pd.DataFrame) or 'Ancho_mm' not in df.columns:
            raise ValueError('La serie debe contener Ancho_mm')
        datos = df.copy()
        original = datos.copy()
        self.datos[nombre] = datos
        self.originales[nombre] = original

    def eliminar(self, nombre):
        self.datos.pop(nombre, None)
        self.originales.pop(nombre, None)

    def restablecer(self, nombre):
        self.datos[nombre] = self.originales[nombre].copy()

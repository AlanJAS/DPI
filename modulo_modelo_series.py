"""Estado de series de co-datación, independiente de Qt."""
import pandas as pd
import numpy as np


class ModeloSeries:
    """Conserva datos editables y originales independientes.

    Los diccionarios se mantienen accesibles para los consumidores históricos.
    """
    def __init__(self):
        self.datos: dict[str, pd.DataFrame] = {}
        self.originales: dict[str, pd.DataFrame] = {}

    @staticmethod
    def _validar(df):
        if not isinstance(df, pd.DataFrame) or 'Ancho_mm' not in df.columns:
            raise ValueError('La serie debe contener Ancho_mm')
        datos = df.copy()
        anios = pd.to_numeric(datos.index, errors='raise').to_numpy(dtype=float)
        if not np.isfinite(anios).all() or not np.equal(anios, np.floor(anios)).all():
            raise ValueError('Los años deben ser enteros finitos')
        datos.index = pd.Index(anios.astype('int64'), name=df.index.name)
        if not datos.index.is_unique or datos.empty:
            raise ValueError('Serie vacía o años duplicados')
        valores = pd.to_numeric(datos['Ancho_mm'], errors='raise')
        if np.isinf(valores).any():
            raise ValueError('Valores infinitos')
        datos['Ancho_mm'] = valores
        return datos.sort_index()

    def registrar(self, nombre, df):
        datos = self._validar(df)
        original = datos.copy()
        self.datos[nombre] = datos
        self.originales[nombre] = original

    def eliminar(self, nombre):
        self.datos.pop(nombre, None)
        self.originales.pop(nombre, None)

    def restablecer(self, nombre):
        self.datos[nombre] = self.originales[nombre].copy()

    def actualizar(self, nombre, df):
        """Valida una edición sin sustituir el respaldo original."""
        if nombre not in self.datos:
            raise KeyError(nombre)
        datos = self._validar(df)
        self.datos[nombre] = datos

    def desplazar(self, nombre, shift):
        df = self.datos.get(nombre)
        if not shift or df is None or df.empty:
            return False
        if not isinstance(shift, (int, np.integer)) or isinstance(shift, bool):
            raise ValueError('El desfase debe ser entero')
        nuevo = df.copy()
        nuevo.index = nuevo.index + int(shift)
        self.actualizar(nombre, nuevo)
        return True

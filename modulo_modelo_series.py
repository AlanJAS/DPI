"""Estado de series de co-datación, independiente de Qt."""
from dataclasses import dataclass

import pandas as pd
import numpy as np


@dataclass(frozen=True)
class _PruebaCorreccion:
    nombre: str
    respaldo: pd.DataFrame


class ModeloSeries:
    """Conserva datos editables y originales independientes.

    Los diccionarios se mantienen accesibles para los consumidores históricos.
    """
    def __init__(self):
        self.datos: dict[str, pd.DataFrame] = {}
        self.originales: dict[str, pd.DataFrame] = {}
        self._prueba: _PruebaCorreccion | None = None

    @property
    def nombre_en_prueba(self):
        return self._prueba.nombre if self._prueba else None

    def _exigir_sin_prueba(self, nombre):
        if self.nombre_en_prueba == nombre:
            raise ValueError('Confirme o descarte la corrección temporal primero')

    def probar_correccion(self, nombre, df):
        """Instala una vista temporal sin alterar la serie original."""
        if self._prueba is not None:
            raise ValueError('Ya existe una corrección temporal')
        respaldo = self.datos[nombre].copy()
        corregido = self._validar(df)
        self.datos[nombre] = corregido
        self._prueba = _PruebaCorreccion(nombre, respaldo)

    def confirmar_correccion(self):
        """Conserva los datos de la prueba, no sustituye el original."""
        if self._prueba is None:
            return False
        self._prueba = None
        return True

    def descartar_correccion(self):
        """Recupera el estado anterior a la prueba, incluidas ediciones previas."""
        if self._prueba is None:
            return False
        prueba = self._prueba
        self.datos[prueba.nombre] = prueba.respaldo
        self._prueba = None
        return True

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
        self._exigir_sin_prueba(nombre)
        datos = self._validar(df)
        original = datos.copy()
        self.datos[nombre] = datos
        self.originales[nombre] = original

    def eliminar(self, nombre):
        self._exigir_sin_prueba(nombre)
        self.datos.pop(nombre, None)
        self.originales.pop(nombre, None)

    def restablecer(self, nombre):
        self._exigir_sin_prueba(nombre)
        self.datos[nombre] = self.originales[nombre].copy()

    def actualizar(self, nombre, df):
        """Valida una edición sin sustituir el respaldo original."""
        self._exigir_sin_prueba(nombre)
        if nombre not in self.datos:
            raise KeyError(nombre)
        datos = self._validar(df)
        self.datos[nombre] = datos

    def desplazar(self, nombre, shift):
        self._exigir_sin_prueba(nombre)
        df = self.datos.get(nombre)
        if not shift or df is None or df.empty:
            return False
        if not isinstance(shift, (int, np.integer)) or isinstance(shift, bool):
            raise ValueError('El desfase debe ser entero')
        nuevo = df.copy()
        nuevo.index = nuevo.index + int(shift)
        self.actualizar(nombre, nuevo)
        return True

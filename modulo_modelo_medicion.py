"""Modelo de puntos de medición, independiente de la interfaz gráfica."""
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite
from numbers import Real


class TipoMarca(Enum):
    NORMAL = False
    SALTO = True
    ESPACIO = 'espacio'
    EW_LW = 'ew_lw'
    QUIEBRE_INI = 'quiebre_ini'


    @classmethod
    def desde_valor(cls, valor):
        """Acepta marcas tipadas y los valores históricos del proyecto."""
        if isinstance(valor, cls):
            return valor
        if type(valor) not in (bool, str):
            raise ValueError(f"Marca inválida: {valor!r}")
        return cls(valor)

    @property
    def es_amarillo(self):
        return self in (TipoMarca.SALTO, TipoMarca.ESPACIO)


@dataclass(frozen=True, slots=True)
class PuntoMedicion:
    coordenada: tuple[float, float]
    tipo: TipoMarca = TipoMarca.NORMAL

    def __post_init__(self):
        x, y = self.coordenada
        if not all(isinstance(v, Real) and not isinstance(v, bool)
                   and isfinite(v) for v in (x, y)):
            raise ValueError("Las coordenadas deben ser números finitos")
        object.__setattr__(self, "coordenada", (float(x), float(y)))
        object.__setattr__(self, "tipo", TipoMarca.desde_valor(self.tipo))


class _VistaCampo(Sequence):
    """Proyección viva de solo lectura, con los valores del formato histórico."""
    def __init__(self, modelo, marcas=False):
        self._modelo = modelo
        self._marcas = marcas

    def __len__(self):
        return len(self._modelo._puntos)

    def _valor(self, punto):
        return punto.tipo.value if self._marcas else punto.coordenada

    def __getitem__(self, indice):
        puntos = self._modelo._puntos[indice]
        if isinstance(indice, slice):
            return [self._valor(p) for p in puntos]
        return self._valor(puntos)

    def __iter__(self):
        return (self._valor(p) for p in self._modelo._puntos)

    def copy(self):
        return list(self)


class ModeloMedicion:
    def __init__(self):
        self._puntos = []
        self.coordenadas = _VistaCampo(self)
        self.marcas = _VistaCampo(self, marcas=True)

    @staticmethod
    def _crear(coordenada, marca):
        return PuntoMedicion(coordenada, marca)

    def cargar(self, coordenadas, marcas):
        # Validar antes de sustituir el estado activo.
        puntos = [self._crear(c, m) for c, m in zip(coordenadas, marcas, strict=True)]
        self._puntos = puntos

    def insertar(self, indice, coordenada, marca=False):
        self._puntos.insert(indice, self._crear(coordenada, marca))

    def agregar(self, coordenada, marca=False):
        self._puntos.append(self._crear(coordenada, marca))

    def borrar(self, indice):
        del self._puntos[indice]

    def limpiar(self):
        self._puntos.clear()

    def mover(self, indice, coordenada):
        self._puntos[indice] = replace(self._puntos[indice], coordenada=coordenada)

    def marcar(self, indice, marca):
        self._puntos[indice] = replace(self._puntos[indice], tipo=marca)

    def captura(self):
        return tuple(self._puntos)

    def restaurar(self, captura):
        puntos = list(captura)
        if not all(isinstance(p, PuntoMedicion) for p in puntos):
            raise ValueError("Captura de medición inválida")
        self._puntos = puntos

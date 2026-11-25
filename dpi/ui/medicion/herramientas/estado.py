"""Estado temporal por herramienta, independiente de Qt."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EstadoCalibracion:
    puntos: list = field(default_factory=list)
    items: list = field(default_factory=list)
    objetivo_mm: float | None = None


@dataclass
class EstadoSeleccion:
    puntos: set[int] = field(default_factory=set)
    items: list = field(default_factory=list)
    arrastre: bool = False
    inicio: tuple[float, float] = (0.0, 0.0)
    rectangulo: Any = None
    candidato: int | None = None
    posicion: tuple[float, float] = (0.0, 0.0)

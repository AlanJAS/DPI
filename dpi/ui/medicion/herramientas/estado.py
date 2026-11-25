"""Estado temporal por herramienta, independiente de Qt."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EstadoCalibracion:
    puntos: list = field(default_factory=list)
    items: list = field(default_factory=list)
    objetivo_mm: float | None = None

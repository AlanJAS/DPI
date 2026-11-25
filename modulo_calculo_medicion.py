"""Cálculos geométricos de medición, sin Qt."""
from dataclasses import dataclass
import math
from modulo_modelo_medicion import PuntoMedicion, TipoMarca


def anchos_anillos(coords, marcas, ppm):
    """Adaptador para consumidores del formato histórico."""
    puntos = tuple(PuntoMedicion(c, m) for c, m in zip(coords, marcas, strict=True))
    return anchos_puntos(puntos, ppm)


@dataclass(frozen=True, slots=True)
class AnilloMedido:
    indice_inicio: int
    indice_fin: int
    ancho_mm: float


def calcular_anillos(puntos, ppm):
    """Conserva las reglas de ancho, incluyendo cierre parcial al final o salto."""
    if not math.isfinite(ppm) or ppm <= 0:
        raise ValueError('Escala de medición inválida')
    anillos = []
    acum = 0.0
    inicio = 0
    fin = 0
    for i, (anterior, actual) in enumerate(zip(puntos, puntos[1:]), 1):
        tipo = actual.tipo
        if tipo is TipoMarca.SALTO:
            if acum > 0:
                anillos.append(AnilloMedido(inicio, fin, acum))
            acum = 0.0
            inicio = i
        elif tipo is not TipoMarca.ESPACIO:
            acum += math.dist(anterior.coordenada, actual.coordenada) / ppm
            fin = i
            if tipo is TipoMarca.NORMAL:
                anillos.append(AnilloMedido(inicio, fin, acum))
                acum = 0.0
                inicio = i
    if acum > 0:
        anillos.append(AnilloMedido(inicio, fin, acum))
    return anillos


def anchos_puntos(puntos, ppm):
    return [a.ancho_mm for a in calcular_anillos(puntos, ppm)]


def anios_por_punto(puntos, ppm, medula, corteza, med_a_cor):
    """Años de los puntos y conjunto de índices que cierran un anillo."""
    cierres = {a.indice_fin for a in calcular_anillos(puntos, ppm)}
    n = 0
    anios = []
    for i in range(len(puntos)):
        n += i in cierres
        if i == 0:
            anios.append(medula - 1 if med_a_cor else corteza)
        else:
            anios.append(medula + n - 1 if med_a_cor else corteza - n + 1)
    return anios, cierres


def anios_medicion(n, medula, corteza, med_a_cor):
    return [medula + i if med_a_cor else corteza - i for i in range(n)]


def dist_punto_segmento(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    l2 = (x1 - x2) ** 2 + (y1 - y2) ** 2
    if l2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
    return math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)))

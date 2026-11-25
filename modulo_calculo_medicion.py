"""Cálculos geométricos de medición, sin Qt."""
import math
from modulo_modelo_medicion import PuntoMedicion, TipoMarca


def anchos_anillos(coords, marcas, ppm):
    """Adaptador para consumidores del formato histórico."""
    puntos = tuple(PuntoMedicion(c, m) for c, m in zip(coords, marcas, strict=True))
    return anchos_puntos(puntos, ppm)


def anchos_puntos(puntos, ppm):
    """Calcula anchos desde la única colección de puntos tipados."""
    if not math.isfinite(ppm) or ppm <= 0:
        raise ValueError('Escala de medición inválida')
    distancias = []
    acum = 0.0
    for anterior, actual in zip(puntos, puntos[1:]):
        tipo = actual.tipo
        d = math.dist(anterior.coordenada, actual.coordenada) / ppm
        if tipo is TipoMarca.SALTO:
            if acum > 0:
                distancias.append(acum)
            acum = 0.0
        elif tipo is TipoMarca.ESPACIO:
            continue
        else:
            acum += d
            if tipo is TipoMarca.NORMAL:
                distancias.append(acum)
                acum = 0.0
    if acum > 0:
        distancias.append(acum)
    return distancias


def anios_medicion(n, medula, corteza, med_a_cor):
    return [medula + i if med_a_cor else corteza - i for i in range(n)]

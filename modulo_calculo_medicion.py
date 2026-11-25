"""Cálculos geométricos de medición, sin Qt."""
import math
from modulo_modelo_medicion import TipoMarca


def anchos_anillos(coords, marcas, ppm):
    distancias = []
    acum = 0.0
    for i in range(1, len(coords)):
        tipo = TipoMarca.desde_valor(marcas[i])
        d = math.hypot(coords[i][0]-coords[i-1][0], coords[i][1]-coords[i-1][1]) / ppm
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

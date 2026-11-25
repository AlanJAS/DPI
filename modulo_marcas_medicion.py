"""Componentes de medición de DPI."""
from modulo_modelo_medicion import TipoMarca


def _tipo(val):
    try:
        return TipoMarca.desde_valor(val)
    except ValueError:
        return None

MODO_MEDIR = 1   # botón «Medir»
MODO_ANADIR = MODO_MEDIR   # alias histórico

MODO_CALIBRAR = 2

MODO_MOVER = 3

MODO_SALTO = 4

MODO_INSERTAR = 5

MODO_BORRAR = 6

MODO_AUTODETECT = 7   # Marcar médula y corteza para auto-detección

MODO_ANOMALIA   = 8   # Marcar anomalías sobre anillos ya medidos

MODO_PITH       = 9   # Marcar puntos del arco para estimar médula faltante

MODO_ESPACIO    = 10  # Marcar espacio dentro de un anillo (intra-ring gap)

MODO_EWLW       = 11  # Marcar límite earlywood/latewood dentro de un anillo

MODO_SELECCIONAR = 12  # Seleccionar múltiples anillos para borrar/convertir



def _es_salto_real(val) -> bool:
    """True solo si el segmento es un salto que rompe la cuenta."""
    return _tipo(val) is TipoMarca.SALTO



def _es_espacio(val) -> bool:
    """True si el segmento es un espacio intra-anillo."""
    return _tipo(val) is TipoMarca.ESPACIO



def _es_quiebre_ini(val) -> bool:
    """True si el segmento es inicio de quiebre (suma distancia, no cierra)."""
    return _tipo(val) is TipoMarca.QUIEBRE_INI



def _es_ewlw(val) -> bool:
    """True si el segmento es un límite earlywood/latewood."""
    return _tipo(val) is TipoMarca.EW_LW



def _es_amarillo(val) -> bool:
    """True si el segmento debe dibujarse en amarillo (salto o espacio)."""
    tipo = _tipo(val)
    return tipo is not None and tipo.es_amarillo


def _es_normal(val) -> bool:
    return _tipo(val) is TipoMarca.NORMAL


def _es_quiebre(val) -> bool:
    tipo = _tipo(val)
    return tipo is not None and tipo.es_quiebre


def _excluye_intensidad(val) -> bool:
    tipo = _tipo(val)
    return tipo is not None and tipo.excluye_intensidad


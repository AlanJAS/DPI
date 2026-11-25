# =============================================================================
# constantes.py — Configuración global de la Plataforma Dendrocronológica
# Centraliza todos los valores "mágicos" del proyecto para facilitar
# mantenimiento y futuros ajustes sin buscar en múltiples archivos.
# =============================================================================

from dpi.medicion.constantes import (
    DPI_DEFECTO,
    MM_POR_PULGADA,
    PIXELES_POR_MM_DEFECTO,
)

from dpi.formatos.constantes import (
    TUCSON_VALOR_FIN,
    TUCSON_VALOR_FALTANTE,
    TUCSON_VALOR_999,
    TUCSON_MAX_CHARS_ID,
    TUCSON_DIVISOR,
)

# --- Historial / Deshacer ---
MAX_PASOS_HISTORIAL = 50

# --- Tolerancias de interacción (en píxeles de pantalla, se escalan con zoom) ---
TOLERANCIA_CLICK_PUNTO = 15    # px — para seleccionar/arrastrar/borrar un punto
TOLERANCIA_CLICK_SEGMENTO = 20 # px — para insertar un punto sobre un segmento

from dpi.ciencia.constantes import (
    VENTANA_COFECHADO_DEFECTO, OVERLAP_MINIMO_ANALISIS, OVERLAP_MINIMO_GRAFICO,
    OVERLAP_MINIMO_FLOTANTE, RANGO_SHIFT_SIMULADOR, UMBRAL_ANCLA_DEFECTO,
    UMBRAL_DESFASE_DEFECTO, UMBRAL_MEJORA_DEFECTO, VENTANA_SUPRESION_ANOMALIAS,
)

from dpi.ui.colores import (
    COLORES_SERIES,
    COLORES_SERIES_INACTIVAS,
    COLOR_PUNTO_ACTIVO,
    COLOR_LINEA_ACTIVA,
    COLOR_SALTO,
    COLOR_GUIA,
    COLOR_CALIBRACION,
    COLOR_PUNTO_INACTIVO,
    COLOR_EWLW,
    INTERVALO_MARCADOR_DECADA,
    INTERVALO_MARCADOR_CINCUENTENA,
    INTERVALO_MARCADOR_CENTENA,
    TIPOS_ANOMALIA,
)

# =============================================================================
# --- Identidad de la aplicación y recursos ---
# =============================================================================
from dpi.version import APP_NOMBRE, APP_SIGLA, APP_SUITE, VERSION
from dpi.ui.recursos import ruta_icono, icono_app, pixmap_icono, _base_recursos

# =============================================================================
# constantes.py — Configuración global de la Plataforma Dendrocronológica
# Centraliza todos los valores "mágicos" del proyecto para facilitar
# mantenimiento y futuros ajustes sin buscar en múltiples archivos.
# =============================================================================

# --- Resolución y escala ---
DPI_DEFECTO = 2400
MM_POR_PULGADA = 25.4
PIXELES_POR_MM_DEFECTO = DPI_DEFECTO / MM_POR_PULGADA  # ≈ 94.49

# --- Formato Tucson (.rwl) ---
TUCSON_VALOR_FIN = -9999       # Marca fin de serie
TUCSON_VALOR_FALTANTE = 9999   # Año sin dato
TUCSON_VALOR_999 = 998         # Legado: no usar para codificar ni decodificar
TUCSON_MAX_CHARS_ID = 8        # Longitud máxima del identificador de serie
TUCSON_DIVISOR = 1000.0        # Unidades de milésimas por mm

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

# --- Tipos de anomalía: clave → (icono, etiqueta, color_hex) ---
# Fuente única de verdad — importar desde aquí en todos los módulos.
TIPOS_ANOMALIA: dict[str, tuple[str, str, str]] = {
    "frost_ring":  ("❄",  "Frost ring",    "#00BFFF"),
    "light_ring":  ("☀",  "Light ring",    "#FFD700"),
    "fire":        ("🔥", "Fuego",         "#FF4500"),
    "compression": ("▼",  "Comp. madera",  "#FF6600"),
    "tension":     ("▲",  "Tensión",       "#9933CC"),
    "false_ring":  ("⊘",  "Falso anillo",  "#3399FF"),
    "wedge":       ("◆",  "Cuña",          "#CCAA00"),
    "resin":       ("●",  "Resina",        "#8B4513"),
    "event":       ("★",  "Otro/Genérico", "#CC0000"),
}

# --- Colores (RGB tuples para pyqtgraph) ---
COLORES_SERIES = [
    (255, 51, 51),
    (51, 136, 255),
    (51, 204, 51),
    (255, 204, 51),
    (204, 51, 255),
]
COLORES_SERIES_INACTIVAS = [
    (51, 204, 51),
    (255, 204, 51),
    (204, 51, 255),
    (255, 102, 0),
]

COLOR_PUNTO_ACTIVO = "#FF3333"
COLOR_LINEA_ACTIVA = "#3388FF"
COLOR_SALTO = "#FFD700"
COLOR_GUIA = "#aaaaaa"
COLOR_CALIBRACION = "#33FF33"
COLOR_PUNTO_INACTIVO = "#5cb85c"
COLOR_EWLW           = "#FF8C00"   # naranja — límite earlywood/latewood

# --- Marcadores de décadas en la imagen ---
INTERVALO_MARCADOR_DECADA = 10
INTERVALO_MARCADOR_CINCUENTENA = 50
INTERVALO_MARCADOR_CENTENA = 100

# =============================================================================
# --- Identidad de la aplicación y recursos ---
# =============================================================================
import os as _os
import sys as _sys

from dpi.version import APP_NOMBRE, APP_SIGLA, APP_SUITE, VERSION

# Nombres y ubicaciones posibles del ícono. Se prueban en orden porque el
# archivo vive en la raíz al correr desde el código fuente, y dentro de
# "iconos/" en el empaquetado de Windows.
_CANDIDATOS_ICONO = (
    _os.path.join("iconos", "dpi.ico"),
    "dpi.ico",
    "dpi_icon.ico",
    _os.path.join("iconos", "dpi_icon.ico"),
    "dpi.png",
    _os.path.join("iconos", "dpi.png"),
)


def _base_recursos() -> str:
    """Carpeta donde buscar recursos: _MEIPASS si está empaquetado, si no
    la carpeta de este archivo."""
    base = getattr(_sys, "_MEIPASS", None)
    if base:
        return base
    return _os.path.dirname(_os.path.abspath(__file__))


def ruta_icono() -> str:
    """Ruta absoluta al ícono de la aplicación, o cadena vacía si no existe."""
    base = _base_recursos()
    for nombre in _CANDIDATOS_ICONO:
        ruta = _os.path.join(base, nombre)
        if _os.path.exists(ruta):
            return ruta
    return ""


def icono_app():
    """QIcon de la aplicación (vacío si no se encontró el archivo)."""
    from PyQt6.QtGui import QIcon
    ruta = ruta_icono()
    return QIcon(ruta) if ruta else QIcon()


def pixmap_icono(lado: int = 200):
    """QPixmap del ícono al tamaño pedido, tomando la MAYOR resolución
    interna disponible. QPixmap(archivo.ico) carga solo la variante de
    16x16, que al escalarla sale pixelada."""
    from PyQt6.QtCore import Qt, QSize
    from PyQt6.QtGui import QPixmap
    ruta = ruta_icono()
    if not ruta:
        return QPixmap()
    ico = icono_app()
    tamanos = ico.availableSizes()
    if tamanos:
        mayor = max(tamanos, key=lambda s: s.width() * s.height())
        pix = ico.pixmap(mayor)
    else:
        pix = QPixmap(ruta)
    if pix.isNull():
        return pix
    return pix.scaled(QSize(lado, lado),
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)

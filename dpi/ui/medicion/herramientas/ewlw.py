"""Operaciones de interfaz extraídas; reciben explícitamente el contexto de la vista."""
from dpi.medicion.modelo import TipoMarca
from dpi.medicion.marcas import _es_amarillo, _es_ewlw

def _paso_ewlw(self, x: float, y: float):
    """
    Modo EW/LW: clic sobre la línea azul del camino.
    Inserta un punto "ew_lw" (tick naranja) que divide el anillo
    en earlywood (izquierda) y latewood (derecha).
    Un anillo puede tener como máximo un límite EW/LW.
    La distancia total del anillo no cambia (EW+LW = total).
    Esc cancela. Ctrl+Z deshace.
    """
    coords = self.coordenadas_anillos
    hit = self._segmento_mas_cercano(x, y) if len(coords) >= 2 else None
    if hit is None:
        try:
            self.estado_cambiado.emit(
                "🍂 Haz clic sobre la línea azul del anillo a dividir.")
        except Exception:
            pass
        return

    seg_idx, t, _ = hit
    # Verificar que el segmento no sea ya un tramo de espacio/quiebre
    val_seg = self.es_salto[seg_idx + 1] if seg_idx + 1 < len(self.es_salto) else False
    if _es_amarillo(val_seg):
        try:
            self.estado_cambiado.emit(
                "🍂 No se puede insertar EW/LW en un tramo de quiebre o salto.")
        except Exception:
            pass
        return

    # Verificar que no haya ya un ew_lw en este anillo
    # (buscar el anillo que contiene seg_idx)
    ini_anillo = seg_idx
    while ini_anillo > 0 and self.es_salto[ini_anillo] is not False:
        ini_anillo -= 1
    fin_anillo = seg_idx + 1
    while fin_anillo < len(coords) and self.es_salto[fin_anillo] is not False:
        fin_anillo += 1
    for j in range(ini_anillo + 1, fin_anillo):
        if j < len(self.es_salto) and _es_ewlw(self.es_salto[j]):
            try:
                self.estado_cambiado.emit(
                    "🍂 Este anillo ya tiene un límite EW/LW. "
                    "Usa 🖐 Mover para reposicionarlo.")
            except Exception:
                pass
            return

    # Calcular punto exacto sobre el segmento
    x1, y1 = coords[seg_idx]
    x2, y2 = coords[seg_idx + 1]
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)

    self.guardar_en_historial()
    self.modelo_medicion.insertar(seg_idx + 1, (px, py), TipoMarca.EW_LW)

    self.recalcular_todas_las_distancias()
    self.progreso_modificado.emit()
    try:
        self.estado_cambiado.emit(
            "🍂 Límite EW/LW insertado. Usa 🖐 Mover para ajustarlo. "
            "Ctrl+Z para deshacer.")
    except Exception:
        pass

"""Operaciones de interfaz; reciben explícitamente su widget propietario."""
import math
from modulo_calculo_medicion import anios_por_punto
from PyQt6.QtGui import QPen, QColor, QBrush
from constantes import INTERVALO_MARCADOR_DECADA, INTERVALO_MARCADOR_CINCUENTENA, INTERVALO_MARCADOR_CENTENA, COLOR_PUNTO_INACTIVO, TIPOS_ANOMALIA
from modulo_marcas_medicion import _es_amarillo, _es_espacio, _es_ewlw, _es_quiebre_ini, _es_salto_real


def redibujar_todo(self):
    """Elimina todos los elementos gráficos y los reconstruye desde el estado."""
    for item in self._items_puntos + self._items_lineas + self._items_textos:
        self.scene().removeItem(item)
    self._items_puntos.clear()
    self._items_lineas.clear()
    self._items_textos.clear()

    # Ajustar grosor de los pens de tick según zoom actual.
    # Esto se hace ANTES del loop para que todos los ticks usen el
    # ancho correcto. Los pens son atributos persistentes; modificar
    # su ancho aquí afecta todo lo que se dibuje en esta pasada.
    grosor_actual = self._grosor_tick_zoom()
    self._pen_punto.setWidthF(grosor_actual)
    self._pen_salto.setWidthF(grosor_actual)
    self._pen_ewlw.setWidthF(grosor_actual)
    # Para el camino activo usamos los mismos pens (con el ancho ya ajustado).
    # Los nombres con sufijo "_zoom" son alias semánticos para claridad.
    self._pen_punto_zoom = self._pen_punto
    self._pen_salto_zoom = self._pen_salto
    self._pen_ewlw_zoom = self._pen_ewlw

    # Tracker para filtro de overlap: bbox del último label dibujado.
    # Se compara con cada nuevo candidato para evitar superposiciones.
    self._ultimo_bbox_label_activo = None

    try:
        anio_medula = self._pestana.spin_medula.value()
        anio_corteza = self._pestana.spin_corteza.value()
        medula_a_corteza = self._pestana.combo_dir.currentIndex() == 0
    except Exception:
        # La vista puede redibujar antes de que los widgets de la pestaña
        # estén completamente inicializados; usamos valores neutros como fallback.
        anio_medula, anio_corteza, medula_a_corteza = 0, 0, True

    anios, cierres = anios_por_punto(self.modelo_medicion.captura(),
        self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)
    for i, coord in enumerate(self.coordenadas_anillos):
        val = self.es_salto[i] if i > 0 else False
        es_amar = _es_amarillo(val)
        es_corte = _es_salto_real(val)
        anio = anios[i]

        # Línea de conexión: ew_lw usa azul (cuenta como distancia)
        if i > 0:
            pen = self._pen_linea if _es_ewlw(val) else (
                self._pen_salto if es_amar else self._pen_linea)
            prev = self.coordenadas_anillos[i - 1]
            linea_conexion = self.scene().addLine(prev[0], prev[1], coord[0], coord[1], pen)
            # zValue=1 para que la línea quede DEBAJO de los ticks (zValue=2).
            # El usuario quiere los límites siempre prominentes.
            linea_conexion.setZValue(1)
            self._items_lineas.append(linea_conexion)

        # Tick perpendicular
        # Color: naranja si es ew_lw, amarillo si es espacio/salto o inicio quiebre,
        # rojo en cualquier otro caso (límite normal de anillo).
        # IMPORTANTE: TODOS los límites se muestran SIEMPRE. Lo que se
        # adapta con el zoom es el ANCHO del tick (más fino al alejar),
        # no su existencia. Esto evita el "muro rojo" al alejar pero
        # mantiene visible cada límite — fundamental para no perder
        # información en series largas.
        val_sale = self.es_salto[i + 1] if i + 1 < len(self.es_salto) else False
        if _es_ewlw(val):
            pen_tick = self._pen_ewlw_zoom
        elif es_amar or _es_espacio(val_sale):
            pen_tick = self._pen_salto_zoom
        else:
            pen_tick = self._pen_punto_zoom
        p1_t, p2_t = self._perp_tick(self.coordenadas_anillos, i)
        p = self.scene().addLine(p1_t[0], p1_t[1], p2_t[0], p2_t[1], pen_tick)
        # zValue=2 → ticks ON TOP de la línea de conexión (zValue=1).
        # Los límites son lo más importante y deben ser visibles aun
        # cuando se cruzan con la línea azul.
        p.setZValue(2)
        if _es_ewlw(val):
            etiqueta = "EW/LW"
        elif _es_espacio(val):
            etiqueta = "Espacio"
        elif _es_quiebre_ini(val):
            etiqueta = "Quiebre"
        elif es_corte:
            etiqueta = "Salto"
        else:
            etiqueta = str(anio)
        p.setToolTip(etiqueta)
        p.anio_texto = etiqueta
        self._items_puntos.append(p)

        # Etiquetas de año — densidad adaptativa según zoom.
        # _escala_vista() = 1/m11: PEQUEÑO = zoom acercado, GRANDE = alejado.
        # Acercado (escala < 0.3) → cada año individual
        # Medio    (0.3–1.5)      → cada 5 años
        # Alejado  (> 1.5)        → solo décadas
        # En todos los casos el font-size se ajusta para ser siempre legible.
        if i in cierres:
            escala = self._escala_vista()
            mostrar = self._filtro_densidad_anio(anio, escala)

            if mostrar:
                # Colocar la etiqueta sobre el segmento AZUL que cierra
                # el anillo actual: punto i-1 → punto i.
                coord_inicio = self.coordenadas_anillos[i - 1]
                coord_sig = coord

                # Filtro de OVERLAP: si el label estimado se solapa con
                # el último aceptado, lo saltamos. El usuario lo dijo
                # claro: nunca dos números encima — preferible que
                # desaparezcan intercaladamente a que se ilegibles.
                bbox_nuevo = self._estimar_bbox_label_pantalla(
                    str(anio), coord_sig, coord_inicio)
                if (self._ultimo_bbox_label_activo is None
                        or not self._labels_se_solapan(
                            self._ultimo_bbox_label_activo, bbox_nuevo)):
                    if anio % INTERVALO_MARCADOR_DECADA == 0:
                        self._items_textos.append(
                            self._crear_marcador_decada(anio, coord_inicio, coord_sig)
                        )
                    else:
                        self._items_textos.append(
                            self._crear_etiqueta_anio(str(anio), "#cccccc",
                                                       coord_inicio, coord_sig)
                        )
                    self._ultimo_bbox_label_activo = bbox_nuevo

    self._dibujar_anomalias()


def _dibujar_anomalias(self):
    """Dibuja marcas de color sobre los ticks de anillos con anomalía registrada."""
    for item in self._items_anomalias:
        self.scene().removeItem(item)
    self._items_anomalias.clear()

    if not self.anomalias or not self.coordenadas_anillos:
        return

    # Construir mapa anio→indice
    anio_a_idx = {}
    try:
        anio_medula = self._pestana.spin_medula.value()
        anio_corteza = self._pestana.spin_corteza.value()
        medula_a_corteza = self._pestana.combo_dir.currentIndex() == 0
    except Exception:
        return

    anillos_validos = 0
    for i, coord in enumerate(self.coordenadas_anillos):
        val = self.es_salto[i] if i > 0 else False
        val_sale_a = self.es_salto[i + 1] if i + 1 < len(self.es_salto) else False
        if (i > 0
                and not _es_amarillo(val)
                and not _es_ewlw(val)
                and not _es_espacio(val_sale_a)):
            anillos_validos += 1
        if medula_a_corteza:
            anio = (anio_medula + anillos_validos - 1) if i > 0 else (anio_medula - 1)
        else:
            anio = (anio_corteza - anillos_validos + 1) if i > 0 else anio_corteza
        anio_a_idx[anio] = i

    escala = self._escala_vista()
    for anio, tipo in self.anomalias.items():
        idx = anio_a_idx.get(anio)
        if idx is None:
            continue
        coord = self.coordenadas_anillos[idx]
        color = TIPOS_ANOMALIA.get(tipo, ("", "", "#CC0000"))[2]
        etiqueta_tipo = TIPOS_ANOMALIA.get(tipo, ("", tipo, ""))[1]

        # 1) Línea perpendicular LARGA y GRUESA, con borde oscuro detrás
        #    para que contraste sobre la madera a cualquier zoom. El largo
        #    es en píxeles de pantalla (constante con el zoom) y el ancho
        #    es cosmético (constante en pantalla).
        p1, p2 = self._perp_tick(self.coordenadas_anillos, idx,
                                 largo_px_pantalla=48.0)
        pen_borde = QPen(QColor("#000000"))
        pen_borde.setCosmetic(True); pen_borde.setWidthF(8.0)
        item_borde = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen_borde)
        item_borde.setZValue(9)
        item_borde.setToolTip(f"{anio}: {etiqueta_tipo}")
        self._items_anomalias.append(item_borde)

        pen = QPen(QColor(color))
        pen.setCosmetic(True); pen.setWidthF(4.0)
        item = self.scene().addLine(p1[0], p1[1], p2[0], p2[1], pen)
        item.setZValue(11)
        item.setToolTip(f"{anio}: {etiqueta_tipo}")
        self._items_anomalias.append(item)

        # 2) Marcador circular relleno sobre el punto del anillo, con
        #    borde blanco para destacar. Radio constante en pantalla
        #    (≈9 px) usando la escala vista→pantalla.
        r = 9.0 * escala
        cx, cy = coord
        pen_circ = QPen(QColor("#ffffff"))
        pen_circ.setCosmetic(True); pen_circ.setWidthF(2.5)
        brush = QBrush(QColor(color))
        circ = self.scene().addEllipse(
            cx - r, cy - r, 2 * r, 2 * r, pen_circ, brush)
        circ.setZValue(12)
        circ.setToolTip(f"{anio}: {etiqueta_tipo}")
        self._items_anomalias.append(circ)


def _crear_marcador_decada(
    self,
    anio: int,
    coord_actual: tuple,
    coord_anterior: tuple,
):
    if anio % INTERVALO_MARCADOR_CENTENA == 0:
        texto, color = f"••• {anio}", "#FFD700"
    elif anio % INTERVALO_MARCADOR_CINCUENTENA == 0:
        texto, color = f"•• {anio}", "#5cb85c"
    else:
        texto, color = f"• {anio}", "#ffffff"

    return self._crear_etiqueta_anio(texto, color, coord_actual, coord_anterior)


def _filtro_densidad_anio(self, anio: int, escala: float) -> bool:
    """Decide si mostrar la etiqueta de un año según el nivel de zoom.

    5 niveles de zoom para evitar recargar la imagen cuando se aleja:
      - Muy acercado (escala < 0.3): cada año
      - Acercado    (0.3 ≤ escala < 1.5): cada 5
      - Medio       (1.5 ≤ escala < 3.5): cada 10
      - Alejado     (3.5 ≤ escala < 7.0): cada 50
      - Muy alejado (escala ≥ 7.0): cada 100

    Acéptese también años 0 y negativos (Schulman) usando módulo positivo.
    """
    a = abs(anio)
    if escala < 0.3:
        return True
    elif escala < 1.5:
        return a % 5 == 0
    elif escala < 3.5:
        return a % 10 == 0
    elif escala < 7.0:
        return a % 50 == 0
    else:
        return a % 100 == 0


def _estimar_bbox_label_pantalla(
    self,
    texto: str,
    coord_actual: tuple,
    coord_anterior: tuple,
    offset_perpendicular_px: float = 8.0,
) -> tuple:
    """Estima la bounding box del label en píxeles de PANTALLA sin
    dibujarlo. Devuelve (cx, cy, ancho, alto) en píxeles relativos al
    origen de la escena dividido por la escala — sirve para chequeos
    de overlap entre labels consecutivos.

    Usa QFontMetrics para medir el ANCHO REAL del texto (antes el
    cálculo simple `chars * 8 + 6` era demasiado conservador para
    fuente Arial Bold y subestimaba los labels — sobre todo cuando el
    zoom era alto y el `fs_pantalla` efectivo superaba los 14 px,
    causando la superposición visible que reportó el usuario).
    """
    from PyQt6.QtGui import QFont, QFontMetrics

    escala = self._escala_vista()

    # Font-size en escena (igual cálculo que _crear_etiqueta_anio).
    # El piso de 8 evita texto microscópico, pero implica que cuando
    # hay mucho zoom-in (escala chica) el render en PANTALLA es más
    # grande que 14 px → labels más anchos de lo esperado.
    fs_escena = max(8, int(14 * escala))
    # Tamaño efectivo en pantalla del font:
    #   fs_escena = font-size en unidades de escena
    #   m11 = 1/escala → pantalla = escena * m11 = escena / escala
    fs_pantalla = fs_escena / escala if escala > 1e-9 else fs_escena

    # Medir el ancho real del texto con QFontMetrics
    font = QFont("Arial")
    font.setBold(True)
    font.setPixelSize(max(8, int(round(fs_pantalla))))
    fm = QFontMetrics(font)
    ancho_texto_px = fm.horizontalAdvance(texto)
    alto_texto_px = fm.height()

    # Padding HTML (1px arriba/abajo, 3px izq/der) + documentMargin
    # del QGraphicsTextItem (default 4 px cada lado).
    ancho_px = ancho_texto_px + 6 + 8  # HTML pad horizontal + doc margin
    alto_px = alto_texto_px + 2 + 8     # HTML pad vertical + doc margin

    # Punto medio del segmento en escena
    mid_x = (coord_actual[0] + coord_anterior[0]) / 2
    mid_y = (coord_actual[1] + coord_anterior[1]) / 2

    # Offset perpendicular dinámico (misma fórmula que _crear_etiqueta_anio)
    if offset_perpendicular_px > 0:
        seg_dx = coord_actual[0] - coord_anterior[0]
        seg_dy = coord_actual[1] - coord_anterior[1]
        seg_norm = math.hypot(seg_dx, seg_dy)
        if seg_norm > 1e-6:
            perp_dx = seg_dy / seg_norm
            perp_dy = -seg_dx / seg_norm
            extension_perp_px = (
                abs(perp_dx) * ancho_px / 2.0
                + abs(perp_dy) * alto_px / 2.0
            )
            offset_total_px = extension_perp_px + offset_perpendicular_px
            offset_escena = offset_total_px * escala
            mid_x += perp_dx * offset_escena
            mid_y += perp_dy * offset_escena

    # Posición en pantalla (proxy: solo las DIFERENCIAS entre labels
    # son relevantes para el test de overlap)
    cx_pantalla = mid_x / escala if escala > 1e-9 else mid_x
    cy_pantalla = mid_y / escala if escala > 1e-9 else mid_y
    return (cx_pantalla, cy_pantalla, ancho_px, alto_px)


def _labels_se_solapan(self, bbox_a: tuple, bbox_b: tuple,
                        margen_px: float = 2.0) -> bool:
    """True si dos bboxes (cx, cy, ancho, alto) en pantalla se tocan
    con menos de `margen_px` de espacio entre ellas. Test AABB.
    """
    cx_a, cy_a, w_a, h_a = bbox_a
    cx_b, cy_b, w_b, h_b = bbox_b
    dx = abs(cx_a - cx_b)
    dy = abs(cy_a - cy_b)
    sep_x_min = (w_a + w_b) / 2 + margen_px
    sep_y_min = (h_a + h_b) / 2 + margen_px
    return dx < sep_x_min and dy < sep_y_min


def _crear_etiqueta_anio(
    self,
    texto: str,
    color: str,
    coord_actual: tuple,
    coord_anterior: tuple,
    offset_perpendicular_px: float = 8.0,
    bg_color: str = "rgba(0,0,0,0.60)",
):
    """
    Crea una etiqueta de texto cuyo tamaño en pantalla es siempre ~14 px,
    independientemente del nivel de zoom.

    OFFSET PERPENDICULAR DINÁMICO:
    El parámetro `offset_perpendicular_px` es solo el MARGEN extra
    respecto al borde más cercano del label. El offset real se calcula
    como: extensión_perpendicular_del_label + margen.

    Por qué:
      - Si el segmento es horizontal, la perpendicular es vertical;
        el label se desplaza hacia arriba y la dimensión relevante
        es su ALTURA → el offset = altura/2 + margen.
      - Si el segmento es vertical, la perpendicular es horizontal;
        el label se desplaza lateralmente y la dimensión relevante
        es su ANCHO → el offset = ancho/2 + margen. Esto es crítico
        porque sin ello los números ("1888", "1887"...) tapaban la
        línea azul vertical.
      - En diagonales, la extensión se compone de ambas dimensiones
        según el seno/coseno del ángulo del segmento.

    Geometría: para una caja UPRIGHT de tamaño W×H, su extensión en
    la dirección del vector perpendicular unitario (perp_dx, perp_dy)
    es:  |perp_dx| · W/2  +  |perp_dy| · H/2
    """
    # Tamaño objetivo en píxeles de pantalla
    PX_OBJETIVO = 14
    fs = max(8, int(PX_OBJETIVO * self._escala_vista()))

    item = self.scene().addText("")
    item.setHtml(
        f"<div style='background-color:{bg_color}; color:{color}; "
        f"padding:1px 3px; border-radius:3px; font-weight:bold; "
        f"font-family:Arial; font-size:{fs}px; white-space:nowrap;'>{texto}</div>"
    )
    rect = item.boundingRect()
    mid_x = (coord_actual[0] + coord_anterior[0]) / 2
    mid_y = (coord_actual[1] + coord_anterior[1]) / 2

    if offset_perpendicular_px > 0:
        seg_dx = coord_actual[0] - coord_anterior[0]
        seg_dy = coord_actual[1] - coord_anterior[1]
        seg_norm = math.hypot(seg_dx, seg_dy)
        if seg_norm > 1e-6:
            # Perpendicular CW al segmento (en Qt y crece hacia abajo,
            # CW pone la etiqueta "arriba" para segmentos horizontales
            # de izq a der)
            perp_dx = seg_dy / seg_norm
            perp_dy = -seg_dx / seg_norm

            # Tamaño del label en píxeles de PANTALLA.
            # El bounding rect está en escena; dividimos por escala
            # para convertir a píxeles de pantalla (porque el font
            # se calculó como 14 * escala).
            escala = self._escala_vista()
            rect_w_px = rect.width() / escala if escala > 0 else rect.width()
            rect_h_px = rect.height() / escala if escala > 0 else rect.height()

            # Extensión del label en la dirección perpendicular
            # al segmento (geometría AABB proyectada sobre un eje).
            extension_perp_px = (
                abs(perp_dx) * rect_w_px / 2.0
                + abs(perp_dy) * rect_h_px / 2.0
            )

            # Offset total = extensión necesaria + margen libre.
            # Así garantizamos que el borde del label queda a
            # `offset_perpendicular_px` de la línea, sin importar
            # la orientación del segmento.
            offset_total_px = extension_perp_px + offset_perpendicular_px
            offset_escena = offset_total_px * escala

            mid_x += perp_dx * offset_escena
            mid_y += perp_dy * offset_escena

    item.setPos(mid_x - rect.width() / 2, mid_y - rect.height() / 2)
    return item


def cargar_caminos_inactivos(self, caminos: dict):
    # Cachear los datos: necesitamos volver a llamar a esta función
    # cuando cambia el zoom (para que las etiquetas de año y los grosores
    # de tick se rerenderan con la nueva escala). Sin esto los labels
    # viejos quedaban con el tamaño en escena de un zoom anterior.
    self._caminos_inactivos_data = dict(caminos)

    # Limpiar items previos (puntos, líneas Y textos)
    for visuales in self.items_caminos_inactivos.values():
        items_a_remover = (
            visuales.get("puntos", [])
            + visuales.get("lineas", [])
            + visuales.get("textos", [])
        )
        for item in items_a_remover:
            try:
                self.scene().removeItem(item)
            except Exception:
                pass
    self.items_caminos_inactivos.clear()

    # Grosor de tick adaptado al zoom (mismo helper que el camino activo)
    grosor = self._grosor_tick_zoom()

    pen_p = QPen(QColor(COLOR_PUNTO_INACTIVO))
    pen_p.setCosmetic(True); pen_p.setWidthF(grosor)
    brush_p = QBrush(QColor(COLOR_PUNTO_INACTIVO))
    pen_l = QPen(QColor("#80c080"))
    pen_l.setCosmetic(True); pen_l.setWidthF(grosor)

    escala = self._escala_vista()

    for nombre, datos in caminos.items():
        coords, saltos = datos.coordenadas, datos.marcas
        anio_medula = datos.anio_medula
        anio_corteza = datos.anio_corteza
        medula_a_corteza = (datos.dir_idx == 0)

        puntos, lineas, textos = [], [], []
        pen_tick_in = QPen(QColor(COLOR_PUNTO_INACTIVO))
        pen_tick_in.setCosmetic(True); pen_tick_in.setWidthF(grosor)

        anios_por_idx, cierres = anios_por_punto(datos.puntos,
            self.pixeles_por_mm, anio_medula, anio_corteza, medula_a_corteza)

        # Primera pasada: dibujar TODOS los ticks y líneas (sin filtro).
        # El grosor ya está adaptado al zoom para evitar saturación.
        # Z-values: línea de conexión por debajo del tick (igual que el
        # camino activo) para que los límites siempre sean visibles.
        for i, c in enumerate(coords):
            # Línea de conexión primero (queda detrás del tick)
            if i > 0:
                pen = self._pen_salto if _es_amarillo(saltos[i]) else pen_l
                linea_conexion = self.scene().addLine(
                    coords[i - 1][0], coords[i - 1][1], c[0], c[1], pen)
                linea_conexion.setZValue(1)  # debajo de los ticks
                lineas.append(linea_conexion)
            # Tick perpendicular — SIEMPRE se dibuja, sin filtro.
            # El grosor se adapta vía pen_tick_in (ya ajustado al zoom).
            t1, t2 = self._perp_tick(coords, i, largo_px_pantalla=22.0)
            tick = self.scene().addLine(t1[0], t1[1], t2[0], t2[1], pen_tick_in)
            tick.setZValue(2)  # arriba de la línea de conexión
            puntos.append(tick)

        # Segunda pasada: etiquetas de año.
        # ESTAS SÍ se filtran por densidad (el helper compartido),
        # porque mostrar todos los números a la vez no aporta valor
        # cuando están comprimidos a pixeles. Además, filtro de
        # OVERLAP por bbox para evitar superposiciones (mismo
        # comportamiento que el camino activo).
        ultimo_bbox_inactivo = None
        for i in range(1, len(coords)):
            if i not in cierres:
                continue
            anio = anios_por_idx[i]
            mostrar = self._filtro_densidad_anio(anio, escala)

            if mostrar:
                # Chequeo de overlap antes de crear el label
                bbox_nuevo = self._estimar_bbox_label_pantalla(
                    str(anio), coords[i], coords[i - 1])
                if (ultimo_bbox_inactivo is not None
                        and self._labels_se_solapan(ultimo_bbox_inactivo,
                                                     bbox_nuevo)):
                    continue
                # Mismo método que el camino activo: solo cambian los
                # colores del texto. Color base verde claro para años
                # normales y verde más brillante para décadas — análogo
                # a "#cccccc" vs blanco del activo. El fondo negro por
                # defecto se mantiene para que el comportamiento de zoom
                # / lectura sea idéntico al camino activo (que el usuario
                # validó).
                color_etiqueta = "#a0d0a0" if anio % INTERVALO_MARCADOR_DECADA == 0 else "#80c080"
                item_txt = self._crear_etiqueta_anio(
                    str(anio),
                    color_etiqueta,
                    coord_actual=coords[i],
                    coord_anterior=coords[i - 1],
                )
                textos.append(item_txt)
                ultimo_bbox_inactivo = bbox_nuevo

        self.items_caminos_inactivos[nombre] = {
            "puntos": puntos,
            "lineas": lineas,
            "textos": textos,
        }

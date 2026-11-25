"""Control de herramientas de medición con dependencias explícitas."""
import os
import logging
from modulo_dialogos_archivo import ultima_carpeta
from modulo_formatos import _escribir_tucson
import math
import cv2
import numpy as np
from modulo_modelo_medicion import PuntoMedicion, TipoMarca
import pandas as pd
import pyqtgraph as pg
from modulo_formatos import _escribir_excel
from PyQt6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QMessageBox, QDialog
from PyQt6.QtGui import QPen, QColor, QBrush
from PyQt6.QtCore import Qt
import estilos_graficos as _gr
from modulo_intensidad import extraer_intensidad_por_anillo, escribir_rwl_intensidad, DialogoConfigBI, DialogoGuardarBI
from modulo_intensidad_nucleo import valores_intensidad
from modulo_pith import estimar_anillos_faltantes, DialogoMetodoPith, DialogoEstimacionPith
from modulo_pith_nucleo import distancia_faltante_dap
logger = logging.getLogger(__name__)
from modulo_marcas_medicion import ModoMedicion, _es_salto_real, _es_normal, _es_espacio, _es_ewlw, _es_amarillo
from modulo_ewlw import detectar_ewlw_imagen, calcular_anchos_ewlw
from modulo_worker_medicion import _Worker, _DialogoProgreso
def _ultima_carpeta(nueva_ruta: str | None = None) -> str:
    return ultima_carpeta("ultima_carpeta", nueva_ruta)


from modulo_banda_intensidad_ui import BandaIntensidad


class ControlMedicionEspecial:
    """Coordina Pith, EW/LW e intensidad sin conocer la pestaña de medición.

    La vista, los controles, las consultas y las acciones son dependencias
    explícitas. El padre Qt se utiliza únicamente para los diálogos.
    """

    def __init__(self, *, parent, vista, datos_medidos, serie_maestra, imagen,
                 ruta, set_modo, guardar_estado, guardar_sidecar, label_estado,
                 spin_medula, spin_corteza, combo_dir, check_tiene_medula,
                 btn_pith, btn_deshacer_pith, btn_mostrar_banda, btn_graficar_bi,
                 btn_guardar_bi, input_codigo):
        self._parent = parent
        self.vista = vista
        self._obtener_mediciones = datos_medidos
        self._obtener_maestra = serie_maestra
        self._obtener_imagen = imagen
        self._obtener_ruta = ruta
        self.set_modo = set_modo
        self._guardar_estado = guardar_estado
        self._guardar_sidecar_anom = guardar_sidecar
        self.label_estado = label_estado
        self.spin_medula = spin_medula
        self.spin_corteza = spin_corteza
        self.combo_dir = combo_dir
        self.check_tiene_medula = check_tiene_medula
        self.btn_pith = btn_pith
        self.btn_deshacer_pith = btn_deshacer_pith
        self.btn_mostrar_banda = btn_mostrar_banda
        self.btn_graficar_bi = btn_graficar_bi
        self.btn_guardar_bi = btn_guardar_bi
        self.input_codigo = input_codigo
        self._pith_estimacion = None
        self._pith_undo = None
        self._bi_datos = []
        self._bi_banda = 30
        self._bi_porcentaje = 100
        self._bi_alineacion = "centro"
        self._bi_canal_vis = "B"
        self._bi_canales = ["B", "G", "R", "Gray"]
        self._banda_intensidad = BandaIntensidad()
        self._pith_metodo = "arco"
        self._pith_n_int = 5
        self._pith_usar_ref = False
        self._pith_dap_mm = 200.0
        self._pith_metodo_calculo = "rg"
        self._bi_worker = None
        self._ewlw_worker = None

    @property
    def datos_medidos(self):
        return self._obtener_mediciones()

    @property
    def serie_maestra(self):
        return self._obtener_maestra()

    @property
    def _img_bgr_original(self):
        return self._obtener_imagen()

    @property
    def ruta_imagen_actual(self):
        return self._obtener_ruta()

    @property
    def configuracion_pith(self):
        return self._pith_n_int, self._pith_metodo_calculo

    @property
    def estimacion(self):
        return dict(self._pith_estimacion) if self._pith_estimacion else None

    @property
    def tareas_en_curso(self):
        return any(w is not None and w.isRunning()
                   for w in (self._ewlw_worker, self._bi_worker))

    def restaurar_estimacion(self, datos):
        if not datos.get("pith_estimated"):
            return
        self._pith_estimacion = {k: v for k, v in datos.items() if k.startswith("pith_")}
        offset = datos.get("pith_offset", 0)
        if offset > 0:
            med_a_cor = self.combo_dir.currentIndex() == 0
            self._pith_undo = {
                "med_a_cor": med_a_cor,
                "anio_medula_old": self.spin_medula.value() + (offset if med_a_cor else 0),
                "anio_corteza_old": self.spin_corteza.value() - (offset if not med_a_cor else 0),
                "medula_checked": False,
                "n_anillos": offset,
            }
            self.btn_deshacer_pith.show()

    def _iniciar_estimacion_pith(self):
        """Abre el diálogo de configuración y activa el modo PITH."""
        # Limpieza defensiva: si por algún motivo quedaron items del modo
        # pith de una sesión anterior (incompleta, mal cancelada, etc.),
        # los borramos antes de empezar. Sin esto, los círculos/líneas/
        # texto naranjas anteriores se solapaban con los nuevos.
        if hasattr(self.vista, "limpiar_pith"):
            self.vista.limpiar_pith()

        n_disponibles = len(self.datos_medidos)
        if n_disponibles < 3:
            QMessageBox.warning(self._parent, "Pocos anillos",
                "Necesitas al menos 3 anillos medidos para usar esta función.")
            self.btn_pith.setChecked(False)
            return

        tiene_ref = (self.serie_maestra is not None
                     and not self.serie_maestra.empty)

        dlg = DialogoMetodoPith(
            tiene_referencia=tiene_ref,
            n_anillos_disponibles=n_disponibles,
            parent=self._parent,
        )
        if dlg.exec() != DialogoMetodoPith.DialogCode.Accepted:
            self.btn_pith.setChecked(False)
            return

        self._pith_metodo    = dlg.metodo
        self._pith_n_int     = dlg.n_internos
        self._pith_usar_ref  = dlg.usar_referencia
        self._pith_dap_mm    = dlg.dap_mm
        self._pith_metodo_calculo = dlg.metodo_calculo  # 'rg', 'bai', 'promedio'

        if self._pith_metodo == "arco":
            self.set_modo(ModoMedicion.PITH)
            self.label_estado.setText(
                "🎯 Paso 1/3: Haz clic en un EXTREMO del arco del anillo más interno."
            )
        else:
            # DAP: no necesita marcado en imagen, calcular directamente
            self.btn_pith.setChecked(False)
            self._calcular_pith_por_dap()


    def _calcular_pith_por_dap(self):
        """Calcula la distancia faltante usando el DAP ingresado."""
        radio_mm    = self._pith_dap_mm / 2.0
        radio_px    = radio_mm * self.vista.pixeles_por_mm

        # Longitud del radio medido: distancia desde el primer punto hasta el último
        if len(self.vista.coordenadas_anillos) < 2:
            QMessageBox.warning(self._parent, "Sin camino",
                "Necesitas tener puntos medidos en el camino activo.")
            return

        coords = self.vista.coordenadas_anillos
        distancia_faltante_px = distancia_faltante_dap(coords, self.vista.es_salto, radio_px)

        if distancia_faltante_px <= 0:
            QMessageBox.information(self._parent, "Sin anillos faltantes",
                "La longitud medida ya cubre o supera el radio estimado por DAP.")
            return

        # Centro estimado: extrapolando desde el primer punto
        cx = coords[0][0]
        cy = coords[0][1]

        self._mostrar_dialogo_resultados_pith(
            cx, cy, radio_px, distancia_faltante_px, metodo="dap"
        )


    def _confirmar_estimacion_pith(self):
        """Confirma la estimación de pith por método arco.

        Llamado desde VistaInteractiva al presionar Enter en MODO_PITH.

        Algoritmo:
          1. La médula está en el centro del círculo ajustado (Duncan GM,
             1989): r = L²/(8h) + h/2 = radio del círculo por mínimos
             cuadrados a través de los puntos marcados.
          2. La distancia faltante es `dist(p_inner, centro)`: desde el
             primer anillo medido más cercano a la médula hasta el centro
             estimado. Esta es la métrica relevante INDEPENDIENTEMENTE
             de qué anillo marque el usuario — el arco marcado es solo
             la herramienta para localizar la médula.
          3. Los anillos faltantes se calculan en el diálogo de resultados
             usando RG (Altman 2016): anillos = distancia / promedio_ancho,
             donde el promedio viene de N anillos junto al arco marcado
             contando hacia la corteza.
        """
        resultado = self.vista.confirmar_pith()
        self.set_modo(ModoMedicion.MEDIR)
        self.btn_pith.setChecked(False)

        if resultado is None:
            return

        cx, cy, radio_px = resultado
        coords = self.vista.coordenadas_anillos

        if radio_px <= 0 or not coords:
            QMessageBox.warning(self._parent, "Estimación inválida",
                "El círculo ajustado tiene radio 0. Verifica los puntos marcados.")
            return

        # p_inner según dirección de medición
        try:
            med_a_cor = self.combo_dir.currentIndex() == 0
        except Exception:
            med_a_cor = True

        if med_a_cor:
            p_inner = coords[0]
        else:
            p_inner = coords[-1] if len(coords) >= 2 else coords[0]

        # Distancia faltante = dist(p_inner, centro). NO usar radio.
        distancia_faltante_px = math.hypot(cx - p_inner[0], cy - p_inner[1])

        if distancia_faltante_px <= 0:
            QMessageBox.warning(self._parent, "Estimación inválida",
                "El primer anillo medido coincide con la médula estimada.\n"
                "No hay anillos faltantes para estimar.")
            return

        self._mostrar_dialogo_resultados_pith(
            cx, cy, radio_px, distancia_faltante_px, metodo="arco"
        )


    def _mostrar_dialogo_resultados_pith(
        self,
        cx: float, cy: float,
        radio_px: float,
        distancia_faltante_px: float,
        metodo: str,
    ):
        """Calcula los resultados y muestra el diálogo de confirmación."""
        import math as _math

        n_int = getattr(self, '_pith_n_int', 5)
        usar_ref = getattr(self, '_pith_usar_ref', False)

        # Obtener los N anillos más internos (los primeros en la lista)
        # datos_medidos está ordenado médula→corteza
        med_a_cor = self.combo_dir.currentIndex() == 0
        dm = self.datos_medidos
        if med_a_cor:
            # Los más internos son los del inicio
            anchos_internos = [d["ancho_mm"] for d in dm[:n_int]]
            anio_inicio = dm[0]["anio"] if dm else None
        else:
            # Los más internos son los del final
            anchos_internos = [d["ancho_mm"] for d in dm[-n_int:]]
            anio_inicio = dm[-1]["anio"] if dm else None

        anchos_internos = [a for a in anchos_internos if a > 0]

        # Serie de referencia si está disponible y seleccionada
        serie_ref = None
        if usar_ref and self.serie_maestra is not None and not self.serie_maestra.empty:
            col = ("Ancho_mm" if "Ancho_mm" in self.serie_maestra.columns
                   else self.serie_maestra.columns[0])
            serie_ref = self.serie_maestra[col].dropna()

        resultados = estimar_anillos_faltantes(
            distancia_faltante_mm=distancia_faltante_px / self.vista.pixeles_por_mm,
            anchos_internos_mm=anchos_internos,
            serie_ref=serie_ref,
            anio_inicio_serie=anio_inicio,
        )

        if not resultados:
            QMessageBox.warning(self._parent, "Sin resultados",
                "No se pudo calcular la estimación. Verifica los datos.")
            return

        tiene_ref = (serie_ref is not None)
        dlg = DialogoEstimacionPith(
            resultados=resultados,
            radio_px=radio_px,
            distancia_faltante_px=distancia_faltante_px,
            pixeles_por_mm=self.vista.pixeles_por_mm,
            n_anillos_internos=len(anchos_internos),
            tiene_referencia=tiene_ref,
            parent=self._parent,
        )
        dlg.poblar_grafico(anchos_internos)
        dlg.aplicar_offset.connect(
            lambda n: self._aplicar_pith_offset(n, dlg.marcar_estimada, resultados, metodo,
                                                 radio_px / self.vista.pixeles_por_mm,
                                                 distancia_faltante_px / self.vista.pixeles_por_mm)
        )
        dlg.exec()


    def _aplicar_pith_offset(
        self,
        n_anillos: int,
        marcar_estimada: bool,
        resultados: dict,
        metodo: str,
        radio_mm: float,
        distancia_faltante_mm: float,
    ):
        """
        Aplica el offset: retrocede el año de médula en n_anillos.
        Actualiza el sidecar con la información de la estimación.
        """
        if n_anillos <= 0:
            return

        # Guardar estado previo para poder deshacer
        med_a_cor = self.combo_dir.currentIndex() == 0
        self._pith_undo = {
            "med_a_cor":        med_a_cor,
            "anio_medula_old":  self.spin_medula.value(),
            "anio_corteza_old": self.spin_corteza.value(),
            "medula_checked":   self.check_tiene_medula.isChecked(),
            "n_anillos":        n_anillos,
        }

        if med_a_cor:
            nuevo_anio_medula = self.spin_medula.value() - n_anillos
            self.spin_medula.setValue(nuevo_anio_medula)
        else:
            nuevo_anio_corteza = self.spin_corteza.value() + n_anillos
            self.spin_corteza.setValue(nuevo_anio_corteza)

        if marcar_estimada:
            self.check_tiene_medula.setChecked(True)

        # Guardar en el sidecar
        self._pith_estimacion = {
            "pith_estimated":       True,
            "pith_offset":          n_anillos,
            "pith_method":          metodo,
            "pith_radio_mm":        round(radio_mm, 2),
            "pith_distancia_mm":    round(distancia_faltante_mm, 2),
            "pith_n_media":         resultados.get("n_media"),
            "pith_n_tendencia":     resultados.get("n_tendencia"),
            "pith_n_referencia":    resultados.get("n_referencia"),
            "pith_ancho_medio":     resultados.get("ancho_medio"),
            "pith_rango_min":       resultados.get("incertidumbre_min"),
            "pith_rango_max":       resultados.get("incertidumbre_max"),
        }
        self._guardar_sidecar_anom()
        self._guardar_estado()

        dist = distancia_faltante_mm
        self.label_estado.setText(
            f"✅ Estimación aplicada: {n_anillos} anillos faltantes al centro · "
            f"distancia {dist:.1f} mm · año médula → {self.spin_medula.value()}"
        )
        self.btn_deshacer_pith.show()


    def _deshacer_pith_offset(self):
        """Revierte la última estimación de médula aplicada."""
        undo = getattr(self, "_pith_undo", None)
        if not undo:
            QMessageBox.information(self._parent, "Nada que deshacer",
                "No hay estimación para revertir.")
            return

        resp = QMessageBox.question(
            self._parent, "Deshacer estimación",
            f"¿Revertir la estimación de {undo['n_anillos']} anillos faltantes?\n"
            f"El año de médula volverá a su valor anterior.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Restaurar años
        self.spin_medula.setValue(undo["anio_medula_old"])
        self.spin_corteza.setValue(undo["anio_corteza_old"])
        self.check_tiene_medula.setChecked(undo["medula_checked"])

        # Limpiar estimación
        self._pith_estimacion = None
        self._pith_undo = None
        self.btn_deshacer_pith.hide()

        self._guardar_sidecar_anom()
        self._guardar_estado()
        self.vista.recalcular_todas_las_distancias()

        self.label_estado.setText(
            f"↩ Estimación revertida · "
            f"año médula → {self.spin_medula.value()}"
        )


    def _eliminar_ewlw(self):
        """Elimina todos los límites EW/LW del radio activo tras confirmación."""
        n_ewlw = sum(1 for v in self.vista.es_salto if _es_ewlw(v))
        if n_ewlw == 0:
            QMessageBox.information(self._parent, "Sin límites EW/LW",
                "No hay límites EW/LW en el radio activo.")
            return
        resp = QMessageBox.question(
            self._parent, "Eliminar límites EW/LW",
            f"¿Eliminar los {n_ewlw} límite(s) EW/LW del radio activo?\n"
            "Esta acción se puede deshacer con Ctrl+Z.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.vista.guardar_en_historial()
        # Eliminar de atrás hacia adelante para no invalidar índices
        indices = [i for i, v in enumerate(self.vista.es_salto) if _es_ewlw(v)]
        for i in reversed(indices):
            self.vista.modelo_medicion.borrar(i)
        self.vista.recalcular_todas_las_distancias()
        self.vista.progreso_modificado.emit()
        self.label_estado.setText(
            f"🗑 {n_ewlw} límite(s) EW/LW eliminados. Ctrl+Z para deshacer.")


    def _detectar_ewlw_automatico(self):
        """Detecta EW/LW automáticamente en hilo separado.

        Bug histórico (causaba freezes y en un caso reinicio de la PC):
          1. cv2.imread() corría en el MAIN thread → bloqueaba la UI varios
             segundos en imágenes grandes (scanners a 2400dpi).
          2. No había protección contra doble clic → se podían lanzar varios
             workers concurrentes, cada uno con su propia copia del array
             gris en memoria (decenas/cientos de MB) → OOM kill.
          3. dlg.cancelado.connect(worker.terminate) — QThread.terminate()
             es UNSAFE según docs de Qt: para el thread sin limpiar
             recursos, puede corromper memoria si estaba en numpy/cv2.
          4. Re-leía la imagen del disco aunque self._img_bgr_original ya
             la tuviera cacheada en RAM.

        Fixes aplicados:
          - Si hay otro worker activo, mensaje y bail (sin lanzar segundo).
          - Reusa self._img_bgr_original cuando está disponible.
          - Mueve cv2.cvtColor también fuera del main thread.
          - Cancelación cooperativa con flag en vez de terminate().
          - Limpia self._ewlw_worker al terminar para liberar memoria.
        """
        # Protección contra doble lanzamiento — uno de los caminos al crash.
        worker_previo = getattr(self, "_ewlw_worker", None)
        if worker_previo is not None and worker_previo.isRunning():
            QMessageBox.information(
                self._parent, "Detección en curso",
                "Ya se está ejecutando una detección de EW/LW.\n"
                "Espera a que termine o cancela el diálogo de progreso."
            )
            return

        if not self.vista.coordenadas_anillos or len(self.vista.coordenadas_anillos) < 2:
            QMessageBox.information(
                self._parent, "Sin anillos",
                "No hay anillos marcados todavía. Marca al menos un anillo antes.")
            return

        # Capturar estado antes de lanzar el hilo
        coords = list(self.vista.coordenadas_anillos)
        saltos = list(self.vista.es_salto)
        banda  = self._bi_banda
        ruta   = self.ruta_imagen_actual
        # Usar la imagen cacheada si existe (común: ya cargada al abrir
        # la pestaña). Solo re-leemos del disco si por algún motivo no
        # está disponible.
        img_cached = self._img_bgr_original

        dlg = _DialogoProgreso("Detectando límites EW/LW", parent=self._parent)
        # Flag de cancelación cooperativa — más seguro que terminate().
        # Se chequea dentro del loop principal de la función worker.
        cancel_flag = {"stop": False}
        dlg.show()

        worker = _Worker(detectar_ewlw_imagen, img_cached, coords, saltos, banda, ruta, cancel_flag)
        self._ewlw_worker = worker

        worker.signals.progreso.connect(dlg.actualizar)

        def _on_error(e):
            dlg.close()
            QMessageBox.critical(self._parent, "Error EW/LW", e)
        worker.signals.error.connect(_on_error)

        def _on_ewlw(inserciones):
            """Callback que aplica los resultados del worker EW/LW.

            Bug arreglado (causaba el "crash al 99%"):
              - Antes: aplicaba TODAS las inserciones (incluso parciales
                de una cancelación) y llamaba redibujar_todo de forma
                sincrónica. Con 200+ inserts + redibujar el main thread
                quedaba freezeado varios segundos → usuario veía el
                progreso pegado al 99% y pensaba que crasheaba.
              - Ahora: (1) si se canceló, descarta los parciales sin
                aplicar nada; (2) si hay resultados, los aplica en
                chunks con QApplication.processEvents() entre chunks
                para que la UI responda; (3) muestra el estado del
                proceso en el diálogo ("Aplicando...", "Redibujando...")
                en vez de quedar 99% silencioso.
            """
            # ── Caso 1: el usuario canceló ──
            # Descartar parciales para no aplicar 200 EW/LW que no quería.
            if cancel_flag.get("stop"):
                try:
                    dlg.close()
                except Exception:
                    pass
                self.label_estado.setText(
                    "🛑 Detección EW/LW cancelada — sin cambios aplicados."
                )
                return

            # ── Caso 2: sin resultados ──
            if not inserciones:
                try:
                    dlg.close()
                except Exception:
                    pass
                self.label_estado.setText(
                    "🍂 No se encontraron límites EW/LW."
                )
                return

            if (self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos):
                dlg.close()
                self.label_estado.setText("Resultados EW/LW descartados: cambió el radio.")
                return

            # ── Caso 3: aplicar resultados ──
            # Actualizar el diálogo para indicar la fase de aplicación.
            # El diálogo sigue VISIBLE durante esta fase para que el
            # usuario sepa que el programa está trabajando, no crasheado.
            try:
                if hasattr(dlg, "_bar"):
                    dlg._bar.setValue(100)
                if hasattr(dlg, "_lbl"):
                    dlg._lbl.setText(
                        f"Aplicando {len(inserciones)} límites EW/LW…")
                QApplication.processEvents()
            except Exception:
                pass

            # processEvents puede haber atendido una cancelación o edición.
            if (cancel_flag.get("stop") or self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos):
                dlg.close()
                return
            # Preparar todos los cambios fuera del modelo activo.
            puntos = list(self.vista.modelo_medicion.captura())
            try:
                for insert_at, px_ins, py_ins in reversed(inserciones):
                    if not 0 <= insert_at <= len(puntos):
                        raise ValueError("Índice de inserción inválido")
                    puntos.insert(insert_at, PuntoMedicion((px_ins, py_ins), TipoMarca.EW_LW))
            except (ValueError, TypeError, IndexError) as exc:
                dlg.close()
                QMessageBox.warning(self._parent, "EW/LW", str(exc))
                return
            self.vista.guardar_en_historial()
            self.vista.modelo_medicion.restaurar(puntos)
            self.vista.recalcular_todas_las_distancias()
            self.vista.progreso_modificado.emit()

            # Cerrar el diálogo SOLO cuando todo terminó.
            try:
                dlg.close()
            except Exception:
                pass
            self.label_estado.setText(
                f"🍂 EW/LW automático: {len(inserciones)} límites insertados. "
                "Usa 🖐 Mover para ajustar."
            )

        worker.signals.resultado.connect(_on_ewlw)

        def _on_cancel():
            """Cancelación segura: setea flag, el worker termina en próxima
            iteración del loop. Mucho más seguro que worker.terminate()."""
            cancel_flag["stop"] = True
            dlg._lbl.setText("Cancelando... espera a que termine la iteración actual.")

        dlg.cancelado.connect(_on_cancel)
        worker.start()
        return


    def _exportar_ewlw(self, codigo: str, ruta_base: str,
                        coords: list | None = None,
                        saltos: list | None = None,
                        datos_medidos: list | None = None, med_a_cor=None):
        """
        Genera codigo_ew.rwl y codigo_lw.rwl con los anchos de earlywood
        y latewood.

        Si coords/saltos/datos_medidos vienen explícitos, los usa (caso
        común: exportar un radio guardado). Si no vienen, cae al estado
        de la vista activa (caso: exportar el radio en progreso).

        Bug histórico: antes siempre leía self.vista.coordenadas_anillos
        y self.vista.es_salto, ignorando el radio que el usuario estaba
        exportando. Si el usuario exportaba un radio guardado pero la
        vista activa estaba vacía, tiene_ewlw era False y nunca se
        generaban los archivos _ew/_lw.
        """
        # Usar parámetros explícitos si se pasaron, si no caer a la vista
        if coords is None:
            coords = self.vista.coordenadas_anillos
        if saltos is None:
            saltos = self.vista.es_salto
        if datos_medidos is None:
            datos_medidos = self.datos_medidos

        if not datos_medidos:
            return

        if med_a_cor is None:
            med_a_cor = self.combo_dir.currentIndex() == 0
        anios_ew, anchos_ew, anios_lw, anchos_lw = calcular_anchos_ewlw(
            coords, saltos, datos_medidos, self.vista.pixeles_por_mm, med_a_cor)

        if not anios_ew:
            return

        import os
        dir_base = os.path.dirname(ruta_base)
        nombre_base = os.path.splitext(os.path.basename(ruta_base))[0]

        from constantes import TUCSON_MAX_CHARS_ID

        for sufijo, anios, anchos in [("ew", anios_ew, anchos_ew),
                                       ("lw", anios_lw, anchos_lw)]:
            ruta_rwl = os.path.join(dir_base, f"{nombre_base}_{sufijo}.rwl")
            try:
                mediciones_int = [int(round(a * 1000)) for a in anchos]
                _escribir_tucson(
                    f"{codigo[:7]}{sufijo[0]}", anios[0], mediciones_int, ruta_rwl, anios=anios
                )
            except Exception as exc:
                logger.warning("Error escribiendo %s: %s", ruta_rwl, exc)


    def _configurar_bi(self):
        """Abre el diálogo de configuración de la extracción de intensidad."""
        dlg = DialogoConfigBI(
            banda_actual=self._bi_banda,
            canales_activos=self._bi_canales,
            porcentaje=self._bi_porcentaje,
            alineacion=self._bi_alineacion,
            canal_vis=self._bi_canal_vis,
            parent=self._parent,
        )
        if dlg.exec():
            self._bi_banda       = dlg.banda
            self._bi_canales     = dlg.canales
            self._bi_porcentaje  = dlg.porcentaje
            self._bi_alineacion  = dlg.alineacion
            self._bi_canal_vis   = dlg.canal_vis
            # Redibujar banda si está activa
            if self.btn_mostrar_banda.isChecked():
                self._dibujar_banda_bi()


    def _calcular_bi(self):
        """Calcula BI/GI/RI en hilo separado con barra de progreso."""
        if not self.datos_medidos:
            QMessageBox.information(self._parent, "Sin mediciones",
                "Mide al menos un anillo antes de calcular la intensidad.")
            return

        # Protección contra doble lanzamiento (mismo problema que en EW/LW:
        # múltiples workers concurrentes con copias de la imagen llevan a OOM
        # y posible crash del sistema).
        worker_previo = getattr(self, "_bi_worker", None)
        if worker_previo is not None and worker_previo.isRunning():
            QMessageBox.information(
                self._parent, "Cálculo en curso",
                "Ya se está ejecutando un cálculo de intensidad.\n"
                "Espera a que termine.")
            return

        # Asegurar que haya canales activos (si el usuario no configuró, usar todos)
        if not self._bi_canales:
            self._bi_canales = ["B", "G", "R", "Gray"]

        ruta = getattr(self, "ruta_imagen_actual", None)
        if not ruta:
            QMessageBox.warning(self._parent, "Sin imagen",
                "No hay imagen cargada para extraer la intensidad.")
            return

        # Usar imagen cacheada si está disponible — evita re-leer del disco
        img_bgr = self._img_bgr_original
        if img_bgr is None:
            img_bgr = cv2.imread(ruta, cv2.IMREAD_COLOR)
            if img_bgr is None:
                QMessageBox.critical(self._parent, "Error",
                    "No se pudo leer la imagen para extraer la intensidad.")
                return

        # Capturar estado en este momento (el worker corre en otro hilo)
        coords   = list(self.vista.coordenadas_anillos)
        saltos   = list(self.vista.es_salto)
        ppm      = self.vista.pixeles_por_mm
        banda    = self._bi_banda
        canales  = list(self._bi_canales)
        anios_capturados = [d["anio"] for d in self.datos_medidos]
        n_anillos = len(anios_capturados)

        dlg = _DialogoProgreso("Calculando intensidad de color", parent=self._parent)
        dlg.show()

        pct_calculo  = self._bi_porcentaje / 100.0
        alin_calculo = self._bi_alineacion
        med_a_cor = self.combo_dir.currentIndex() == 0

        def _tarea(sig_prog, img, c, s, p, b, ch, pct, alin):
            return extraer_intensidad_por_anillo(
                signal_progreso=sig_prog,
                imagen_bgr=img,
                coordenadas=c,
                es_salto=s,
                pixeles_por_mm=p,
                banda_px=b,
                canales=ch,
                porcentaje=pct,
                alineacion=alin, med_a_cor=med_a_cor,
            )

        worker = _Worker(_tarea, img_bgr, coords, saltos, ppm, banda, canales,
                          pct_calculo, alin_calculo)
        self._bi_worker = worker  # evitar que el GC lo destruya

        worker.signals.progreso.connect(dlg.actualizar)

        def _on_error(e):
            dlg.close()
            QMessageBox.critical(self._parent, "Error al calcular BI", e)
        worker.signals.error.connect(_on_error)

        def _on_resultado(resultados):
            dlg.close()
            if (self.ruta_imagen_actual != ruta
                    or list(self.vista.coordenadas_anillos) != coords
                    or list(self.vista.es_salto) != saltos
                    or self.vista.pixeles_por_mm != ppm
                    or (self.combo_dir.currentIndex() == 0) != med_a_cor
                    or [d["anio"] for d in self.datos_medidos] != anios_capturados):
                self.label_estado.setText("Resultados BI descartados: cambió el radio.")
                return
            for resultado in resultados:
                resultado["anio"] = anios_capturados[resultado["indice_anillo"]]
            self._bi_datos = resultados
            self.btn_guardar_bi.setEnabled(bool(resultados))
            self.btn_graficar_bi.setEnabled(bool(resultados))
            self.label_estado.setText(
                f"🎨 {len(resultados)} anillos · banda {banda}px · "
                f"canales: {', '.join(canales)}")

        worker.signals.resultado.connect(_on_resultado)

        def _on_cancel():
            """Cancelación segura: cierra el diálogo y desconecta callbacks,
            pero deja al worker terminar en silencio. NO usa terminate()
            porque interrumpir un thread con cv2/numpy en pleno cálculo
            puede corromper memoria o reiniciar el sistema."""
            try:
                worker.signals.resultado.disconnect()
                worker.signals.error.disconnect()
                worker.signals.progreso.disconnect()
            except (TypeError, RuntimeError):
                pass
            dlg.close()
            self.label_estado.setText(
                "Cálculo BI cancelado (terminará silenciosamente en background).")

        dlg.cancelado.connect(_on_cancel)
        worker.start()


    def _toggle_banda_bi(self, activo: bool):
        """Muestra u oculta la banda de muestreo BI sobre la imagen."""
        if activo:
            self._dibujar_banda_bi()
        else:
            self._limpiar_banda_bi()


    def _dibujar_banda_bi(self):
        self._banda_intensidad.limpiar()
        ruta = getattr(self, "ruta_imagen_actual", None)
        if not ruta:
            return
        img = cv2.imread(ruta, cv2.IMREAD_COLOR)
        self._banda_intensidad.dibujar(self.vista.scene(), img,
            self.vista.coordenadas_anillos, self.vista.es_salto,
            self._bi_canal_vis, self._bi_banda, self._bi_porcentaje / 100.0,
            self._bi_alineacion, med_a_cor=self.combo_dir.currentIndex() == 0)


    def _limpiar_banda_bi(self):
        self._banda_intensidad.limpiar()


    def _graficar_bi_ventana(self):
        """Abre una ventana independiente con el gráfico de BI/GI/RI con zoom."""
        if not self._bi_datos:
            return

        anios = [d.get("anio", i) for i, d in enumerate(self._bi_datos)]
        colores = {"B": "#4488FF", "G": "#44BB44", "R": "#FF4444", "Gray": "#AAAAAA"}
        estilos = {
            "mean": (Qt.PenStyle.SolidLine,  "Promedio"),
            "min":  (Qt.PenStyle.DashLine,   "Mínimo"),
            "max":  (Qt.PenStyle.DotLine,    "Máximo"),
        }

        win = QDialog(self._parent)
        win.setWindowTitle("Intensidad de color — BI/GI/RI/GrayI")
        win.resize(900, 450)
        lay = QVBoxLayout(win)

        pw = pg.PlotWidget()
        _gr.aplicar_a_pyqtgraph(pw)
        pw.showGrid(x=True, y=True, alpha=0.3)
        pw.setLabel("bottom", "Año")
        pw.setLabel("left",   "Intensidad (0-255)")
        pw.setYRange(0, 255, padding=0.05)
        pw.addLegend(offset=(10, 10))
        pw.setMouseEnabled(x=True, y=True)
        lay.addWidget(pw)

        from PyQt6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout as QHL
        chks_canal: dict[str, QCheckBox] = {}
        chks_met:   dict[str, QCheckBox] = {}

        def _reconstruir():
            pw.clear()
            pw.addLegend(offset=(10, 10))
            for canal, chk_c in chks_canal.items():
                if not chk_c.isChecked():
                    continue
                color = colores.get(canal, "#888888")
                for met, (estilo, etiq) in estilos.items():
                    if not chks_met[met].isChecked():
                        continue
                    key = f"{canal}_{met}"
                    vals = [d.get(key) for d in self._bi_datos if key in d]
                    if not vals or len(vals) != len(anios):
                        continue
                    pw.plot(anios, vals,
                            pen=pg.mkPen(color,
                                         width=2.0 if met == "mean" else 1.0,
                                         style=estilo),
                            name=f"{canal} {etiq}")

        fila = QHL()
        grp_c = QGroupBox("Canales")
        lay_c = QHL(grp_c)
        for canal in ["B", "G", "R", "Gray"]:
            chk = QCheckBox(canal)
            chk.setChecked(canal in self._bi_canales)
            chk.toggled.connect(_reconstruir)
            lay_c.addWidget(chk)
            chks_canal[canal] = chk
        fila.addWidget(grp_c)

        grp_m = QGroupBox("Métricas")
        lay_m = QHL(grp_m)
        for met, etiq in [("mean","Promedio"), ("min","Mínimo"), ("max","Máximo")]:
            chk = QCheckBox(etiq)
            chk.setChecked(True)
            chk.toggled.connect(_reconstruir)
            lay_m.addWidget(chk)
            chks_met[met] = chk
        fila.addWidget(grp_m)
        fila.addStretch()
        lay.addLayout(fila)

        _reconstruir()
        win.show()
        self._bi_ventana = win   # evitar GC


    def _guardar_bi(self):
        """
        Abre el diálogo de selección de métricas y guarda en el formato
        elegido por la extensión del archivo:
          • .rwl       → un archivo Tucson por canal×métrica
          • .xlsx      → un Excel multi-columna con todas las series
          • .csv/.txt  → un texto multi-columna con coma decimal
        """
        if not self._bi_datos:
            QMessageBox.information(self._parent, "Sin datos",
                "Primero calcula la intensidad con el botón 🎨 Calcular BI.")
            return

        # 1. Diálogo de selección de canales y métricas
        dlg = DialogoGuardarBI(
            canales_calculados=self._bi_canales,
            parent=self._parent,
        )
        if dlg.exec() != DialogoGuardarBI.DialogCode.Accepted:
            return

        seleccion = dlg.seleccion
        if not seleccion:
            QMessageBox.information(self._parent, "Sin selección",
                "No se seleccionó ningún canal/métrica para exportar.")
            return

        # 2. Selector de archivo con formato
        codigo = self.input_codigo.text().strip() or "serie"
        ruta_default = os.path.join(_ultima_carpeta(), f"{codigo}_bi.txt")

        ruta, filtro = QFileDialog.getSaveFileName(
            self._parent, "Guardar intensidad de color",
            ruta_default,
            "Texto multi-columna (*.txt);;"
            "CSV multi-columna (*.csv);;"
            "Excel multi-columna (*.xlsx);;"
            "Tucson — un archivo por canal (*.rwl)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not ruta:
            return

        _ultima_carpeta(ruta)
        ext = os.path.splitext(ruta)[1].lower()
        if not ext:
            # Si no escribieron extensión, deducir del filtro
            if "rwl" in filtro:
                ruta += ".rwl"
                ext = ".rwl"
            elif "csv" in filtro:
                ruta += ".csv"
                ext = ".csv"
            elif "xlsx" in filtro:
                ruta += ".xlsx"
                ext = ".xlsx"
            else:
                ruta += ".txt"
                ext = ".txt"

        anios = [d.get("anio", i) for i, d in enumerate(self._bi_datos)]
        if not anios:
            return

        try:
            if ext == ".rwl":
                self._exportar_bi_tucson(ruta, anios, seleccion)
            else:
                self._exportar_bi_multicolumna(ruta, ext, anios, seleccion, codigo)
        except Exception as exc:
            logger.error("Error al exportar BI: %s", exc)
            QMessageBox.critical(self._parent, "Error",
                                 f"Fallo al exportar:\n{exc}")


    def _exportar_bi_tucson(self, ruta: str, anios: list, seleccion: list):
        """Genera un .rwl Tucson por cada (canal, métrica)."""
        codigo = self.input_codigo.text().strip() or "serie"
        directorio = os.path.dirname(ruta)
        base = os.path.splitext(os.path.basename(ruta))[0]
        # Si terminaba en "_bi", quitarlo para evitar duplicación
        if base.lower().endswith("_bi"):
            base = base[:-3]

        escritos = []
        errores = []

        for canal, met in seleccion:
            vals = valores_intensidad(self._bi_datos, canal, met)
            if canal in ("B_R", "B_G"):
                r_max = max(vals) if vals else 1.0
                vals_norm = [v / r_max for v in vals]
                suf = canal.lower().replace("_", "div")
            else:
                vals_norm = [v / 255.0 for v in vals]
                suf = f"{canal.lower()}_{met}"

            nombre_archivo = f"{base}_{suf}.rwl"
            ruta_rwl = os.path.join(directorio, nombre_archivo)
            try:
                from modulo_formatos import escribir_tucson
                escribir_tucson(pd.Series(vals_norm, index=anios), ruta_rwl,
                    codigo=f"{codigo[:6]}{canal[:1].lower()}{met[:1] if met else ''}")
                escritos.append(nombre_archivo)
            except Exception as exc:
                errores.append(f"{nombre_archivo}: {exc}")

        msg = f"✅ Guardados {len(escritos)} archivos Tucson en:\n{directorio}"
        if escritos:
            msg += "\n\n" + "\n".join(f"  • {f}" for f in escritos)
        if errores:
            msg += "\n\n⚠ Errores:\n" + "\n".join(errores)
        QMessageBox.information(self._parent, "Guardado completado", msg)


    def _exportar_bi_multicolumna(self, ruta: str, ext: str, anios: list,
                                    seleccion: list, codigo: str):
        """Genera un solo archivo Excel/CSV/TXT con todas las series como columnas."""
        # Construir DataFrame con una columna por cada (canal, métrica)
        data = {"Anio": anios}
        for canal, met in seleccion:
            col_label = f"{canal}_ratio" if canal in ("B_R", "B_G") else f"{canal}_{met}"
            data[col_label] = valores_intensidad(self._bi_datos, canal, met)

        df = pd.DataFrame(data)

        if ext == ".xlsx":
            _escribir_excel(df, ruta)
        elif ext == ".csv":
            # CSV chileno: separador ; y decimal con coma
            df.to_csv(ruta, index=False, sep=";", decimal=",",
                      float_format="%.6f")
        else:  # .txt
            df.to_csv(ruta, index=False, sep="\t", decimal=",",
                      float_format="%.6f")

        n_cols = len(df.columns) - 1  # restar la columna Anio
        QMessageBox.information(
            self._parent, "✅ Exportación completada",
            f"Archivo guardado:\n{ruta}\n\n"
            f"Formato: multi-columna ({n_cols} series)\n"
            f"Filas: {len(df)} años\n"
            f"Columnas: Anio + {n_cols} canales/métricas"
        )

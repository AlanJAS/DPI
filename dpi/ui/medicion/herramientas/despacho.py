"""Asociación única entre modos y acciones de clic."""
from dpi.medicion.marcas import ModoMedicion

def acciones_click(self):
    return {
        ModoMedicion.INSERTAR: self._insertar_en_segmento,
        ModoMedicion.BORRAR: self._borrar_punto_cercano,
        ModoMedicion.SELECCIONAR: self._iniciar_seleccion_mouse,
        ModoMedicion.CALIBRAR: self._paso_calibracion,
        ModoMedicion.MEDIR: self._paso_medir,
        ModoMedicion.SALTO: self._paso_medir,
        ModoMedicion.AUTODETECT: self._paso_autodetect,
        ModoMedicion.ANOMALIA: self._paso_anomalia,
        ModoMedicion.PITH: self._paso_pith,
        ModoMedicion.ESPACIO: self._paso_espacio,
        ModoMedicion.EWLW: self._paso_ewlw,
    }

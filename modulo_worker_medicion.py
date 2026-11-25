"""Componentes de medición de DPI."""

from PyQt6.QtCore import QObject, QThread, Qt
from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QDialog, QPushButton, QVBoxLayout, QLabel, QProgressBar,
)


class _WorkerSignals(QObject):
    progreso  = Signal(int, str)   # (porcentaje 0-100, mensaje)
    resultado = Signal(object)     # payload de vuelta al hilo principal
    error     = Signal(str)        # mensaje de error



class _Worker(QThread):
    """
    Ejecuta una función pesada en un hilo secundario.
    La función recibe una señal de progreso como primer argumento.

    Uso:
        w = _Worker(fn, arg1, arg2)
        w.signals.progreso.connect(actualizar_ui)
        w.signals.resultado.connect(usar_resultado)
        w.signals.error.connect(mostrar_error)
        w.start()
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self):
        try:
            resultado = self._fn(
                self.signals.progreso,
                *self._args,
                **self._kwargs,
            )
            self.signals.resultado.emit(resultado)
        except Exception as exc:
            import traceback
            self.signals.error.emit(traceback.format_exc())



class _DialogoProgreso(QDialog):
    """Barra de progreso modal cancelable."""

    cancelado = Signal()

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        self._lbl = QLabel("Iniciando...")
        layout.addWidget(self._lbl)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)
        btn = QPushButton("Cancelar")
        btn.clicked.connect(self.cancelado)
        layout.addWidget(btn)

    def actualizar(self, pct: int, msg: str):
        self._lbl.setText(msg)
        self._bar.setValue(pct)


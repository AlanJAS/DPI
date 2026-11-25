"""Ciclo de vida de tareas de medición en Qt."""
from threading import Event
import traceback
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QLabel, QProgressBar


class _Worker(QThread):
    progreso = pyqtSignal(int, str)

    def __init__(self, tarea, cancelacion):
        super().__init__()
        self.tarea = tarea
        self.cancelacion = cancelacion
        self.resultado = None
        self.error = None

    def run(self):
        try:
            self.resultado = self.tarea(self.progreso, self.cancelacion.is_set)
        except Exception:
            self.error = traceback.format_exc()


class _DialogoProgreso(QDialog):
    cancelado = pyqtSignal()

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        self._lbl = QLabel("Iniciando...")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._btn = QPushButton("Cancelar")
        self._btn.clicked.connect(self.reject)
        layout.addWidget(self._lbl)
        layout.addWidget(self._bar)
        layout.addWidget(self._btn)

    def reject(self):
        # Escape y botón utilizan la misma ruta cooperativa.
        self.cancelado.emit()

    def solicitar_cancelacion(self):
        self._btn.setEnabled(False)
        self._lbl.setText("Cancelando...")

    def actualizar(self, pct, msg):
        self._bar.setValue(pct)
        if self._btn.isEnabled():
            self._lbl.setText(msg)


class GestorTareasMedicion(QObject):
    """Una tarea por pestaña; callbacks ejecutados al finalizar en el hilo de Qt."""
    def __init__(self, parent):
        super().__init__(parent)
        self._worker = None

    @property
    def en_curso(self):
        return self._worker is not None

    def iniciar(self, titulo, tarea, al_resultado, al_error, al_cancelar):
        if self.en_curso:
            return False
        self._cancelacion = Event()
        self._dialogo = _DialogoProgreso(titulo, self.parent())
        self._callbacks = (al_resultado, al_error, al_cancelar)
        worker = _Worker(tarea, self._cancelacion)
        self._worker = worker
        worker.progreso.connect(self._dialogo.actualizar)
        self._dialogo.cancelado.connect(self.cancelar)
        worker.finished.connect(self._finalizar, Qt.ConnectionType.QueuedConnection)
        self._dialogo.show()
        worker.start()
        return True

    @pyqtSlot()
    def cancelar(self):
        if self.en_curso:
            self._cancelacion.set()
            self._dialogo.solicitar_cancelacion()

    @pyqtSlot()
    def _finalizar(self):
        worker = self._worker
        if worker is None:
            return
        resultado, error, cancelar = self._callbacks
        dialogo = self._dialogo
        try:
            dialogo.done(0)
            if self._cancelacion.is_set():
                cancelar()
            elif worker.error is not None:
                error(worker.error)
            else:
                resultado(worker.resultado)
        except Exception:
            error(traceback.format_exc())
        finally:
            self._worker = None
            self._callbacks = None
            self._dialogo = None
            worker.deleteLater()
            dialogo.deleteLater()

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(
        self, function: Callable[..., Any], *args: object, with_progress: bool = False
    ) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.with_progress = with_progress
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.function(*self.args, progress=self.signals.progress.emit)
            else:
                result = self.function(*self.args)
            self.signals.result.emit(result)
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()

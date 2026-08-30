from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Event, Lock

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from ..core.video import RenderCancelled
from .studio3d_capture import StandaloneStudio3DCapture
from .studio3d_export import qimage_to_rgb
from .studio3d_renderer import PreparedStudio3DRender


@dataclass(slots=True)
class _CaptureRequest:
    prepared: PreparedStudio3DRender
    frame_index: int
    cancelled: Event | None
    done: Event = field(default_factory=Event)
    result: np.ndarray | None = None
    error: Exception | None = None


class Studio3DCaptureBridge(QObject):
    """Backpressure bridge from proxy workers to UI-owned Quick 3D surfaces."""

    captureRequested = Signal(object)

    def __init__(self, parent: QObject | None = None, *, max_surfaces: int = 3) -> None:
        super().__init__(parent)
        if max_surfaces < 1:
            raise ValueError("Le cache GPU doit conserver au moins une surface")
        self.captureRequested.connect(self._capture_on_ui_thread)
        self.max_surfaces = int(max_surfaces)
        self._surfaces: OrderedDict[
            tuple[int, int], StandaloneStudio3DCapture
        ] = OrderedDict()
        self._pending: dict[int, _CaptureRequest] = {}
        self._lock = Lock()
        self._closed = False

    @property
    def surface_count(self) -> int:
        return len(self._surfaces)

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Le pont de capture Studio 3D est fermé")

    def capture(
        self,
        prepared: PreparedStudio3DRender,
        frame_index: int,
        *,
        cancelled: Event | None = None,
    ) -> np.ndarray:
        self._assert_open()
        request = _CaptureRequest(prepared, int(frame_index), cancelled)
        if QThread.currentThread() is self.thread():
            self._capture_on_ui_thread(request)
        else:
            with self._lock:
                self._pending[id(request)] = request
            self.captureRequested.emit(request)
            while not request.done.wait(0.05):
                if cancelled is not None and cancelled.is_set():
                    request.error = RenderCancelled("Capture Studio 3D annulée")
                    request.done.set()
        with self._lock:
            self._pending.pop(id(request), None)
        if request.error is not None:
            raise request.error
        if request.result is None:
            raise RuntimeError("Le pont Studio 3D n’a retourné aucune frame")
        return request.result

    def release(self, _prepared: PreparedStudio3DRender) -> None:
        """Prepared scenes own no GUI surface; surfaces stay bounded by resolution."""

    @Slot(object)
    def _capture_on_ui_thread(self, request: _CaptureRequest) -> None:
        if request.done.is_set():
            return
        try:
            self._assert_open()
            if request.cancelled is not None and request.cancelled.is_set():
                raise RenderCancelled("Capture Studio 3D annulée")
            key = (request.prepared.width, request.prepared.height)
            surface = self._surfaces.get(key)
            if surface is None:
                surface = StandaloneStudio3DCapture(*key)
                self._surfaces[key] = surface
                while len(self._surfaces) > self.max_surfaces:
                    _old_key, removed = self._surfaces.popitem(last=False)
                    removed.close()
            else:
                self._surfaces.move_to_end(key)
            image = surface.capture_at(
                request.prepared,
                request.frame_index,
                cancelled=request.cancelled,
            )
            request.result = qimage_to_rgb(image)
        except Exception as exc:
            request.error = exc
        finally:
            request.done.set()

    def cancel_pending(self) -> None:
        with self._lock:
            pending = tuple(self._pending.values())
        for request in pending:
            if not request.done.is_set():
                request.error = RenderCancelled("Capture Studio 3D annulée")
                request.done.set()

    def close(self) -> None:
        if self._closed:
            return
        application = QApplication.instance()
        if application is not None and QThread.currentThread() is not application.thread():
            raise RuntimeError("Le pont Studio 3D doit être fermé sur le thread UI")
        self._closed = True
        self.cancel_pending()
        for surface in self._surfaces.values():
            surface.close()
        self._surfaces.clear()

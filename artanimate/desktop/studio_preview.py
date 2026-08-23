from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImage

from ..studio.model import StudioProject
from ..studio.preview import (
    ArtworkSourceRegistry,
    DEFAULT_CACHE_BYTES,
    DEFAULT_PROXY_WIDTH,
    StudioProxyCache,
    render_studio_preview_frame,
)


logger = logging.getLogger(__name__)


def preview_qimage(frame: np.ndarray) -> QImage:
    height, width = frame.shape[:2]
    return QImage(
        frame.data,
        width,
        height,
        width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


class StudioPreviewWorker(QObject):
    ready = Signal(int, int, object, bool)
    failed = Signal(int, object)
    finished = Signal(int)

    def __init__(
        self,
        revision: int,
        project: StudioProject,
        artwork_path: Path,
        frame: int,
        proxy_width: int,
        cache: StudioProxyCache,
        sources: ArtworkSourceRegistry,
    ):
        super().__init__()
        self.revision = int(revision)
        self.project = project
        self.artwork_path = artwork_path
        self.frame = int(frame)
        self.proxy_width = int(proxy_width)
        self.cache = cache
        self.sources = sources
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        try:
            frame, cached = render_studio_preview_frame(
                self.project,
                self.artwork_path,
                self.frame,
                requested_width=self.proxy_width,
                cache=self.cache,
                source_registry=self.sources,
                cancelled=self._cancelled,
            )
            if frame is not None and not self._cancelled.is_set():
                self.ready.emit(
                    self.revision,
                    self.frame,
                    preview_qimage(frame),
                    cached,
                )
        except Exception as exc:
            if not self._cancelled.is_set():
                logger.exception("Calcul du proxy Studio impossible")
                self.failed.emit(self.revision, exc)
        finally:
            self.finished.emit(self.revision)


class StudioPreviewController(QObject):
    frameReady = Signal(int, object, bool)
    renderingChanged = Signal(bool)
    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cache_bytes: int = DEFAULT_CACHE_BYTES,
    ):
        super().__init__(parent)
        self.cache = StudioProxyCache(cache_bytes)
        self.sources = ArtworkSourceRegistry()
        self.proxy_width = DEFAULT_PROXY_WIDTH
        self._revision = 0
        self._jobs: dict[int, tuple[QThread, StudioPreviewWorker]] = {}
        self._shutting_down = False

    @property
    def active_job_count(self) -> int:
        return len(self._jobs)

    def set_proxy_width(self, width: int) -> None:
        value = int(width)
        if value < 90 or value > 1080:
            raise ValueError("La largeur proxy doit être comprise entre 90 et 1080")
        self.proxy_width = value

    def request(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        frame: int,
    ) -> int:
        if self._shutting_down:
            return self._revision
        self._revision += 1
        revision = self._revision
        for _old_revision, (_thread, worker) in tuple(self._jobs.items()):
            worker.cancel()
        thread = QThread(self)
        worker = StudioPreviewWorker(
            revision,
            project,
            Path(artwork_path),
            int(frame),
            self.proxy_width,
            self.cache,
            self.sources,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(self._frame_ready)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda selected=revision: self._thread_finished(selected)
        )
        thread.finished.connect(thread.deleteLater)
        self._jobs[revision] = (thread, worker)
        self.renderingChanged.emit(True)
        thread.start()
        return revision

    @Slot(int, int, object, bool)
    def _frame_ready(
        self,
        revision: int,
        frame: int,
        image: QImage,
        cached: bool,
    ) -> None:
        if not self._shutting_down and revision == self._revision:
            self.frameReady.emit(frame, image, cached)

    @Slot(int, object)
    def _failed(self, revision: int, exc: Exception) -> None:
        if not self._shutting_down and revision == self._revision:
            self.failed.emit(str(exc))

    def _thread_finished(self, revision: int) -> None:
        self._jobs.pop(revision, None)
        if revision == self._revision and not self._shutting_down:
            self.renderingChanged.emit(False)

    def cancel_pending(self) -> None:
        self._revision += 1
        for _thread, worker in tuple(self._jobs.values()):
            worker.cancel()
        self.renderingChanged.emit(False)

    def shutdown(self, wait_ms: int = 3000) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        for _thread, worker in tuple(self._jobs.values()):
            worker.cancel()
        for thread, _worker in tuple(self._jobs.values()):
            thread.quit()
            thread.wait(max(0, int(wait_ms)))
        self._jobs.clear()
        self.cache.clear()
        self.sources.clear()
        self.renderingChanged.emit(False)


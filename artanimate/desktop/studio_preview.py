from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, TimeoutError
import logging
from pathlib import Path
from threading import Event
from time import monotonic

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage

from ..studio.model import StudioProject
from ..studio.preview import (
    ArtworkSourceRegistry,
    DEFAULT_CACHE_BYTES,
    DEFAULT_PROXY_WIDTH,
    StudioProxyCache,
    render_studio_preview_frame,
)
from .problems import translate_studio_exception
from .studio3d_bridge import Studio3DCaptureBridge
from .studio3d_renderer import ClassicStudio3DRenderer


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
        resource_base: Path | None,
        three_d_capture: Studio3DCaptureBridge,
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
        self.three_d_capture = three_d_capture
        self.resource_base = resource_base

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            three_d_renderer = ClassicStudio3DRenderer(
                self.artwork_path,
                fingerprint=self.project.artwork.fingerprint,
                capture_port=self.three_d_capture,
                cancelled=self._cancelled,
            )

            frame, cached = render_studio_preview_frame(
                self.project,
                self.artwork_path,
                self.frame,
                requested_width=self.proxy_width,
                cache=self.cache,
                source_registry=self.sources,
                cancelled=self._cancelled,
                extra_renderers=(three_d_renderer,),
                resource_base=self.resource_base,
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
    failed = Signal(object)

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
        self.three_d_capture = Studio3DCaptureBridge(self)
        self._jobs: dict[int, tuple[Future[None], StudioPreviewWorker]] = {}
        self._shutting_down = False
        self.worker_thread_prefix = f"ArtAnimateProxy-{id(self):x}"
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix=self.worker_thread_prefix,
        )

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
        *,
        resource_base: str | Path | None = None,
    ) -> int:
        if self._shutting_down:
            return self._revision
        self._revision += 1
        revision = self._revision
        for old_revision, (future, worker) in tuple(self._jobs.items()):
            worker.cancel()
            if future.cancel():
                self._jobs.pop(old_revision, None)
        self.three_d_capture.cancel_pending()
        worker = StudioPreviewWorker(
            revision,
            project,
            Path(artwork_path),
            int(frame),
            self.proxy_width,
            self.cache,
            self.sources,
            Path(resource_base) if resource_base is not None else None,
            self.three_d_capture,
        )
        worker.ready.connect(
            self._frame_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            self._failed,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(
            self._job_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        gate = Event()

        def run_after_registration() -> None:
            gate.wait()
            worker.run()

        future = self._executor.submit(run_after_registration)
        self._jobs[revision] = (future, worker)
        gate.set()
        self.renderingChanged.emit(True)
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
            job = self._jobs.get(revision)
            source = job[1].artwork_path if job is not None else None
            self.failed.emit(
                translate_studio_exception(
                    exc, "preview", source=source
                )
            )

    @Slot(int)
    def _job_finished(self, revision: int) -> None:
        self._jobs.pop(revision, None)
        if revision == self._revision and not self._shutting_down:
            self.renderingChanged.emit(False)

    def cancel_pending(self) -> None:
        self._revision += 1
        for revision, (future, worker) in tuple(self._jobs.items()):
            worker.cancel()
            if future.cancel():
                self._jobs.pop(revision, None)
        self.three_d_capture.cancel_pending()
        self.renderingChanged.emit(False)

    def shutdown(self, wait_ms: int = 3000) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        jobs = tuple(self._jobs.values())
        for future, worker in jobs:
            worker.cancel()
            future.cancel()
        deadline = monotonic() + max(0, int(wait_ms)) / 1000
        self.three_d_capture.cancel_pending()
        for future, _worker in jobs:
            remaining = max(0.0, deadline - monotonic())
            try:
                future.result(timeout=remaining)
            except (CancelledError, TimeoutError):
                pass
            except Exception:
                logger.exception("Arrêt du worker proxy Studio en erreur")
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._jobs.clear()
        self.cache.clear()
        self.sources.clear()
        self.renderingChanged.emit(False)
        self.three_d_capture.close()

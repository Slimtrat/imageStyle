from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..studio.assets import AssetAvailability, check_media_asset
from ..studio.model import AssetKind, ClipKind, StudioProject
from ..studio.waveform import WaveformCache, WaveformCancelled, WaveformEnvelope
from .problems import translate_studio_exception


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WaveformRequest:
    asset_id: str
    path: Path
    fingerprint: str


class StudioWaveformWorker(QObject):
    ready = Signal(int, object)
    failed = Signal(int, object)
    cancelled = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        revision: int,
        requests: tuple[WaveformRequest, ...],
        cache: WaveformCache,
    ) -> None:
        super().__init__()
        self.revision = revision
        self.requests = requests
        self.cache = cache
        self.cancellation = Event()

    def cancel(self) -> None:
        self.cancellation.set()

    def run(self) -> None:
        try:
            results: dict[str, WaveformEnvelope] = {}
            for request in self.requests:
                if self.cancellation.is_set():
                    raise WaveformCancelled("Calcul waveform annulé")
                results[request.asset_id] = self.cache.load_or_extract(
                    request.path,
                    request.fingerprint,
                    cancelled=self.cancellation,
                )
            if not self.cancellation.is_set():
                self.ready.emit(self.revision, results)
        except WaveformCancelled:
            self.cancelled.emit(self.revision)
        except Exception as exc:
            if self.cancellation.is_set():
                self.cancelled.emit(self.revision)
            else:
                logger.exception("Calcul local de waveform impossible")
                self.failed.emit(self.revision, exc)
        finally:
            self.finished.emit(self.revision)


class StudioWaveformController(QObject):
    waveformsReady = Signal(object)
    runningChanged = Signal(bool)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cache_dir: str | Path,
        cache: WaveformCache | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache or WaveformCache(cache_dir)
        self._revision = 0
        self._jobs: dict[int, tuple[Future[None], StudioWaveformWorker]] = {}
        self._shutting_down = False
        self.worker_thread_prefix = f"ArtAnimateWaveform-{id(self):x}"
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=self.worker_thread_prefix,
        )

    @property
    def active_job_count(self) -> int:
        return len(self._jobs)

    def request(self, project: StudioProject, project_path: str | Path) -> int:
        project.validate()
        if self._shutting_down:
            return self._revision
        self.cancel_pending(notify=False)
        self._revision += 1
        revision = self._revision
        referenced = {
            clip.asset_id
            for track in project.tracks
            for clip in track.clips
            if clip.kind == ClipKind.AUDIO and clip.asset_id is not None
        }
        requests: list[WaveformRequest] = []
        for asset in project.assets:
            if asset.asset_id not in referenced or asset.kind != AssetKind.AUDIO:
                continue
            check = check_media_asset(asset, project_path)
            if check.state == AssetAvailability.INVALID or check.current is None:
                continue
            requests.append(
                WaveformRequest(
                    asset.asset_id,
                    check.resolved_path,
                    check.current.fingerprint,
                )
            )
        if not requests:
            self.waveformsReady.emit({})
            self.runningChanged.emit(False)
            return revision
        worker = StudioWaveformWorker(revision, tuple(requests), self.cache)
        worker.ready.connect(self._ready, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(self._cancelled, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._job_finished, Qt.ConnectionType.QueuedConnection)
        gate = Event()

        def run_after_registration() -> None:
            gate.wait()
            worker.run()

        future = self._executor.submit(run_after_registration)
        self._jobs[revision] = (future, worker)
        gate.set()
        self.runningChanged.emit(True)
        return revision

    @Slot(int, object)
    def _ready(self, revision: int, results: dict[str, WaveformEnvelope]) -> None:
        if not self._shutting_down and revision == self._revision:
            self.waveformsReady.emit(results)

    @Slot(int, object)
    def _failed(self, revision: int, exc: Exception) -> None:
        if not self._shutting_down and revision == self._revision:
            job = self._jobs.get(revision)
            source = job[1].requests[0].path if job and job[1].requests else None
            self.failed.emit(
                translate_studio_exception(exc, "waveform", source=source)
            )

    @Slot(int)
    def _cancelled(self, revision: int) -> None:
        if not self._shutting_down and revision == self._revision:
            self.cancelled.emit()

    @Slot(int)
    def _job_finished(self, revision: int) -> None:
        self._jobs.pop(revision, None)
        if not self._shutting_down and revision == self._revision:
            self.runningChanged.emit(False)

    def cancel_pending(self, *, notify: bool = True) -> None:
        jobs = tuple(self._jobs.values())
        if not jobs:
            return
        self._revision += 1
        for revision, (future, worker) in tuple(self._jobs.items()):
            worker.cancel()
            if future.cancel():
                self._jobs.pop(revision, None)
        self.runningChanged.emit(False)
        if notify:
            self.cancelled.emit()

    def shutdown(self, wait_ms: int = 3000) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        jobs = tuple(self._jobs.values())
        for future, worker in jobs:
            worker.cancel()
            future.cancel()
        deadline = monotonic() + max(0, int(wait_ms)) / 1000
        for future, _worker in jobs:
            try:
                future.result(timeout=max(0.0, deadline - monotonic()))
            except (CancelledError, TimeoutError):
                pass
            except Exception:
                logger.exception("Arrêt du worker waveform en erreur")
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._jobs.clear()
        self.runningChanged.emit(False)

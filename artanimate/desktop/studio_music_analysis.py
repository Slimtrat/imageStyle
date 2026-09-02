from __future__ import annotations

from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    TimeoutError,
)
from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..studio.assets import AssetAvailability, check_media_asset
from ..studio.clock import StudioClock
from ..studio.model import AssetKind, StudioProject
from ..studio.music_analysis import (
    MusicAnalysis,
    MusicAnalysisCache,
    MusicAnalysisCancelled,
    MusicAnalysisSettings,
    MusicEventKind,
)
from .problems import translate_studio_exception


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MusicAnalysisRequest:
    asset_id: str
    path: Path
    fingerprint: str
    fps: int
    settings: MusicAnalysisSettings


class StudioMusicAnalysisWorker(QObject):
    ready = Signal(int, str, object)
    failed = Signal(int, object)
    cancelled = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        revision: int,
        request: MusicAnalysisRequest,
        cache: MusicAnalysisCache,
    ) -> None:
        super().__init__()
        self.revision = revision
        self.request = request
        self.cache = cache
        self.cancellation = Event()

    def cancel(self) -> None:
        self.cancellation.set()

    def run(self) -> None:
        try:
            request = self.request
            result = self.cache.load_or_analyze(
                request.path,
                request.fingerprint,
                fps=request.fps,
                settings=request.settings,
                cancelled=self.cancellation,
            )
            if not self.cancellation.is_set():
                self.ready.emit(self.revision, request.asset_id, result)
        except MusicAnalysisCancelled:
            self.cancelled.emit(self.revision)
        except Exception as exc:
            if self.cancellation.is_set():
                self.cancelled.emit(self.revision)
            else:
                logger.exception("Analyse musicale locale impossible")
                self.failed.emit(self.revision, exc)
        finally:
            self.finished.emit(self.revision)


class StudioMusicAnalysisController(QObject):
    analysisReady = Signal(str, object)
    runningChanged = Signal(bool)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cache_dir: str | Path,
        cache: MusicAnalysisCache | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache or MusicAnalysisCache(cache_dir)
        self._revision = 0
        self._jobs: dict[
            int, tuple[Future[None], StudioMusicAnalysisWorker]
        ] = {}
        self._shutting_down = False
        self.worker_thread_prefix = f"ArtAnimateMusicAnalysis-{id(self):x}"
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=self.worker_thread_prefix,
        )

    @property
    def active_job_count(self) -> int:
        return len(self._jobs)

    def request(
        self,
        project: StudioProject,
        project_path: str | Path,
        asset_id: str,
        settings: MusicAnalysisSettings,
    ) -> int:
        project.validate()
        settings.validate()
        if self._shutting_down:
            return self._revision
        asset = next(
            (
                item
                for item in project.assets
                if item.asset_id == asset_id and item.kind == AssetKind.AUDIO
            ),
            None,
        )
        if asset is None:
            raise ValueError("La piste choisie n’est plus dans le projet")
        check = check_media_asset(asset, project_path)
        if (
            check.state == AssetAvailability.INVALID
            or check.current is None
            or not check.resolved_path.is_file()
        ):
            raise ValueError("La piste audio choisie est illisible ou manquante")
        self.cancel_pending(notify=False)
        self._revision += 1
        revision = self._revision
        request = MusicAnalysisRequest(
            asset_id,
            check.resolved_path,
            check.current.fingerprint,
            project.settings.fps,
            settings,
        )
        worker = StudioMusicAnalysisWorker(revision, request, self.cache)
        worker.ready.connect(self._ready, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(
            self._cancelled, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(
            self._job_finished, Qt.ConnectionType.QueuedConnection
        )
        gate = Event()

        def run_after_registration() -> None:
            gate.wait()
            worker.run()

        future = self._executor.submit(run_after_registration)
        self._jobs[revision] = (future, worker)
        gate.set()
        self.runningChanged.emit(True)
        return revision

    @Slot(int, str, object)
    def _ready(
        self,
        revision: int,
        asset_id: str,
        result: MusicAnalysis,
    ) -> None:
        if not self._shutting_down and revision == self._revision:
            self.analysisReady.emit(asset_id, result)

    @Slot(int, object)
    def _failed(self, revision: int, exc: Exception) -> None:
        if not self._shutting_down and revision == self._revision:
            job = self._jobs.get(revision)
            source = job[1].request.path if job else None
            self.failed.emit(
                translate_studio_exception(
                    exc,
                    "music_analysis",
                    source=source,
                )
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
        if not self._jobs:
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
                logger.exception("Arrêt du worker d’analyse musicale en erreur")
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._jobs.clear()
        self.runningChanged.emit(False)


_EVENT_LABELS = {
    MusicEventKind.BEAT: "Beat",
    MusicEventKind.DOWNBEAT: "Temps fort",
    MusicEventKind.DROP: "Drop",
}


class StudioMusicAnalysisPanel(QFrame):
    analysisRequested = Signal(str, object)
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioMusicAnalysisPanel")
        self._project: StudioProject | None = None
        self._project_path: Path | None = None
        self._result: MusicAnalysis | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("RYTHME · ANALYSE LOCALE")
        title.setObjectName("studioMusicAnalysisTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Le Studio propose des beats, temps forts et drops. "
            "Rien n’est encore imposé à la timeline."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Piste à analyser"))
        self.asset_combo = QComboBox()
        self.asset_combo.setObjectName("studioMusicAnalysisAsset")
        self.asset_combo.currentIndexChanged.connect(self._source_changed)
        layout.addWidget(self.asset_combo)

        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("Sensibilité"))
        self.sensitivity_value = QLabel()
        self.sensitivity_value.setObjectName("studioMusicSensitivityValue")
        sensitivity_row.addStretch(1)
        sensitivity_row.addWidget(self.sensitivity_value)
        layout.addLayout(sensitivity_row)
        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setObjectName("studioMusicSensitivity")
        self.sensitivity_slider.setRange(0, 100)
        self.sensitivity_slider.setSingleStep(5)
        self.sensitivity_slider.setPageStep(10)
        self.sensitivity_slider.valueChanged.connect(
            self._sensitivity_changed
        )
        layout.addWidget(self.sensitivity_slider)

        controls = QHBoxLayout()
        self.analyze_button = QPushButton("Analyser la piste")
        self.analyze_button.setObjectName("studioMusicAnalyze")
        self.analyze_button.clicked.connect(self._request_analysis)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setObjectName("studioMusicCancel")
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.analyze_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.status = QLabel(
            "Ajoutez une piste audio locale pour analyser son rythme."
        )
        self.status.setObjectName("studioMusicAnalysisStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.events = QTreeWidget()
        self.events.setObjectName("studioMusicEvents")
        self.events.setHeaderLabels(
            ("Timecode", "Événement", "Confiance")
        )
        self.events.setRootIsDecorated(False)
        self.events.setAlternatingRowColors(True)
        self.events.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.events.setMinimumHeight(150)
        layout.addWidget(self.events, 1)
        note = QLabel(
            "Les propositions « à vérifier » restent visibles. "
            "La prochaine étape permettra de les accepter et de les corriger."
        )
        note.setObjectName("studioMusicAnalysisNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.sensitivity_slider.setValue(55)
        self._update_enabled_state()

    @property
    def selected_asset_id(self) -> str | None:
        value = self.asset_combo.currentData()
        return str(value) if value is not None else None

    @property
    def settings(self) -> MusicAnalysisSettings:
        return MusicAnalysisSettings(
            self.sensitivity_slider.value() / 100.0
        ).validate()

    def set_context(
        self,
        project: StudioProject | None,
        project_path: str | Path | None,
    ) -> None:
        selected = self.selected_asset_id
        self._project = project
        self._project_path = (
            Path(project_path) if project_path is not None else None
        )
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        if project is not None:
            for asset in project.assets:
                if asset.kind == AssetKind.AUDIO:
                    self.asset_combo.addItem(
                        Path(asset.path).name,
                        asset.asset_id,
                    )
            settings = MusicAnalysisSettings.from_project(project)
            self.sensitivity_slider.blockSignals(True)
            self.sensitivity_slider.setValue(
                int(round(settings.sensitivity * 100))
            )
            self.sensitivity_slider.blockSignals(False)
            self._sensitivity_changed(self.sensitivity_slider.value())
        if selected is not None:
            index = self.asset_combo.findData(selected)
            if index >= 0:
                self.asset_combo.setCurrentIndex(index)
        self.asset_combo.blockSignals(False)
        self._result = None
        self.events.clear()
        if self.asset_combo.count():
            self.status.setText(
                "Prêt · l’analyse reste sur cette machine et ne modifie pas l’audio."
            )
        else:
            self.status.setText(
                "Ajoutez une piste audio locale pour analyser son rythme."
            )
        self._update_enabled_state()

    def set_busy(self, busy: bool) -> None:
        self.asset_combo.setEnabled(not busy and self.asset_combo.count() > 0)
        self.sensitivity_slider.setEnabled(not busy)
        self.analyze_button.setEnabled(
            not busy
            and self.selected_asset_id is not None
            and self._project_path is not None
        )
        self.cancel_button.setEnabled(busy)
        if busy:
            self.status.setText(
                "Analyse locale en cours… tempo, beats, temps forts et drops."
            )

    def set_result(self, asset_id: str, result: MusicAnalysis) -> None:
        if asset_id != self.selected_asset_id:
            return
        self._result = result.validate()
        self.events.clear()
        clock = StudioClock(result.fps)
        for event in result.events:
            state = "À vérifier" if event.uncertain else "Fiable"
            item = QTreeWidgetItem(
                (
                    clock.format_timecode(event.frame),
                    _EVENT_LABELS[event.kind],
                    f"{event.confidence * 100:.0f} % · {state}",
                )
            )
            if event.uncertain:
                item.setForeground(2, QColor("#f0b44d"))
            else:
                item.setForeground(2, QColor("#72d69a"))
            item.setData(0, Qt.ItemDataRole.UserRole, event.frame)
            item.setData(1, Qt.ItemDataRole.UserRole, event.kind.value)
            self.events.addTopLevelItem(item)
        counts = {
            kind: len(result.events_of(kind)) for kind in MusicEventKind
        }
        uncertain = sum(item.uncertain for item in result.events)
        tempo = (
            f"{result.tempo_bpm:.1f} BPM "
            f"({result.tempo_confidence * 100:.0f} % de confiance)"
            if result.tempo_bpm is not None
            else "tempo non déterminé"
        )
        origin = "cache local" if result.cache_hit else "calcul local"
        self.status.setText(
            f"{tempo} · {counts[MusicEventKind.BEAT]} beats · "
            f"{counts[MusicEventKind.DOWNBEAT]} temps forts · "
            f"{counts[MusicEventKind.DROP]} drops · "
            f"{uncertain} à vérifier · {origin}."
        )
        self.events.resizeColumnToContents(0)
        self.events.resizeColumnToContents(1)

    def set_feedback(self, message: str) -> None:
        self.status.setText(message)

    def _source_changed(self, _index: int) -> None:
        self._result = None
        self.events.clear()
        self._update_enabled_state()

    def _sensitivity_changed(self, value: int) -> None:
        if value < 35:
            qualifier = "sélective"
        elif value > 70:
            qualifier = "large"
        else:
            qualifier = "équilibrée"
        self.sensitivity_value.setText(f"{value} % · {qualifier}")
        self._result = None
        self.events.clear()

    def _request_analysis(self) -> None:
        asset_id = self.selected_asset_id
        if asset_id is not None:
            self.analysisRequested.emit(asset_id, self.settings)

    def _update_enabled_state(self) -> None:
        enabled = (
            self.selected_asset_id is not None
            and self._project_path is not None
        )
        self.asset_combo.setEnabled(self.asset_combo.count() > 0)
        self.sensitivity_slider.setEnabled(self._project is not None)
        self.analyze_button.setEnabled(enabled)
        self.cancel_button.setEnabled(False)

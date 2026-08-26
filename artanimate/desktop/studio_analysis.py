from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, TimeoutError
import logging
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..studio.analysis import (
    AnalysisCancelled,
    LocalCompositionAnalyzer,
    SceneAnalysisRequest,
    SceneAnalysisResult,
    SceneAnalyzer,
)
from ..studio.model import StudioProject
from ..studio.semantic import Bounds


logger = logging.getLogger(__name__)
_ANALYSIS_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="ArtAnimateSceneAnalysis",
)


class StudioAnalysisWorker(QObject):
    ready = Signal(int, object)
    failed = Signal(int, object)
    cancelled = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        revision: int,
        analyzer: SceneAnalyzer,
        request: SceneAnalysisRequest,
    ) -> None:
        super().__init__()
        self.revision = int(revision)
        self.analyzer = analyzer
        self.request = request

    def cancel(self) -> None:
        self.request.cancelled.set()

    def run(self) -> None:
        try:
            result = self.analyzer.analyze(self.request)
            if not self.request.cancelled.is_set():
                self.ready.emit(self.revision, result)
        except AnalysisCancelled:
            self.cancelled.emit(self.revision)
        except Exception as exc:
            if not self.request.cancelled.is_set():
                logger.exception("Analyse locale de scène impossible")
                self.failed.emit(self.revision, exc)
            else:
                self.cancelled.emit(self.revision)
        finally:
            self.finished.emit(self.revision)


class StudioAnalysisController(QObject):
    analysisReady = Signal(object)
    runningChanged = Signal(bool)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        analyzer: SceneAnalyzer | None = None,
        cache_dir: str | Path,
    ) -> None:
        super().__init__(parent)
        self.analyzer = analyzer or LocalCompositionAnalyzer()
        self.cache_dir = Path(cache_dir)
        self._revision = 0
        self._jobs: dict[int, tuple[Future[None], StudioAnalysisWorker]] = {}
        self._shutting_down = False

    @property
    def active_job_count(self) -> int:
        return len(self._jobs)

    def request(self, project: StudioProject, artwork_path: str | Path) -> int:
        project.validate()
        if self._shutting_down:
            return self._revision
        self.cancel_pending(notify=False)
        self._revision += 1
        revision = self._revision
        worker = StudioAnalysisWorker(
            revision,
            self.analyzer,
            SceneAnalysisRequest(
                Path(artwork_path),
                project.artwork.asset_id,
                self.cache_dir,
                Event(),
            ),
        )
        worker.ready.connect(self._ready, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(
            self._cancelled,
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

        future = _ANALYSIS_EXECUTOR.submit(run_after_registration)
        self._jobs[revision] = (future, worker)
        gate.set()
        self.runningChanged.emit(True)
        return revision

    @Slot(int, object)
    def _ready(self, revision: int, result: SceneAnalysisResult) -> None:
        if not self._shutting_down and revision == self._revision:
            self.analysisReady.emit(result)

    @Slot(int, object)
    def _failed(self, revision: int, exc: Exception) -> None:
        if not self._shutting_down and revision == self._revision:
            self.failed.emit(str(exc))

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
        for future, worker in jobs:
            worker.cancel()
            future.cancel()
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
                logger.exception("Arrêt du worker d’analyse locale en erreur")
        self._jobs.clear()
        self.runningChanged.emit(False)


class StudioAnalysisPanel(QFrame):
    analysisRequested = Signal()
    cancelRequested = Signal()
    selectionRequested = Signal(object, str)
    correctionRequested = Signal(str, object, str)
    maskRequested = Signal(object, str)
    ignoreRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioAnalysisPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._project: StudioProject | None = None
        self._selected_object_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(7)
        title = QLabel("ANALYSE LOCALE DE L’ŒUVRE")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Détecte une zone principale, un masque et une profondeur sans réseau. "
            "Toute proposition reste corrigeable ou ignorable."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        analysis_row = QHBoxLayout()
        self.analyze_button = QPushButton("Analyser localement")
        self.analyze_button.setObjectName("studioAnalyzeSceneButton")
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setObjectName("studioCancelAnalysisButton")
        analysis_row.addWidget(self.analyze_button)
        analysis_row.addWidget(self.cancel_button)
        layout.addLayout(analysis_row)
        self.status = QLabel("Aucune analyse avancée · les actions natives restent disponibles.")
        self.status.setObjectName("studioAnalysisStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.label_edit = QLineEdit("Zone manuelle")
        self.label_edit.setObjectName("studioAnalysisObjectLabel")
        form.addRow("Nom", self.label_edit)
        self.bounds_x = self._coordinate("studioAnalysisX", 0.15)
        self.bounds_y = self._coordinate("studioAnalysisY", 0.15)
        self.bounds_width = self._coordinate("studioAnalysisWidth", 0.7, minimum=0.01)
        self.bounds_height = self._coordinate("studioAnalysisHeight", 0.7, minimum=0.01)
        form.addRow("X", self.bounds_x)
        form.addRow("Y", self.bounds_y)
        form.addRow("Largeur", self.bounds_width)
        form.addRow("Hauteur", self.bounds_height)
        layout.addLayout(form)

        self.add_selection_button = QPushButton("Ajouter cette zone")
        self.add_selection_button.setObjectName("studioAddManualSelectionButton")
        self.add_mask_button = QPushButton("Associer un masque local…")
        self.add_mask_button.setObjectName("studioAddManualMaskButton")
        self.correct_button = QPushButton("Corriger la zone sélectionnée")
        self.correct_button.setObjectName("studioCorrectSceneObjectButton")
        self.ignore_button = QPushButton("Ignorer la détection sélectionnée")
        self.ignore_button.setObjectName("studioIgnoreSceneObjectButton")
        layout.addWidget(self.add_selection_button)
        layout.addWidget(self.add_mask_button)
        layout.addWidget(self.correct_button)
        layout.addWidget(self.ignore_button)
        layout.addStretch(1)

        self.analyze_button.clicked.connect(self.analysisRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.add_selection_button.clicked.connect(self._request_selection)
        self.add_mask_button.clicked.connect(self._request_mask)
        self.correct_button.clicked.connect(self._request_correction)
        self.ignore_button.clicked.connect(self._request_ignore)
        self.set_busy(False)
        self.set_project(None)

    @staticmethod
    def _coordinate(
        name: str,
        value: float,
        *,
        minimum: float = 0.0,
    ) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setDecimals(3)
        control.setSingleStep(0.01)
        control.setRange(minimum, 1.0)
        control.setValue(value)
        return control

    def set_project(self, project: StudioProject | None) -> None:
        self._project = project
        enabled = project is not None
        self.analyze_button.setEnabled(enabled and not self.cancel_button.isEnabled())
        self.add_selection_button.setEnabled(enabled)
        self.add_mask_button.setEnabled(enabled)
        if project is None or project.scene is None:
            self.status.setText("Importez une œuvre pour commencer l’analyse locale.")
        elif project.scene.analyzer_provenance:
            latest = project.scene.analyzer_provenance[-1]
            self.status.setText(
                f"Analyse {latest.analyzer_id} · version {latest.version} · "
                f"source {latest.source_fingerprint[-12:]}"
            )
        else:
            self.status.setText(
                "Aucune analyse avancée · les actions natives restent disponibles."
            )
        self.set_selected_target(self._selected_object_id)

    def set_selected_target(self, object_id: str | None) -> None:
        self._selected_object_id = object_id
        scene_object = (
            self._project.scene.object_by_id(object_id)
            if self._project is not None
            and self._project.scene is not None
            and object_id is not None
            else None
        )
        editable = (
            scene_object is not None
            and scene_object.semantic_type
            not in {"artwork", "scene.background", "scene.camera"}
        )
        self.correct_button.setEnabled(editable and scene_object.bounds is not None)
        self.ignore_button.setEnabled(editable)
        if editable and scene_object.bounds is not None:
            self.label_edit.setText(scene_object.label)
            self.bounds_x.setValue(scene_object.bounds.x)
            self.bounds_y.setValue(scene_object.bounds.y)
            self.bounds_width.setValue(scene_object.bounds.width)
            self.bounds_height.setValue(scene_object.bounds.height)

    def set_busy(self, busy: bool) -> None:
        self.cancel_button.setEnabled(bool(busy))
        self.analyze_button.setEnabled(not busy and self._project is not None)
        if busy:
            self.status.setText("Analyse locale en cours…")

    def set_feedback(self, message: str) -> None:
        self.status.setText(message)

    def bounds(self) -> Bounds:
        return Bounds(
            self.bounds_x.value(),
            self.bounds_y.value(),
            self.bounds_width.value(),
            self.bounds_height.value(),
        )

    def _validated_bounds(self) -> Bounds | None:
        try:
            return self.bounds()
        except ValueError as exc:
            self.status.setText(f"Zone invalide · {exc}")
            return None

    def _request_selection(self) -> None:
        bounds = self._validated_bounds()
        if bounds is not None:
            self.selectionRequested.emit(bounds, self.label_edit.text())

    def _request_mask(self) -> None:
        bounds = self._validated_bounds()
        if bounds is not None:
            self.maskRequested.emit(bounds, self.label_edit.text())

    def _request_correction(self) -> None:
        bounds = self._validated_bounds()
        if bounds is not None and self._selected_object_id is not None:
            self.correctionRequested.emit(
                self._selected_object_id,
                bounds,
                self.label_edit.text(),
            )

    def _request_ignore(self) -> None:
        if self._selected_object_id is not None:
            self.ignoreRequested.emit(self._selected_object_id)

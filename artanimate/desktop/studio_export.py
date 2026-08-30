from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, TimeoutError
from dataclasses import replace
import logging
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.video import RenderCancelled
from ..studio.export import StudioExportResult, export_studio_project
from ..studio.model import AudioExportMode, ExportSettings, StudioProject
from .problems import translate_studio_exception
from .studio3d_bridge import Studio3DCaptureBridge
from .studio3d_renderer import ClassicStudio3DRenderer


logger = logging.getLogger(__name__)


class StudioExportWorker(QObject):
    progress = Signal(int, int, int)
    phase = Signal(int, str)
    succeeded = Signal(int, object)
    failed = Signal(int, object)
    cancelled = Signal(int)
    finished = Signal(int)

    def __init__(
        self,
        job_id: int,
        project: StudioProject,
        artwork_path: Path,
        destination: Path,
        resource_base: Path | None,
        three_d_capture: Studio3DCaptureBridge,
    ) -> None:
        super().__init__()
        self.job_id = int(job_id)
        self.project = project
        self.artwork_path = artwork_path
        self.destination = destination
        self.resource_base = resource_base
        self.three_d_capture = three_d_capture
        self._cancelled = Event()

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
            result = export_studio_project(
                self.project,
                self.artwork_path,
                self.destination,
                resource_base=self.resource_base,
                progress=lambda done, total: self.progress.emit(
                    self.job_id, done, total
                ),
                phase=lambda value: self.phase.emit(self.job_id, value),
                should_cancel=self._cancelled.is_set,
                extra_renderers=(three_d_renderer,),
            )
            self.succeeded.emit(self.job_id, result)
        except RenderCancelled:
            self.cancelled.emit(self.job_id)
        except Exception as exc:
            logger.exception("Export Studio impossible")
            self.failed.emit(self.job_id, exc)
        finally:
            self.finished.emit(self.job_id)


class StudioExportController(QObject):
    progressChanged = Signal(int, int)
    phaseChanged = Signal(str)
    runningChanged = Signal(bool)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.three_d_capture = Studio3DCaptureBridge(self)
        self._job_id = 0
        self._job: tuple[Future[None], StudioExportWorker] | None = None
        self._shutting_down = False
        self.worker_thread_prefix = f"ArtAnimateExport-{id(self):x}"
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=self.worker_thread_prefix,
        )

    @property
    def running(self) -> bool:
        return self._job is not None

    def request(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        destination: str | Path,
        *,
        resource_base: str | Path | None = None,
    ) -> int:
        if self._shutting_down:
            raise RuntimeError("Le contrôleur d’export Studio est fermé")
        if self._job is not None:
            raise RuntimeError("Un export Studio est déjà en cours")
        self._job_id += 1
        worker = StudioExportWorker(
            self._job_id,
            project.validate(),
            Path(artwork_path),
            Path(destination),
            Path(resource_base) if resource_base is not None else None,
            self.three_d_capture,
        )
        worker.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        worker.phase.connect(self._phase, Qt.ConnectionType.QueuedConnection)
        worker.succeeded.connect(self._succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(self._cancelled, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        gate = Event()

        def run_after_registration() -> None:
            gate.wait()
            worker.run()

        future = self._executor.submit(run_after_registration)
        self._job = (future, worker)
        gate.set()
        self.runningChanged.emit(True)
        return self._job_id

    @Slot(int, int, int)
    def _progress(self, job_id: int, done: int, total: int) -> None:
        if not self._shutting_down and job_id == self._job_id:
            self.progressChanged.emit(done, total)

    @Slot(int, str)
    def _phase(self, job_id: int, phase: str) -> None:
        if not self._shutting_down and job_id == self._job_id:
            self.phaseChanged.emit(phase)

    @Slot(int, object)
    def _succeeded(self, job_id: int, result: StudioExportResult) -> None:
        if not self._shutting_down and job_id == self._job_id:
            self.succeeded.emit(result)

    @Slot(int, object)
    def _failed(self, job_id: int, exc: Exception) -> None:
        if not self._shutting_down and job_id == self._job_id:
            worker = self._job[1] if self._job is not None else None
            self.failed.emit(
                translate_studio_exception(
                    exc,
                    "export",
                    source=worker.artwork_path if worker is not None else None,
                    destination=worker.destination.parent if worker is not None else None,
                )
            )

    @Slot(int)
    def _cancelled(self, job_id: int) -> None:
        if not self._shutting_down and job_id == self._job_id:
            self.cancelled.emit()

    @Slot(int)
    def _finished(self, job_id: int) -> None:
        if job_id != self._job_id:
            return
        self._job = None
        if not self._shutting_down:
            self.runningChanged.emit(False)

    def cancel(self) -> None:
        if self._job is None:
            return
        future, worker = self._job
        worker.cancel()
        self.three_d_capture.cancel_pending()
        if future.cancel():
            self._job = None
            if not self._shutting_down:
                self.runningChanged.emit(False)
                self.cancelled.emit()

    def shutdown(self, wait_ms: int = 5000) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        job = self._job
        if job is not None:
            future, worker = job
            worker.cancel()
            self.three_d_capture.cancel_pending()
            future.cancel()
            deadline = monotonic() + max(0, int(wait_ms)) / 1000
            try:
                future.result(timeout=max(0.0, deadline - monotonic()))
            except (CancelledError, TimeoutError):
                pass
            except Exception:
                logger.exception("Arrêt du worker d’export Studio en erreur")
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._job = None
        self.three_d_capture.close()


class StudioExportPanel(QWidget):
    settingsRequested = Signal(str, int, str, str)
    exportRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: StudioProject | None = None
        self._syncing = False
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        heading = QLabel("EXPORT FINAL LOCAL")
        heading.setObjectName("studioExportHeading")
        layout.addWidget(heading)
        description = QLabel(
            "Le Reel est calculé image par image avec le même moteur que l’aperçu, "
            "puis remplacé atomiquement à la destination."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.format_label = QLabel("Aucun projet")
        self.format_label.setWordWrap(True)
        form.addRow("Format", self.format_label)
        self.container = QComboBox()
        self.container.setObjectName("studioExportContainer")
        self.container.addItem("MP4 · H.264", "mp4")
        self.container.addItem("MOV · H.264", "mov")
        self.container.addItem("WebM · VP9", "webm")
        form.addRow("Conteneur", self.container)
        self.quality = QComboBox()
        self.quality.setObjectName("studioExportQuality")
        self.quality.addItem("Studio · encodage soigné", "studio")
        self.quality.addItem("Rapide · validation", "fast")
        form.addRow("Profil", self.quality)
        self.audio_mode = QComboBox()
        self.audio_mode.setObjectName("studioExportAudioMode")
        self.audio_mode.addItem("Référence · vidéo seule", AudioExportMode.REFERENCE.value)
        self.audio_mode.addItem("Intégré · AAC / Opus", AudioExportMode.EMBEDDED.value)
        form.addRow("Musique", self.audio_mode)
        self.crf = QSpinBox()
        self.crf.setObjectName("studioExportCrf")
        self.crf.setRange(0, 51)
        self.crf.setToolTip("Plus la valeur est basse, plus la qualité et le fichier augmentent.")
        form.addRow("CRF", self.crf)
        layout.addLayout(form)

        self.destination_label = QLabel("Aucune destination choisie")
        self.destination_label.setObjectName("studioExportDestination")
        self.destination_label.setWordWrap(True)
        layout.addWidget(self.destination_label)
        self.progress = QProgressBar()
        self.progress.setObjectName("studioExportProgress")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("En attente")
        layout.addWidget(self.progress)
        self.status = QLabel("Prêt à exporter localement.")
        self.status.setObjectName("studioExportStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        self.export_button = QPushButton("Choisir et exporter…")
        self.export_button.setObjectName("studioExportStart")
        self.export_button.clicked.connect(self.exportRequested)
        actions.addWidget(self.export_button, 1)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setObjectName("studioExportCancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancelRequested)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.container.currentIndexChanged.connect(self._settings_changed)
        self.quality.currentIndexChanged.connect(self._settings_changed)
        self.audio_mode.currentIndexChanged.connect(self._settings_changed)
        self.crf.valueChanged.connect(self._settings_changed)
        self.set_project(None)

    def set_project(self, project: StudioProject | None) -> None:
        self._project = project
        self._syncing = True
        try:
            enabled = project is not None and not self._running
            self.container.setEnabled(enabled)
            self.quality.setEnabled(enabled)
            self.audio_mode.setEnabled(enabled)
            self.crf.setEnabled(enabled)
            self.export_button.setEnabled(enabled)
            if project is None:
                self.format_label.setText("Aucun projet")
                self.destination_label.setText("Aucune destination choisie")
                self.status.setText("Ouvrez une œuvre pour préparer l’export.")
                return
            settings = project.settings
            duration = settings.duration_frames / settings.fps
            self.format_label.setText(
                f"{settings.width} × {settings.height} · {settings.fps} FPS · "
                f"{duration:g} s · {settings.duration_frames} images"
            )
            self._select_data(self.container, project.export.container)
            self._select_data(self.quality, project.export.quality)
            self._select_data(self.audio_mode, project.export.audio_mode.value)
            self.crf.setValue(project.export.crf)
            if not self.status.text() or self.status.text().startswith("Ouvrez"):
                self.status.setText("Prêt à exporter localement.")
        finally:
            self._syncing = False

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _settings_changed(self, _value: int) -> None:
        if self._syncing or self._project is None:
            return
        self.settingsRequested.emit(
            str(self.container.currentData()),
            int(self.crf.value()),
            str(self.quality.currentData()),
            str(self.audio_mode.currentData()),
        )

    def settings(self) -> ExportSettings:
        if self._project is None:
            raise RuntimeError("Aucun projet Studio à exporter")
        return replace(
            self._project.export,
            container=str(self.container.currentData()),
            crf=int(self.crf.value()),
            quality=str(self.quality.currentData()),
            audio_mode=AudioExportMode(str(self.audio_mode.currentData())),
        ).validate()

    def set_destination(self, path: str | Path) -> None:
        self.destination_label.setText(str(Path(path)))

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        enabled = self._project is not None and not self._running
        self.container.setEnabled(enabled)
        self.quality.setEnabled(enabled)
        self.audio_mode.setEnabled(enabled)
        self.crf.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.cancel_button.setEnabled(self._running)
        if self._running:
            self.status.setText("Rendu final en cours…")

    def set_progress(self, done: int, total: int) -> None:
        safe_total = max(1, int(total))
        self.progress.setRange(0, safe_total)
        self.progress.setValue(max(0, min(int(done), safe_total)))
        self.progress.setFormat(f"{done} / {total} images · %p %")

    def set_phase(self, phase: str) -> None:
        messages = {
            "video": "Calcul des images et encodage vidéo…",
            "audio": "Décodage et mix PCM local…",
            "mux": "Intégration de la musique sans réencoder les images…",
            "complete": "Finalisation atomique terminée.",
        }
        self.status.setText(messages.get(phase, f"Export · {phase}"))

    def show_success(self, result: StudioExportResult) -> None:
        self.progress.setRange(0, max(1, result.frame_count))
        self.progress.setValue(result.frame_count)
        self.progress.setFormat("Export terminé · 100 %")
        audio = (
            "musique intégrée"
            if result.audio_mode == AudioExportMode.EMBEDDED
            else "vidéo seule · musique de référence conservée"
        )
        self.status.setText(
            f"Reel créé · {result.width} × {result.height} · {result.fps} FPS · "
            f"{result.frame_count} images · {audio}."
        )
        self.set_destination(result.path)

    def show_cancelled(self) -> None:
        self.progress.setFormat("Export annulé")
        self.status.setText(
            "Export annulé · le fichier existant est resté intact et le temporaire a été supprimé."
        )

    def show_error(self, message: str) -> None:
        self.progress.setFormat("Échec de l’export")
        self.status.setText(f"Export impossible · {message}")

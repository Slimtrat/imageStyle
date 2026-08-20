from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from ..core.analysis import analyze_artwork
from ..core.config import RenderConfig
from ..core.renderer import ArtworkRenderer
from ..core.video import RenderCancelled, encode_video
from .preview import frame_to_qimage
from .problems import (
    translate_exception,
    validate_destination_path,
    validate_source_path,
)


logger = logging.getLogger(__name__)


class RenderWorker(QObject):
    progress = Signal(int)
    preview = Signal(QImage)
    thumbnail = Signal(QImage)
    status = Signal(str)
    finished = Signal(str)
    cancelled = Signal()
    failed = Signal(object)

    def __init__(self, source: Path, destination: Path, config: RenderConfig):
        super().__init__()
        self.source = source
        self.destination = destination
        self.config = config
        self._cancelled = Event()

    def cancel(self) -> None:
        logger.info("Demande d’annulation reçue")
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        try:
            logger.info("Tâche desktop démarrée : %s -> %s", self.source, self.destination)
            source = validate_source_path(self.source, verify_image=False)
            validate_destination_path(self.destination.parent)
            self.status.emit("Analyse des couleurs et des contours…")
            analysis = analyze_artwork(source, self.config)
            if self._cancelled.is_set():
                raise RenderCancelled("Rendu annulé")
            self.status.emit("Préparation des masques d’animation…")
            renderer = ArtworkRenderer(analysis, self.config)
            self.thumbnail.emit(
                frame_to_qimage(renderer.frame_at(self.config.duration * 0.56))
            )
            preview_stride = max(1, renderer.frame_count // 72)

            def on_progress(done: int, total: int) -> None:
                self.progress.emit(int(round(done * 100 / total)))

            def on_frame(frame, done: int, total: int) -> None:  # type: ignore[no-untyped-def]
                if done == 1 or done == total or done % preview_stride == 0:
                    self.preview.emit(frame_to_qimage(frame))

            validate_destination_path(self.destination.parent)
            self.status.emit("Création de la vidéo…")
            encode_video(
                renderer,
                self.destination,
                on_progress,
                frame_callback=on_frame,
                should_cancel=self._cancelled.is_set,
            )
            self.progress.emit(100)
            logger.info("Tâche desktop terminée : %s", self.destination.resolve())
            self.finished.emit(str(self.destination.resolve()))
        except RenderCancelled:
            logger.warning("Tâche desktop annulée")
            self.cancelled.emit()
        except Exception as exc:
            logger.exception("Échec de la tâche desktop")
            self.failed.emit(
                translate_exception(
                    exc,
                    "render",
                    source=self.source,
                    destination=self.destination.parent,
                )
            )

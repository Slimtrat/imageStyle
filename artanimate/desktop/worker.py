from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from ..core.analysis import analyze_artwork
from ..core.config import RenderConfig
from ..core.renderer import ArtworkRenderer
from ..core.video import RenderCancelled, encode_video


class RenderWorker(QObject):
    progress = Signal(int)
    preview = Signal(QImage)
    status = Signal(str)
    finished = Signal(str)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, source: Path, destination: Path, config: RenderConfig):
        super().__init__()
        self.source = source
        self.destination = destination
        self.config = config
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("Analyse des couleurs et des contours…")
            analysis = analyze_artwork(self.source, self.config)
            if self._cancelled.is_set():
                raise RenderCancelled("Rendu annulé")
            self.status.emit("Préparation des masques d’animation…")
            renderer = ArtworkRenderer(analysis, self.config)
            preview_stride = max(1, renderer.frame_count // 72)

            def on_progress(done: int, total: int) -> None:
                self.progress.emit(int(round(done * 100 / total)))

            def on_frame(frame, done: int, total: int) -> None:  # type: ignore[no-untyped-def]
                if done == 1 or done == total or done % preview_stride == 0:
                    height, width = frame.shape[:2]
                    image = QImage(
                        frame.data,
                        width,
                        height,
                        width * 3,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    self.preview.emit(image)

            self.status.emit("Création de la vidéo…")
            encode_video(
                renderer,
                self.destination,
                on_progress,
                frame_callback=on_frame,
                should_cancel=self._cancelled.is_set,
            )
            self.progress.emit(100)
            self.finished.emit(str(self.destination.resolve()))
        except RenderCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

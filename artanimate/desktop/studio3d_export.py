from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from ..core.analysis import analyze_artwork
from ..core.config import RenderConfig
from ..core.renderer import ArtworkRenderer
from ..core.video import RenderCancelled
from .preview import frame_to_qimage
from .problems import translate_exception, validate_source_path


logger = logging.getLogger(__name__)
STUDIO_TEXTURE_WIDTH = 720


def effect_progress(config: RenderConfig, frame_index: int, frame_count: int) -> float:
    """Return the active-effect progress, excluding the configured holds."""
    if frame_count < 2:
        raise ValueError("Une animation 3D doit contenir au moins deux images")
    seconds = config.duration * frame_index / (frame_count - 1)
    active_end = config.duration - config.hold_end
    if seconds <= config.hold_start:
        return 0.0
    if seconds >= active_end:
        return 1.0
    return (seconds - config.hold_start) / (active_end - config.hold_start)


def qimage_to_rgb(image: QImage) -> np.ndarray:
    """Copy a QImage into a tightly packed uint8 RGB NumPy frame."""
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width = converted.width()
    height = converted.height()
    if width <= 0 or height <= 0:
        raise ValueError("Capture 3D vide")
    row_bytes = converted.bytesPerLine()
    buffer = np.frombuffer(converted.constBits(), dtype=np.uint8).reshape(
        height, row_bytes
    )
    return np.ascontiguousarray(buffer[:, : width * 3].reshape(height, width, 3))


class Studio3DFrameWorker(QObject):
    """Stream effect textures with explicit GUI backpressure between frames."""

    prepared = Signal(int, int, int)
    frame_ready = Signal(QImage, int, int, float)
    finished = Signal()
    cancelled = Signal()
    failed = Signal(object)

    def __init__(self, source: Path, config: RenderConfig):
        super().__init__()
        self.source = source
        self.config = config.with_overrides(
            {"width": min(config.width, STUDIO_TEXTURE_WIDTH)}
        )
        self._cancelled = Event()
        self._acknowledged = Event()

    def acknowledge(self) -> None:
        """Allow the producer to compute the next texture after GUI capture."""
        self._acknowledged.set()

    def cancel(self) -> None:
        logger.info("Annulation du rendu Studio 3D demandée")
        self._cancelled.set()
        self._acknowledged.set()

    @Slot()
    def run(self) -> None:
        try:
            source = validate_source_path(self.source, verify_image=False)
            logger.info(
                "Préparation du rendu Studio 3D : source=%s, effet=%s, texture=%d px",
                source,
                self.config.effect,
                self.config.width,
            )
            analysis = analyze_artwork(source, self.config)
            if self._cancelled.is_set():
                raise RenderCancelled("Rendu 3D annulé")
            renderer = ArtworkRenderer(analysis, self.config)
            total = renderer.frame_count
            self.prepared.emit(total, renderer.width, renderer.height)
            for index, frame in enumerate(renderer.frames()):
                if self._cancelled.is_set():
                    raise RenderCancelled("Rendu 3D annulé")
                progress = effect_progress(self.config, index, total)
                self._acknowledged.clear()
                self.frame_ready.emit(
                    frame_to_qimage(frame), index, total, progress
                )
                while not self._acknowledged.wait(0.05):
                    if self._cancelled.is_set():
                        raise RenderCancelled("Rendu 3D annulé")
            logger.info("Toutes les textures du rendu Studio 3D ont été composées")
            self.finished.emit()
        except RenderCancelled:
            logger.warning("Composition du Studio 3D annulée")
            self.cancelled.emit()
        except Exception as exc:
            logger.exception("Échec de la composition Studio 3D")
            self.failed.emit(
                translate_exception(exc, "render", source=self.source)
            )

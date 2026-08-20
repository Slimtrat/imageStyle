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
from .problems import translate_exception, validate_source_path


logger = logging.getLogger(__name__)

PREVIEW_WIDTH = 384
PREVIEW_COLORS = 12
PREVIEW_DURATION = 6.0
PREVIEW_FRAME_COUNT = 24
PREVIEW_INTERVAL_MS = 180


def build_preview_config(config: RenderConfig) -> RenderConfig:
    """Return a bounded low-cost configuration preserving the artistic choices."""
    return config.with_overrides(
        {
            "width": min(config.width, PREVIEW_WIDTH),
            "colors": min(config.colors, PREVIEW_COLORS),
            "duration": PREVIEW_DURATION,
            "fps": 10,
            "hold_start": 0.25,
            "hold_end": 0.35,
        }
    )


def frame_to_qimage(frame: np.ndarray) -> QImage:
    """Detach an RGB NumPy frame from its buffer for safe cross-thread delivery."""
    height, width = frame.shape[:2]
    return QImage(
        frame.data,
        width,
        height,
        width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


class PreviewWorker(QObject):
    """Build a small in-memory animation without invoking the video encoder."""

    ready = Signal(int, object, str)
    failed = Signal(int, object)
    finished = Signal(int)

    def __init__(self, source: Path, config: RenderConfig, revision: int):
        super().__init__()
        self.source = source
        self.config = build_preview_config(config)
        self.revision = revision
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        try:
            logger.info(
                "Prérendu démarré : effet=%s, largeur=%d, images=%d",
                self.config.effect,
                self.config.width,
                PREVIEW_FRAME_COUNT,
            )
            source = validate_source_path(self.source, verify_image=False)
            analysis = analyze_artwork(source, self.config)
            if self._cancelled.is_set():
                logger.info("Prérendu obsolète annulé après analyse")
                return
            renderer = ArtworkRenderer(analysis, self.config)
            frames: list[QImage] = []
            for seconds in np.linspace(
                0.0,
                self.config.duration,
                PREVIEW_FRAME_COUNT,
            ):
                if self._cancelled.is_set():
                    logger.info("Prérendu obsolète annulé pendant la composition")
                    return
                frames.append(frame_to_qimage(renderer.frame_at(float(seconds))))
            quality = (
                f"Prérendu {renderer.width}×{renderer.height} · "
                f"{PREVIEW_FRAME_COUNT} images"
            )
            logger.info("Prérendu prêt : %s", quality)
            self.ready.emit(self.revision, tuple(frames), quality)
        except Exception as exc:
            logger.exception("Échec du prérendu")
            self.failed.emit(
                self.revision,
                translate_exception(exc, "preview", source=self.source),
            )
        finally:
            self.finished.emit(self.revision)

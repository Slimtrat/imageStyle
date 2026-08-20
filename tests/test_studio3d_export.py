import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QImage

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d import StudioExportSettings
from artanimate.desktop.studio3d_export import (
    Studio3DFrameWorker,
    capture_requires_retry,
    effect_progress,
    qimage_to_rgb,
)


def test_effect_progress_excludes_holds() -> None:
    config = RenderConfig(duration=10.0, fps=10, hold_start=2.0, hold_end=2.0)

    assert effect_progress(config, 0, 101) == 0.0
    assert effect_progress(config, 20, 101) == 0.0
    assert effect_progress(config, 50, 101) == pytest.approx(0.5)
    assert effect_progress(config, 80, 101) == 1.0
    assert effect_progress(config, 100, 101) == 1.0


def test_blank_gpu_capture_is_retried_but_a_dark_scene_is_kept() -> None:
    assert capture_requires_retry(np.full((32, 48, 3), 255, dtype=np.uint8))
    assert capture_requires_retry(np.zeros((32, 48, 3), dtype=np.uint8))

    scene = np.full((32, 48, 3), 12, dtype=np.uint8)
    scene[8:24, 14:34] = (48, 72, 56)
    assert not capture_requires_retry(scene)


def test_qimage_conversion_removes_scanline_padding() -> None:
    image = QImage(7, 5, QImage.Format.Format_RGB888)
    image.fill("#7846dc")

    frame = qimage_to_rgb(image)

    assert frame.shape == (5, 7, 3)
    assert frame.dtype == np.uint8
    assert frame.flags.c_contiguous
    assert frame.flags.owndata
    assert tuple(frame[0, 0]) == (120, 70, 220)

def test_export_dimensions_keep_the_selected_long_edge() -> None:
    horizontal = StudioExportSettings("wide.mp4", ".mp4", 1920, 16 / 9)
    vertical = StudioExportSettings("story.mp4", ".mp4", 1920, 9 / 16)
    square = StudioExportSettings("square.mp4", ".mp4", 1280, 1.0)

    assert (horizontal.width, horizontal.height) == (1920, 1080)
    assert (vertical.width, vertical.height) == (1080, 1920)
    assert (square.width, square.height) == (1280, 1280)


def test_frame_worker_streams_one_texture_at_a_time(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 80), (210, 45, 90)).save(source)
    worker = Studio3DFrameWorker(
        source,
        RenderConfig(
            effect="rgb_fade",
            duration=3.0,
            fps=12,
            width=64,
            quality="fast",
        ),
    )
    frames: list[tuple[int, int, float]] = []
    prepared: list[tuple[int, int, int]] = []
    finished: list[bool] = []

    def accept_frame(_image: QImage, index: int, total: int, progress: float) -> None:
        frames.append((index, total, progress))
        worker.acknowledge()

    worker.prepared.connect(lambda total, width, height: prepared.append((total, width, height)))
    worker.frame_ready.connect(accept_frame)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()

    assert prepared == [(36, 64, 44)]
    assert len(frames) == 36
    assert frames[0][2] == 0.0
    assert frames[-1][2] == 1.0
    assert finished == [True]

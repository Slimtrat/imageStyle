import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QImage

from artanimate.core.config import RenderConfig
from artanimate.desktop.preview import (
    PREVIEW_COLORS,
    PREVIEW_DURATION,
    PREVIEW_FRAME_COUNT,
    PREVIEW_WIDTH,
    PreviewWorker,
    build_preview_config,
)


def make_source(path: Path) -> None:
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 75, 90), fill=(225, 40, 50))
    draw.rectangle((85, 10, 150, 90), fill=(35, 90, 225))
    draw.ellipse((55, 25, 105, 75), fill=(240, 190, 35))
    image.save(path)


def test_preview_configuration_is_bounded_but_preserves_effect() -> None:
    config = RenderConfig(
        effect="wave",
        width=1920,
        colors=32,
        direction="radial",
        seed=42,
    )
    preview = build_preview_config(config)

    assert preview.effect == "wave"
    assert preview.direction == "radial"
    assert preview.seed == 42
    assert preview.width == PREVIEW_WIDTH
    assert preview.colors == PREVIEW_COLORS
    assert preview.duration == PREVIEW_DURATION
    assert preview.fps == 10


def test_preview_worker_builds_an_in_memory_animation(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    make_source(source)
    ready: list[tuple[int, tuple[QImage, ...], str]] = []
    finished: list[int] = []
    worker = PreviewWorker(
        source,
        RenderConfig(width=320, colors=8, duration=6.0),
        revision=7,
    )
    worker.ready.connect(
        lambda revision, frames, quality: ready.append((revision, frames, quality))
    )
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [7]
    assert len(ready) == 1
    revision, frames, quality = ready[0]
    assert revision == 7
    assert len(frames) == PREVIEW_FRAME_COUNT
    assert all(not frame.isNull() for frame in frames)
    assert frames[0] != frames[len(frames) // 2]
    assert "Prérendu" in quality

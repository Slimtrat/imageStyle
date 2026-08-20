from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.core.analysis import PRESENTATION_CANVAS_COLOR, analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer


def test_saturated_border_color_is_animated_instead_of_filling_opening(
    tmp_path: Path,
) -> None:
    source = tmp_path / "yellow-artwork.png"
    image = Image.new("RGB", (100, 80), (210, 161, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 14, 82, 66), fill=(35, 75, 205), outline=(15, 15, 18), width=3)
    image.save(source)
    config = RenderConfig(
        width=100,
        colors=6,
        duration=2,
        fps=5,
        background_tolerance=8,
    )

    analysis = analyze_artwork(source, config)
    first = ArtworkRenderer(analysis, config).frame_at(0)

    assert analysis.background_color == PRESENTATION_CANVAS_COLOR
    assert not analysis.background_mask.any()
    assert np.all(first == np.asarray(PRESENTATION_CANVAS_COLOR, dtype=np.uint8))
    candidate = np.asarray((210, 161, 30), dtype=np.float32)
    assert any(
        np.linalg.norm(np.asarray(layer.color, dtype=np.float32) - candidate) < 30
        for layer in analysis.layers
    )

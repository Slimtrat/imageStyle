from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.analysis import analyze_artwork
from artanimate.config import RenderConfig


def make_artwork(path: Path) -> None:
    image = Image.new("RGB", (128, 96), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 48, 82), fill=(235, 30, 40), outline="black", width=3)
    draw.ellipse((54, 12, 112, 66), fill=(25, 85, 220), outline="black", width=3)
    draw.rectangle((62, 70, 110, 86), fill=(245, 155, 20), outline="black", width=3)
    image.save(path)


def test_analysis_detects_background_outline_and_families(tmp_path: Path) -> None:
    source = tmp_path / "art.png"
    make_artwork(source)
    config = RenderConfig(width=128, colors=8, background_tolerance=5, outline_luma=30)
    analysis = analyze_artwork(source, config)
    keys = {layer.key for layer in analysis.layers}
    assert {"red", "orange", "blue"}.issubset(keys)
    assert analysis.outline is not None
    assert analysis.outline.pixel_count > 300
    assert analysis.background_mask[0, 0]
    assert analysis.size == (128, 96)


def test_chromatic_order_places_neutral_last(tmp_path: Path) -> None:
    source = tmp_path / "art.png"
    make_artwork(source)
    config = RenderConfig(width=128, colors=8)
    analysis = analyze_artwork(source, config)
    ordered = analysis.ordered_layers("chromatic", 0)
    keys = [layer.key for layer in ordered]
    assert keys.index("red") < keys.index("orange") < keys.index("blue")

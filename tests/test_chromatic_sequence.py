from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.core.analysis import ArtworkAnalysis, ColorLayer, analyze_artwork
from artanimate.core.config import RenderConfig


def _layer(key: str, hue: float, luma: float) -> ColorLayer:
    return ColorLayer(
        key=key,
        label=key,
        color=(128, 128, 128),
        mask=np.ones((1, 1), dtype=bool),
        hue=hue,
        luma=luma,
        pixel_count=1,
    )


def test_rotated_chromatic_order_and_separate_neutrals() -> None:
    analysis = ArtworkAnalysis(
        source=np.zeros((1, 1, 3), dtype=np.uint8),
        background_color=(255, 255, 255),
        background_mask=np.zeros((1, 1), dtype=bool),
        layers=[
            _layer("red", 0, 50),
            _layer("green", 125, 50),
            _layer("blue", 232, 50),
            _layer("neutral_light", 0, 82),
            _layer("neutral_dark", 0, 42),
        ],
        outline=None,
        source_path="synthetic.png",
    )

    last = analysis.ordered_layers("chromatic", 120, "last")
    first = analysis.ordered_layers("chromatic", 120, "first")
    reverse = analysis.ordered_layers("reverse", 120, "last")

    assert [layer.key for layer in last] == [
        "green",
        "blue",
        "red",
        "neutral_dark",
        "neutral_light",
    ]
    assert [layer.key for layer in first[:2]] == ["neutral_dark", "neutral_light"]
    assert [layer.key for layer in reverse[:3]] == ["red", "blue", "green"]


def test_completed_analysis_remains_a_disjoint_full_partition(tmp_path: Path) -> None:
    source = tmp_path / "partition.png"
    image = Image.new("RGB", (72, 60), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 63, 51), fill=(225, 35, 40), outline="black", width=2)
    draw.ellipse((30, 22, 42, 34), fill=(35, 95, 225))
    draw.point((20, 20), fill=(35, 95, 225))
    image.save(source)

    analysis = analyze_artwork(
        source,
        RenderConfig(
            width=72,
            colors=6,
            background_tolerance=5,
            outline_luma=30,
            shape_completion=2,
        ),
    )
    stack = np.stack([layer.mask for layer in analysis.layers], axis=0)
    expected = ~analysis.background_mask
    if analysis.outline is not None:
        expected &= ~analysis.outline.mask

    assert np.all(stack.sum(axis=0) <= 1)
    assert np.array_equal(stack.any(axis=0), expected)

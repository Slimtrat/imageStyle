from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.quality import ease_in_out, exposure_average
from artanimate.core.renderer import ArtworkRenderer


def test_easing_is_smooth_monotonic_and_symmetric() -> None:
    values = [ease_in_out(value) for value in np.linspace(0.0, 1.0, 21)]
    assert values[0] == 0.0
    assert values[-1] == 1.0
    assert values == sorted(values)
    assert ease_in_out(0.25) == pytest.approx(1.0 - ease_in_out(0.75))
    assert ease_in_out(0.01) < 0.001


def test_temporal_exposure_is_accumulated_in_linear_light() -> None:
    black = np.zeros((2, 2, 3), dtype=np.uint8)
    white = np.full((2, 2, 3), 255, dtype=np.uint8)

    result = exposure_average((black, white))

    assert np.all((result >= 187) & (result <= 189))


def test_studio_frames_keep_exact_endpoints_and_blend_motion(tmp_path: Path) -> None:
    source = tmp_path / "motion.png"
    image = Image.new("RGB", (80, 60), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 72, 52), fill=(220, 35, 55))
    image.save(source)
    config = RenderConfig(
        effect="wave",
        quality="studio",
        width=80,
        colors=4,
        duration=2,
        fps=8,
        hold_start=0.1,
        hold_end=0.1,
    )
    analysis = analyze_artwork(source, config)
    renderer = ArtworkRenderer(analysis, config)

    frames = list(renderer.frames())
    middle_index = len(frames) // 2
    point_sample = renderer.frame_at(config.duration * middle_index / (len(frames) - 1))

    assert np.array_equal(frames[0], renderer.frame_at(0.0))
    assert np.array_equal(frames[-1], analysis.source)
    assert not np.array_equal(frames[middle_index], point_sample)


def test_unknown_quality_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="quality"):
        RenderConfig(quality="ultra-secret").validate()

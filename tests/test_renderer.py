from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.effects import reveal_opacity, wave_field
from artanimate.core.renderer import ArtworkRenderer


def make_source(path: Path) -> None:
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 45, 55), fill=(230, 35, 45), outline="black", width=2)
    draw.rectangle((50, 8, 88, 55), fill=(35, 95, 225), outline="black", width=2)
    image.save(path)


def test_reveal_is_monotonic() -> None:
    mask = np.ones((32, 48), dtype=bool)
    field = wave_field(48, 32, "left", 0.05, 2.0, 0.08, seed=3)
    early = reveal_opacity(mask, field, 0.25, 0.01)
    late = reveal_opacity(mask, field, 0.75, 0.01)
    assert np.all(late >= early)
    assert reveal_opacity(mask, field, 0, 0.01).sum() == 0
    assert reveal_opacity(mask, field, 1, 0.01).sum() == mask.sum()


def test_renderer_starts_blank_and_finishes_exactly(tmp_path: Path) -> None:
    path = tmp_path / "source.png"
    make_source(path)
    config = RenderConfig(
        effect="sand",
        width=96,
        colors=6,
        duration=2,
        fps=8,
        hold_start=0.2,
        hold_end=0.2,
        grain_density=0.001,
    )
    analysis = analyze_artwork(path, config)
    renderer = ArtworkRenderer(analysis, config)
    first = renderer.frame_at(0)
    middle = renderer.frame_at(1)
    final = renderer.frame_at(2)
    assert not np.array_equal(first, analysis.source)
    assert not np.array_equal(middle, first)
    assert np.array_equal(final, analysis.source)
    assert len(list(renderer.frames())) == 16


def test_wave_renderer_is_reproducible(tmp_path: Path) -> None:
    path = tmp_path / "source.png"
    make_source(path)
    config = RenderConfig(effect="wave", width=96, colors=6, duration=2, fps=5, seed=42)
    analysis = analyze_artwork(path, config)
    first = ArtworkRenderer(analysis, config).frame_at(1.0)
    second = ArtworkRenderer(analysis, config).frame_at(1.0)
    assert np.array_equal(first, second)


def test_screenprint_laser_keeps_black_outline_for_the_final_act(tmp_path: Path) -> None:
    path = tmp_path / "signature.png"
    make_source(path)
    config = RenderConfig(
        effect="screenprint_laser",
        outline="together",
        width=96,
        colors=6,
        duration=4,
        fps=8,
    )
    analysis = analyze_artwork(path, config)
    renderer = ArtworkRenderer(analysis, config)

    assert analysis.outline is not None
    assert renderer.stages[-1].is_outline
    assert renderer.stage_stride() == 1.0
    assert not np.array_equal(renderer.frame_at(2.0), analysis.source)
    assert np.array_equal(renderer.frame_at(4.0), analysis.source)


def test_decorated_effects_remain_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "decorated.png"
    make_source(path)
    for effect in ("vertical_halo", "screenprint", "contour_laser", "screenprint_laser"):
        config = RenderConfig(effect=effect, width=96, colors=6, duration=3, fps=8)
        analysis = analyze_artwork(path, config)
        first = ArtworkRenderer(analysis, config).frame_at(1.35)
        second = ArtworkRenderer(analysis, config).frame_at(1.35)
        assert np.array_equal(first, second), effect
        assert first.dtype == np.uint8

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer
from artanimate.core.quality import ease_in_out
from artanimate.desktop.studio3d_particles import (
    StudioLaserPathRecord,
    StudioSceneData,
    build_studio_scene_data,
    studio_laser_cursor,
)


def _artwork(path: Path) -> None:
    image = Image.new("RGB", (100, 70), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 49, 61), fill=(225, 38, 50), outline=(18, 18, 18), width=3)
    draw.rectangle((54, 9, 92, 60), fill=(30, 98, 224), outline=(18, 18, 18), width=3)
    image.save(path)


def test_every_studio_grain_uses_a_real_source_pixel_and_timing(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    _artwork(source)
    config = RenderConfig(
        effect="sand", width=100, colors=6, duration=5, fps=10, seed=19
    )
    analysis = analyze_artwork(source, config)
    renderer = ArtworkRenderer(analysis, config)
    scene = build_studio_scene_data(renderer, particle_count=180)

    assert len(scene.particles) == 180
    assert scene.stage_count == len(renderer.stages)
    settlements = set()
    for grain in scene.particles:
        x = int(grain.target_u * renderer.width)
        y = int(grain.target_v * renderer.height)
        assert grain.color == tuple(int(channel) for channel in analysis.source[y, x])
        assert 0.0 <= grain.birth_progress <= grain.settle_progress <= 1.0
        settlements.add(round(grain.settle_progress, 4))
    assert len(settlements) > 12


def test_paint_drop_stages_target_real_analyzed_pixels(tmp_path: Path) -> None:
    source = tmp_path / "paint.png"
    _artwork(source)
    config = RenderConfig(effect="paint_drop", width=100, colors=6)
    analysis = analyze_artwork(source, config)
    renderer = ArtworkRenderer(analysis, config)
    scene = build_studio_scene_data(renderer)

    assert len(scene.tool_stages) == len(renderer.stages)
    for stage, layer in zip(scene.tool_stages, renderer.stages, strict=True):
        x = min(renderer.width - 1, int(stage.target_u * renderer.width))
        y = min(renderer.height - 1, int(stage.target_v * renderer.height))
        assert layer.mask[y, x]
        assert stage.color == layer.color


def test_laser_studio_path_matches_the_detected_contour_stage(tmp_path: Path) -> None:
    source = tmp_path / "laser.png"
    _artwork(source)
    config = RenderConfig(effect="contour_laser", width=100, colors=6)
    renderer = ArtworkRenderer(analyze_artwork(source, config), config)
    scene = build_studio_scene_data(renderer)

    assert len(scene.laser_path) > 20
    assert any(point.laser_on for point in scene.laser_path)
    assert all(0.0 <= point.target_u <= 1.0 for point in scene.laser_path)
    assert all(0.0 <= point.target_v <= 1.0 for point in scene.laser_path)
    outline = next(layer for layer in renderer.stages if layer.is_outline)
    for point in scene.laser_path:
        if not point.laser_on:
            continue
        x = min(renderer.width - 1, int(point.target_u * renderer.width))
        y = min(renderer.height - 1, int(point.target_v * renderer.height))
        assert outline.mask[y, x]


def test_laser_cursor_matches_the_renderer_eased_contour_field(tmp_path: Path) -> None:
    source = tmp_path / "cursor.png"
    _artwork(source)
    config = RenderConfig(effect="contour_laser", width=140, colors=6)
    renderer = ArtworkRenderer(analyze_artwork(source, config), config)
    scene = build_studio_scene_data(renderer)
    outline = next(layer for layer in renderer.stages if layer.is_outline)
    field = renderer.fields[outline.key]
    errors = []

    for progress in np.linspace(0.04, 0.96, 80):
        cursor = studio_laser_cursor(scene, "contour_laser", float(progress))
        if not cursor.beam_on:
            continue
        x = min(renderer.width - 1, int(cursor.target_u * renderer.width))
        y = min(renderer.height - 1, int(cursor.target_v * renderer.height))
        assert outline.mask[y, x]
        errors.append(abs(float(field[y, x]) - ease_in_out(float(progress))))

    assert len(errors) > 30
    assert float(np.percentile(errors, 95)) < 0.025


def test_laser_cursor_stays_off_while_crossing_between_shapes() -> None:
    data = StudioSceneData(
        particles=(),
        stage_count=1,
        outline_stage=0,
        laser_path=(
            StudioLaserPathRecord(0.0, 0.2, True),
            StudioLaserPathRecord(0.4, 0.2, False),
            StudioLaserPathRecord(0.6, 0.8, True),
            StudioLaserPathRecord(1.0, 0.8, True),
        ),
    )

    cursor = studio_laser_cursor(data, "contour_laser", 0.5)

    assert cursor.beam_on is False


def test_wow_laser_cursor_uses_only_the_outline_stage() -> None:
    path = tuple(
        StudioLaserPathRecord(index / 100, 0.5, True)
        for index in range(101)
    )
    data = StudioSceneData(
        particles=(), stage_count=3, outline_stage=2, laser_path=path
    )

    color_pass = studio_laser_cursor(data, "screenprint_laser", 0.5)
    outline_pass = studio_laser_cursor(data, "screenprint_laser", 0.8)

    assert color_pass.beam_on is False
    assert outline_pass.beam_on is True
    assert outline_pass.target_u == pytest.approx(ease_in_out(0.4), abs=0.002)


def test_non_particle_effect_clears_the_studio_particle_bank(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    _artwork(source)
    config = RenderConfig(effect="vertical_halo", width=100, colors=6)
    analysis = analyze_artwork(source, config)
    scene = build_studio_scene_data(ArtworkRenderer(analysis, config))

    assert scene.particles == ()
    assert scene.stage_count > 0

from pathlib import Path

from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer
from artanimate.desktop.studio3d_particles import build_studio_scene_data


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


def test_non_particle_effect_clears_the_studio_particle_bank(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    _artwork(source)
    config = RenderConfig(effect="vertical_halo", width=100, colors=6)
    analysis = analyze_artwork(source, config)
    scene = build_studio_scene_data(ArtworkRenderer(analysis, config))

    assert scene.particles == ()
    assert scene.stage_count > 0

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.effects import pigment_sweep_field, targeted_particle_position
from artanimate.core.renderer import ArtworkRenderer
from artanimate.desktop.studio3d_particles import build_studio_scene_data


def _artwork(path: Path) -> None:
    image = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (8, 9, 62, 70), radius=13, fill=(226, 39, 55), outline=(17, 17, 19), width=3
    )
    draw.ellipse((67, 12, 111, 67), fill=(35, 102, 226), outline=(17, 17, 19), width=3)
    image.save(path)


def test_sweep_field_respects_all_four_entry_edges() -> None:
    for direction, near, far in (
        ("left", (slice(None), slice(0, 10)), (slice(None), slice(-10, None))),
        ("right", (slice(None), slice(-10, None)), (slice(None), slice(0, 10))),
        ("top", (slice(0, 10), slice(None)), (slice(-10, None), slice(None))),
        ("bottom", (slice(-10, None), slice(None)), (slice(0, 10), slice(None))),
    ):
        field = pigment_sweep_field(90, 60, direction, 0.12, seed=31)
        assert field.dtype == np.float32
        assert float(np.median(field[near])) < float(np.median(field[far]))


def test_targeted_trajectory_overshoots_then_locks_exactly() -> None:
    common = {
        "origin_x": np.array([-5.0], dtype=np.float32),
        "origin_y": np.array([4.0], dtype=np.float32),
        "target_x": np.array([10.0], dtype=np.float32),
        "target_y": np.array([4.0], dtype=np.float32),
        "overshoot_x": np.array([3.0], dtype=np.float32),
        "overshoot_y": np.array([0.0], dtype=np.float32),
        "curl_x": np.array([0.0], dtype=np.float32),
        "curl_y": np.array([2.0], dtype=np.float32),
        "phase": np.array([0.4], dtype=np.float32),
    }
    at_overshoot = targeted_particle_position(
        **common, travel=np.array([0.78], dtype=np.float32)
    )
    final = targeted_particle_position(
        **common, travel=np.array([1.0], dtype=np.float32)
    )

    assert at_overshoot[0][0] == pytest.approx(13.0, abs=1e-4)
    assert final[0][0] == pytest.approx(10.0, abs=1e-4)
    assert final[1][0] == pytest.approx(4.0, abs=1e-4)


def test_renderer_builds_one_global_true_pixel_particle_bank(tmp_path: Path) -> None:
    source = tmp_path / "pigments.png"
    _artwork(source)
    config = RenderConfig(
        effect="pigment_sweep",
        width=120,
        colors=8,
        duration=4.0,
        fps=8,
        direction="left",
        seed=23,
    )
    analysis = analyze_artwork(source, config)
    first = ArtworkRenderer(analysis, config)
    second = ArtworkRenderer(analysis, config)

    assert len(first.stages) == 1
    assert first.stages[0].key == "pigment_sweep"
    assert np.array_equal(first.stages[0].mask, np.logical_not(analysis.background_mask))
    bank = first.particles["pigment_sweep"]
    duplicate = second.particles["pigment_sweep"]
    assert np.array_equal(bank.target_x, duplicate.target_x)
    assert np.array_equal(bank.origin_x, duplicate.origin_x)
    assert np.array_equal(bank.colors, duplicate.colors)
    assert bank.origin_x is not None
    assert np.all(bank.origin_x < 0.0)
    for x, y, color in zip(bank.target_x, bank.target_y, bank.colors, strict=True):
        assert tuple(int(channel) for channel in color) == tuple(
            int(channel) for channel in analysis.source[int(y), int(x)]
        )

    middle = first.frame_at(config.duration * 0.5)
    studio_texture = first.frame_at(config.duration * 0.5, presentation="texture")
    assert middle.dtype == np.uint8
    assert not np.array_equal(middle, studio_texture)
    assert not np.array_equal(middle, first.blank)
    assert not np.array_equal(middle, analysis.source)
    assert np.array_equal(first.frame_at(config.duration), analysis.source)


def test_studio_reuses_the_renderer_targeted_bank(tmp_path: Path) -> None:
    source = tmp_path / "studio-pigments.png"
    _artwork(source)
    config = RenderConfig(effect="pigment_sweep", width=120, colors=8, seed=41)
    renderer = ArtworkRenderer(analyze_artwork(source, config), config)
    scene = build_studio_scene_data(renderer, particle_count=90)
    bank = renderer.particles["pigment_sweep"]
    bank_targets = {
        (round((float(x) + 0.5) / renderer.width, 7), round((float(y) + 0.5) / renderer.height, 7))
        for x, y in zip(bank.target_x, bank.target_y, strict=True)
    }

    assert len(scene.particles) == 90
    assert scene.stage_count == 1
    for grain in scene.particles:
        assert (round(grain.target_u, 7), round(grain.target_v, 7)) in bank_targets
        assert grain.origin_u < 0.0
        assert grain.overshoot_u > 0.0
        assert grain.curl_v != 0.0
        assert 0.0 <= grain.birth_progress <= grain.settle_progress <= 1.0


def test_invalid_sweep_settings_fail_with_explicit_messages() -> None:
    with pytest.raises(ValueError, match="Pigment Sweep accepte uniquement"):
        RenderConfig(effect="pigment_sweep", direction="radial").validate()
    with pytest.raises(ValueError, match="sweep_rebound"):
        RenderConfig(effect="pigment_sweep", sweep_rebound=0.5).validate()

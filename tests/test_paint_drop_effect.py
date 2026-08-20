from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.effects import EffectContext, create_effect
from artanimate.core.effects.paint_drop import paint_drop_target
from artanimate.core.renderer import ArtworkRenderer


def _source(path: Path) -> None:
    image = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 62, 68), fill=(225, 36, 48), outline=(18, 18, 18), width=3)
    draw.rectangle((70, 15, 108, 65), fill=(35, 98, 225), outline=(18, 18, 18), width=3)
    image.save(path)


def test_drop_targets_a_real_mask_pixel_and_waits_for_impact() -> None:
    mask = np.zeros((40, 64), dtype=bool)
    mask[8:34, 16:51] = True
    config = RenderConfig(effect="paint_drop", width=64, paint_fall_ratio=0.32)
    effect = create_effect("paint_drop")
    field = effect.create_field(
        EffectContext(64, 40, 17, config, layer_mask=mask)
    )
    target_x, target_y = paint_drop_target(mask)

    assert mask[target_y, target_x]
    assert float(field[mask].min()) >= config.paint_fall_ratio - 1e-6
    assert field[target_y, target_x] == np.min(field[mask])
    assert np.all(field[~mask] == 1.0)


def test_legacy_brush_parameter_is_ignored_without_leaking_to_new_configs() -> None:
    values = RenderConfig(effect="paint_drop").to_dict()
    values["paint_brush_width"] = 0.34

    restored = RenderConfig.from_dict(values)

    assert "paint_brush_width" not in restored.to_dict()


def test_flat_render_draws_drop_but_studio_texture_does_not(tmp_path: Path) -> None:
    source = tmp_path / "paint.png"
    _source(source)
    config = RenderConfig(
        effect="paint_drop",
        width=120,
        colors=5,
        duration=4.0,
        hold_start=0.0,
        hold_end=0.1,
    )
    renderer = ArtworkRenderer(analyze_artwork(source, config), config)
    flat = renderer.frame_at(0.40, presentation="2d")
    texture = renderer.frame_at(0.40, presentation="texture")

    assert not np.array_equal(flat, texture)
    assert np.any(flat[: max(5, renderer.height // 8)] != texture[: max(5, renderer.height // 8)])
    assert np.array_equal(renderer.frame_at(config.duration), renderer.analysis.source)

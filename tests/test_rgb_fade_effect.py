from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.effects.rgb_fade import rgb_channel_weights
from artanimate.core.renderer import ArtworkRenderer


def test_rgb_channels_build_in_overlapping_r_g_b_order() -> None:
    early = rgb_channel_weights(0.20, "channels")
    middle = rgb_channel_weights(0.50, "channels")
    late = rgb_channel_weights(0.80, "channels")

    assert early[0] > 0 and early[1] == 0 and early[2] == 0
    assert middle[0] == 1 and 0 < middle[1] < 1 and middle[2] == 0
    assert late[0] == 1 and late[1] == 1 and 0 < late[2] < 1


def test_together_mode_raises_all_channels_equally() -> None:
    weights = rgb_channel_weights(0.42, "together")
    assert weights[0] == weights[1] == weights[2]
    assert 0 < weights[0] < 1


def test_rgb_renderer_starts_black_and_finishes_exactly(tmp_path: Path) -> None:
    source = tmp_path / "rgb.png"
    pixels = np.zeros((40, 64, 3), dtype=np.uint8)
    pixels[..., 0] = 220
    pixels[..., 1] = 140
    pixels[..., 2] = 70
    Image.fromarray(pixels).save(source)
    config = RenderConfig(
        effect="rgb_fade",
        rgb_mode="channels",
        width=64,
        duration=2,
        fps=8,
        colors=4,
        hold_start=0.1,
        hold_end=0.1,
    )
    analysis = analyze_artwork(source, config)
    renderer = ArtworkRenderer(analysis, config)

    first = renderer.frame_at(0.0)
    red_stage = renderer.frame_at(0.42)
    final = renderer.frame_at(2.0)

    assert not first.any()
    assert red_stage[..., 0].max() > 0
    assert not red_stage[..., 1].any()
    assert not red_stage[..., 2].any()
    assert np.array_equal(final, analysis.source)

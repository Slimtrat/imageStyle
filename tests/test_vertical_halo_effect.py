from pathlib import Path

import numpy as np
from PIL import Image

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer


def _renderer(path: Path, direction: str) -> ArtworkRenderer:
    width, height = 120, 60
    gradient = np.zeros((height, width, 3), dtype=np.uint8)
    gradient[..., 0] = np.arange(width, dtype=np.uint8)[None, :] + 80
    gradient[..., 1] = 35
    gradient[..., 2] = 145
    Image.fromarray(gradient).save(path)
    config = RenderConfig(
        effect="vertical_halo",
        halo_direction=direction,
        width=width,
        duration=2.0,
        hold_start=0.0,
        hold_end=0.1,
        soft_edge=0.005,
        halo_width=0.04,
    )
    return ArtworkRenderer(analyze_artwork(path, config), config)


def test_halo_reveals_only_the_side_already_crossed(tmp_path: Path) -> None:
    left = _renderer(tmp_path / "left.png", "left")
    right = _renderer(tmp_path / "right.png", "right")
    seconds = 0.95
    left_frame = left.frame_at(seconds)
    right_frame = right.frame_at(seconds)
    left_blank = left.blank
    right_blank = right.blank

    # Well ahead of the luminous border, the original pixels remain fully hidden.
    assert np.array_equal(left_frame[:, 92:], left_blank[:, 92:])
    assert np.array_equal(right_frame[:, :28], right_blank[:, :28])
    # Behind the border, a substantial part of the source is already present.
    assert np.mean(left_frame[:, :28] != left_blank[:, :28]) > 0.45
    assert np.mean(right_frame[:, 92:] != right_blank[:, 92:]) > 0.45


def test_halo_final_frame_is_exact_source(tmp_path: Path) -> None:
    renderer = _renderer(tmp_path / "final.png", "left")
    assert np.array_equal(
        renderer.frame_at(renderer.config.duration), renderer.analysis.source
    )

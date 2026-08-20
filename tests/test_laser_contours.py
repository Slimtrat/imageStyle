from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.effects.contour_paths import (
    build_contour_trace,
    detected_contour_mask,
    sample_laser_path,
)
from artanimate.core.renderer import ArtworkRenderer


def _shapes() -> tuple[np.ndarray, np.ndarray]:
    first = np.zeros((72, 110), dtype=bool)
    first[10:54, 9:45] = True
    second = np.zeros_like(first)
    y, x = np.ogrid[:72, :110]
    second[(x - 78) ** 2 + (y - 38) ** 2 <= 22**2] = True
    return first, second


def test_detected_shapes_produce_continuous_paths_with_beam_off_between_them() -> None:
    first, second = _shapes()
    mask = detected_contour_mask((first, second))
    trace = build_contour_trace(mask)
    sampled = sample_laser_path(mask, 180)

    assert trace.component_count >= 2
    assert np.ptp(trace.field[mask]) > 0.75
    assert all(0.0 <= point.progress <= 1.0 for point in sampled)
    assert any(point.laser_on for point in sampled)
    assert any(not point.laser_on for point in sampled)
    for previous, current in zip(trace.points, trace.points[1:], strict=False):
        if current.laser_on:
            assert np.hypot(current.x - previous.x, current.y - previous.y) <= np.sqrt(2) + 1e-6


def test_laser_field_follows_a_loop_instead_of_a_horizontal_scan() -> None:
    first, _ = _shapes()
    mask = detected_contour_mask((first,))
    trace = build_contour_trace(mask)
    top = trace.field[10, 25]
    bottom = trace.field[53, 25]
    left = trace.field[30, 9]

    assert len({round(float(top), 2), round(float(bottom), 2), round(float(left), 2)}) >= 2
    assert not np.allclose(trace.field[mask], np.broadcast_to(np.linspace(0, 1, 110), mask.shape)[mask])
    assert all(point.laser_on for point in trace.points)


def _artwork(path: Path) -> None:
    image = Image.new("RGB", (140, 90), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 62, 78), radius=12, fill=(225, 38, 50), outline=(15, 15, 18), width=4)
    draw.ellipse((76, 12, 130, 76), fill=(35, 96, 225), outline=(15, 15, 18), width=4)
    image.save(path)


def test_contour_laser_starts_from_colored_artwork_and_writes_one_trace(tmp_path: Path) -> None:
    source = tmp_path / "laser.png"
    _artwork(source)
    config = RenderConfig(
        effect="contour_laser",
        width=140,
        colors=6,
        duration=4.0,
        hold_start=0.0,
        hold_end=0.1,
    )
    renderer = ArtworkRenderer(analyze_artwork(source, config), config)

    assert len(renderer.stages) == 1
    assert renderer.stages[0].is_outline
    trace_mask = renderer.stages[0].mask
    assert np.array_equal(renderer.blank[~trace_mask], renderer.analysis.source[~trace_mask])
    assert np.any(renderer.blank[trace_mask] != renderer.analysis.source[trace_mask])
    middle = renderer.frame_at(1.8)
    assert np.any(middle[trace_mask] == renderer.analysis.source[trace_mask])
    assert np.any(middle[trace_mask] != renderer.analysis.source[trace_mask])
    assert np.array_equal(renderer.frame_at(config.duration), renderer.analysis.source)

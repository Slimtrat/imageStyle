from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pytest

from artanimate.core.video import VideoFrameEncoder
from artanimate.studio.model import Easing, Transition, TransitionKind
from artanimate.studio.recipe import build_portable_project
from artanimate.studio.spatial_match import (
    SpatialMatchSettings,
    spatial_solution_from_transform,
    spatial_transform_from_solution,
)
from artanimate.studio.transition_matching import (
    AkazeArtworkMatchSolver,
    SpatialMatchSolution,
)
from artanimate.studio.transition_strategies import compose_transition_frames


def _textured_artwork(width: int = 420, height: int = 300) -> Image.Image:
    rng = np.random.default_rng(31)
    pixels = rng.integers(20, 236, size=(height, width, 3), dtype=np.uint8)
    image = Image.fromarray(pixels, "RGB")
    draw = ImageDraw.Draw(image)
    for x in range(20, width, 40):
        draw.line((x, 0, width - x // 2, height), fill=(250, 220, 30), width=4)
    for y in range(15, height, 35):
        draw.ellipse((y, y // 2, y + 28, y // 2 + 28), outline=(20, 20, 30), width=4)
    draw.text((30, height - 55), "ARTANIMATE 3D", fill=(255, 255, 255), stroke_width=2)
    return image


def _wall_with_artwork(
    artwork: Image.Image,
    *,
    width: int = 800,
    height: int = 600,
) -> tuple[Image.Image, tuple[tuple[float, float], ...]]:
    source = np.asarray(artwork, dtype=np.uint8)
    source_quad = np.float32(
        ((0, 0), (artwork.width - 1, 0), (artwork.width - 1, artwork.height - 1), (0, artwork.height - 1))
    )
    target_quad = np.float32(((135, 105), (690, 74), (720, 515), (112, 540)))
    matrix = cv2.getPerspectiveTransform(source_quad, target_quad)
    warped = cv2.warpPerspective(source, matrix, (width, height))
    alpha = cv2.warpPerspective(
        np.ones((artwork.height, artwork.width), dtype=np.uint8) * 255,
        matrix,
        (width, height),
    )
    wall = np.empty((height, width, 3), dtype=np.uint8)
    wall[:] = (210, 195, 180)
    mask = alpha > 0
    wall[mask] = warped[mask]
    normalized = tuple(
        (float(x / (width - 1)), float(y / (height - 1)))
        for x, y in target_quad
    )
    return Image.fromarray(wall, "RGB"), normalized


def _solution_for_quad(
    quad: tuple[tuple[float, float], ...],
    *,
    confidence: float = 0.83,
) -> SpatialMatchSolution:
    source = np.float32(((0, 0), (1, 0), (1, 1), (0, 1)))
    target = np.asarray(quad, dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    return SpatialMatchSolution(
        quad,
        tuple(tuple(float(value) for value in row) for row in matrix),
        120,
        160,
        72,
        48,
        39,
        0.8125,
        1.4,
        confidence,
    ).validate()


@pytest.mark.parametrize(
    "quad",
    (
        ((0.14, 0.18), (0.82, 0.11), (0.88, 0.86), (0.09, 0.91)),
        ((0.84, 0.16), (0.18, 0.14), (0.13, 0.88), (0.89, 0.91)),
        ((-0.12, 0.08), (0.78, 0.02), (0.91, 0.82), (-0.18, 0.94)),
    ),
    ids=("perspective", "reflection", "partial-framing"),
)
def test_editor_contract_preserves_difficult_automatic_quads(
    quad: tuple[tuple[float, float], ...],
) -> None:
    automatic = _solution_for_quad(quad)

    transform = spatial_transform_from_solution(automatic)
    restored = spatial_solution_from_transform(automatic, transform)

    assert np.asarray(restored.target_quad) == pytest.approx(
        np.asarray(automatic.target_quad), abs=1.0e-6
    )
    assert np.asarray(restored.homography) == pytest.approx(
        np.asarray(automatic.homography), abs=1.0e-5
    )
    assert restored.confidence == automatic.confidence
    assert restored.inliers == automatic.inliers


def test_akaze_solves_a_projective_artwork_match() -> None:
    artwork = _textured_artwork()
    wall, expected = _wall_with_artwork(artwork)

    solution = AkazeArtworkMatchSolver().solve(artwork, wall)

    assert solution.inliers >= 10
    assert solution.inlier_ratio >= 0.8
    assert solution.reprojection_error <= 2.0
    assert solution.confidence >= 0.8
    for actual, wanted in zip(solution.target_quad, expected, strict=True):
        assert actual == pytest.approx(wanted, abs=0.02)
    restored = SpatialMatchSolution.from_dict(solution.to_dict())
    assert restored.to_dict() == solution.to_dict()


def test_akaze_rejects_an_unrelated_uniform_photo() -> None:
    with pytest.raises(ValueError, match="AKAZE|Correspondance"):
        AkazeArtworkMatchSolver().solve(
            _textured_artwork(),
            Image.new("RGB", (800, 600), (210, 195, 180)),
        )


def test_akaze_keeps_the_artwork_geometry_under_a_bright_reflection() -> None:
    artwork = _textured_artwork()
    wall, expected = _wall_with_artwork(artwork)
    reflected = np.asarray(wall, dtype=np.uint8).copy()
    glare = np.zeros(reflected.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(
        glare,
        np.asarray(((250, 70), (360, 60), (570, 535), (445, 540)), dtype=np.int32),
        255,
    )
    selected = glare > 0
    reflected[selected] = np.rint(
        reflected[selected].astype(np.float32) * 0.62 + 255.0 * 0.38
    ).astype(np.uint8)

    solution = AkazeArtworkMatchSolver().solve(artwork, reflected)

    assert solution.confidence >= 0.65
    assert np.asarray(solution.target_quad) == pytest.approx(
        np.asarray(expected), abs=0.035
    )


def test_spatial_strategy_reveals_the_real_frame_without_opacity_fade() -> None:
    outgoing = np.empty((120, 160, 3), dtype=np.uint8)
    outgoing[:] = (230, 40, 70)
    incoming = np.empty_like(outgoing)
    incoming[:] = (25, 80, 150)
    solution = SpatialMatchSolution(
        ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)),
        ((0.5, 0.0, 0.25), (0.0, 0.5, 0.25), (0.0, 0.0, 1.0)),
        100,
        100,
        50,
        40,
        36,
        0.9,
        0.5,
        0.9,
    ).validate()
    transition = Transition(
        "spatial",
        TransitionKind.SPATIAL_MATCH,
        "virtual",
        "real",
        10,
        11,
        SpatialMatchSettings(solution, Easing.LINEAR).to_dict(),
    ).validate()

    start = compose_transition_frames(transition, outgoing, incoming, 0.0)
    middle = compose_transition_frames(transition, outgoing, incoming, 0.5)
    reveal = compose_transition_frames(transition, outgoing, incoming, 0.9)
    end = compose_transition_frames(transition, outgoing, incoming, 1.0)

    assert np.array_equal(start, outgoing)
    assert np.array_equal(middle, outgoing)
    assert np.array_equal(reveal[0, 0], incoming[0, 0])
    assert np.array_equal(reveal[-1, -1], outgoing[-1, -1])
    assert np.array_equal(end[0, 0], incoming[0, 0])
    assert np.array_equal(end[60, 80], incoming[60, 80])


def test_spatial_comparison_overlay_uses_the_requested_opacity_only_in_preview() -> None:
    outgoing = np.full((16, 20, 3), (200, 40, 20), dtype=np.uint8)
    incoming = np.full((16, 20, 3), (20, 80, 180), dtype=np.uint8)
    solution = _solution_for_quad(
        ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))
    )
    settings = SpatialMatchSettings(
        solution,
        Easing.LINEAR,
        overlay_opacity=0.25,
        comparison_overlay=True,
    )
    transition = Transition(
        "overlay",
        TransitionKind.SPATIAL_MATCH,
        "virtual",
        "real",
        10,
        11,
        settings.to_dict(),
    ).validate()

    compared = compose_transition_frames(transition, outgoing, incoming, 0.5)

    expected = np.rint(outgoing * 0.75 + incoming * 0.25).astype(np.uint8)
    assert np.array_equal(compared, expected)


def test_recipe_persists_the_automatic_spatial_solution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artwork = _textured_artwork(320, 240)
    wall, _quad = _wall_with_artwork(artwork, width=640, height=480)
    artwork_path = source / "artwork.png"
    wall_path = source / "wall.jpg"
    artwork.save(artwork_path)
    wall.save(wall_path, quality=96)
    recipe = {
        "schema_version": 1,
        "name": "Raccord spatial",
        "artwork": str(artwork_path),
        "project": {"width": 320, "height": 240, "fps": 30},
        "media": {"wall": {"path": str(wall_path), "kind": "image"}},
        "shots": [
            {"id": "virtual", "kind": "artwork_3d", "duration_frames": 30},
            {"id": "real", "kind": "still", "asset": "wall", "duration_frames": 30},
        ],
        "transitions": [
            {
                "kind": "spatial_match",
                "from": "virtual",
                "to": "real",
                "duration_frames": 12,
            }
        ],
    }
    recipe_path = source / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    result = build_portable_project(recipe_path, tmp_path / "portable")

    assert result.project.transitions[0].kind == TransitionKind.SPATIAL_MATCH
    settings = SpatialMatchSettings.from_transition(result.project.transitions[0])
    assert settings.solution.confidence >= 0.8
    assert settings.solution.inliers >= 10
    virtual = result.project.tracks[0].clips[0]
    camera_match = virtual.parameters["camera"]["match"]
    assert camera_match["start_frame"] == 24
    assert camera_match["end_frame"] > camera_match["start_frame"]
    assert camera_match["reprojection_error"] < 5.0
    second = build_portable_project(recipe_path, tmp_path / "portable")
    assert second.changed is False
    assert second.project.transitions[0].parameters == result.project.transitions[0].parameters


def test_recipe_uses_one_selected_video_frame_for_the_spatial_solution(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-video"
    source.mkdir()
    artwork = _textured_artwork(320, 240)
    wall, _quad = _wall_with_artwork(artwork, width=640, height=480)
    artwork_path = source / "artwork.png"
    video_path = source / "wall.mp4"
    artwork.save(artwork_path)
    wall_rgb = np.asarray(wall, dtype=np.uint8)
    encoder = VideoFrameEncoder(
        video_path,
        640,
        480,
        30,
        quality="studio",
        crf=12,
        total_frames=30,
    )
    try:
        for index in range(30):
            frame = np.clip(
                wall_rgb.astype(np.int16) + index % 3,
                0,
                255,
            ).astype(np.uint8)
            encoder.write(frame)
        encoder.finish()
    except BaseException:
        encoder.abort()
        raise
    recipe = {
        "schema_version": 1,
        "name": "Raccord spatial vidéo",
        "artwork": str(artwork_path),
        "project": {"width": 640, "height": 480, "fps": 30},
        "media": {"wall": {"path": str(video_path), "kind": "video"}},
        "shots": [
            {"id": "virtual", "kind": "artwork_3d", "duration_frames": 20},
            {
                "id": "real",
                "kind": "video",
                "asset": "wall",
                "duration_frames": 20,
                "source_in_frame": 5,
            },
        ],
        "transitions": [
            {
                "kind": "spatial_match",
                "from": "virtual",
                "to": "real",
                "duration_frames": 8,
                "settings": {"reference_source_frame": 7},
            }
        ],
    }
    recipe_path = source / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    result = build_portable_project(recipe_path, tmp_path / "portable-video")

    transition = result.project.transitions[0]
    settings = SpatialMatchSettings.from_transition(transition)
    assert settings.reference_source_frame == 7
    assert settings.solution.confidence >= 0.7
    assert settings.original_solution.to_dict() == settings.solution.to_dict()
    expected_transform = spatial_transform_from_solution(settings.solution)
    assert np.asarray(
        [(point.x, point.y) for point in settings.editor_transform.target_corner_offsets]
    ) == pytest.approx(
        np.asarray(
            [(point.x, point.y) for point in expected_transform.target_corner_offsets]
        ),
        abs=1.0e-7,
    )

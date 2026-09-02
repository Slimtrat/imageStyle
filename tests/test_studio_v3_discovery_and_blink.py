from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pytest

from artanimate.studio.model import ClipKind, TransitionKind
from artanimate.studio.persistence import load_project
from artanimate.studio.prologue import PrologueSettings, render_prologue_frame
from artanimate.studio.recipe import build_portable_project
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.semantic_detection import (
    SemanticRegionCandidate,
    SemanticRegionDetection,
)
from artanimate.studio.semantic import Bounds


def _textured_artwork(width: int = 320, height: int = 240) -> Image.Image:
    rng = np.random.default_rng(71)
    pixels = rng.integers(28, 225, size=(height, width, 3), dtype=np.uint8)
    image = Image.fromarray(pixels, "RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse((48, 72, 96, 108), fill=(245, 239, 220), outline=(20, 18, 25), width=5)
    draw.ellipse((64, 82, 78, 99), fill=(25, 34, 48))
    for x in range(12, width, 37):
        draw.line((x, 0, width - x // 3, height), fill=(250, 192, 30), width=3)
    draw.text((130, 190), "ARTANIMATE", fill=(250, 250, 250), stroke_width=2)
    return image


def _wall_with_artwork(artwork: Image.Image) -> Image.Image:
    width, height = 640, 480
    source = np.asarray(artwork, dtype=np.uint8)
    source_quad = np.float32(
        ((0, 0), (artwork.width - 1, 0), (artwork.width - 1, artwork.height - 1), (0, artwork.height - 1))
    )
    target_quad = np.float32(((105, 75), (548, 62), (575, 417), (88, 432)))
    matrix = cv2.getPerspectiveTransform(source_quad, target_quad)
    warped = cv2.warpPerspective(source, matrix, (width, height))
    alpha = cv2.warpPerspective(
        np.full((artwork.height, artwork.width), 255, dtype=np.uint8),
        matrix,
        (width, height),
    )
    wall = np.empty((height, width, 3), dtype=np.uint8)
    wall[:] = (207, 196, 183)
    wall[alpha > 0] = warped[alpha > 0]
    return Image.fromarray(wall, "RGB")


def test_prologue_is_deterministic_and_discovery_starts_without_the_artwork(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "artwork.png"
    _textured_artwork().save(artwork)
    settings = PrologueSettings.from_mapping(
        {"title": "Sans titre", "subtitle": "Œuvre originale"}
    )
    first = render_prologue_frame(settings, 320, 240, 0, 30)
    repeated = render_prologue_frame(settings, 320, 240, 0, 30)
    assert np.array_equal(first, repeated)

    recipe = {
        "schema_version": 1,
        "name": "Découverte",
        "artwork": str(artwork),
        "project": {"width": 320, "height": 240, "fps": 30},
        "media": {},
        "shots": [
            {
                "id": "title",
                "kind": "prologue",
                "duration_frames": 30,
                "settings": settings.to_dict(),
            },
            {"id": "artwork", "kind": "artwork_2d", "duration_frames": 30},
        ],
        "transitions": [
            {
                "kind": "discover",
                "from": "title",
                "to": "artwork",
                "duration_frames": 12,
                "settings": {"direction": "center-out", "softness": 0.03},
            }
        ],
    }
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
    result = build_portable_project(recipe_path, tmp_path / "portable")

    clips = result.project.tracks[0].clips
    assert clips[0].kind == ClipKind.PROLOGUE
    assert result.project.transitions[0].kind == TransitionKind.DISCOVER
    with StudioRenderSession(
        result.project,
        result.assets_directory / "artwork" / "artwork-artwork.png",
        output_width=320,
        output_height=240,
        resource_base=result.project_path.parent,
    ) as session:
        prologue = session.frame_at(0)
        revealed = session.frame_at(41)
    assert np.array_equal(prologue, first)
    assert not np.array_equal(prologue, revealed)
    assert load_project(result.project_path).transitions[0].kind == TransitionKind.DISCOVER


def test_recipe_projects_a_manual_eye_region_and_blinks_at_the_real_shot_end(
    tmp_path: Path,
) -> None:
    artwork_image = _textured_artwork()
    wall_image = _wall_with_artwork(artwork_image)
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.png"
    artwork_image.save(artwork)
    wall_image.save(wall)
    recipe = {
        "schema_version": 1,
        "name": "Œuvre vivante",
        "artwork": str(artwork),
        "project": {"width": 320, "height": 240, "fps": 30},
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {"id": "virtual", "kind": "artwork_2d", "duration_frames": 30},
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
        "semantic_regions": [
            {
                "id": "left-eye",
                "type": "eye",
                "label": "Œil gauche",
                "bounds": [0.15, 0.30, 0.15, 0.15],
                "mask": {"shape": "ellipse", "feather": 0.06},
                "blink": {
                    "axis": [0.04, 0.68, 0.96, 0.78],
                    "curvature": -0.08,
                    "amplitude": 0.96,
                    "protection": 0.12,
                    "seam_width": 0.014,
                },
            }
        ],
        "semantic_actions": [
            {
                "id": "final-blink",
                "capability": "region.blink",
                "target": "left-eye",
                "trigger": {"event": "shot_end", "shot": "real"},
                "parameters": {
                    "close_frames": 6,
                    "hold_frames": 2,
                    "open_frames": 10,
                    "intensity": 1.0,
                    "easing": "ease-in-out",
                },
            }
        ],
    }
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding="utf-8")
    result = build_portable_project(recipe_path, tmp_path / "portable")

    assert result.project.scene is not None
    eye = result.project.scene.object_by_id("region-left-eye")
    assert eye is not None
    assert "blinkable" in eye.affordance_ids
    assert eye.attributes["blink_model"]["axis"] == (0.04, 0.68, 0.96, 0.78)
    assert eye.attributes["blink_model"]["amplitude"] == pytest.approx(0.96)
    action = next(item for item in result.project.invocations if item.capability_id == "region.blink")
    assert (action.start_frame, action.duration_frames) == (42, 18)
    assert result.project.triggers[0].offset_frames == -18
    artwork_path = result.assets_directory / "artwork" / "artwork-artwork.png"
    with StudioRenderSession(
        result.project,
        artwork_path,
        output_width=320,
        output_height=240,
        resource_base=result.project_path.parent,
    ) as session:
        opened = session.frame_at(42)
        closed = session.frame_at(47)
        reopened = session.frame_at(59)
        repeated = session.frame_at(47)
    assert not np.array_equal(opened, closed)
    assert np.array_equal(opened, reopened)
    assert np.array_equal(closed, repeated)
    rebuilt = build_portable_project(recipe_path, tmp_path / "portable")
    assert rebuilt.changed is False
    assert rebuilt.project == result.project



def test_detector_contract_keeps_engine_specific_metadata_outside_the_region() -> None:
    candidate = SemanticRegionCandidate(
        "eye",
        "Œil",
        Bounds(0.1, 0.2, 0.3, 0.2),
        0.91,
        np.ones((8, 12), dtype=np.float32),
    ).validate()
    result = SemanticRegionDetection("local.test", "1", (candidate,)).validate()
    assert result.candidates[0].region_type == "eye"
    assert result.analyzer_id == "local.test"

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from artanimate.cli.main import main as cli_main
from artanimate.headless_studio import write_headless_studio_report


def _recipe(tmp_path: Path) -> Path:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.jpg"
    Image.new("RGB", (96, 128), (210, 70, 80)).save(artwork)
    Image.new("RGB", (96, 128), (80, 120, 170)).save(wall)
    recipe = {
        "schema_version": 1,
        "name": "Headless test",
        "artwork": str(artwork),
        "project": {"width": 108, "height": 192, "fps": 30, "quality": "fast"},
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {"id": "art", "kind": "artwork_2d", "duration_frames": 10},
            {"id": "wall", "kind": "still", "asset": "wall", "duration_frames": 10},
        ],
        "transitions": [
            {"kind": "dissolve", "from": "art", "to": "wall", "duration_frames": 6}
        ],
        "outputs": {"control_sheet": "renders/controls.jpg", "control_width": 80},
    }
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    return path


def test_headless_job_writes_controls_and_structured_report(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path)
    output = tmp_path / "portable"
    report_path = tmp_path / "report.json"

    exit_code = write_headless_studio_report(recipe, output, report_path)

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["success"] is True
    assert report["project"]["path"] == str(output / "project.artanimate")
    assert report["project"]["assets"] == [
        "assets/artwork/artwork-artwork.png",
        "assets/media/wall-wall.jpg",
    ]
    assert report["project"]["color_policies"] == []
    assert report["controls"]["execution_mode"] == "semantic"
    assert report["controls"]["color_fidelity"] is None
    assert report["controls"]["blink_previews"] == []
    assert len(report["controls"]["frames"]) >= 4
    assert (output / "renders" / "controls.jpg").is_file()


def test_headless_job_writes_enlarged_canonical_and_real_blink_preview(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.png"
    pixels = np.random.default_rng(77).integers(
        16,
        240,
        size=(240, 320, 3),
        dtype=np.uint8,
    )
    artwork_image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(artwork_image)
    for x in range(12, artwork_image.width, 37):
        draw.line(
            (x, 0, artwork_image.width - x // 3, artwork_image.height),
            fill=(250, 192, 30),
            width=3,
        )
    draw.ellipse((48, 72, 112, 126), fill=(235, 82, 121), outline=(12, 13, 18), width=5)
    draw.text((132, 188), "ARTANIMATE", fill=(250, 250, 250), stroke_width=2)
    artwork_image.save(artwork)
    artwork_image.save(wall)
    recipe = {
        "schema_version": 1,
        "name": "Blink headless",
        "artwork": str(artwork),
        "project": {"width": 160, "height": 120, "fps": 30},
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {"id": "art", "kind": "artwork_2d", "duration_frames": 12},
            {"id": "wall", "kind": "still", "asset": "wall", "duration_frames": 20},
        ],
        "transitions": [
            {
                "kind": "spatial_match",
                "from": "art",
                "to": "wall",
                "duration_frames": 6,
            }
        ],
        "semantic_regions": [
            {
                "id": "eye",
                "type": "eye",
                "label": "Œil",
                "bounds": [0.20, 0.30, 0.40, 0.25],
                "mask": {"shape": "ellipse", "feather": 0.04},
                "blink": {
                    "axis": [0.04, 0.68, 0.96, 0.78],
                    "curvature": -0.08,
                    "protection": 0.12,
                },
            }
        ],
        "semantic_actions": [
            {
                "id": "blink",
                "capability": "region.blink",
                "target": "eye",
                "trigger": {"event": "shot_end", "shot": "wall"},
                "parameters": {
                    "close_frames": 3,
                    "hold_frames": 1,
                    "open_frames": 3,
                    "intensity": 1.0,
                    "easing": "ease-in-out",
                },
            }
        ],
        "outputs": {"control_sheet": "renders/controls.jpg", "control_width": 160},
    }
    recipe_path = tmp_path / "blink.json"
    recipe_path.write_text(
        json.dumps(recipe, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "blink-project"
    report_path = tmp_path / "blink-report.json"

    assert write_headless_studio_report(recipe_path, output, report_path) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    previews = report["controls"]["blink_previews"]
    assert len(previews) == 1
    assert previews[0]["target_id"] == "region-eye"
    assert [state["label"] for state in previews[0]["states"]] == [
        "ouvert",
        "mi-course",
        "fermé",
        "réouvert",
    ]
    assert previews[0]["artist_review"] == "pending"
    assert Path(previews[0]["path"]).is_file()


def test_cli_build_and_error_report_are_stable(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path)
    output = tmp_path / "cli-project"

    assert cli_main(["studio", "build", str(recipe), "--output", str(output)]) == 0
    success = json.loads((output / "headless-report.json").read_text(encoding="utf-8"))
    assert success["success"] is True

    missing = tmp_path / "missing.json"
    failure_report = tmp_path / "failure.json"
    assert write_headless_studio_report(missing, output, failure_report) == 2
    failure = json.loads(failure_report.read_text(encoding="utf-8"))
    assert failure["success"] is False
    assert failure["error"]["type"] == "FileNotFoundError"

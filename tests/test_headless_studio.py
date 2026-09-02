from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

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
    assert len(report["controls"]["frames"]) >= 4
    assert (output / "renders" / "controls.jpg").is_file()


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

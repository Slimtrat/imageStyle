from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from artanimate.studio.recipe import build_portable_project


def test_rebuild_preserves_an_open_render_outside_managed_files(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.jpg"
    Image.new("RGB", (96, 128), (200, 80, 60)).save(artwork)
    Image.new("RGB", (96, 128), (70, 100, 150)).save(wall)
    recipe_path = tmp_path / "recipe.json"
    recipe = {
        "schema_version": 1,
        "name": "Open render",
        "artwork": str(artwork),
        "project": {"width": 108, "height": 192, "fps": 30},
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {"id": "art", "kind": "artwork_2d", "duration_frames": 10},
            {"id": "wall", "kind": "still", "asset": "wall", "duration_frames": 10},
        ],
    }
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    output = tmp_path / "portable"
    build_portable_project(recipe_path, output)
    renders = output / "renders"
    renders.mkdir()
    control = renders / "controls.jpg"
    control.write_bytes(b"render kept outside the managed transaction")
    recipe["shots"][1]["duration_frames"] = 20  # type: ignore[index]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    with control.open("rb") as opened_control:
        rebuilt = build_portable_project(recipe_path, output)
        assert opened_control.read() == b"render kept outside the managed transaction"

    assert rebuilt.changed is True
    assert rebuilt.snapshot_path is not None and rebuilt.snapshot_path.is_file()
    assert control.read_bytes() == b"render kept outside the managed transaction"
    assert rebuilt.project.settings.duration_frames == 30

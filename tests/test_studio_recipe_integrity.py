from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from artanimate.studio.recipe import build_portable_project


def test_identical_recipe_repairs_a_modified_portable_asset(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.jpg"
    Image.new("RGB", (96, 128), (200, 80, 60)).save(artwork)
    Image.new("RGB", (96, 128), (70, 100, 150)).save(wall)
    recipe = {
        "schema_version": 1,
        "name": "Integrity",
        "artwork": str(artwork),
        "project": {"width": 108, "height": 192, "fps": 30},
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {"id": "art", "kind": "artwork_2d", "duration_frames": 10},
            {"id": "wall", "kind": "still", "asset": "wall", "duration_frames": 10},
        ],
    }
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    output = tmp_path / "portable"
    first = build_portable_project(recipe_path, output)
    portable_wall = next(first.assets_directory.glob("media/*.jpg"))
    portable_wall.write_bytes(b"modified outside ArtAnimate")

    repaired = build_portable_project(recipe_path, output)

    assert repaired.changed is True
    assert repaired.snapshot_path is not None and repaired.snapshot_path.is_file()
    assert portable_wall.read_bytes() == wall.read_bytes()

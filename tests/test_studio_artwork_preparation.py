from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from artanimate.studio.assets import resolve_asset_path
from artanimate.studio.recipe import build_portable_project


def _perspective_artwork(path: Path) -> None:
    image = Image.new("RGB", (420, 320), (218, 197, 176))
    corners = ((64, 54), (350, 42), (368, 260), (48, 274))
    draw = ImageDraw.Draw(image)
    draw.polygon(corners, fill=(36, 145, 186))
    draw.ellipse((145, 95, 290, 235), fill=(216, 54, 104))
    draw.line((*corners, corners[0]), fill=(30, 28, 42), width=4, joint="curve")
    image.save(path)


def test_portable_build_preserves_source_and_uses_rectified_artwork(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artwork = source / "artwork-photo.png"
    wall = source / "wall.jpg"
    _perspective_artwork(artwork)
    Image.new("RGB", (420, 320), (190, 180, 170)).save(wall)
    recipe_path = source / "recipe.json"
    recipe_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Œuvre redressée vers mur",
                "artwork": str(artwork),
                "artwork_preparation": {
                    "mode": "auto_rectify",
                    "minimum_confidence": 0.75,
                    "inset_ratio": 0.0,
                    "max_output_edge": 1024,
                },
                "project": {"width": 108, "height": 192, "fps": 30},
                "media": {"wall": {"path": str(wall), "kind": "image"}},
                "shots": [
                    {
                        "id": "virtual",
                        "kind": "artwork_3d",
                        "duration_frames": 30,
                    },
                    {
                        "id": "real",
                        "kind": "still",
                        "asset": "wall",
                        "duration_frames": 30,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "portable"

    first = build_portable_project(recipe_path, destination)

    preparation = first.artwork_preparation
    assert preparation is not None
    assert preparation["mode"] == "auto_rectify"
    assert preparation["confidence"] >= 0.75
    assert preparation["source_path"].startswith("assets/source/")
    assert preparation["artwork_path"].endswith("-rectified.png")
    assert (destination / preparation["source_path"]).is_file()
    assert (destination / preparation["manifest_path"]).is_file()
    assert (destination / preparation["preview_path"]).is_file()
    prepared = resolve_asset_path(first.project.artwork.path, first.project_path)
    assert prepared == destination / preparation["artwork_path"]
    assert prepared.is_file()
    assert first.project.artwork.width > first.project.artwork.height

    second = build_portable_project(recipe_path, destination)

    assert second.changed is False
    assert second.artwork_preparation == preparation
    portable_recipe = json.loads((destination / "recipe.json").read_text(encoding="utf-8"))
    assert portable_recipe["artwork"].startswith("assets/source/")
    assert portable_recipe["artwork_preparation"]["mode"] == "auto_rectify"

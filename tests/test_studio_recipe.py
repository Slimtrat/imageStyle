from __future__ import annotations

import json
from pathlib import Path
import zipfile

from PIL import Image
import pytest

from artanimate.studio.model import ClipKind, TransitionKind
from artanimate.studio.persistence import load_project, project_digest
from artanimate.studio.recipe import build_portable_project


def _image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (96, 128), color).save(path)


def _recipe(artwork: Path, wall: Path, *, real_duration: int = 30) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "Œuvre vers mur",
        "artwork": str(artwork),
        "project": {
            "width": 108,
            "height": 192,
            "fps": 30,
            "quality": "fast",
            "crf": 20,
        },
        "media": {"wall": {"path": str(wall), "kind": "image"}},
        "shots": [
            {
                "id": "virtual",
                "kind": "artwork_3d",
                "duration_frames": 30,
                "settings": {
                    "render_config": {"effect": "sand", "seed": 4},
                    "camera": {"motion": "top_drift", "motion_strength": 0.4},
                },
            },
            {
                "id": "real",
                "kind": "still",
                "asset": "wall",
                "duration_frames": real_duration,
            },
        ],
        "transitions": [
            {
                "kind": "manual_match",
                "from": "virtual",
                "to": "real",
                "duration_frames": 10,
                "settings": {"overlay_opacity": 0.55},
            }
        ],
    }


def test_recipe_build_is_portable_deterministic_and_snapshotted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    artwork = source / "artwork.png"
    wall = source / "wall.jpg"
    _image(artwork, (210, 80, 60))
    _image(wall, (70, 100, 150))
    recipe_path = source / "recipe.json"
    recipe_path.write_text(
        json.dumps(_recipe(artwork, wall), ensure_ascii=False),
        encoding="utf-8",
    )
    destination = tmp_path / "portable"

    first = build_portable_project(recipe_path, destination)

    assert first.changed is True
    assert first.snapshot_path is None
    assert first.project_path == destination / "project.artanimate"
    assert first.project_path.is_file()
    assert (destination / "recipe.json").is_file()
    assert len(tuple((destination / "assets").rglob("*.*"))) == 2
    assert not Path(first.project.artwork.path).is_absolute()
    assert all(not Path(asset.path).is_absolute() for asset in first.project.assets)
    clips = first.project.tracks[0].clips
    assert [clip.kind for clip in clips] == [ClipKind.ARTWORK_3D, ClipKind.STILL]
    assert clips[0].parameters["color_policy"]["mode"] == "faithful"
    assert clips[0].parameters["color_policy"]["texture_color_space"] == "srgb"
    assert first.project.transitions[0].kind == TransitionKind.MATCH
    first_digest = project_digest(first.project)

    second = build_portable_project(recipe_path, destination)

    assert second.changed is False
    assert second.snapshot_path is None
    assert project_digest(second.project) == first_digest
    assert not (destination / "snapshots").exists()

    recipe_path.write_text(
        json.dumps(_recipe(artwork, wall, real_duration=45), ensure_ascii=False),
        encoding="utf-8",
    )
    third = build_portable_project(recipe_path, destination)

    assert third.changed is True
    assert third.snapshot_path is not None and third.snapshot_path.is_file()
    assert project_digest(third.project) != first_digest
    with zipfile.ZipFile(third.snapshot_path) as archive:
        assert {"project.artanimate", "recipe.json"}.issubset(archive.namelist())
        archive.extract("project.artanimate", tmp_path / "snapshot")
    assert project_digest(load_project(tmp_path / "snapshot" / "project.artanimate")) == first_digest


def test_invalid_recipe_never_replaces_the_last_valid_project(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.jpg"
    _image(artwork, (200, 80, 60))
    _image(wall, (70, 90, 140))
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(_recipe(artwork, wall)), encoding="utf-8")
    destination = tmp_path / "portable"
    valid = build_portable_project(recipe_path, destination)
    saved_digest = project_digest(valid.project)

    invalid = _recipe(artwork, wall)
    invalid["unexpected"] = True
    recipe_path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError, match="inconnue"):
        build_portable_project(recipe_path, destination)

    assert project_digest(load_project(destination / "project.artanimate")) == saved_digest


def test_recipe_persists_an_explicit_scene_integrated_color_mode(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "artwork.png"
    wall = tmp_path / "wall.jpg"
    _image(artwork, (200, 80, 60))
    _image(wall, (70, 90, 140))
    payload = _recipe(artwork, wall)
    payload["shots"][0]["settings"]["color_policy"] = {
        "mode": "scene_integrated"
    }
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(payload), encoding="utf-8")

    result = build_portable_project(recipe_path, tmp_path / "portable")

    policy = result.project.tracks[0].clips[0].parameters["color_policy"]
    assert policy["mode"] == "scene_integrated"
    assert policy["exposure"] == 1.0

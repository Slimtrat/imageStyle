import os
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_assets import StudioAssetPanel
from artanimate.studio.assets import (
    FolderRelinkResult,
    register_media_asset,
    relink_project_from_folders,
)
from artanimate.studio.model import Clip, ClipKind, StudioProject, Track, TrackKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_image(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 120), color).save(path)


def test_registry_reuses_identical_media_without_copy(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    media = tmp_path / "outside" / "real.png"
    make_image(artwork, "white")
    make_image(media, "red")
    project_path = tmp_path / "project" / "reel.artanimate"
    project_path.parent.mkdir()
    project = StudioProject.new(artwork)

    first, asset, created = register_media_asset(project, media, project_path)
    second, same, created_again = register_media_asset(first, media, project_path)

    assert created
    assert not created_again
    assert same.asset_id == asset.asset_id
    assert len(second.assets) == 1
    assert media.exists()
    assert not (project_path.parent / media.name).exists()


def test_folder_relink_updates_all_clip_references_and_panel_state(app, tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    original = tmp_path / "original" / "real.png"
    moved = tmp_path / "library" / "nested" / "real.png"
    make_image(artwork, "white")
    make_image(original, "blue")
    make_image(moved, "blue")
    project_path = tmp_path / "reel.artanimate"
    project = StudioProject.new(artwork)
    project, asset, _created = register_media_asset(project, original, project_path)
    track = Track(
        "video-real",
        TrackKind.VIDEO,
        "Réel",
        (
            Clip("real-a", ClipKind.STILL, 0, 30, asset_id=asset.asset_id),
            Clip("real-b", ClipKind.STILL, 30, 30, asset_id=asset.asset_id),
        ),
    )
    project = replace(project, tracks=(*project.tracks, track)).validate()
    original.unlink()

    relinked, result = relink_project_from_folders(project, (tmp_path / "library",), project_path)

    assert result == FolderRelinkResult(relinked=(asset.asset_id,))
    assert relinked.assets[0].asset_id == asset.asset_id
    assert {clip.asset_id for clip in relinked.tracks[-1].clips} == {asset.asset_id}

    panel = StudioAssetPanel()
    panel.set_context(relinked, project_path)
    assert panel.tree.topLevelItemCount() == 2
    assert panel.tree.topLevelItem(1).text(2) == "Disponible"


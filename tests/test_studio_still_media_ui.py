from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_assets import StudioAssetPanel
from artanimate.desktop.studio_media_inspector import StudioMediaInspector
from artanimate.studio.assets import register_media_asset
from artanimate.studio.media import add_still_clip
from artanimate.studio.model import StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_asset_panel_shows_image_thumbnail_and_normalized_metadata(app, tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    media = tmp_path / "real.png"
    Image.new("RGB", (90, 160), "white").save(artwork)
    Image.new("RGB", (80, 120), "blue").save(media)
    project_path = tmp_path / "reel.artanimate"
    project = StudioProject.new(artwork)
    project, asset, _created = register_media_asset(project, media, project_path)

    panel = StudioAssetPanel()
    panel.set_context(project, project_path)
    item = panel.tree.topLevelItem(1)

    assert not item.icon(0).isNull()
    assert "80 × 120" in item.toolTip(0)
    assert "sRGB présumé" in item.toolTip(0)
    assert item.data(0, Qt.ItemDataRole.UserRole) == asset.asset_id


def test_still_inspector_selects_editable_clip_and_emits_typed_edit(app, tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    media = tmp_path / "real.png"
    Image.new("RGB", (90, 160), "white").save(artwork)
    Image.new("RGB", (80, 120), "blue").save(media)
    project = StudioProject.new(artwork)
    project, asset, _created = register_media_asset(
        project, media, tmp_path / "reel.artanimate"
    )
    project, clip = add_still_clip(project, asset.asset_id, start_frame=30, duration_frames=90)
    inspector = StudioMediaInspector()
    captured = []
    inspector.applyRequested.connect(captured.append)

    inspector.set_selection(project, (clip.clip_id,))
    inspector.rotation.setValue(12.5)
    inspector.crop_width.setValue(75.0)
    inspector.apply_button.click()

    assert inspector.selected_clip_id == clip.clip_id
    assert inspector.apply_button.isEnabled()
    assert captured[0].clip_id == clip.clip_id
    assert captured[0].settings.rotation_degrees == pytest.approx(12.5)
    assert captured[0].settings.crop_width == pytest.approx(0.75)

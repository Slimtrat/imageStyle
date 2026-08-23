import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController
from artanimate.studio.assets import AssetAvailability, check_media_asset


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_image(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 160), color).save(path)


def controller(tmp_path: Path) -> tuple[StudioPanel, StudioDocumentController]:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    panel = StudioPanel()
    document = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", f"Assets-{tmp_path.name}"),
        QWidget(),
    )
    return panel, document


def test_controller_imports_reference_once_and_relinks_without_copy(app, tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    original = tmp_path / "external" / "real.png"
    moved = tmp_path / "library" / "real.png"
    make_image(artwork, "white")
    make_image(original, "orange")
    make_image(moved, "orange")
    panel, document = controller(tmp_path)
    assert document.new_project(artwork)

    assert document.import_media(original)
    assert document.import_media(original)
    assert len(panel.project.assets) == 1
    asset_id = panel.project.assets[0].asset_id
    assert original.exists()
    assert not (artwork.parent / "real.png").exists()

    original.unlink()
    document.refresh_assets()
    assert panel.asset_panel.tree.topLevelItem(1).text(2) == "Manquant"

    assert document.relink_asset(asset_id, moved)
    relinked = panel.project.assets[0]
    assert relinked.asset_id == asset_id
    assert check_media_asset(
        relinked, document._asset_context_path()
    ).state == AssetAvailability.AVAILABLE
    assert panel.asset_panel.tree.topLevelItem(1).text(2) == "Disponible"


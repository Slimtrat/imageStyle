import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_shared_legacy_artwork_starts_clean_then_camera_edit_marks_dirty(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    artwork = tmp_path / "shared.png"
    Image.new("RGB", (180, 120), "purple").save(artwork)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    panel = StudioPanel()
    controller = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", "AdoptedArtwork"),
        QWidget(),
    )

    assert controller.adopt_artwork(artwork)
    assert controller.project is not None
    assert not controller.dirty

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: pytest.fail("un projet adopté propre ne doit pas alerter"),
    )
    assert controller.close_allowed()

    panel.camera_inspector.zoom.setValue(1.5)
    assert controller.dirty


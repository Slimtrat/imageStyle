import os
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController
from artanimate.studio.model import ProjectSettings
from artanimate.studio.persistence import autosave_path, load_project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build_controller(tmp_path: Path) -> tuple[StudioPanel, StudioDocumentController]:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    panel = StudioPanel()
    controller = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", f"Studio-{tmp_path.name}"),
        QWidget(),
    )
    return panel, controller


def test_document_save_dirty_autosave_and_recovery(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (320, 180), (220, 80, 40)).save(artwork)
    panel, controller = build_controller(tmp_path)
    destination = tmp_path / "reel.artanimate"

    assert controller.new_project(artwork)
    assert controller.dirty
    assert controller.save(destination)
    assert not controller.dirty
    assert destination.exists()

    project = controller.project
    assert project is not None
    edited = replace(
        project,
        settings=ProjectSettings(duration_frames=450),
    ).validate()
    panel.set_project(edited)
    assert controller.dirty
    assert controller.autosave()
    assert autosave_path(destination).exists()
    assert load_project(destination).settings.duration_frames == 360

    recovered_panel, recovered = build_controller(tmp_path / "recovered")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    assert recovered.open_project(destination)
    assert recovered_panel.project.settings.duration_frames == 450
    assert destination in recovered.recent_projects()


def test_shared_artwork_does_not_replace_an_existing_project(app, tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 100), "red").save(first)
    Image.new("RGB", (100, 100), "blue").save(second)
    panel, controller = build_controller(tmp_path)

    assert controller.adopt_artwork(first)
    project_id = panel.project.project_id
    assert not controller.adopt_artwork(second)
    assert panel.project.project_id == project_id
    assert panel.project.artwork.path == str(first)


def test_close_can_discard_or_cancel_dirty_project(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (100, 100), "green").save(artwork)
    _panel, controller = build_controller(tmp_path)
    controller.new_project(artwork)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )
    assert not controller.close_allowed()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    assert controller.close_allowed()


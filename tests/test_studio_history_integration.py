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
from artanimate.studio.model import ClipKind, TrackKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def controller_for(tmp_path: Path) -> tuple[StudioPanel, StudioDocumentController]:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    panel = StudioPanel()
    controller = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", f"History-{tmp_path.name}"),
        QWidget(),
    )
    return panel, controller


def test_undo_returns_to_saved_state_and_continuous_camera_edits_merge(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (320, 180), "navy").save(artwork)
    panel, controller = controller_for(tmp_path)
    try:
        assert controller.new_project(artwork)
        assert controller.save(tmp_path / "saved.artanimate")
        assert not controller.dirty
        assert not panel.history.can_undo

        panel.camera_inspector.x.setValue(0.2)
        panel.camera_inspector.y.setValue(0.3)
        assert controller.dirty
        assert panel.history.undo_count == 1
        assert panel.history.undo_label == "Ajuster la caméra"
        assert panel.undo_action.isEnabled()
        assert panel.undo_action.shortcuts()

        assert panel.undo()
        assert not controller.dirty
        assert panel.history.can_redo
        assert "Ajuster la caméra" in panel.redo_action.text()

        assert panel.redo()
        assert controller.dirty
        assert panel.undo()
        panel.camera_inspector.zoom.setValue(1.5)
        assert not panel.history.can_redo
    finally:
        controller.shutdown()


def test_timeline_and_local_media_commands_are_reversible_without_source_writes(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    media = tmp_path / "room.jpg"
    Image.new("RGB", (320, 180), "white").save(artwork)
    Image.new("RGB", (96, 64), "orange").save(media)
    media_bytes = media.read_bytes()
    panel, controller = controller_for(tmp_path)
    try:
        assert controller.new_project(artwork)
        panel.timeline.scene.set_selection(("artwork-main",))
        panel.transport.seek(120)
        panel.timeline.splitRequested.emit(("artwork-main",))
        assert sum(len(track.clips) for track in panel.project.tracks) == 2
        assert panel.history.undo_label == "Scinder les clips"
        assert panel.undo()
        assert sum(len(track.clips) for track in panel.project.tracks) == 1
        assert panel.redo()
        assert sum(len(track.clips) for track in panel.project.tracks) == 2

        assert controller.import_media(media)
        assert len(panel.project.assets) == 1
        assert any(
            clip.kind == ClipKind.STILL
            for track in panel.project.tracks
            for clip in track.clips
        )
        assert panel.history.undo_label == f"Importer et placer l’image {media.name}"
        assert panel.undo()
        assert panel.project.assets == ()
        assert media.read_bytes() == media_bytes

        panel.timeline.addTrackRequested.emit(TrackKind.EFFECT)
        assert not panel.history.can_redo
    finally:
        controller.shutdown()

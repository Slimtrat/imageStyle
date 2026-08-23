import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.model import Easing


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_panel(tmp_path: Path) -> StudioPanel:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (400, 240), (220, 80, 40)).save(artwork)
    panel = StudioPanel()
    panel.set_artwork(artwork)
    return panel


def camera_frames(panel: StudioPanel) -> list[int]:
    return [
        keyframe.frame
        for keyframe in panel.project.tracks[0].clips[0].camera.keyframes
    ]


def test_keyframe_strip_moves_copies_eases_and_deletes_project_keyframes(
    app,
    tmp_path: Path,
) -> None:
    panel = make_panel(tmp_path)
    panel.transport.seek(30)
    panel.camera_inspector.zoom.setValue(2.0)
    assert camera_frames(panel) == [0, 30]

    panel.keyframe_strip.keyframeMoved.emit(30, 40)
    assert camera_frames(panel) == [0, 40]
    assert panel.transport.current_frame == 40

    panel.keyframe_strip.keyframeCopied.emit(40, 50)
    assert camera_frames(panel) == [0, 40, 50]
    assert panel.transport.current_frame == 50

    easing_index = panel.camera_inspector.easing.findData(Easing.EASE_IN)
    panel.camera_inspector.easing.setCurrentIndex(easing_index)
    keyframes = panel.project.tracks[0].clips[0].camera.keyframes
    assert keyframes[-1].easing == Easing.EASE_IN

    panel.keyframe_strip.keyframeDeleteRequested.emit(50)
    assert camera_frames(panel) == [0, 40]


def test_inspector_distinguishes_exact_and_interpolated_frames(app, tmp_path: Path) -> None:
    panel = make_panel(tmp_path)
    panel.transport.seek(30)
    panel.camera_inspector.zoom.setValue(2.0)
    assert panel.camera_inspector.remove_keyframe_button.isEnabled()
    assert panel.camera_inspector.add_keyframe_button.text() == "Mettre à jour"

    panel.transport.seek(15)
    assert not panel.camera_inspector.remove_keyframe_button.isEnabled()
    assert panel.camera_inspector.add_keyframe_button.text() == "Ajouter keyframe"


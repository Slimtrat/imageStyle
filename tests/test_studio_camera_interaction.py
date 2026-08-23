import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, QCoreApplication, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.camera import resolve_camera_pose


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_panel(tmp_path: Path) -> StudioPanel:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (400, 240), (220, 80, 40)).save(artwork)
    panel = StudioPanel()
    panel.resize(1000, 800)
    panel.show()
    QApplication.processEvents()
    panel.set_artwork(artwork)
    return panel


def test_camera_inspector_writes_keyframes_into_artwork_clip(app, tmp_path: Path) -> None:
    panel = make_panel(tmp_path)
    panel.camera_inspector.zoom.setValue(2.0)
    panel.transport.seek(30)
    panel.camera_inspector.x.setValue(0.75)

    clip = panel.project.tracks[0].clips[0]
    assert [keyframe.frame for keyframe in clip.camera.keyframes] == [0, 30]
    assert clip.camera.keyframes[0].pose.zoom == 2.0
    assert clip.camera.keyframes[1].pose.x == 0.75
    assert resolve_camera_pose(clip.camera, 15).zoom > 1.0


def test_canvas_drag_and_wheel_update_normalized_camera(app, tmp_path: Path) -> None:
    panel = make_panel(tmp_path)
    canvas = panel.canvas
    canvas.resize(500, 700)
    QApplication.processEvents()
    center = QPointF(canvas.frame_rect().center())
    before = canvas.camera_pose

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        center,
        center,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        center + QPointF(40, 20),
        center + QPointF(40, 20),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        center + QPointF(40, 20),
        center + QPointF(40, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QCoreApplication.sendEvent(canvas, press)
    QCoreApplication.sendEvent(canvas, move)
    QCoreApplication.sendEvent(canvas, release)
    assert canvas.camera_pose.x < before.x
    assert canvas.camera_pose.y < before.y

    zoom_before = canvas.camera_pose.zoom
    wheel = QWheelEvent(
        center,
        center,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QCoreApplication.sendEvent(canvas, wheel)
    assert canvas.camera_pose.zoom > zoom_before


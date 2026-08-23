import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.timeline import clip_location


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_dragging_clip_edge_trims_at_an_integer_frame(app, tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    editor = StudioPanel()
    editor.resize(1200, 1000)
    editor.set_artwork(artwork)
    editor.show()
    QApplication.processEvents()
    editor.transport.seek(120)
    editor.timeline.scene.set_selection(("artwork-main",))
    editor.timeline.splitRequested.emit(("artwork-main",))
    scene = editor.timeline.scene
    left = next(
        layout for layout in scene.clip_layouts
        if layout.clip.clip_id == "artwork-main"
    )
    start = QPoint(int(left.rect.right() - 1), int(left.rect.center().y()))
    destination = QPoint(int(scene.frame_x(90)), start.y())

    QTest.mousePress(scene, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(scene, destination)
    QTest.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=destination)

    trimmed = clip_location(editor.project, "artwork-main")[3]
    assert (trimmed.start_frame, trimmed.end_frame) == (0, 90)
    assert isinstance(trimmed.duration_frames, int)


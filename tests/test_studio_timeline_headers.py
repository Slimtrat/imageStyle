import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_timeline import StudioTimelineScene
from artanimate.studio.model import StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_header_buttons_request_mute_lock_and_visibility_changes(app, tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    scene = StudioTimelineScene()
    scene.set_project(StudioProject.new(artwork))
    scene.show()
    QApplication.processEvents()
    row = next(
        layout for layout in scene._track_layouts
        if layout.track.track_id == "video-main"
    )
    requested: list[tuple[str, str, bool]] = []
    scene.trackStateRequested.connect(
        lambda track_id, field, value: requested.append((track_id, field, value))
    )

    for field in ("muted", "locked", "hidden"):
        QTest.mouseClick(
            scene,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            scene._state_rects(row)[field].center().toPoint(),
        )

    assert requested == [
        ("video-main", "muted", True),
        ("video-main", "locked", True),
        ("video-main", "hidden", True),
    ]


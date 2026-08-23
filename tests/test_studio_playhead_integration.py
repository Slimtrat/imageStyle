import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_transport_seek_updates_canvas_and_frame_signal(app, tmp_path: Path) -> None:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (400, 240), (220, 80, 40)).save(artwork)
    panel = StudioPanel()
    requested = []
    panel.frame_requested.connect(requested.append)
    panel.set_artwork(artwork)

    panel.transport.seek(30)

    assert panel.canvas.playhead_frame == 30
    assert panel.transport.timecode.text() == "00:00:01:00"
    assert requested[-1] == 30


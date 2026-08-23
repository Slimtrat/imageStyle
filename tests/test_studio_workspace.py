import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioCanvas, StudioPanel
from artanimate.studio.model import TrackKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_canvas_keeps_vertical_reel_ratio(app) -> None:
    canvas = StudioCanvas()
    canvas.resize(720, 720)
    rect = canvas.frame_rect()

    assert abs(rect.width() / rect.height() - 9 / 16) < 0.01
    assert rect.center() == canvas.rect().center()


def test_studio_panel_creates_artwork_first_project(app, tmp_path: Path) -> None:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (400, 240), (220, 80, 40)).save(artwork)
    panel = StudioPanel()
    changes = []
    panel.project_changed.connect(changes.append)

    assert panel.set_artwork(artwork)

    assert panel.project is not None
    assert panel.project.artwork.path == str(artwork)
    assert [track.kind for track in panel.project.tracks] == [
        TrackKind.VIDEO,
        TrackKind.EFFECT,
        TrackKind.AUDIO,
    ]
    assert "painting.png" in panel.project_status.text()
    assert "1080 × 1920" in panel.format_status.text()
    assert changes[-1] == panel.project


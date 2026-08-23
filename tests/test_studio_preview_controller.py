import os
from pathlib import Path
import time

import numpy as np
from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from artanimate.desktop import studio_preview
from artanimate.desktop.studio_preview import StudioPreviewController
from artanimate.studio.model import StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_latest_preview_request_wins_even_if_old_worker_finishes_late(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    project = StudioProject.new(artwork)

    def fake_render(project, artwork_path, frame, **kwargs):
        del project, artwork_path, kwargs
        if frame == 1:
            time.sleep(0.08)
        return np.full((16, 9, 3), frame, dtype=np.uint8), False

    monkeypatch.setattr(studio_preview, "render_studio_preview_frame", fake_render)
    controller = StudioPreviewController(cache_bytes=1024 * 1024)
    received: list[int] = []
    loop = QEventLoop()
    controller.frameReady.connect(
        lambda frame, _image, _cached: (received.append(frame), loop.quit())
    )
    controller.request(project, artwork, 1)
    controller.request(project, artwork, 2)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    deadline = time.monotonic() + 2
    while controller.active_job_count and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert received == [2]
    controller.shutdown()
    assert controller.active_job_count == 0
    assert controller.cache.entry_count == 0


def test_cancel_pending_prevents_delivery(app, tmp_path: Path, monkeypatch) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    project = StudioProject.new(artwork)

    def slow_render(project, artwork_path, frame, **kwargs):
        del project, artwork_path, kwargs
        time.sleep(0.05)
        return np.zeros((16, 9, 3), dtype=np.uint8), False

    monkeypatch.setattr(studio_preview, "render_studio_preview_frame", slow_render)
    controller = StudioPreviewController()
    received: list[int] = []
    controller.frameReady.connect(lambda frame, _image, _cached: received.append(frame))
    controller.request(project, artwork, 3)
    controller.cancel_pending()
    deadline = time.monotonic() + 1
    while controller.active_job_count and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert received == []
    controller.shutdown()


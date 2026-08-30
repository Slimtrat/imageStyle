from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from artanimate.desktop import studio3d_bridge
from artanimate.desktop.studio3d_bridge import Studio3DCaptureBridge, _CaptureRequest


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_gpu_capture_surfaces_use_a_bounded_lru(app, monkeypatch) -> None:
    created = []

    class Surface:
        def __init__(self, width: int, height: int) -> None:
            self.width = width
            self.height = height
            self.closed = False
            created.append(self)

        def capture_at(self, _prepared, _frame_index, *, cancelled=None) -> QImage:
            del cancelled
            image = QImage(self.width, self.height, QImage.Format.Format_RGB888)
            image.fill(QColor(70, 80, 90))
            return image

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(studio3d_bridge, "StandaloneStudio3DCapture", Surface)
    bridge = Studio3DCaptureBridge(max_surfaces=2)
    try:
        for width, height in ((10, 20), (20, 30), (10, 20), (30, 40)):
            prepared = SimpleNamespace(width=width, height=height)
            request = _CaptureRequest(prepared, 0, None)
            bridge._capture_on_ui_thread(request)
            assert request.error is None
            assert request.result is not None
            assert request.result.shape == (height, width, 3)
            assert bridge.surface_count <= 2

        assert len(created) == 3
        assert created[1].closed
        assert not created[0].closed
        assert not created[2].closed
    finally:
        bridge.close()
    assert all(surface.closed for surface in created)

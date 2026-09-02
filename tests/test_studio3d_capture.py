from __future__ import annotations

from types import SimpleNamespace
import os
from threading import Event

import pytest
import numpy as np



os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from artanimate.core.video import RenderCancelled
from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d_capture import (
    StandaloneStudio3DCapture,
    capture_with_retry,
)
from artanimate.desktop.studio3d_wave import OrganicWaveSettings


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _solid_image(value: int) -> QImage:
    image = QImage(12, 8, QImage.Format.Format_RGB888)
    image.fill(QColor(value, value, value))
    return image


def test_capture_retry_is_bounded_and_accepts_a_real_dark_scene(app) -> None:
    frames = [QImage(), _solid_image(255), _solid_image(45)]
    waits: list[bool] = []

    captured = capture_with_retry(
        lambda: frames.pop(0),
        max_retries=4,
        wait_for_scene=lambda: waits.append(True),
    )

    assert captured.pixelColor(0, 0).red() == 45
    assert waits == [True, True]


def test_capture_retry_honours_cancellation_before_touching_the_surface(app) -> None:
    cancelled = Event()
    cancelled.set()
    calls: list[bool] = []

    with pytest.raises(RenderCancelled, match="annulée"):
        capture_with_retry(
            lambda: (calls.append(True), _solid_image(45))[1],
            cancelled=cancelled,
        )

    assert calls == []


def test_capture_retry_fails_after_the_exact_retry_budget(app) -> None:
    calls: list[bool] = []

    with pytest.raises(RuntimeError, match="3 captures vides"):
        capture_with_retry(
            lambda: (calls.append(True), _solid_image(0))[1],
            max_retries=2,
            wait_for_scene=lambda: None,
        )

    assert len(calls) == 3


class _FakeCapturePanel:
    def __init__(self) -> None:
        self.attributes: list[tuple[object, bool]] = []
        self.calls: list[object] = []
        self.scene_errors = ()

    def setAttribute(self, attribute, enabled) -> None:
        self.attributes.append((attribute, enabled))

    def resize(self, width, height) -> None:
        self.calls.append(("resize", width, height))

    def show(self) -> None:
        self.calls.append("show")

    def activate(self) -> None:
        self.calls.append("activate")

    def is_ready(self) -> bool:
        return True

    def set_hud_visible(self, visible) -> None:
        self.calls.append(("hud", visible))

    def set_scene_data(self, data) -> None:
        self.calls.append(("scene", data))

    def set_effect(self, *values) -> None:
        self.calls.append(("effect", values))

    def set_frame(self, image, frame_index, frame_count, progress) -> None:
        self.calls.append(("frame", frame_index, frame_count, progress, image.isNull()))

    def apply_scene_state(self, state) -> None:
        self.calls.append(("state", state.frame_index))

    def capture_frame(self, width, height) -> QImage:
        self.calls.append(("capture", width, height))
        return _solid_image(45).scaled(width, height)

    def close(self) -> None:
        self.calls.append("close")

    def deleteLater(self) -> None:
        self.calls.append("delete")


class _FakePrepared3D:
    def __init__(self) -> None:
        config = RenderConfig(
            duration=1.0,
            fps=30,
            hold_start=0.1,
            hold_end=0.1,
        )
        self.closed = False
        self.scene_data = object()
        self.source = SimpleNamespace(renderer=SimpleNamespace(config=config))
        settings = SimpleNamespace(
            direction="left",
            wave=OrganicWaveSettings(),
        )
        self.state = SimpleNamespace(
            frame_index=7,
            frame_count=30,
            effect_progress=0.25,
            settings=settings,
        )

    def state_at(self, frame_index):
        return SimpleNamespace(**{**vars(self.state), "frame_index": frame_index})

    def frame_at(self, frame_index):
        assert frame_index == 7
        return SimpleNamespace(image=np.full((8, 12, 3), 80, dtype=np.uint8))


def test_standalone_capture_owns_an_offscreen_surface(app) -> None:
    panel = _FakeCapturePanel()
    prepared = _FakePrepared3D()

    with StandaloneStudio3DCapture(
        90,
        160,
        panel_factory=lambda: panel,
    ) as capture:
        image = capture.capture_at(prepared, 7, max_retries=0)

    assert image.size().toTuple() == (90, 160)
    assert (Qt.WidgetAttribute.WA_DontShowOnScreen, True) in panel.attributes
    assert ("capture", 90, 160) in panel.calls
    assert ("hud", False) in panel.calls
    assert panel.calls[-2:] == ["close", "delete"]

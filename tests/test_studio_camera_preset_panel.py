import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_camera_presets import StudioCameraPresetPanel
from artanimate.studio.camera_presets import CameraPreset, PresetApplyMode


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_preset_panel_emits_explicit_bounded_request(app) -> None:
    panel = StudioCameraPresetPanel()
    emitted: list[tuple[object, float, int, object]] = []
    panel.presetRequested.connect(
        lambda preset, intensity, duration, mode: emitted.append(
            (preset, intensity, duration, mode)
        )
    )
    panel.preset.setCurrentIndex(panel.preset.findData(CameraPreset.HANDHELD))
    panel.intensity.setValue(0.25)
    panel.set_remaining_frames(45, fps=30)
    panel.duration.setValue(40)
    panel.mode.setCurrentIndex(panel.mode.findData(PresetApplyMode.INSERT))
    panel.apply_button.click()

    assert emitted == [
        (CameraPreset.HANDHELD, 0.25, 40, PresetApplyMode.INSERT)
    ]
    panel.set_remaining_frames(1, fps=30)
    assert not panel.apply_button.isEnabled()


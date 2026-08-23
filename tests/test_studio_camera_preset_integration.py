import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.camera_presets import CameraPreset, PresetApplyMode
from artanimate.studio.model import CameraPose


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_panel(tmp_path: Path) -> StudioPanel:
    artwork = tmp_path / "landscape.png"
    Image.new("RGB", (800, 450), "white").save(artwork)
    panel = StudioPanel()
    panel.set_artwork(artwork)
    return panel


def camera_keyframes(panel: StudioPanel):
    return panel.project.tracks[0].clips[0].camera.keyframes


def test_reveal_panel_generates_then_allows_editing_ordinary_keyframes(
    app,
    tmp_path: Path,
) -> None:
    panel = make_panel(tmp_path)
    panel.transport.seek(30)
    preset_index = panel.camera_presets.preset.findData(CameraPreset.REVEAL)
    panel.camera_presets.preset.setCurrentIndex(preset_index)
    panel.camera_presets.duration.setValue(90)
    panel.camera_presets.apply_button.click()

    keyframes = camera_keyframes(panel)
    generated = [keyframe for keyframe in keyframes if 30 <= keyframe.frame <= 119]
    assert generated[0].frame == 30
    assert generated[-1].frame == 119
    assert generated[-1].pose == CameraPose()
    assert generated[-2].pose == CameraPose()

    panel.transport.seek(generated[1].frame)
    panel.camera_inspector.zoom.setValue(1.75)
    edited = next(
        keyframe for keyframe in camera_keyframes(panel)
        if keyframe.frame == generated[1].frame
    )
    assert edited.pose.zoom == pytest.approx(1.75)


def test_insert_mode_keeps_an_existing_key_inside_preset_range(app, tmp_path: Path) -> None:
    panel = make_panel(tmp_path)
    panel.transport.seek(45)
    panel.camera_inspector.zoom.setValue(1.33)
    panel.transport.seek(30)
    panel.camera_presets.preset.setCurrentIndex(
        panel.camera_presets.preset.findData(CameraPreset.DRIFT)
    )
    panel.camera_presets.mode.setCurrentIndex(
        panel.camera_presets.mode.findData(PresetApplyMode.INSERT)
    )
    panel.camera_presets.duration.setValue(60)
    panel.camera_presets.apply_button.click()

    assert 45 in {keyframe.frame for keyframe in camera_keyframes(panel)}


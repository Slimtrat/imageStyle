import os
from pathlib import Path

from PIL import Image
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from artanimate.core.config import RenderConfig
from artanimate.core.effects import effect_descriptors
from artanimate.desktop.controls import ParameterSlider
from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_effects import StudioEffectInspector
from artanimate.studio.effect_2d import settings_for_effect_clip
from artanimate.studio.model import ClipKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def effect_clips(panel: StudioPanel):
    return tuple(
        clip
        for track in panel.project.tracks
        for clip in track.clips
        if clip.kind == ClipKind.EFFECT_2D
    )


def test_effect_inspector_uses_factory_descriptions_and_parameters(app) -> None:
    inspector = StudioEffectInspector()
    descriptors = effect_descriptors()

    assert inspector.effect_combo.count() == len(descriptors)
    for index, descriptor in enumerate(descriptors):
        assert inspector.effect_combo.itemData(index) == descriptor.key
        assert (
            inspector.effect_combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
            == descriptor.description
        )
        assert set(inspector._controls[descriptor.key]) == {
            parameter.key for parameter in descriptor.parameters
        }
        for parameter in descriptor.parameters:
            control = inspector._controls[descriptor.key][parameter.key]
            assert control.toolTip() == parameter.description
            assert isinstance(control, (ParameterSlider, QComboBox))


def test_add_edit_duplicate_and_undo_effect_layer_with_frozen_snapshot(
    app,
    tmp_path: Path,
) -> None:
    path = tmp_path / "art.png"
    Image.new("RGB", (96, 64), (210, 45, 30)).save(path)
    atelier = RenderConfig(
        effect="sand",
        width=96,
        colors=4,
        duration=4.0,
        hold_start=0.2,
        hold_end=0.4,
        quality="fast",
    ).validate()
    panel = StudioPanel(effect_config_provider=lambda: atelier)
    try:
        assert panel.set_artwork(path)
        inspector = panel.effect_inspector
        wave_index = inspector.effect_combo.findData("wave")
        inspector.effect_combo.setCurrentIndex(wave_index)
        inspector.duration.setValue(0.5)
        amplitude = inspector._controls["wave"]["wave_amplitude"]
        assert isinstance(amplitude, ParameterSlider)
        amplitude.setValue(0.08)

        inspector.add_button.click()
        app.processEvents()

        (clip,) = effect_clips(panel)
        settings = settings_for_effect_clip(clip)
        assert clip.duration_frames == 15
        assert settings.effect == "wave"
        assert settings.config.wave_amplitude == 0.08
        assert panel.history.undo_label == "Ajouter l’effet wave"
        assert inspector.selected_clip_id == clip.clip_id

        atelier.effect = "rgb_fade"
        atelier.wave_amplitude = 0.02
        assert settings_for_effect_clip(effect_clips(panel)[0]).effect == "wave"
        assert settings_for_effect_clip(effect_clips(panel)[0]).config.wave_amplitude == 0.08

        inspector.enabled.setChecked(False)
        inspector.opacity.setValue(0.7)
        inspector.apply_button.click()
        app.processEvents()
        edited = effect_clips(panel)[0]
        assert edited.enabled is False
        assert edited.opacity == 0.7
        assert panel.undo()
        assert effect_clips(panel)[0].enabled is True

        panel.timeline.scene.set_selection((clip.clip_id,))
        inspector.duplicate_button.click()
        app.processEvents()
        assert len(effect_clips(panel)) == 2
        assert panel.history.undo_label == "Dupliquer les clips"
        assert panel.undo()
        assert len(effect_clips(panel)) == 1
        assert panel.undo()
        assert effect_clips(panel) == ()
        assert panel.redo()
        assert len(effect_clips(panel)) == 1
    finally:
        panel.shutdown()

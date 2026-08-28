from __future__ import annotations

from dataclasses import replace
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
from artanimate.studio.model import Easing, StudioProject
from artanimate.studio.transitions import DissolveSettings


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (64, 64), (160, 80, 40)).save(artwork)
    base = StudioProject.new(artwork)
    original = base.tracks[0].clips[0]
    track = replace(
        base.tracks[0],
        clips=(
            replace(original, clip_id="shot-a", duration_frames=30),
            replace(
                original,
                clip_id="shot-b",
                start_frame=30,
                duration_frames=base.settings.duration_frames - 30,
                camera=None,
            ),
        ),
    )
    return replace(base, tracks=(track, *base.tracks[1:])).validate()


def test_panel_creates_edits_resizes_and_deletes_a_dissolve_with_undo(
    app,
    tmp_path: Path,
) -> None:
    panel = StudioPanel()
    panel.set_project(_project(tmp_path), reset_history=True)
    panel.timeline.scene.set_selection(("shot-a", "shot-b"))

    panel.timeline.dissolve_button.click()

    assert len(panel.project.transitions) == 1
    transition = panel.project.transitions[0]
    assert transition.duration_frames == 12
    assert panel.timeline.selected_transition_id == transition.transition_id
    assert panel.transition_inspector.selected_transition_id == transition.transition_id
    assert panel.inspector_tabs.currentWidget() is panel.transition_inspector
    assert len(panel.timeline.scene.transition_layouts) == 1

    panel.undo()
    assert panel.project.transitions == ()
    panel.redo()
    assert len(panel.project.transitions) == 1
    transition = panel.project.transitions[0]
    panel.timeline.scene.set_transition_selection(transition.transition_id)

    panel.transition_inspector.duration.setValue(10)
    easing_index = panel.transition_inspector.easing.findData(Easing.EASE_OUT)
    panel.transition_inspector.easing.setCurrentIndex(easing_index)
    panel.transition_inspector.apply_button.click()

    edited = panel.project.transitions[0]
    assert edited.duration_frames == 10
    assert DissolveSettings.from_transition(edited).easing == Easing.EASE_OUT

    panel.timeline.scene.set_pixels_per_frame(4.0)
    layout = panel.timeline.scene.transition_layouts[0]
    rect = layout.rect
    handle = QPoint(int(round(rect.right())), int(round(rect.center().y())))
    moved = QPoint(handle.x() + 8, handle.y())
    QTest.mousePress(
        panel.timeline.scene,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        handle,
    )
    QTest.mouseMove(panel.timeline.scene, moved)
    QTest.mouseRelease(
        panel.timeline.scene,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        moved,
    )

    assert panel.project.transitions[0].duration_frames == 12
    assert panel.timeline.selected_transition_id == transition.transition_id

    panel.transition_inspector.delete_button.click()
    assert panel.project.transitions == ()
    panel.undo()
    assert len(panel.project.transitions) == 1, (
        panel.project_status.text(), panel.timeline.selected_clip_ids
    )

    restored = panel.project.transitions[0]
    panel.timeline.scene.set_transition_selection(restored.transition_id)
    panel.timeline.delete_button.click()
    assert panel.project.transitions == ()

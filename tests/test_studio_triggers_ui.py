from __future__ import annotations

import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_timeline import semantic_clip_label
from artanimate.studio.model import StudioProject
from artanimate.studio.semantic import CapabilityInvocation
from artanimate.studio.semantic_actions import add_semantic_action_clip


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> tuple[StudioProject, object, object]:
    artwork = tmp_path / "trigger-ui.png"
    Image.new("RGB", (120, 80), (80, 130, 200)).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=5)
    first = CapabilityInvocation(
        "first-action", "camera.zoom_out", 0, 5, target_id="camera"
    )
    second = CapabilityInvocation(
        "second-action", "camera.zoom_out", 30, 5, target_id="camera"
    )
    project, first_clip = add_semantic_action_clip(project, first)
    project, second_clip = add_semantic_action_clip(project, second)
    return project, first_clip, second_clip


def _choose(combo, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_trigger_editor_create_offset_delete_and_history(
    app,
    tmp_path: Path,
) -> None:
    project, first_clip, second_clip = _project(tmp_path)
    panel = StudioPanel()
    try:
        panel.set_project(project, reset_history=True)
        triggers = panel.trigger_panel
        _choose(triggers.source_combo, "first-action")
        _choose(triggers.action_combo, "second-action")
        _choose(triggers.event_combo, "completed")
        triggers.offset_frames.setValue(2)
        triggers.add_button.click()
        app.processEvents()

        assert panel.project is not None
        assert len(panel.project.triggers) == 1
        trigger_id = panel.project.triggers[0].trigger_id
        assert panel.project.triggers[0].offset_frames == 2
        assert "1 lien(s)" in triggers.status.text()
        assert semantic_clip_label(panel.project, first_clip).startswith("⚡")
        assert semantic_clip_label(panel.project, second_clip).startswith("↳")

        triggers.tree.setCurrentItem(triggers.tree.topLevelItem(0))
        triggers.offset_frames.setValue(-1)
        triggers.apply_button.click()
        app.processEvents()
        assert panel.project.triggers[0].offset_frames == -1
        assert panel.history.undo_label == "Décaler un déclencheur sémantique"

        assert panel.undo()
        assert panel.project.triggers[0].offset_frames == 2
        assert panel.redo()
        assert panel.project.triggers[0].offset_frames == -1

        triggers.tree.setCurrentItem(triggers.tree.topLevelItem(0))
        triggers.delete_button.click()
        app.processEvents()
        assert panel.project.triggers == ()
        assert panel.undo()
        assert panel.project.triggers[0].trigger_id == trigger_id
    finally:
        panel.shutdown()


def test_trigger_editor_refuses_cycles_and_keeps_the_valid_graph(
    app,
    tmp_path: Path,
) -> None:
    project, _first_clip, _second_clip = _project(tmp_path)
    panel = StudioPanel()
    try:
        panel.set_project(project, reset_history=True)
        triggers = panel.trigger_panel
        _choose(triggers.source_combo, "first-action")
        _choose(triggers.action_combo, "second-action")
        triggers.add_button.click()
        app.processEvents()
        assert len(panel.project.triggers) == 1

        _choose(triggers.source_combo, "second-action")
        _choose(triggers.action_combo, "first-action")
        triggers.add_button.click()
        app.processEvents()

        assert len(panel.project.triggers) == 1
        assert "Cycle de déclencheurs" in triggers.status.text()
    finally:
        panel.shutdown()

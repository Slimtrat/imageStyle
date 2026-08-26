from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_semantic import StudioSemanticPanel
from artanimate.studio.effect_2d import settings_for_effect_clip
from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.semantic import (
    Bounds,
    CapabilityDescriptor,
    CapabilityRegistry,
    CapabilityRequirement,
    SceneObject,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _artwork(tmp_path: Path, name: str = "art.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (160, 100), (35, 90, 180)).save(path)
    return path


def _effect_clips(panel: StudioPanel):
    assert panel.project is not None
    return tuple(
        clip
        for track in panel.project.tracks
        for clip in track.clips
        if clip.kind == ClipKind.EFFECT_2D
    )


def test_scene_tree_empty_state_keyboard_and_minimal_capabilities(
    app,
    tmp_path: Path,
) -> None:
    semantic = StudioSemanticPanel()
    semantic.set_project(None)
    assert not semantic.add_button.isEnabled()
    assert not semantic.apply_button.isEnabled()
    assert not semantic.delete_button.isEnabled()
    assert not semantic.empty_state.isHidden()

    project = StudioProject.new(_artwork(tmp_path))
    semantic.set_project(project)
    assert semantic.empty_state.isHidden()
    assert semantic.scene_item("artwork") is not None
    assert semantic.scene_item("background") is not None
    assert semantic.scene_item("camera") is not None
    assert semantic.capability_item("reveal.wave").text(1) == "Disponible"
    assert semantic.capability_item("camera.animate").text(1) == "Disponible"
    media = semantic.capability_item("media.present")
    assert media is not None
    semantic.capability_tree.setCurrentItem(media)
    assert media.text(1) == "Indisponible"
    assert "média local" in semantic.explanation.text()
    assert not semantic.add_button.isEnabled()

    semantic.scene_tree.show()
    semantic.scene_tree.setFocus()
    semantic.select_target("artwork")
    before = semantic.scene_tree.currentItem()
    QTest.keyClick(semantic.scene_tree, Qt.Key.Key_Down)
    assert semantic.scene_tree.currentItem() is not before


def test_missing_analysis_is_explained_and_action_stays_disabled(
    app,
    tmp_path: Path,
) -> None:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDescriptor(
            "object.mask_reveal",
            "Révéler par masque",
            "reveal",
            requirements=(
                CapabilityRequirement(
                    "mask-required",
                    "Un masque local est nécessaire",
                    semantic_types=("artwork",),
                    resource_kinds=("mask",),
                ),
            ),
            renderer_candidates=("local.mask",),
        )
    )
    registry.freeze()
    semantic = StudioSemanticPanel(capabilities=registry)
    semantic.set_project(StudioProject.new(_artwork(tmp_path, "plain.png")))
    item = semantic.capability_item("object.mask_reveal")
    assert item is not None
    semantic.capability_tree.setCurrentItem(item)
    assert item.text(1) == "Analyse requise"
    assert "analyse(s) manquante(s) mask" in semantic.explanation.text()
    assert not semantic.add_button.isEnabled()


def test_semantic_effect_add_edit_delete_and_undo(
    app,
    tmp_path: Path,
) -> None:
    config = RenderConfig(
        effect="sand",
        width=160,
        duration=4.0,
        hold_start=0.2,
        hold_end=0.2,
        quality="fast",
    ).validate()
    panel = StudioPanel(effect_config_provider=lambda: config)
    try:
        assert panel.set_artwork(_artwork(tmp_path, "editable.png"))
        semantic = panel.semantic_panel
        semantic.select_target("artwork")
        capability = semantic.capability_item("reveal.wave")
        assert capability is not None
        semantic.capability_tree.setCurrentItem(capability)
        assert "classic.effect.wave" in semantic.renderer_status.text()

        semantic.add_button.click()
        app.processEvents()
        (clip,) = _effect_clips(panel)
        assert settings_for_effect_clip(clip).effect == "wave"
        assert panel.history.undo_label == "Ajouter l’effet wave"
        assert clip.invocation_id is not None

        assert semantic.select_invocation(clip.invocation_id)
        intensity = semantic.parameter_controls["intensity"]
        assert isinstance(intensity, QDoubleSpinBox)
        intensity.setValue(0.35)
        semantic.apply_button.click()
        app.processEvents()
        assert settings_for_effect_clip(_effect_clips(panel)[0]).intensity == 0.35

        semantic.delete_button.click()
        app.processEvents()
        assert _effect_clips(panel) == ()
        assert panel.undo()
        assert len(_effect_clips(panel)) == 1
        assert panel.undo()
        assert settings_for_effect_clip(_effect_clips(panel)[0]).intensity == 1.0
        assert panel.undo()
        assert _effect_clips(panel) == ()
    finally:
        panel.shutdown()


def test_depth_and_camera_actions_are_native_and_reversible(
    app,
    tmp_path: Path,
) -> None:
    panel = StudioPanel()
    try:
        assert panel.set_artwork(_artwork(tmp_path, "depth.png"))
        semantic = panel.semantic_panel
        semantic.select_target("artwork")
        depth = semantic.capability_item("scene.depth_present")
        assert depth is not None
        semantic.capability_tree.setCurrentItem(depth)
        semantic.add_button.click()
        app.processEvents()

        assert panel.project is not None
        main_clip = panel.project.tracks[0].clips[0]
        assert main_clip.kind == ClipKind.ARTWORK_3D
        assert main_clip.parameters["schema_version"] == 1
        assert any(
            item.capability_id == "scene.depth_present"
            for item in panel.project.invocations
        )
        assert panel.undo()
        assert panel.project.tracks[0].clips[0].kind == ClipKind.ARTWORK_2D

        camera = next(
            item for item in panel.project.invocations
            if item.capability_id == "camera.animate"
        )
        assert semantic.select_invocation(camera.invocation_id)
        assert semantic.selected_invocation_id == camera.invocation_id
        semantic.delete_button.click()
        app.processEvents()
        assert all(
            item.capability_id != "camera.animate"
            for item in panel.project.invocations
        )
        assert panel.project.tracks[0].clips[0].camera is None
        assert panel.undo()
        assert any(
            item.capability_id == "camera.animate"
            for item in panel.project.invocations
        )
    finally:
        panel.shutdown()


def test_scene_and_canvas_selection_are_bidirectional(app, tmp_path: Path) -> None:
    panel = StudioPanel()
    try:
        artwork = _artwork(tmp_path, "objects.png")
        assert panel.set_artwork(artwork)
        assert panel.project is not None and panel.project.scene is not None
        scene = panel.project.scene
        subject = SceneObject(
            "subject-1",
            "subject.person",
            "Personnage",
            bounds=Bounds(0.3, 0.2, 0.3, 0.5),
        )
        project = replace(
            panel.project,
            scene=replace(scene, objects=(*scene.objects, subject)),
        )
        panel.set_project(project, reset_history=True)
        panel.canvas.resize(420, 720)
        panel.canvas.show()
        app.processEvents()

        assert panel.semantic_panel.select_target("subject-1")
        assert panel.canvas.semantic_target_id == "subject-1"
        artwork_rect = panel.canvas._artwork_rect(panel.canvas.frame_rect())
        outside_subject = artwork_rect.center().toPoint()
        outside_subject.setX(
            int(artwork_rect.left() + artwork_rect.width() * 0.85)
        )
        QTest.mouseClick(
            panel.canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            outside_subject,
        )
        assert panel.semantic_panel.selected_target_id == "artwork"
        assert panel.canvas.semantic_target_id == "artwork"
    finally:
        panel.shutdown()

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
from artanimate.studio.assets import import_media_asset
from artanimate.studio.manual_match import ManualMatchSettings, MatchPoint
from artanimate.studio.media import add_still_clip
from artanimate.studio.model import AssetKind, Easing, StudioProject, TransitionKind
from artanimate.studio.transitions import transition_progress
from artanimate.studio.spatial_match import (
    SpatialMatchSettings,
    add_spatial_match,
)
from artanimate.studio.transition_matching import SpatialMatchSolution


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> tuple[StudioProject, str]:
    artwork = tmp_path / "artwork.png"
    real = tmp_path / "real.png"
    Image.new("RGB", (64, 64), (180, 70, 30)).save(artwork)
    Image.new("RGB", (64, 64), (25, 100, 190)).save(real)

    base = StudioProject.new(artwork)
    original = base.tracks[0].clips[0]
    video_track = replace(
        base.tracks[0],
        clips=(replace(original, clip_id="virtual", duration_frames=30),),
    )
    asset = import_media_asset(
        real,
        AssetKind.IMAGE,
        tmp_path / "project.artanimate",
        asset_id="real-asset",
    )
    base = replace(
        base,
        assets=(asset,),
        tracks=(video_track, *base.tracks[1:]),
    ).validate()
    project, real_clip = add_still_clip(
        base,
        asset.asset_id,
        start_frame=30,
        duration_frames=base.settings.duration_frames - 30,
        track_id=video_track.track_id,
    )
    return project, real_clip.clip_id


def test_manual_match_ui_edits_previews_canvas_and_history(
    app,
    tmp_path: Path,
) -> None:
    project, real_clip_id = _project(tmp_path)
    panel = StudioPanel()
    panel.resize(1400, 1000)
    panel.show()
    panel.set_project(project, reset_history=True)
    panel.timeline.scene.set_selection(("virtual", real_clip_id))

    panel.timeline.match_button.click()

    assert len(panel.project.transitions) == 1
    transition = panel.project.transitions[0]
    assert transition.kind == TransitionKind.MATCH
    assert panel.timeline.selected_transition_id == transition.transition_id
    assert panel.match_inspector.selected_transition_id == transition.transition_id
    assert panel.inspector_tabs.currentWidget() is panel.match_inspector
    assert panel.canvas.match_transition_id == transition.transition_id
    assert len(panel.timeline.scene.transition_layouts) == 1

    inspector = panel.match_inspector
    inspector.preview_mode.setCurrentIndex(inspector.preview_mode.findData("after"))
    assert panel.transport.current_frame == (
        transition.start_frame + transition.duration_frames - 1
    )
    inspector.preview_mode.setCurrentIndex(inspector.preview_mode.findData("before"))
    assert panel.transport.current_frame == transition.start_frame
    inspector.overlay_opacity.setValue(40.0)
    inspector.preview_mode.setCurrentIndex(inspector.preview_mode.findData("overlay"))
    expected = min(
        range(transition.start_frame, transition.start_frame + transition.duration_frames),
        key=lambda frame: abs(transition_progress(transition, frame) - 0.4),
    )
    assert panel.transport.current_frame == expected

    inspector.duration.setValue(10)
    inspector.position_x.setValue(45.0)
    inspector.position_y.setValue(55.0)
    inspector.scale.setValue(110.0)
    inspector.rotation.setValue(5.0)
    inspector.crop_x.setValue(5.0)
    inspector.crop_y.setValue(4.0)
    inspector.crop_width.setValue(90.0)
    inspector.crop_height.setValue(92.0)
    inspector.target_corners[0][0].setValue(2.0)
    inspector.target_corners[0][1].setValue(1.0)
    inspector.easing.setCurrentIndex(inspector.easing.findData(Easing.EASE_OUT))
    inspector.apply_button.click()

    edited = panel.project.transitions[0]
    settings = ManualMatchSettings.from_transition(edited)
    assert edited.duration_frames == 10
    assert settings.overlay_opacity == pytest.approx(0.4)
    assert settings.easing == Easing.EASE_OUT
    assert settings.transform.position_x == pytest.approx(0.45)
    assert settings.transform.position_y == pytest.approx(0.55)
    assert settings.transform.scale == pytest.approx(1.1)
    assert settings.transform.rotation_degrees == pytest.approx(5.0)
    assert settings.transform.source_crop.x == pytest.approx(0.05)
    assert settings.transform.target_corner_offsets[0].x == pytest.approx(0.02)

    panel.undo()
    restored = ManualMatchSettings.from_transition(panel.project.transitions[0])
    assert restored.transform.position_x == pytest.approx(0.5)
    panel.redo()
    panel.timeline.scene.set_transition_selection(transition.transition_id)

    app.processEvents()
    before_drag = ManualMatchSettings.from_transition(
        panel.project.transitions[0]
    ).transform
    handle = panel.canvas._match_widget_points()[0].toPoint()
    moved = handle + QPoint(10, 8)
    QTest.mousePress(
        panel.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        handle,
    )
    QTest.mouseMove(panel.canvas, moved)
    QTest.mouseRelease(
        panel.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        moved,
    )

    after_drag = ManualMatchSettings.from_transition(
        panel.project.transitions[0]
    ).transform
    assert after_drag.target_corner_offsets[0] != before_drag.target_corner_offsets[0]
    displayed = panel.match_inspector.transform()
    assert displayed.target_corner_offsets[0].x == pytest.approx(
        after_drag.target_corner_offsets[0].x,
        abs=0.0001,
    )
    assert displayed.target_corner_offsets[0].y == pytest.approx(
        after_drag.target_corner_offsets[0].y,
        abs=0.0001,
    )

    panel.undo()
    after_undo = ManualMatchSettings.from_transition(
        panel.project.transitions[0]
    ).transform
    assert after_undo == before_drag
    panel.redo()

    panel.timeline.scene.set_transition_selection(transition.transition_id)
    before_body_drag = ManualMatchSettings.from_transition(
        panel.project.transitions[0]
    ).transform
    points = panel.canvas._match_widget_points()
    center = QPoint(
        int(round(sum(point.x() for point in points) / 4)),
        int(round(sum(point.y() for point in points) / 4)),
    )
    moved_center = center + QPoint(8, -6)
    QTest.mousePress(
        panel.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        center,
    )
    QTest.mouseMove(panel.canvas, moved_center)
    QTest.mouseRelease(
        panel.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        moved_center,
    )
    after_body_drag = ManualMatchSettings.from_transition(
        panel.project.transitions[0]
    ).transform
    assert after_body_drag.position_x != before_body_drag.position_x
    assert after_body_drag.position_y != before_body_drag.position_y
    assert (
        after_body_drag.target_corner_offsets
        == before_body_drag.target_corner_offsets
    )

    panel.timeline.delete_button.click()
    assert panel.project.transitions == ()
    assert panel.canvas.match_transition_id is None
    panel.undo()
    assert panel.project.transitions[0].kind == TransitionKind.MATCH
    panel.close()


def test_spatial_match_ui_previews_rejects_accepts_and_restores_history(
    app,
    tmp_path: Path,
) -> None:
    project, real_clip_id = _project(tmp_path)
    solution = SpatialMatchSolution(
        ((-0.08, 0.12), (0.82, 0.08), (0.88, 0.86), (-0.04, 0.92)),
        ((0.9, 0.04, -0.08), (-0.04, 0.8, 0.12), (0.0, 0.0, 1.0)),
        90,
        110,
        45,
        25,
        14,
        0.56,
        3.8,
        0.48,
    ).validate()
    project, transition = add_spatial_match(
        project,
        "virtual",
        real_clip_id,
        solution,
    )
    panel = StudioPanel()
    panel.resize(1400, 1000)
    panel.show()
    panel.set_project(project, reset_history=True)
    panel.timeline.scene.set_transition_selection(transition.transition_id)

    inspector = panel.match_inspector
    assert inspector.selected_transition_kind == TransitionKind.SPATIAL_MATCH
    assert "faible" in inspector.diagnostic.text()
    assert "cadrage partiel" in inspector.diagnostic.text()
    assert inspector.restore_button.isVisible()
    original = panel.project.to_dict()
    settings = SpatialMatchSettings.from_transition(panel.project.transitions[0])
    inspector.overlay_opacity.setValue(35.0)
    inspector.preview_mode.setCurrentIndex(inspector.preview_mode.findData("overlay"))
    assert panel.project.to_dict() == original
    assert panel._match_proposal is not None
    overlay_settings = SpatialMatchSettings.from_transition(
        panel._match_proposal[1].transitions[0]
    )
    assert overlay_settings.comparison_overlay is True
    assert overlay_settings.overlay_opacity == pytest.approx(0.35)
    inspector.reject_button.click()
    assert panel.project.to_dict() == original
    offsets = list(settings.editor_transform.target_corner_offsets)
    offsets[0] = MatchPoint(offsets[0].x + 0.03, offsets[0].y + 0.02)
    adjusted = replace(settings.editor_transform, target_corner_offsets=tuple(offsets))

    panel._canvas_match_transform_changed(adjusted)

    assert panel.project.to_dict() == original
    assert panel._match_proposal is not None
    inspector.reject_button.click()
    assert panel._match_proposal is None
    assert panel.project.to_dict() == original

    panel._canvas_match_transform_changed(adjusted)
    inspector.apply_button.click()

    accepted = SpatialMatchSettings.from_transition(panel.project.transitions[0])
    assert accepted.review_status == "adjusted"
    assert accepted.comparison_overlay is False
    assert accepted.solution.target_quad != settings.solution.target_quad
    assert panel._match_proposal is None
    assert panel.history.can_undo
    reopened = StudioProject.from_dict(panel.project.to_dict())
    reopened_settings = SpatialMatchSettings.from_transition(reopened.transitions[0])
    assert reopened_settings.solution.to_dict() == accepted.solution.to_dict()
    assert panel.undo()
    assert panel.project.to_dict() == original
    panel.close()

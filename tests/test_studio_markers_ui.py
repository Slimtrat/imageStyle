from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import wave

import numpy as np
from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_timeline import RULER_HEIGHT, StudioTimeline
from artanimate.studio.assets import import_media_asset
from artanimate.studio.audio import add_audio_clip
from artanimate.studio.markers import (
    MarkerKind,
    TimelineMarkerState,
    add_custom_marker,
    marker_by_id,
)
from artanimate.studio.model import AssetKind, StudioProject
from artanimate.studio.music_analysis import (
    MusicAnalysis,
    MusicAnalysisSettings,
    MusicEvent,
    MusicEventKind,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project_with_audio(
    tmp_path: Path,
) -> tuple[StudioProject, Path, str]:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (120, 80), "purple").save(artwork)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(np.zeros(8 * 8_000, dtype="<i2").tobytes())
    asset = import_media_asset(
        audio,
        AssetKind.AUDIO,
        project_path,
        asset_id="music",
    )
    project = replace(
        StudioProject.new(artwork, fps=30, duration_seconds=8),
        assets=(asset,),
    ).validate()
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=60,
        source_in_frame=30,
        duration_frames=150,
    )
    return project, project_path, clip.clip_id


def _analysis() -> MusicAnalysis:
    return MusicAnalysis(
        "audio-fingerprint",
        MusicAnalysisSettings(),
        30,
        8_000,
        64_000,
        120.0,
        0.9,
        (
            MusicEvent(MusicEventKind.DOWNBEAT, 30, 8_000, 0.92, False),
            MusicEvent(MusicEventKind.BEAT, 60, 16_000, 0.58, True),
            MusicEvent(MusicEventKind.DROP, 90, 24_000, 0.86, False),
            MusicEvent(MusicEventKind.BEAT, 210, 56_000, 0.8, False),
        ),
    ).validate()


def test_timeline_renders_selects_and_drags_visible_markers(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "timeline.png"
    Image.new("RGB", (80, 60), "navy").save(artwork)
    project = StudioProject.new(artwork, duration_seconds=5)
    project, marker = add_custom_marker(project, 44, label="Impact")
    timeline = StudioTimeline()
    timeline.set_project(project)
    timeline.show()
    app.processEvents()
    for zoom in (75, 300, 1_800):
        timeline.zoom.setValue(zoom)
        image = timeline.scene.grab().toImage()
        assert not image.isNull()

    selected = QSignalSpy(timeline.markerSelectionChanged)
    moved = QSignalSpy(timeline.markerMoveRequested)
    start = QPoint(
        int(round(timeline.scene.frame_x(marker.frame))),
        RULER_HEIGHT - 5,
    )
    destination_frame = 70
    destination = QPoint(
        int(round(timeline.scene.frame_x(destination_frame))),
        RULER_HEIGHT - 5,
    )
    QTest.mousePress(timeline.scene, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(timeline.scene, destination)
    QTest.mouseRelease(
        timeline.scene,
        Qt.MouseButton.LeftButton,
        pos=destination,
    )

    assert selected.count() >= 1
    assert timeline.selected_marker_id == marker.marker_id
    assert moved.count() == 1
    assert moved.at(0) == [marker.marker_id, destination_frame]


def test_detected_markers_become_editable_undoable_and_audio_independent(
    app,
    tmp_path: Path,
) -> None:
    project, project_path, audio_clip_id = _project_with_audio(tmp_path)
    panel = StudioPanel(analysis_cache_dir=tmp_path / "cache")
    try:
        panel.set_project(project, reset_history=True)
        panel.asset_panel.set_context(project, project_path)
        rhythm = panel.music_analysis_panel
        rhythm.set_result("music", _analysis())
        assert rhythm.add_markers_button.isEnabled()
        rhythm.add_markers_button.click()

        state = TimelineMarkerState.from_project(panel.project)
        assert [(item.kind, item.frame) for item in state.markers] == [
            (MarkerKind.DOWNBEAT, 60),
            (MarkerKind.BEAT, 90),
            (MarkerKind.DROP, 120),
        ]
        assert panel.history.undo_label == "Ajouter les repères musicaux"
        assert panel.inspector_tabs.currentWidget() is panel.marker_panel
        marker_id = state.markers[1].marker_id
        panel.timeline.set_marker_selection(marker_id)
        assert panel.marker_panel.selected_marker_id == marker_id

        marker_panel = panel.marker_panel
        marker_panel.frame_spin.setValue(94)
        marker_panel.label_edit.setText("Clignement")
        kind_index = marker_panel.kind_combo.findData(MarkerKind.CUSTOM.value)
        marker_panel.kind_combo.setCurrentIndex(kind_index)
        marker_panel.apply_button.click()
        edited = marker_by_id(panel.project, marker_id)
        assert (edited.frame, edited.kind, edited.label) == (
            94,
            MarkerKind.CUSTOM,
            "Clignement",
        )
        assert edited.adjusted and not edited.uncertain
        assert panel.undo()
        assert marker_by_id(panel.project, marker_id).frame == 90
        assert panel.redo()
        assert marker_by_id(panel.project, marker_id).frame == 94

        panel.timeline.snap_button.setChecked(True)
        panel._move_timeline_marker(marker_id, 61)
        assert marker_by_id(panel.project, marker_id).frame == 60
        panel.timeline.snap_button.setChecked(False)
        panel._move_timeline_marker(marker_id, 61)
        assert marker_by_id(panel.project, marker_id).frame == 61

        drop_index = marker_panel.filter_combo.findData(MarkerKind.DROP.value)
        marker_panel.filter_combo.setCurrentIndex(drop_index)
        visible = TimelineMarkerState.from_project(panel.project).visible_markers()
        assert len(visible) == 1 and visible[0].kind == MarkerKind.DROP
        marker_panel.next_button.click()
        assert panel.transport.current_frame == visible[0].frame

        marker_panel.filter_combo.setCurrentIndex(0)
        panel.transport.seek(150)
        marker_panel.add_button.click()
        custom = [
            item
            for item in TimelineMarkerState.from_project(panel.project).markers
            if item.frame == 150 and item.kind == MarkerKind.CUSTOM
        ]
        assert len(custom) == 1
        marker_panel.deleteRequested.emit(custom[0].marker_id)
        assert custom[0].marker_id not in {
            item.marker_id
            for item in TimelineMarkerState.from_project(panel.project).markers
        }

        panel.timeline_actions.delete_clips((audio_clip_id,))
        persisted = TimelineMarkerState.from_project(panel.project).markers
        assert persisted
        reopened = StudioProject.from_dict(panel.project.to_dict())
        assert TimelineMarkerState.from_project(reopened).markers == persisted
    finally:
        panel.shutdown()

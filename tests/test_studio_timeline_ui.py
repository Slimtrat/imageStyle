import os
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_timeline import StudioTimelineScene
from artanimate.studio.model import Clip, ClipKind, StudioProject, Track, TrackKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    project = StudioProject.new(artwork)
    overlapping = Track(
        "video-overlap",
        TrackKind.VIDEO,
        "Révélations",
        (
            Clip("reveal-a", ClipKind.ARTWORK_2D, 20, 80),
            Clip("reveal-b", ClipKind.ARTWORK_2D, 60, 90),
        ),
    )
    return replace(project, tracks=(*project.tracks, overlapping)).validate()


def test_scene_displays_top_z_first_and_separates_overlaps(app, tmp_path: Path) -> None:
    project = make_project(tmp_path)
    scene = StudioTimelineScene()
    scene.set_project(project)
    scene.show()
    QApplication.processEvents()

    assert scene.visible_track_ids == tuple(
        track.track_id for track in reversed(project.tracks)
    )
    reveal_layouts = {
        layout.clip.clip_id: layout for layout in scene.clip_layouts
        if layout.track_id == "video-overlap"
    }
    assert reveal_layouts["reveal-a"].lane != reveal_layouts["reveal-b"].lane
    assert not reveal_layouts["reveal-a"].rect.intersects(
        reveal_layouts["reveal-b"].rect
    )

    before = scene.width()
    scene.set_pixels_per_frame(8)
    assert scene.width() > before


def test_scene_supports_single_and_ctrl_multiple_selection(app, tmp_path: Path) -> None:
    scene = StudioTimelineScene()
    scene.set_project(make_project(tmp_path))
    scene.show()
    QApplication.processEvents()
    layouts = {
        layout.clip.clip_id: layout
        for layout in scene.clip_layouts
        if layout.clip.clip_id in {"reveal-a", "reveal-b"}
    }

    QTest.mouseClick(
        scene,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        layouts["reveal-a"].rect.center().toPoint(),
    )
    assert scene.selected_clip_ids == ("reveal-a",)
    QTest.mouseClick(
        scene,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        layouts["reveal-b"].rect.center().toPoint(),
    )
    assert set(scene.selected_clip_ids) == {"reveal-a", "reveal-b"}


def test_panel_adds_tracks_toggles_headers_and_syncs_playhead(app, tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    panel = StudioPanel()
    panel.set_artwork(artwork)

    panel.timeline.addTrackRequested.emit(TrackKind.VIDEO)
    panel.timeline.addTrackRequested.emit(TrackKind.EFFECT)
    panel.timeline.addTrackRequested.emit(TrackKind.AUDIO)
    assert sum(track.kind == TrackKind.VIDEO for track in panel.project.tracks) == 2
    assert sum(track.kind == TrackKind.EFFECT for track in panel.project.tracks) == 2
    assert sum(track.kind == TrackKind.AUDIO for track in panel.project.tracks) == 2

    panel.timeline.trackStateRequested.emit("video-main", "locked", True)
    video_main = next(track for track in panel.project.tracks if track.track_id == "video-main")
    assert video_main.locked

    panel.transport.seek(75)
    assert panel.timeline.scene._playhead == 75
    panel.timeline.seekRequested.emit(42)
    assert panel.transport.current_frame == 42


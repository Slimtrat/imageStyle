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
from artanimate.studio.model import TrackKind
from artanimate.studio.timeline import clip_location


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def panel(tmp_path: Path) -> StudioPanel:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    result = StudioPanel()
    result.resize(1200, 1000)
    result.set_artwork(artwork)
    result.show()
    QApplication.processEvents()
    return result


def clip_ids(editor: StudioPanel) -> set[str]:
    return {
        clip.clip_id
        for track in editor.project.tracks
        for clip in track.clips
    }


def test_toolbar_split_duplicate_delete_and_track_order(app, tmp_path: Path) -> None:
    editor = panel(tmp_path)
    editor.timeline.scene.set_selection(("artwork-main",))
    editor.transport.seek(120)
    editor.timeline.splitRequested.emit(editor.timeline.selected_clip_ids)

    assert len(clip_ids(editor)) == 2
    right_id = editor.timeline.selected_clip_ids[0]
    assert clip_location(editor.project, right_id)[3].start_frame == 120

    editor.timeline.duplicateRequested.emit(editor.timeline.selected_clip_ids)
    copied = editor.timeline.selected_clip_ids
    assert len(clip_ids(editor)) == 3
    assert len(copied) == 1

    editor.timeline.deleteRequested.emit(copied)
    assert len(clip_ids(editor)) == 2

    editor.timeline.addTrackRequested.emit(TrackKind.VIDEO)
    added = editor.project.tracks[-1].track_id
    editor.timeline.trackReorderRequested.emit(added, -1)
    assert editor.project.tracks[-2].track_id == added


def test_move_and_trim_signals_snap_in_integer_frames(app, tmp_path: Path) -> None:
    editor = panel(tmp_path)
    editor.timeline.scene.set_selection(("artwork-main",))
    editor.transport.seek(120)
    editor.timeline.splitRequested.emit(("artwork-main",))
    right_id = editor.timeline.selected_clip_ids[0]

    # Frame 118 is within the magnetic threshold of the left clip end at 120.
    editor.timeline.clipMoveRequested.emit((right_id,), right_id, 118, "video-main")
    assert clip_location(editor.project, right_id)[3].start_frame == 120

    editor.timeline.snap_button.setChecked(False)
    editor.timeline.clipMoveRequested.emit((right_id,), right_id, 118, "video-main")
    assert clip_location(editor.project, right_id)[3].start_frame == 118

    editor.timeline.clipTrimRequested.emit(right_id, 130, 300)
    trimmed = clip_location(editor.project, right_id)[3]
    assert (trimmed.start_frame, trimmed.end_frame) == (130, 300)
    assert isinstance(trimmed.start_frame, int)


def test_mouse_drag_moves_clip_between_compatible_video_tracks(app, tmp_path: Path) -> None:
    editor = panel(tmp_path)
    editor.transport.seek(120)
    editor.timeline.scene.set_selection(("artwork-main",))
    editor.timeline.splitRequested.emit(("artwork-main",))
    editor.timeline.addTrackRequested.emit(TrackKind.VIDEO)
    target_track = editor.project.tracks[-1].track_id
    scene = editor.timeline.scene
    left_layout = next(
        layout for layout in scene.clip_layouts
        if layout.clip.clip_id == "artwork-main"
    )
    target_row = next(
        row for row in scene._track_layouts
        if row.track.track_id == target_track
    )
    start = left_layout.rect.center().toPoint()
    # The drag preserves the grabbed offset: the center was frame 60, so
    # placing it at frame 90 moves the clip start from frame 0 to frame 30.
    destination = QPoint(
        int(scene.frame_x(90)),
        int(target_row.rect.center().y()),
    )

    QTest.mousePress(scene, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(scene, destination)
    QTest.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=destination)

    moved = clip_location(editor.project, "artwork-main")
    assert moved[2].track_id == target_track
    assert moved[3].start_frame == 30


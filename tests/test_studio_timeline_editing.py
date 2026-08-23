from dataclasses import replace
from pathlib import Path
import random

from PIL import Image
import pytest

from artanimate.studio.model import (
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Clip,
    ClipKind,
    StudioProject,
    Track,
    TrackKind,
)
from artanimate.studio.timeline import (
    OVERLAP_POLICY,
    clip_location,
    delete_clips,
    duplicate_clip,
    move_clip,
    reorder_track,
    snap_frame,
    split_clip,
    timeline_snap_targets,
    trim_clip,
)


def make_project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    project = StudioProject.new(artwork)
    camera = CameraAnimation(
        (
            CameraKeyframe(0, CameraPose(zoom=1.0)),
            CameraKeyframe(60, CameraPose(zoom=2.0)),
            CameraKeyframe(119, CameraPose(zoom=3.0)),
        )
    )
    base = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre",
        (
            Clip("shot-a", ClipKind.ARTWORK_2D, 0, 120, camera=camera),
            Clip("shot-b", ClipKind.ARTWORK_2D, 150, 60),
        ),
    )
    upper = Track("video-upper", TrackKind.VIDEO, "Réel")
    return replace(project, tracks=(base, upper, *project.tracks[1:])).validate()


def test_trim_split_move_duplicate_delete_and_reorder_are_frame_exact(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert OVERLAP_POLICY == "layered"

    project = trim_clip(project, "shot-a", 30, 100)
    trimmed = clip_location(project, "shot-a")[3]
    assert (trimmed.start_frame, trimmed.duration_frames, trimmed.source_in_frame) == (
        30,
        70,
        30,
    )
    assert trimmed.camera.keyframes[0].frame == 0

    project, right = split_clip(project, "shot-a", 60)
    left = clip_location(project, "shot-a")[3]
    assert (left.start_frame, left.duration_frames) == (30, 30)
    assert (right.start_frame, right.duration_frames, right.source_in_frame) == (
        60,
        40,
        60,
    )
    assert right.camera.keyframes[0].frame == 0

    project = move_clip(project, right.clip_id, 90, target_track_id="video-upper")
    assert clip_location(project, right.clip_id)[2].track_id == "video-upper"
    assert clip_location(project, right.clip_id)[3].start_frame == 90

    project, duplicate = duplicate_clip(
        project,
        right.clip_id,
        target_frame=100,
    )
    assert duplicate.clip_id != right.clip_id
    assert duplicate.start_frame == 100
    project = delete_clips(project, (duplicate.clip_id,))
    with pytest.raises(KeyError, match="introuvable"):
        clip_location(project, duplicate.clip_id)

    reordered = reorder_track(project, "video-upper", 0)
    assert reordered.tracks[0].track_id == "video-upper"
    assert reordered.validate() is reordered


def test_snapping_uses_clip_edges_keyframes_and_playhead(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    targets = timeline_snap_targets(project, playhead=75, exclude_clip_ids=("shot-b",))

    assert {0, 60, 75, 119, 120, project.settings.duration_frames} <= set(targets)
    assert snap_frame(73, targets, threshold_frames=3) == 75
    assert snap_frame(73, targets, threshold_frames=1) == 73
    assert snap_frame(73, targets, threshold_frames=3, enabled=False) == 73


def test_locked_tracks_refuse_destructive_edits(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    tracks = list(project.tracks)
    tracks[0] = replace(tracks[0], locked=True)
    project = replace(project, tracks=tuple(tracks)).validate()

    with pytest.raises(PermissionError, match="verrouillée"):
        trim_clip(project, "shot-a", 10, 100)
    with pytest.raises(PermissionError, match="verrouillée"):
        delete_clips(project, ("shot-a",))


def test_random_edit_sequences_keep_project_valid(tmp_path: Path) -> None:
    rng = random.Random(20260823)
    project = make_project(tmp_path)
    for _step in range(120):
        clips = [clip for track in project.tracks for clip in track.clips]
        clip = rng.choice(clips)
        operation = rng.choice(("move", "trim", "split", "duplicate", "delete"))
        if operation == "move":
            target = rng.randint(0, project.settings.duration_frames - clip.duration_frames)
            project = move_clip(project, clip.clip_id, target)
        elif operation == "trim" and clip.duration_frames > 1:
            left = rng.randint(0, clip.duration_frames - 1)
            right = rng.randint(left + 1, clip.duration_frames)
            project = trim_clip(
                project,
                clip.clip_id,
                clip.start_frame + left,
                clip.start_frame + right,
            )
        elif operation == "split" and clip.duration_frames > 1:
            frame = rng.randint(clip.start_frame + 1, clip.end_frame - 1)
            project, _right = split_clip(project, clip.clip_id, frame)
        elif operation == "duplicate" and len(clips) < 24:
            target = rng.randint(0, project.settings.duration_frames - clip.duration_frames)
            project, _copy = duplicate_clip(project, clip.clip_id, target_frame=target)
        elif operation == "delete" and len(clips) > 2:
            project = delete_clips(project, (clip.clip_id,))
        project.validate()


from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from artanimate.studio.model import (
    Clip,
    ClipKind,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
)
from artanimate.studio.timeline import move_clip, split_clip, trim_clip
from artanimate.studio.transitions import (
    add_dissolve,
    transition_end_frame,
    update_dissolve,
)


def _three_shot_project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (64, 64), (120, 80, 40)).save(artwork)
    base = StudioProject.new(artwork, duration_seconds=1)
    track = Track(
        "video-main",
        TrackKind.VIDEO,
        "Trois plans",
        (
            Clip("shot-a", ClipKind.ARTWORK_2D, 0, 10),
            Clip("shot-b", ClipKind.ARTWORK_2D, 10, 10),
            Clip("shot-c", ClipKind.ARTWORK_2D, 20, 10),
        ),
    )
    return replace(
        base,
        settings=ProjectSettings(
            width=64,
            height=64,
            fps=30,
            duration_frames=30,
            background=(0, 0, 0),
        ),
        tracks=(track, *base.tracks[1:]),
    ).validate()


def test_a_clip_can_have_distinct_entry_and_exit_dissolves(
    tmp_path: Path,
) -> None:
    project = _three_shot_project(tmp_path)
    project, first = add_dissolve(
        project,
        "shot-a",
        "shot-b",
        duration_frames=4,
    )
    project, second = add_dissolve(
        project,
        "shot-b",
        "shot-c",
        duration_frames=4,
    )

    assert len(project.transitions) == 2
    assert first.to_clip_id == second.from_clip_id == "shot-b"


def test_timing_edits_remove_connected_dissolves_before_validation(
    tmp_path: Path,
) -> None:
    project, _transition = add_dissolve(
        _three_shot_project(tmp_path),
        "shot-a",
        "shot-b",
        duration_frames=4,
    )

    assert move_clip(project, "shot-a", 1).transitions == ()
    assert trim_clip(project, "shot-a", 0, 9).transitions == ()
    split_project, _right = split_clip(project, "shot-a", 5)
    assert split_project.transitions == ()


def test_duration_edits_recenter_but_preserve_an_unchanged_window(
    tmp_path: Path,
) -> None:
    project, transition = add_dissolve(
        _three_shot_project(tmp_path),
        "shot-a",
        "shot-b",
        duration_frames=4,
    )

    centered = update_dissolve(
        project,
        transition.transition_id,
        duration_frames=6,
    ).transitions[0]
    assert (centered.start_frame, transition_end_frame(centered)) == (7, 13)

    asymmetric_project = update_dissolve(
        project,
        transition.transition_id,
        start_frame=9,
        end_frame=12,
    )
    preserved = update_dissolve(
        asymmetric_project,
        transition.transition_id,
        duration_frames=3,
    ).transitions[0]
    assert (preserved.start_frame, transition_end_frame(preserved)) == (9, 12)

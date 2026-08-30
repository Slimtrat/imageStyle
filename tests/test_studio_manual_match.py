from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
from artanimate.core.video import VideoFrameEncoder

from artanimate.studio.assets import import_media_asset

from artanimate.studio.compositor import StudioCompositor
from artanimate.studio.manual_match import (
    ManualMatchSettings,
    ManualMatchTransform,
    MatchCrop,
    MatchPoint,
    add_manual_match,
    update_manual_match,
)
from artanimate.studio.model import (
    AssetKind,
    Clip,
    ClipKind,
    Easing,
    MediaAsset,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
    TransitionKind,
)
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.transitions import add_dissolve, transition_progress


class SolidSource:
    def __init__(self, color: tuple[int, int, int], *, frame_count: int = 30):
        self.width = 64
        self.height = 64
        self.fps = 30
        self.frame_count = frame_count
        self._frame = np.full((64, 64, 3), color, dtype=np.uint8)

    def frame_at(self, frame_index: int) -> np.ndarray:
        if not 0 <= frame_index < self.frame_count:
            raise IndexError(frame_index)
        return self._frame


def _encode_video(path: Path, *, frame_count: int = 12) -> tuple[np.ndarray, ...]:
    frames = tuple(
        np.full(
            (64, 64, 3),
            (10, 30 + index * 10, 220 - index * 8),
            dtype=np.uint8,
        )
        for index in range(frame_count)
    )
    encoder = VideoFrameEncoder(
        path,
        64,
        64,
        30,
        quality="fast",
        total_frames=frame_count,
    )
    try:
        for frame in frames:
            encoder.write(frame)
        encoder.finish()
    except Exception:
        encoder.abort()
        raise
    return frames

def _still_project(tmp_path: Path) -> tuple[StudioProject, Path]:
    artwork = tmp_path / "artwork.png"
    real = tmp_path / "real.png"
    Image.new("RGB", (64, 64), (255, 0, 0)).save(artwork)
    Image.new("RGB", (64, 64), (0, 0, 255)).save(real)
    base = StudioProject.new(artwork, duration_seconds=1)
    asset = MediaAsset(
        "real-photo",
        AssetKind.IMAGE,
        str(real),
        width=64,
        height=64,
    )
    track = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre vers réel",
        (
            Clip("virtual", ClipKind.ARTWORK_2D, 0, 5),
            Clip(
                "real",
                ClipKind.STILL,
                5,
                5,
                asset_id=asset.asset_id,
            ),
        ),
    )
    project = replace(
        base,
        settings=ProjectSettings(
            width=64,
            height=64,
            fps=30,
            duration_frames=10,
            background=(0, 0, 0),
        ),
        assets=(asset,),
        tracks=(track, *base.tracks[1:]),
    ).validate()
    return project, artwork


def _video_project(tmp_path: Path) -> StudioProject:
    project, _artwork = _still_project(tmp_path)
    asset = MediaAsset(
        "real-video",
        AssetKind.VIDEO,
        str(tmp_path / "real.mp4"),
        width=64,
        height=64,
        metadata={"native_frame_count": 20, "native_fps": 30.0},
    )
    track = replace(
        project.tracks[0],
        clips=(
            project.tracks[0].clips[0],
            Clip(
                "real-video-clip",
                ClipKind.VIDEO,
                5,
                5,
                source_in_frame=4,
                asset_id=asset.asset_id,
            ),
        ),
    )
    return replace(
        project,
        assets=(asset,),
        tracks=(track, *project.tracks[1:]),
    ).validate()


def test_manual_match_round_trips_and_keeps_exact_transition_boundaries(
    tmp_path: Path,
) -> None:
    project, artwork = _still_project(tmp_path)
    project, match = add_manual_match(
        project,
        "virtual",
        "real",
        duration_frames=5,
        easing=Easing.LINEAR,
    )

    assert match.kind == TransitionKind.MATCH
    assert transition_progress(match, match.start_frame) == 0.0
    assert transition_progress(match, match.start_frame + 2) == 0.5
    assert transition_progress(match, match.start_frame + 4) == 1.0
    assert StudioProject.from_dict(project.to_dict()) == project

    with StudioRenderSession(project, artwork) as session:
        assert session.execution_mode == "semantic"
        assert np.all(session.frame_at(3) == (255, 0, 0))
        assert np.all(session.frame_at(5) == (128, 0, 128))
        assert np.all(session.frame_at(7) == (0, 0, 255))
        assert np.all(session.frame_at(8) == (0, 0, 255))


def test_match_transform_affects_the_real_shot_after_the_blend(
    tmp_path: Path,
) -> None:
    project, artwork = _still_project(tmp_path)
    project, match = add_manual_match(
        project,
        "virtual",
        "real",
        duration_frames=5,
        easing=Easing.LINEAR,
    )
    settings = ManualMatchSettings.from_transition(match)
    project = update_manual_match(
        project,
        match.transition_id,
        transform=replace(settings.transform, scale=0.5),
    )

    with StudioRenderSession(project, artwork) as session:
        final = session.frame_at(8)

    assert np.all(final[32, 32] == (0, 0, 255))
    assert np.all(final[2, 2] == (0, 0, 0))


def test_classic_compositor_matches_semantic_boundaries_and_geometry(
    tmp_path: Path,
) -> None:
    project, _artwork = _still_project(tmp_path)
    project, match = add_manual_match(
        project,
        "virtual",
        "real",
        duration_frames=5,
        easing=Easing.LINEAR,
    )
    project = update_manual_match(
        project,
        match.transition_id,
        transform=replace(
            ManualMatchSettings.from_transition(match).transform,
            scale=0.5,
        ),
    )
    compositor = StudioCompositor(
        project,
        {
            "virtual": SolidSource((255, 0, 0)),
            "real": SolidSource((0, 0, 255)),
        },
    )

    assert np.all(compositor.frame_at(3) == (255, 0, 0))
    assert np.all(compositor.frame_at(5)[32, 32] == (128, 0, 128))
    assert np.all(compositor.frame_at(7)[32, 32] == (0, 0, 255))
    assert np.all(compositor.frame_at(8)[32, 32] == (0, 0, 255))
    assert np.all(compositor.frame_at(8)[2, 2] == (0, 0, 0))



def test_dissolve_can_be_promoted_without_changing_its_window(
    tmp_path: Path,
) -> None:
    project, _artwork = _still_project(tmp_path)
    project, dissolve = add_dissolve(
        project,
        "virtual",
        "real",
        duration_frames=4,
        easing=Easing.EASE_OUT,
    )
    project, match = add_manual_match(project, "virtual", "real")

    assert match.transition_id == dissolve.transition_id
    assert match.start_frame == dissolve.start_frame
    assert match.duration_frames == dissolve.duration_frames
    assert ManualMatchSettings.from_transition(match).easing == Easing.EASE_OUT
    assert project.transitions == (match,)


def test_video_reference_frame_is_serialized_and_bounded(tmp_path: Path) -> None:
    project = _video_project(tmp_path)
    project, match = add_manual_match(
        project,
        "virtual",
        "real-video-clip",
        duration_frames=2,
    )

    assert ManualMatchSettings.from_transition(match).reference_source_frame == 4
    updated = update_manual_match(
        project,
        match.transition_id,
        reference_source_frame=7,
        overlay_opacity=0.7,
    )
    settings = ManualMatchSettings.from_transition(updated.transitions[0])
    assert settings.reference_source_frame == 7
    assert settings.overlay_opacity == 0.7
    with pytest.raises(ValueError, match="plan vidéo réel"):
        update_manual_match(
            project,
            match.transition_id,
            reference_source_frame=9,
        )

def test_manual_match_renders_a_real_video_without_freezing_reference(
    tmp_path: Path,
) -> None:
    project, artwork = _still_project(tmp_path)
    video = tmp_path / "real.mp4"
    native_frames = _encode_video(video)
    asset = import_media_asset(
        video,
        AssetKind.VIDEO,
        tmp_path / "project.artanimate",
        asset_id="real-video",
    )
    track = replace(
        project.tracks[0],
        clips=(
            project.tracks[0].clips[0],
            Clip(
                "real-video-clip",
                ClipKind.VIDEO,
                5,
                5,
                source_in_frame=2,
                asset_id=asset.asset_id,
            ),
        ),
    )
    project = replace(
        project,
        assets=(asset,),
        tracks=(track, *project.tracks[1:]),
    ).validate()
    project, match = add_manual_match(
        project,
        "virtual",
        "real-video-clip",
        duration_frames=5,
        easing=Easing.LINEAR,
    )
    project = update_manual_match(
        project,
        match.transition_id,
        reference_source_frame=6,
    )

    with StudioRenderSession(
        project,
        artwork,
        resource_base=tmp_path,
    ) as session:
        start = session.frame_at(3)
        end = session.frame_at(7)
        later = session.frame_at(8)

    assert np.all(start == (255, 0, 0))
    assert np.abs(end.astype(np.float32).mean(axis=(0, 1)) - native_frames[4][0, 0]).max() < 12
    assert np.abs(later.astype(np.float32).mean(axis=(0, 1)) - native_frames[5][0, 0]).max() < 12
    assert not np.array_equal(end, later)


def test_crop_and_four_corner_perspective_are_validated() -> None:
    transform = ManualMatchTransform(
        source_crop=MatchCrop(0.1, 0.2, 0.8, 0.6),
        source_corner_offsets=(
            MatchPoint(0.0, 0.0),
            MatchPoint(-0.05, 0.02),
            MatchPoint(-0.02, -0.04),
            MatchPoint(0.03, -0.01),
        ),
        position_x=0.45,
        position_y=0.55,
        scale=0.8,
        rotation_degrees=3.0,
        target_corner_offsets=(
            MatchPoint(0.01, 0.02),
            MatchPoint(-0.02, 0.01),
            MatchPoint(-0.01, -0.02),
            MatchPoint(0.02, -0.01),
        ),
    ).validate()

    assert ManualMatchTransform.from_dict(transform.to_dict()) == transform
    with pytest.raises(ValueError, match="convexes"):
        replace(
            transform,
            target_corner_offsets=(
                MatchPoint(),
                MatchPoint(-1.0, 1.0),
                MatchPoint(),
                MatchPoint(),
            ),
        ).validate()

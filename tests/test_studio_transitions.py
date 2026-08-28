from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.studio.compositor import StudioCompositor
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
)
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.transitions import (
    DissolveSettings,
    add_dissolve,
    delete_transition,
    dissolve_progress,
    update_dissolve,
    validate_project_transitions,
)


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


def _visual_project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (64, 64), (255, 0, 0)).save(artwork)
    base = StudioProject.new(artwork, duration_seconds=1)
    settings = ProjectSettings(
        width=64,
        height=64,
        fps=30,
        duration_frames=10,
        background=(0, 0, 0),
    )
    track = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre puis réel",
        (
            Clip("artwork-a", ClipKind.ARTWORK_2D, 0, 5),
            Clip("artwork-b", ClipKind.ARTWORK_2D, 5, 5),
        ),
    )
    return replace(
        base,
        settings=settings,
        tracks=(track, *base.tracks[1:]),
    ).validate()


def _video_asset(asset_id: str, frame_count: int) -> MediaAsset:
    return MediaAsset(
        asset_id,
        AssetKind.VIDEO,
        f"C:/{asset_id}.mp4",
        width=64,
        height=64,
        metadata={
            "native_frame_count": frame_count,
            "native_fps": 30.0,
        },
    )


def test_dissolve_has_exact_endpoints_midpoint_and_cut_restoration(
    tmp_path: Path,
) -> None:
    project = _visual_project(tmp_path)
    project, transition = add_dissolve(
        project,
        "artwork-a",
        "artwork-b",
        duration_frames=5,
        easing=Easing.LINEAR,
    )
    compositor = StudioCompositor(
        project,
        {
            "artwork-a": SolidSource((255, 0, 0)),
            "artwork-b": SolidSource((0, 0, 255)),
        },
    )

    assert (transition.start_frame, transition.duration_frames) == (3, 5)
    assert dissolve_progress(transition, 3) == 0.0
    assert dissolve_progress(transition, 5) == 0.5
    assert dissolve_progress(transition, 7) == 1.0
    assert np.all(compositor.frame_at(3) == (255, 0, 0))
    assert np.all(compositor.frame_at(5) == (128, 0, 128))
    assert np.all(compositor.frame_at(7) == (0, 0, 255))

    cut_project = delete_transition(project, transition.transition_id)
    cut_compositor = StudioCompositor(
        cut_project,
        {
            "artwork-a": SolidSource((255, 0, 0)),
            "artwork-b": SolidSource((0, 0, 255)),
        },
    )
    assert np.all(cut_compositor.frame_at(4) == (255, 0, 0))
    assert np.all(cut_compositor.frame_at(5) == (0, 0, 255))


def test_semantic_render_session_uses_the_same_golden_dissolve(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "red.png"
    real = tmp_path / "blue.png"
    Image.new("RGB", (64, 64), (255, 0, 0)).save(artwork)
    Image.new("RGB", (64, 64), (0, 0, 255)).save(real)
    base = StudioProject.new(artwork, duration_seconds=1)
    asset = MediaAsset(
        "real-blue",
        AssetKind.IMAGE,
        str(real),
        width=64,
        height=64,
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
        tracks=(
            Track(
                "video-main",
                TrackKind.VIDEO,
                "Œuvre puis photo réelle",
                (
                    Clip("artwork", ClipKind.ARTWORK_2D, 0, 5),
                    Clip(
                        "real",
                        ClipKind.STILL,
                        5,
                        5,
                        asset_id=asset.asset_id,
                    ),
                ),
            ),
            *base.tracks[1:],
        ),
    ).validate()
    project, transition = add_dissolve(
        project,
        "artwork",
        "real",
        duration_frames=5,
        easing=Easing.LINEAR,
    )

    with StudioRenderSession(project, artwork) as session:
        assert session.execution_mode == "semantic"
        assert np.all(session.frame_at(transition.start_frame) == (255, 0, 0))
        assert np.all(session.frame_at(5) == (128, 0, 128))
        assert np.all(session.frame_at(7) == (0, 0, 255))


def test_dissolve_settings_round_trip_and_window_update(tmp_path: Path) -> None:
    project, transition = add_dissolve(
        _visual_project(tmp_path),
        "artwork-a",
        "artwork-b",
        duration_frames=4,
    )
    updated = update_dissolve(
        project,
        transition.transition_id,
        start_frame=2,
        end_frame=8,
        easing=Easing.EASE_OUT,
    )
    resolved = updated.transitions[0]

    assert resolved.duration_frames == 6
    assert DissolveSettings.from_transition(resolved).easing == Easing.EASE_OUT
    assert StudioProject.from_dict(updated.to_dict()) == updated


def test_video_handle_shortage_is_rejected_before_render(tmp_path: Path) -> None:
    base = _visual_project(tmp_path)
    source = _video_asset("source-a", 6)
    target = _video_asset("target-b", 12)
    track = Track(
        "video-main",
        TrackKind.VIDEO,
        "Deux vidéos",
        (
            Clip("video-a", ClipKind.VIDEO, 0, 5, asset_id=source.asset_id),
            Clip(
                "video-b",
                ClipKind.VIDEO,
                5,
                5,
                source_in_frame=1,
                asset_id=target.asset_id,
            ),
        ),
    )
    project = replace(
        base,
        assets=(source, target),
        tracks=(track, *base.tracks[1:]),
    ).validate()
    project, transition = add_dissolve(
        project,
        "video-a",
        "video-b",
        duration_frames=2,
        easing=Easing.LINEAR,
    )
    validate_project_transitions(project, validate_sources=True)

    with pytest.raises(ValueError, match="Poignée de sortie insuffisante"):
        update_dissolve(
            project,
            transition.transition_id,
            end_frame=7,
        )
    with pytest.raises(ValueError, match="Poignée d’entrée insuffisante"):
        update_dissolve(
            project,
            transition.transition_id,
            start_frame=3,
            end_frame=6,
        )

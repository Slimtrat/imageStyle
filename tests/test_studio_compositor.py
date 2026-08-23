from dataclasses import dataclass, replace

import numpy as np
import pytest

from artanimate.studio.compositor import MissingClipSourceError, StudioCompositor
from artanimate.studio.model import (
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Clip,
    ClipKind,
    FitMode,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
)
from artanimate.studio.sources import validate_frame_index


@dataclass
class ColorSource:
    color: tuple[int, int, int]
    width: int
    height: int
    fps: int = 30
    frame_count: int = 60

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        frame = np.empty((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = self.color
        return frame


def project_with_tracks(*tracks: Track, duration_frames: int = 10) -> StudioProject:
    project = StudioProject.new("painting.png")
    return replace(
        project,
        settings=ProjectSettings(
            width=108,
            height=192,
            fps=30,
            duration_frames=duration_frames,
            background=(10, 20, 30),
        ),
        tracks=tracks,
    ).validate()


def test_empty_compositor_returns_the_project_background() -> None:
    compositor = StudioCompositor(project_with_tracks(), {})

    frame = compositor.frame_at(0)

    assert frame.shape == (192, 108, 3)
    assert np.all(frame == (10, 20, 30))


def test_tracks_are_composited_bottom_to_top_with_clip_opacity() -> None:
    bottom_clip = Clip(
        "bottom",
        ClipKind.ARTWORK_2D,
        0,
        10,
        fit=FitMode.STRETCH,
    )
    top_clip = Clip(
        "top",
        ClipKind.ARTWORK_2D,
        0,
        10,
        opacity=0.5,
        fit=FitMode.STRETCH,
    )
    project = project_with_tracks(
        Track("bottom-track", TrackKind.VIDEO, "Bas", (bottom_clip,)),
        Track("top-track", TrackKind.VIDEO, "Haut", (top_clip,)),
    )
    compositor = StudioCompositor(
        project,
        {
            "bottom": ColorSource((255, 0, 0), 108, 192),
            "top": ColorSource((0, 0, 255), 108, 192),
        },
    )

    frame = compositor.frame_at(4)

    assert tuple(frame[50, 50]) == (128, 0, 128)
    assert np.array_equal(frame, compositor.frame_at(4))


def test_clip_range_is_half_open_and_source_in_is_respected() -> None:
    clip = Clip(
        "shot",
        ClipKind.ARTWORK_2D,
        start_frame=2,
        duration_frames=2,
        source_in_frame=5,
        fit=FitMode.STRETCH,
    )

    class IndexedSource(ColorSource):
        def frame_at(self, frame_index: int) -> np.ndarray:
            validate_frame_index(frame_index, self.frame_count)
            return np.full((self.height, self.width, 3), frame_index, dtype=np.uint8)

    project = project_with_tracks(Track("video", TrackKind.VIDEO, "Vidéo", (clip,)))
    compositor = StudioCompositor(project, {"shot": IndexedSource((0, 0, 0), 108, 192)})

    assert tuple(compositor.frame_at(1)[0, 0]) == (10, 20, 30)
    assert tuple(compositor.frame_at(2)[0, 0]) == (5, 5, 5)
    assert tuple(compositor.frame_at(3)[0, 0]) == (6, 6, 6)
    assert tuple(compositor.frame_at(4)[0, 0]) == (10, 20, 30)


def test_contain_preserves_source_ratio_and_background() -> None:
    clip = Clip("shot", ClipKind.ARTWORK_2D, 0, 10, fit=FitMode.CONTAIN)
    project = project_with_tracks(Track("video", TrackKind.VIDEO, "Vidéo", (clip,)))
    compositor = StudioCompositor(project, {"shot": ColorSource((240, 40, 20), 100, 50)})

    frame = compositor.frame_at(0)

    assert tuple(frame[0, 0]) == (10, 20, 30)
    assert tuple(frame[96, 54]) == (240, 40, 20)


def test_camera_keyframes_change_the_composed_artwork_frame() -> None:
    camera = CameraAnimation(
        (
            CameraKeyframe(0, CameraPose(x=0.25, y=0.5, zoom=2.0)),
            CameraKeyframe(9, CameraPose(x=0.75, y=0.5, zoom=2.0)),
        )
    )
    clip = Clip("shot", ClipKind.ARTWORK_2D, 0, 10, camera=camera)
    project = project_with_tracks(Track("video", TrackKind.VIDEO, "Vidéo", (clip,)))

    class SplitSource(ColorSource):
        def frame_at(self, frame_index: int) -> np.ndarray:
            validate_frame_index(frame_index, self.frame_count)
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            frame[:, : self.width // 2] = (255, 0, 0)
            frame[:, self.width // 2 :] = (0, 0, 255)
            return frame

    compositor = StudioCompositor(project, {"shot": SplitSource((0, 0, 0), 108, 192)})

    assert tuple(compositor.frame_at(0)[96, 54]) == (255, 0, 0)
    assert tuple(compositor.frame_at(9)[96, 54]) == (0, 0, 255)


def test_hidden_tracks_are_skipped_and_active_missing_sources_are_explicit() -> None:
    clip = Clip("shot", ClipKind.ARTWORK_2D, 0, 10)
    hidden_project = project_with_tracks(
        Track("video", TrackKind.VIDEO, "Vidéo", (clip,), hidden=True)
    )
    assert np.all(StudioCompositor(hidden_project, {}).frame_at(0) == (10, 20, 30))

    visible_project = project_with_tracks(Track("video", TrackKind.VIDEO, "Vidéo", (clip,)))
    with pytest.raises(MissingClipSourceError, match="shot"):
        StudioCompositor(visible_project, {}).frame_at(0)


def test_proxy_must_keep_project_aspect_ratio() -> None:
    project = project_with_tracks()
    compositor = StudioCompositor(project, {}, output_width=54, output_height=96)
    assert compositor.frame_at(0).shape == (96, 54, 3)

    with pytest.raises(ValueError, match="ratio"):
        StudioCompositor(project, {}, output_width=64, output_height=64)


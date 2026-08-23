from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from artanimate.studio.compositor import StudioCompositor
from artanimate.studio.model import Clip, ClipKind, StudioProject, Track, TrackKind


class RedSource:
    width = 9
    height = 16
    fps = 30
    frame_count = 30

    def frame_at(self, frame_index: int) -> np.ndarray:
        assert 0 <= frame_index < self.frame_count
        return np.full((16, 9, 3), (255, 0, 0), dtype=np.uint8)


def test_muted_visual_track_is_not_composited(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (9, 16), "white").save(artwork)
    project = StudioProject.new(artwork)
    track = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre",
        (Clip("artwork-main", ClipKind.ARTWORK_2D, 0, 30),),
        muted=True,
    )
    project = replace(project, tracks=(track,)).validate()

    frame = StudioCompositor(project, {"artwork-main": RedSource()}).frame_at(0)

    expected = np.empty(
        (project.settings.height, project.settings.width, 3),
        dtype=np.uint8,
    )
    expected[:] = project.settings.background
    assert np.array_equal(frame, expected)


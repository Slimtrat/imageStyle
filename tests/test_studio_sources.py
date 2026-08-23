from dataclasses import dataclass

import numpy as np
import pytest

from artanimate.studio.sources import (
    TimedFrameSource,
    timed_frames,
    validate_frame_index,
    validate_timed_frame,
)


@dataclass
class SolidTimedSource:
    width: int = 4
    height: int = 3
    fps: int = 30
    frame_count: int = 3

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        return np.full(
            (self.height, self.width, 3),
            frame_index,
            dtype=np.uint8,
        )


def test_timed_source_is_runtime_checkable_and_sequentially_adaptable() -> None:
    source = SolidTimedSource()

    assert isinstance(source, TimedFrameSource)
    frames = list(timed_frames(source))
    assert [int(frame[0, 0, 0]) for frame in frames] == [0, 1, 2]
    assert np.array_equal(source.frame_at(1), source.frame_at(1))


def test_timed_source_validates_bounds_shape_and_dtype() -> None:
    source = SolidTimedSource()

    with pytest.raises(IndexError, match="hors plage"):
        source.frame_at(3)
    with pytest.raises(TypeError, match="entier"):
        validate_frame_index(True, 3)
    with pytest.raises(ValueError, match="attendu"):
        validate_timed_frame(source, np.zeros((2, 2, 3), dtype=np.uint8))
    with pytest.raises(TypeError, match="uint8"):
        validate_timed_frame(source, np.zeros((3, 4, 3), dtype=np.float32))


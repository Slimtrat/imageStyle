from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import numpy as np


def validate_frame_index(frame_index: int, frame_count: int) -> int:
    if isinstance(frame_index, bool) or not isinstance(frame_index, int):
        raise TypeError("L’index de frame doit être un entier")
    if frame_count <= 0:
        raise ValueError("Une source temporelle doit contenir au moins une frame")
    if not 0 <= frame_index < frame_count:
        raise IndexError(
            f"Frame {frame_index} hors plage, attendu 0 à {frame_count - 1}"
        )
    return frame_index


@runtime_checkable
class TimedFrameSource(Protocol):
    """Random-access frame source consumed by the V3 Studio compositor."""

    width: int
    height: int
    fps: int
    frame_count: int

    def frame_at(self, frame_index: int) -> np.ndarray:
        """Return a deterministic RGB uint8 frame at ``frame_index``."""
        ...


def timed_frames(source: TimedFrameSource) -> Iterator[np.ndarray]:
    """Expose a timed source sequentially without weakening its random-access API."""

    for frame_index in range(source.frame_count):
        yield source.frame_at(frame_index)


def validate_timed_frame(source: TimedFrameSource, frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    expected = (source.height, source.width, 3)
    if array.shape != expected:
        raise ValueError(f"Frame Studio de forme {array.shape}, attendu {expected}")
    if array.dtype != np.uint8:
        raise TypeError("Les frames Studio doivent être en uint8 RGB")
    return array


from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import numpy as np

from .config import RenderConfig


@runtime_checkable
class FrameSource(Protocol):
    """Video-encoder contract shared by 2D and future 3D presentations.

    The current :class:`ArtworkRenderer` is a direct 2D frame source. A V2 room
    renderer will wrap it, use its frames as an animated artwork texture, and expose
    the same contract after camera, lighting and scene composition.
    """

    config: RenderConfig
    width: int
    height: int

    @property
    def frame_count(self) -> int:
        """Number of frames that will be yielded."""
        ...

    def frames(self) -> Iterator[np.ndarray]:
        """Yield deterministic RGB uint8 frames in chronological order."""
        ...

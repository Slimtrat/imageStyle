from __future__ import annotations

from pathlib import Path

import numpy as np

from .compositor import StudioCompositor
from .model import StudioProject
from .source_registry import ArtworkSourceRegistry


class StudioRenderSession:
    """One canonical frame pipeline shared by proxy preview and final export."""

    def __init__(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        *,
        output_width: int | None = None,
        output_height: int | None = None,
        source_registry: ArtworkSourceRegistry | None = None,
    ):
        self.project = project.validate()
        self.artwork_path = Path(artwork_path)
        self.source_registry = source_registry or ArtworkSourceRegistry()
        self.sources = self.source_registry.sources_for(self.project, self.artwork_path)
        self.compositor = StudioCompositor(
            self.project,
            self.sources,
            output_width=output_width,
            output_height=output_height,
        )
        self.width = self.compositor.width
        self.height = self.compositor.height
        self.fps = self.compositor.fps
        self.frame_count = self.compositor.frame_count

    def frame_at(self, frame_index: int) -> np.ndarray:
        return self.compositor.frame_at(frame_index)

from __future__ import annotations

from pathlib import Path

import numpy as np

from .adapters.classic_2d import (
    PreparedRenderPlan,
    build_classic_2d_renderer_registry,
    build_legacy_capability_registry,
    prepare_render_plan,
)
from .adapters.legacy_project import project_as_semantic
from .adapters.semantic_compositor import SemanticPlanCompositor
from .compositor import StudioCompositor
from .model import StudioProject
from .semantic import RenderConstraints, RenderPlanner
from .source_registry import ArtworkSourceRegistry


_SEMANTIC_2D_CAPABILITIES = frozenset(
    {"artwork.present", "camera.animate", "audio.play"}
)


class StudioRenderSession:
    """Canonical preview/export pipeline with a progressive semantic execution path."""

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
        self.width = output_width or self.project.settings.width
        self.height = output_height or self.project.settings.height
        self.fps = self.project.settings.fps
        self.frame_count = self.project.settings.duration_frames
        self.prepared_plan: PreparedRenderPlan | None = None
        self.execution_mode = "legacy"

        semantic = project_as_semantic(self.project)
        visual_invocations = tuple(
            invocation
            for invocation in semantic.invocations
            if invocation.capability_id != "audio.play"
        )
        semantic_2d_only = all(
            invocation.capability_id in _SEMANTIC_2D_CAPABILITIES
            or invocation.capability_id.startswith("reveal.")
            for invocation in visual_invocations
        )
        if semantic_2d_only:
            renderers = build_classic_2d_renderer_registry(
                self.project,
                self.artwork_path,
                sources=self.source_registry,
            )
            plan = RenderPlanner(
                build_legacy_capability_registry(),
                renderers,
            ).plan(
                self.project.project_id,
                semantic.scene,
                visual_invocations,
                RenderConstraints(
                    self.width,
                    self.height,
                    self.fps,
                    quality=self.project.export.quality,
                    proxy=(
                        self.width != self.project.settings.width
                        or self.height != self.project.settings.height
                    ),
                ),
            )
            self.prepared_plan = prepare_render_plan(plan, renderers)
            self.compositor = SemanticPlanCompositor(
                self.project,
                semantic,
                self.prepared_plan,
            )
            self.sources = {}
            self.execution_mode = "semantic"
            return

        # Compatibility bridge while 3D and real-media renderers are migrated.
        self.sources = self.source_registry.sources_for(
            self.project,
            self.artwork_path,
        )
        self.compositor = StudioCompositor(
            self.project,
            self.sources,
            output_width=self.width,
            output_height=self.height,
        )

    def frame_at(self, frame_index: int) -> np.ndarray:
        return self.compositor.frame_at(frame_index)

    def close(self) -> None:
        if self.prepared_plan is not None:
            self.prepared_plan.close()
            self.prepared_plan = None

    def __enter__(self) -> "StudioRenderSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

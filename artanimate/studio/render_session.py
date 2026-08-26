from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from .adapters.classic_2d import (
    PreparedRenderPlan,
    build_classic_2d_renderer_registry,
    build_studio_capability_registry,
    prepare_render_plan,
)
from .adapters.legacy_project import project_as_semantic
from .adapters.semantic_compositor import SemanticPlanCompositor
from .events import TriggerCompilation, compile_timeline_triggers
from .compositor import StudioCompositor
from .model import StudioProject
from .semantic import (
    CapabilityRenderer,
    RendererPolicyMode,
    RenderConstraints,
    RenderPlanner,
)
from .source_registry import ArtworkSourceRegistry


class StudioRenderSession:
    """Canonical preview/export pipeline with a progressive semantic execution path."""

    def __init__(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        *,
        output_width: int | None = None,
        output_height: int | None = None,
        extra_renderers: tuple[CapabilityRenderer, ...] = (),
        resource_base: str | Path | None = None,
        source_registry: ArtworkSourceRegistry | None = None,
    ):
        self.project = project.validate()
        self.artwork_path = Path(artwork_path)
        self._owns_source_registry = source_registry is None
        self.source_registry = source_registry or ArtworkSourceRegistry()
        self.width = output_width or self.project.settings.width
        self.height = output_height or self.project.settings.height
        self.fps = self.project.settings.fps
        self.frame_count = self.project.settings.duration_frames
        self.prepared_plan: PreparedRenderPlan | None = None
        self.execution_mode = "legacy"

        semantic = project_as_semantic(self.project)
        capabilities = build_studio_capability_registry()
        self.trigger_compilation: TriggerCompilation = compile_timeline_triggers(
            self.project,
            capabilities,
        )
        semantic = replace(semantic, invocations=self.trigger_compilation.invocations)
        visual_invocations = tuple(
            invocation
            for invocation in semantic.invocations
            if invocation.capability_id != "audio.play"
        )
        renderers = build_classic_2d_renderer_registry(
            self.project,
            self.artwork_path,
            resource_base=resource_base,
            sources=self.source_registry,
            extra_renderers=extra_renderers,
        )

        def renderer_available(invocation) -> bool:
            policy = invocation.renderer_policy
            if policy.mode == RendererPolicyMode.AUTOMATIC:
                return bool(renderers.candidates_for(invocation.capability_id))
            for renderer_id in policy.renderer_ids:
                try:
                    renderers.get(renderer_id)
                except KeyError:
                    continue
                return True
            return False

        if all(renderer_available(item) for item in visual_invocations):
            plan = RenderPlanner(
                capabilities,
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
        if self._owns_source_registry:
            self.source_registry.clear()

    def __enter__(self) -> "StudioRenderSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

"""Compatibility adapters that migrate native Artanimate engines behind capabilities."""

from .catalog import effect_capability_id, legacy_capability_catalog
from .classic_2d import (
    ClosedPreparedRenderError,
    PreparedRenderPlan,
    build_classic_2d_renderer_registry,
    build_legacy_capability_registry,
    build_studio_capability_registry,
    prepare_render_plan,
)
from .legacy_project import (
    LegacyInvocationBinding,
    LegacySemanticProject,
    minimal_scene_for_project,
    project_as_semantic,
)
from .semantic_actions import LocalSemanticActionRenderer
from .semantic_compositor import SemanticPlanCompositor

__all__ = [
    "ClosedPreparedRenderError",
    "LegacyInvocationBinding",
    "LegacySemanticProject",
    "PreparedRenderPlan",
    "SemanticPlanCompositor",
    "LocalSemanticActionRenderer",
    "build_studio_capability_registry",
    "build_classic_2d_renderer_registry",
    "build_legacy_capability_registry",
    "effect_capability_id",
    "legacy_capability_catalog",
    "minimal_scene_for_project",
    "prepare_render_plan",
    "project_as_semantic",
]

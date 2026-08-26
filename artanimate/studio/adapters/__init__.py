"""Compatibility adapters that migrate native Artanimate engines behind capabilities."""

from .catalog import effect_capability_id, legacy_capability_catalog
from .legacy_project import (
    LegacyInvocationBinding,
    LegacySemanticProject,
    minimal_scene_for_project,
    project_as_semantic,
)

__all__ = [
    "LegacyInvocationBinding",
    "LegacySemanticProject",
    "effect_capability_id",
    "legacy_capability_catalog",
    "minimal_scene_for_project",
    "project_as_semantic",
]

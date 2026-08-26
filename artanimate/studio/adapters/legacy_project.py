from __future__ import annotations

from dataclasses import dataclass

from ..legacy_semantics import (
    invocation_bindings,
    minimal_scene_for_project as _minimal_scene_for_project,
)
from ..model import StudioProject
from ..semantic import CapabilityInvocation, SemanticScene


@dataclass(frozen=True, slots=True)
class LegacyInvocationBinding:
    invocation_id: str
    track_id: str
    clip_id: str
    role: str


@dataclass(frozen=True, slots=True)
class LegacySemanticProject:
    """Semantic document plus temporary timeline bindings for legacy clips."""

    project_id: str
    source_schema_version: int
    scene: SemanticScene
    invocations: tuple[CapabilityInvocation, ...]
    bindings: tuple[LegacyInvocationBinding, ...]

    def __post_init__(self) -> None:
        invocation_ids = tuple(item.invocation_id for item in self.invocations)
        binding_ids = tuple(item.invocation_id for item in self.bindings)
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("Le document sémantique contient une invocation dupliquée")
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("Le document sémantique contient un binding dupliqué")
        if not set(binding_ids) <= set(invocation_ids):
            raise ValueError("Un binding de timeline référence une invocation absente")

    def binding_for(self, invocation_id: str) -> LegacyInvocationBinding:
        try:
            return next(
                item for item in self.bindings if item.invocation_id == invocation_id
            )
        except StopIteration as exc:
            raise KeyError(f"Binding legacy introuvable : {invocation_id}") from exc


def minimal_scene_for_project(project: StudioProject) -> SemanticScene:
    project.validate()
    return _minimal_scene_for_project(project)


def project_as_semantic(project: StudioProject) -> LegacySemanticProject:
    """Read the persisted V2 intent without mutating or reinterpreting it."""
    project.validate()
    if project.scene is None:
        raise ValueError("Le projet Studio ne contient aucune scène sémantique")
    bindings = tuple(
        LegacyInvocationBinding(invocation_id, track_id, clip_id, role)
        for invocation_id, track_id, clip_id, role in invocation_bindings(project)
    )
    return LegacySemanticProject(
        project.project_id,
        project.schema_version,
        project.scene,
        project.invocations,
        bindings,
    )

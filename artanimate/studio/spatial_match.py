from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .model import ClipKind, Easing, StudioProject, Transition, TransitionKind
from .transition_matching import SpatialMatchSolution


@dataclass(frozen=True, slots=True)
class SpatialMatchSettings:
    solution: SpatialMatchSolution
    easing: Easing = Easing.EASE_IN_OUT

    def validate(self) -> SpatialMatchSettings:
        self.solution.validate()
        if not isinstance(self.easing, Easing):
            raise TypeError("L’interpolation du raccord spatial doit être un Easing")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "easing": self.easing.value,
            "solution": self.solution.to_dict(),
        }

    @classmethod
    def from_transition(cls, transition: Transition) -> SpatialMatchSettings:
        if transition.kind != TransitionKind.SPATIAL_MATCH:
            raise ValueError("Les réglages demandés ne concernent pas un raccord spatial")
        values = transition.parameters or {}
        if not isinstance(values, dict):
            raise TypeError("Les réglages du raccord spatial doivent être un objet JSON")
        unknown = sorted(set(values) - {"easing", "solution"})
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans les réglages du raccord spatial : "
                + ", ".join(unknown)
            )
        try:
            easing = Easing(values.get("easing", Easing.EASE_IN_OUT.value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Interpolation de raccord spatial inconnue") from exc
        return cls(
            SpatialMatchSolution.from_dict(values.get("solution")),
            easing,
        ).validate()


def validate_spatial_match_transition(
    project: StudioProject,
    transition: Transition,
) -> SpatialMatchSettings:
    from .transitions import transition_clip_pair

    settings = SpatialMatchSettings.from_transition(transition)
    pair = transition_clip_pair(project, transition)
    if pair.from_clip.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
        raise ValueError("Le départ d’un raccord spatial doit être un plan d’œuvre")
    if pair.to_clip.kind != ClipKind.STILL:
        raise ValueError("Cette slice du raccord spatial exige une photo réelle")
    return settings


def add_spatial_match(
    project: StudioProject,
    first_clip_id: str,
    second_clip_id: str,
    solution: SpatialMatchSolution,
    *,
    duration_frames: int | None = None,
    easing: Easing = Easing.EASE_IN_OUT,
) -> tuple[StudioProject, Transition]:
    from .transitions import add_dissolve, validate_project_transitions

    solution.validate()
    dissolved, dissolve = add_dissolve(
        project,
        first_clip_id,
        second_clip_id,
        duration_frames=duration_frames,
        easing=easing,
    )
    spatial = replace(
        dissolve,
        kind=TransitionKind.SPATIAL_MATCH,
        parameters=SpatialMatchSettings(solution, easing).to_dict(),
    ).validate()
    candidate = replace(
        dissolved,
        transitions=tuple(
            spatial if item.transition_id == dissolve.transition_id else item
            for item in dissolved.transitions
        ),
    )
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate(), spatial

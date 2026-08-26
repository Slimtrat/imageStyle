from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .common import EMPTY_JSON, FrozenJsonObject, confidence, identifier


@dataclass(frozen=True, slots=True)
class Affordance:
    """One evidence-backed property that capabilities may require."""

    affordance_id: str
    confidence: float = 1.0
    parameters: FrozenJsonObject = field(default_factory=FrozenJsonObject)
    source: str = "manual"

    def __post_init__(self) -> None:
        identifier(self.affordance_id, "affordance.affordance_id")
        confidence(self.confidence, "affordance.confidence")
        identifier(self.source, "affordance.source")
        if not isinstance(self.parameters, FrozenJsonObject):
            object.__setattr__(
                self,
                "parameters",
                FrozenJsonObject(self.parameters, where="affordance.parameters"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affordance_id": self.affordance_id,
            "confidence": self.confidence,
            "parameters": self.parameters.to_dict(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "Affordance":
        if not isinstance(values, Mapping):
            raise TypeError("Une affordance doit être un objet JSON")
        unknown = set(values) - {
            "affordance_id",
            "confidence",
            "parameters",
            "source",
        }
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans Affordance : " + ", ".join(sorted(unknown))
            )
        return cls(
            affordance_id=values["affordance_id"],
            confidence=values.get("confidence", 1.0),
            parameters=FrozenJsonObject(
                values.get("parameters", EMPTY_JSON),
                where="affordance.parameters",
            ),
            source=values.get("source", "manual"),
        )


@dataclass(frozen=True, slots=True)
class AffordanceSet:
    """Validated immutable lookup with deterministic merge semantics."""

    values: tuple[Affordance, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.values, key=lambda item: item.affordance_id))
        identifiers = tuple(item.affordance_id for item in ordered)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Un objet ne peut pas contenir deux fois la même affordance")
        object.__setattr__(self, "values", ordered)

    def __contains__(self, affordance_id: str) -> bool:
        return any(item.affordance_id == affordance_id for item in self.values)

    def get(self, affordance_id: str) -> Affordance | None:
        return next(
            (item for item in self.values if item.affordance_id == affordance_id),
            None,
        )

    @classmethod
    def merge(cls, *groups: Iterable[Affordance]) -> "AffordanceSet":
        """Keep the strongest evidence for each affordance in a stable order."""
        selected: dict[str, Affordance] = {}
        for group in groups:
            for item in group:
                current = selected.get(item.affordance_id)
                if current is None or item.confidence > current.confidence:
                    selected[item.affordance_id] = item
        return cls(tuple(selected.values()))

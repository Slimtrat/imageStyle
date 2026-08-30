from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .semantic import Bounds, FrozenJsonObject


@dataclass(frozen=True, slots=True)
class SemanticRegionCandidate:
    """A detector-neutral region proposal expressed in canonical artwork space."""

    region_type: str
    label: str
    bounds: Bounds
    confidence: float
    mask: np.ndarray
    metadata: FrozenJsonObject = FrozenJsonObject()

    def validate(self) -> SemanticRegionCandidate:
        Bounds(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("La confiance d’une région doit être comprise entre 0 et 1")
        if self.mask.ndim != 2 or self.mask.size == 0:
            raise ValueError("Le masque d’une région doit être une image 2D non vide")
        return self


@dataclass(frozen=True, slots=True)
class SemanticRegionDetection:
    analyzer_id: str
    analyzer_version: str
    candidates: tuple[SemanticRegionCandidate, ...]
    metadata: FrozenJsonObject = FrozenJsonObject()

    def validate(self) -> SemanticRegionDetection:
        if not self.analyzer_id or not self.analyzer_version:
            raise ValueError("Un détecteur doit déclarer son identité et sa version")
        for candidate in self.candidates:
            candidate.validate()
        return self


class SemanticRegionDetector(Protocol):
    """Port for local CV, segmentation models, or user-assisted analyzers."""

    analyzer_id: str
    analyzer_version: str

    def detect(self, artwork_rgb: np.ndarray) -> SemanticRegionDetection: ...

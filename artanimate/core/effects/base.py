from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from .documentation import ParameterDocumentation, documentation_for


if TYPE_CHECKING:
    from ..config import RenderConfig


class EffectCapability(StrEnum):
    """Independent renderer/UI capabilities an effect can explicitly support."""

    CHROMATIC_SEQUENCE = "chromatic_sequence"
    FALLING_PARTICLES = "falling_particles"


@dataclass(frozen=True, slots=True)
class EffectDescriptor:
    """Stable metadata shared by configuration, UI and documentation."""

    key: str
    selector_label: str
    description: str
    config_fields: tuple[str, ...]
    parameters: tuple[ParameterDocumentation, ...]
    capabilities: frozenset[EffectCapability]

    def supports(self, capability: EffectCapability) -> bool:
        """Report whether this effect supports an independent capability."""
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class EffectContext:
    """Immutable input passed to one effect for one prepared color layer."""

    width: int
    height: int
    seed: int
    config: RenderConfig

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Les dimensions du contexte d’effet doivent être positives")


class AnimationEffect(ABC):
    """Contract implemented by every animation effect.

    Subclasses are deliberately stateless. The factory may therefore create a new
    instance for each renderer without lifecycle concerns. Implementations only
    build a normalized reveal field; scheduling, layer compositing and exact final
    fidelity remain responsibilities of :class:`ArtworkRenderer`.
    """

    key: ClassVar[str]
    config_fields: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[EffectCapability]] = frozenset()

    @classmethod
    def descriptor(cls) -> EffectDescriptor:
        """Return immutable metadata without instantiating the effect."""
        documentation = documentation_for(cls.key)
        return EffectDescriptor(
            key=cls.key,
            selector_label=documentation.selector_label,
            description=documentation.description,
            config_fields=cls.config_fields,
            parameters=documentation.parameters,
            capabilities=cls.capabilities,
        )

    @classmethod
    def supports(cls, capability: EffectCapability) -> bool:
        """Report whether the effect implements an optional capability."""
        return capability in cls.capabilities

    def create_field(self, context: EffectContext) -> np.ndarray:
        """Build and validate the normalized ``[0, 1]`` reveal field.

        The validation lives in the contract so a malformed future effect fails at
        preparation time with a useful message instead of corrupting video frames.
        """
        field = np.asarray(self.build_field(context), dtype=np.float32)
        expected_shape = (context.height, context.width)
        if field.shape != expected_shape:
            raise ValueError(
                f"L’effet {self.key!r} a produit {field.shape}, attendu {expected_shape}"
            )
        if not np.all(np.isfinite(field)):
            raise ValueError(f"L’effet {self.key!r} a produit des valeurs non finies")
        minimum = float(field.min(initial=0.0))
        maximum = float(field.max(initial=1.0))
        if minimum < -1e-5 or maximum > 1.0 + 1e-5:
            raise ValueError(
                f"L’effet {self.key!r} doit produire un champ normalisé, reçu "
                f"[{minimum:.4f}, {maximum:.4f}]"
            )
        return np.clip(field, 0.0, 1.0)

    @abstractmethod
    def build_field(self, context: EffectContext) -> np.ndarray:
        """Return a deterministic reveal-time field with shape ``height × width``."""
        raise NotImplementedError

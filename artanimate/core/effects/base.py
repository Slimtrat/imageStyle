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
    DETECTED_CONTOURS = "detected_contours"
    FALLING_PARTICLES = "falling_particles"
    FRAME_COMPOSITOR = "frame_compositor"
    FRAME_DECORATOR = "frame_decorator"
    STRICT_SEQUENCE = "strict_sequence"
    OUTLINE_FINALE = "outline_finale"


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
    layer_mask: np.ndarray | None = None
    layer_color: tuple[int, int, int] | None = None
    is_outline: bool = False

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Les dimensions du contexte d’effet doivent être positives")
        if self.layer_mask is not None and self.layer_mask.shape != (self.height, self.width):
            raise ValueError("Le masque de couche doit correspondre aux dimensions du contexte")


@dataclass(frozen=True, slots=True)
class FrameCompositionContext:
    """Immutable source data offered to effects that compose a complete frame."""

    source: np.ndarray
    canvas: np.ndarray
    config: RenderConfig
    linear_source: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.source.ndim != 3 or self.source.shape[2] != 3:
            raise ValueError("La source du compositeur doit être une image RGB")
        if self.canvas.shape != self.source.shape:
            raise ValueError("La toile et la source du compositeur doivent avoir la même taille")
        if self.linear_source is not None and self.linear_source.shape != self.source.shape:
            raise ValueError("La source linéaire doit avoir la même taille que la source RGB")


@dataclass(frozen=True, slots=True)
class LayerFrameState:
    """State of one analyzed layer at the current animation instant."""

    mask: np.ndarray
    field: np.ndarray
    progress: float
    color: tuple[int, int, int]
    is_outline: bool


@dataclass(frozen=True, slots=True)
class FrameDecorationContext:
    """Read-only data exposed to effects that draw a physical light or tool."""

    source: np.ndarray
    config: RenderConfig
    progress: float
    layers: tuple[LayerFrameState, ...]
    presentation: str = "2d"

    def __post_init__(self) -> None:
        if self.presentation not in {"2d", "texture"}:
            raise ValueError("La présentation doit être '2d' ou 'texture'")


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

    def create_frame(
        self,
        context: FrameCompositionContext,
        progress: float,
    ) -> np.ndarray | None:
        """Compose and validate an optional whole-image frame."""
        frame = self.compose_frame(context, float(np.clip(progress, 0.0, 1.0)))
        if frame is None:
            return None
        result = np.asarray(frame)
        if result.shape != context.source.shape:
            raise ValueError(
                f"L’effet {self.key!r} a composé {result.shape}, "
                f"attendu {context.source.shape}"
            )
        if result.dtype != np.uint8:
            raise ValueError(f"L’effet {self.key!r} doit composer des pixels RGB uint8")
        return result

    def compose_frame(
        self,
        context: FrameCompositionContext,
        progress: float,
    ) -> np.ndarray | None:
        """Optionally replace the generic layer renderer for the complete frame."""
        return None

    def create_decoration(
        self,
        frame: np.ndarray,
        context: FrameDecorationContext,
    ) -> np.ndarray:
        """Decorate a generic layer frame and validate the public contract."""
        result = np.asarray(self.decorate_frame(frame, context))
        if result.shape != context.source.shape:
            raise ValueError(
                f"L’effet {self.key!r} a décoré {result.shape}, "
                f"attendu {context.source.shape}"
            )
        if result.dtype != np.uint8:
            raise ValueError(f"L’effet {self.key!r} doit décorer des pixels RGB uint8")
        return result

    def decorate_frame(
        self,
        frame: np.ndarray,
        context: FrameDecorationContext,
    ) -> np.ndarray:
        """Optionally add a transient halo or physical tool to a layer frame."""
        return frame

    @abstractmethod
    def build_field(self, context: EffectContext) -> np.ndarray:
        """Return a deterministic reveal-time field with shape ``height × width``."""
        raise NotImplementedError

from __future__ import annotations

from typing import TypeVar

from .base import AnimationEffect, EffectCapability, EffectDescriptor


EffectType = TypeVar("EffectType", bound=type[AnimationEffect])
_REGISTRY: dict[str, type[AnimationEffect]] = {}


def register_effect(effect_type: EffectType) -> EffectType:
    """Register an effect class and enforce the public contract immediately.

    The decorator keeps each implementation self-contained. Importing its module
    is sufficient to make it available to configuration, the renderer and the UI.
    """
    if not issubclass(effect_type, AnimationEffect):
        raise TypeError("Un effet doit hériter de AnimationEffect")
    key = getattr(effect_type, "key", "").strip()
    if not key or not key.isidentifier() or key.lower() != key:
        raise ValueError("La clé d’un effet doit être un identifiant Python en minuscules")
    descriptor = effect_type.descriptor()
    documented_fields = tuple(parameter.key for parameter in descriptor.parameters)
    if documented_fields != effect_type.config_fields:
        raise ValueError(
            f"L’effet {key!r} déclare {effect_type.config_fields}, mais sa documentation "
            f"décrit {documented_fields}"
        )
    if (
        effect_type.supports(EffectCapability.TARGETED_PARTICLES)
        and effect_type.build_targeted_particles is AnimationEffect.build_targeted_particles
    ):
        raise ValueError(
            f"L’effet {key!r} déclare des pigments ciblés sans construire leur banque"
        )
    if (
        effect_type.supports(EffectCapability.FRAME_COMPOSITOR)
        and effect_type.compose_frame is AnimationEffect.compose_frame
    ):
        raise ValueError(
            f"L’effet {key!r} déclare un compositeur sans implémenter compose_frame"
        )
    if (
        effect_type.supports(EffectCapability.FRAME_DECORATOR)
        and effect_type.decorate_frame is AnimationEffect.decorate_frame
    ):
        raise ValueError(
            f"L’effet {key!r} déclare une décoration sans implémenter decorate_frame"
        )
    previous = _REGISTRY.get(key)
    if previous is not None and previous is not effect_type:
        raise ValueError(f"Un effet est déjà enregistré sous la clé {key!r}")
    _REGISTRY[key] = effect_type
    return effect_type


def create_effect(key: str) -> AnimationEffect:
    """Create the registered effect identified by ``key``."""
    try:
        effect_type = _REGISTRY[key]
    except KeyError as exc:
        available = ", ".join(effect_keys()) or "aucun"
        raise ValueError(f"Effet inconnu {key!r}. Effets disponibles : {available}") from exc
    return effect_type()


def effect_keys() -> tuple[str, ...]:
    """Return registered keys in deterministic UI/CLI order."""
    return tuple(_REGISTRY)


def effect_descriptors() -> tuple[EffectDescriptor, ...]:
    """Return metadata for every registered effect."""
    return tuple(effect_type.descriptor() for effect_type in _REGISTRY.values())

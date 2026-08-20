from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext
from .factory import register_effect
from .noise import fractal_noise, normalize_reveal_field, normalized_coordinates, value_noise


def sand_field(width: int, height: int, turbulence: float, seed: int) -> np.ndarray:
    """Build a top-to-bottom settling field disturbed by organic noise."""
    _, y = normalized_coordinates(width, height)
    organic = (fractal_noise(width, height, seed) - 0.5) * turbulence
    micro_grain = (value_noise(width, height, seed + 4099, scale=4.0) - 0.5) * 0.045
    field = (1.0 - y) + organic + micro_grain
    return normalize_reveal_field(field)


@register_effect
class SandEffect(AnimationEffect):
    """Reveal colors as grains that fall and settle into their final shapes."""

    key = "sand"
    config_fields = ("grain_density", "grain_size", "turbulence")
    capabilities = frozenset(
        {EffectCapability.CHROMATIC_SEQUENCE, EffectCapability.FALLING_PARTICLES}
    )

    def build_field(self, context: EffectContext) -> np.ndarray:
        return sand_field(
            context.width,
            context.height,
            context.config.turbulence,
            context.seed,
        )

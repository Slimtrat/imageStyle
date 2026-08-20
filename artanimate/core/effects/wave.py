from __future__ import annotations

import math

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext
from .factory import register_effect
from .noise import fractal_noise, normalize_reveal_field, normalized_coordinates


def wave_field(
    width: int,
    height: int,
    direction: str,
    amplitude: float,
    frequency: float,
    turbulence: float,
    seed: int,
) -> np.ndarray:
    """Build a directional, oscillating reveal field normalized to ``[0, 1]``."""
    x, y = normalized_coordinates(width, height)
    if direction == "right":
        base, across = 1.0 - x, y
    elif direction == "top":
        base, across = y, x
    elif direction == "bottom":
        base, across = 1.0 - y, x
    elif direction == "diagonal":
        base, across = (x + y) * 0.5, (x - y) * 0.5
    elif direction == "radial":
        dx, dy = x - 0.5, y - 0.5
        base = np.sqrt(dx * dx + dy * dy) / math.sqrt(0.5)
        across = np.arctan2(dy, dx) / (2.0 * math.pi)
    else:
        base, across = x, y

    oscillation = np.sin(across * frequency * 2.0 * math.pi + base * math.pi) * amplitude
    noise = (fractal_noise(width, height, seed) - 0.5) * turbulence
    field = base + oscillation + noise
    return normalize_reveal_field(field)


@register_effect
class WaveEffect(AnimationEffect):
    """Reveal colors behind a fluid directional front."""

    key = "wave"
    config_fields = (
        "direction",
        "wave_amplitude",
        "wave_frequency",
        "turbulence",
        "soft_edge",
    )
    capabilities = frozenset({EffectCapability.CHROMATIC_SEQUENCE})

    def build_field(self, context: EffectContext) -> np.ndarray:
        return wave_field(
            context.width,
            context.height,
            context.config.direction,
            context.config.wave_amplitude,
            context.config.wave_frequency,
            context.config.turbulence,
            context.seed,
        )

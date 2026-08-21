from __future__ import annotations

import numpy as np

from .base import (
    AnimationEffect,
    EffectCapability,
    EffectContext,
    TargetedParticleBank,
    TargetedParticleContext,
)
from .factory import register_effect
from .noise import fractal_noise, normalize_reveal_field, normalized_coordinates, value_noise


PIGMENT_SWEEP_DIRECTIONS = ("left", "right", "top", "bottom")


def pigment_sweep_field(
    width: int,
    height: int,
    direction: str,
    turbulence: float,
    seed: int,
) -> np.ndarray:
    """Return one organic, direction-aware settlement field for the whole artwork.

    Unlike layer effects, Pigment Sweep traverses the complete foreground once.
    Broad noise shapes the visible mass while fine noise prevents a mechanical
    ruler-straight edge. The field remains deterministic for a given seed.
    """
    if direction not in PIGMENT_SWEEP_DIRECTIONS:
        raise ValueError(
            "La direction Pigment Sweep doit être : "
            + ", ".join(PIGMENT_SWEEP_DIRECTIONS)
        )
    x, y = normalized_coordinates(width, height)
    if direction == "right":
        base, across = 1.0 - x, y
    elif direction == "top":
        base, across = y, x
    elif direction == "bottom":
        base, across = 1.0 - y, x
    else:
        base, across = x, y

    strength = float(np.clip(turbulence, 0.0, 0.45))
    broad = (fractal_noise(width, height, seed) - 0.5) * strength
    folds = np.sin(across * np.pi * 5.0 + broad * 4.0) * strength * 0.10
    grain = (value_noise(width, height, seed + 6151, scale=7.0) - 0.5) * 0.018
    return normalize_reveal_field(base + broad + folds + grain, margin=0.055)


def targeted_particle_position(
    origin_x: np.ndarray,
    origin_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    overshoot_x: np.ndarray,
    overshoot_y: np.ndarray,
    curl_x: np.ndarray,
    curl_y: np.ndarray,
    phase: np.ndarray,
    travel: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate targeted pigment trajectories in the artwork plane.

    The first 78% is an eased flight toward a point just beyond the destination.
    The remaining time is a damped return that ends exactly on the target. Arrays
    are used so the 2D renderer and Studio-data tests can evaluate whole banks at
    once without per-grain Python state.
    """
    t = np.clip(np.asarray(travel, dtype=np.float32), 0.0, 1.0)
    approach = np.clip(t / 0.78, 0.0, 1.0)
    eased = approach**3 * (approach * (approach * 6.0 - 15.0) + 10.0)
    curl_wave = (
        np.sin(np.pi * eased)
        * np.sin(np.asarray(phase, dtype=np.float32) + eased * np.pi * 2.0)
    )
    approach_x = origin_x + (target_x + overshoot_x - origin_x) * eased + curl_x * curl_wave
    approach_y = origin_y + (target_y + overshoot_y - origin_y) * eased + curl_y * curl_wave

    rebound = np.clip((t - 0.78) / 0.22, 0.0, 1.0)
    residual = (1.0 - rebound) ** 2 * np.cos(rebound * np.pi * 1.25)
    rebound_curl = (
        np.sin(np.pi * rebound)
        * (1.0 - rebound)
        * np.sin(np.asarray(phase, dtype=np.float32) + rebound * np.pi)
        * 0.18
    )
    rebound_x = target_x + overshoot_x * residual + curl_x * rebound_curl
    rebound_y = target_y + overshoot_y * residual + curl_y * rebound_curl
    return (
        np.where(t < 0.78, approach_x, rebound_x).astype(np.float32),
        np.where(t < 0.78, approach_y, rebound_y).astype(np.float32),
    )


@register_effect
class PigmentSweepEffect(AnimationEffect):
    """Reconstruct the complete artwork with targeted, rebounding pigments."""

    key = "pigment_sweep"
    config_fields = (
        "direction",
        "sweep_density",
        "sweep_grain_size",
        "sweep_turbulence",
        "sweep_rebound",
    )
    capabilities = frozenset(
        {
            EffectCapability.GLOBAL_REVEAL,
            EffectCapability.TARGETED_PARTICLES,
        }
    )

    def build_targeted_particles(
        self,
        context: TargetedParticleContext,
    ) -> TargetedParticleBank | None:
        """Tie every visible grain to one exact source pixel and path."""
        coordinates = np.argwhere(context.mask)
        if len(coordinates) == 0:
            return None
        desired = int(round(len(coordinates) * context.config.sweep_density))
        desired = min(len(coordinates), max(320, min(7600, desired)))
        rng = np.random.default_rng(context.seed + 15485863)
        chosen = rng.choice(len(coordinates), size=desired, replace=False)
        targets = coordinates[chosen]
        target_y = targets[:, 0].astype(np.float32)
        target_x = targets[:, 1].astype(np.float32)
        settle = context.field[targets[:, 0], targets[:, 1]].astype(np.float32)
        phase = rng.uniform(0.0, np.pi * 2.0, desired).astype(np.float32)
        short_side = float(max(1, min(context.width, context.height)))
        margin = float(max(context.width, context.height)) * 0.11 + 4.0
        turbulence = float(context.config.sweep_turbulence)
        lateral = np.clip(
            rng.normal(0.0, max(1.5, turbulence * short_side * 0.34), desired),
            -short_side * 0.22,
            short_side * 0.22,
        ).astype(np.float32)
        curl = rng.normal(
            0.0, max(0.8, turbulence * short_side * 0.14), desired
        ).astype(np.float32)
        lead = rng.uniform(0.0, margin * 0.65, desired).astype(np.float32)
        rebound = (
            float(context.config.sweep_rebound)
            * short_side
            * rng.uniform(0.22, 0.42, desired)
        ).astype(np.float32)
        origin_x = target_x.copy()
        origin_y = target_y.copy()
        overshoot_x = np.zeros(desired, dtype=np.float32)
        overshoot_y = np.zeros(desired, dtype=np.float32)
        curl_x = np.zeros(desired, dtype=np.float32)
        curl_y = np.zeros(desired, dtype=np.float32)
        direction = context.config.direction
        if direction == "right":
            origin_x[:] = context.width + margin + lead
            origin_y += lateral
            overshoot_x[:] = -rebound
            curl_y[:] = curl
        elif direction == "top":
            origin_x += lateral
            origin_y[:] = -margin - lead
            overshoot_y[:] = rebound
            curl_x[:] = curl
        elif direction == "bottom":
            origin_x += lateral
            origin_y[:] = context.height + margin + lead
            overshoot_y[:] = -rebound
            curl_x[:] = curl
        else:
            origin_x[:] = -margin - lead
            origin_y += lateral
            overshoot_x[:] = rebound
            curl_y[:] = curl
        return TargetedParticleBank(
            target_x=target_x,
            target_y=target_y,
            settle=settle,
            flight=rng.uniform(0.19, 0.34, desired).astype(np.float32),
            sway=lateral,
            phase=phase,
            colors=context.source[targets[:, 0], targets[:, 1]],
            origin_x=origin_x,
            origin_y=origin_y,
            overshoot_x=overshoot_x,
            overshoot_y=overshoot_y,
            curl_x=curl_x,
            curl_y=curl_y,
            brush_size=float(context.config.sweep_grain_size),
        )

    def build_field(self, context: EffectContext) -> np.ndarray:
        return pigment_sweep_field(
            context.width,
            context.height,
            context.config.direction,
            context.config.sweep_turbulence,
            context.seed,
        )

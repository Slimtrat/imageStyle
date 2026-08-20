from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameCompositionContext
from .factory import register_effect
from .light_tools import blend_glow, gaussian_band, horizontal_field
from .reveal import reveal_opacity


@register_effect
class VerticalHaloEffect(AnimationEffect):
    """Reveal the whole artwork strictly behind one moving vertical light curtain."""

    key = "vertical_halo"
    config_fields = ("halo_direction", "halo_width", "halo_intensity", "soft_edge")
    capabilities = frozenset({EffectCapability.FRAME_COMPOSITOR})

    def build_field(self, context: EffectContext) -> np.ndarray:
        field = horizontal_field(context.width, context.height)
        return 1.0 - field if context.config.halo_direction == "right" else field

    def compose_frame(
        self, context: FrameCompositionContext, progress: float
    ) -> np.ndarray:
        if progress <= 0.0:
            return context.canvas.copy()
        if progress >= 1.0:
            return context.source.copy()
        height, width = context.source.shape[:2]
        field = horizontal_field(width, height)
        if context.config.halo_direction == "right":
            field = 1.0 - field
        mask = np.ones((height, width), dtype=bool)
        opacity = reveal_opacity(mask, field, progress, context.config.soft_edge)
        frame = context.canvas.copy()
        active = opacity > 0.0
        if np.any(active):
            alpha = opacity[active, None]
            foreground = context.source[active].astype(np.float32)
            background = frame[active].astype(np.float32)
            frame[active] = np.rint(
                background * (1.0 - alpha) + foreground * alpha
            ).astype(np.uint8)

        band = gaussian_band(field, progress, context.config.halo_width)
        trailing = np.clip(
            (progress - field + context.config.soft_edge)
            / max(context.config.soft_edge * 2.0, 1e-5),
            0.0,
            1.0,
        )
        strength = band * trailing * 0.62 * context.config.halo_intensity
        return blend_glow(frame, strength, (255, 231, 196))

from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .factory import register_effect
from .light_tools import (
    blend_glow,
    boundary_mask,
    expand_mask,
    feather_mask,
    gaussian_band,
    horizontal_field,
)


@register_effect
class ContourLaserEffect(AnimationEffect):
    """Scan detected shape boundaries from left to right with a focused laser."""

    key = "contour_laser"
    config_fields = ("laser_width", "laser_intensity", "soft_edge")
    capabilities = frozenset(
        {EffectCapability.CHROMATIC_SEQUENCE, EffectCapability.FRAME_DECORATOR}
    )

    def build_field(self, context: EffectContext) -> np.ndarray:
        return horizontal_field(context.width, context.height)

    def decorate_frame(
        self, frame: np.ndarray, context: FrameDecorationContext
    ) -> np.ndarray:
        result = frame
        radius = max(2, min(6, round(context.source.shape[1] / 260)))
        for state in context.layers:
            if state.progress <= 0.0 or state.progress >= 1.0:
                continue
            contour = boundary_mask(state.mask)
            aura = feather_mask(expand_mask(contour, 1), radius)
            band = gaussian_band(state.field, state.progress, context.config.laser_width)
            strength = band * aura * context.config.laser_intensity
            result = blend_glow(result, strength, (80, 225, 255))
        return result

from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .factory import register_effect
from .light_tools import blend_glow, expand_mask, gaussian_band, horizontal_field


@register_effect
class ScreenPrintLaserEffect(AnimationEffect):
    """Print color layers first, then reconstruct only the detected black outline."""

    key = "screenprint_laser"
    config_fields = (
        "screenprint_width",
        "halo_intensity",
        "laser_width",
        "laser_intensity",
        "soft_edge",
    )
    capabilities = frozenset(
        {
            EffectCapability.CHROMATIC_SEQUENCE,
            EffectCapability.FRAME_DECORATOR,
            EffectCapability.STRICT_SEQUENCE,
            EffectCapability.OUTLINE_FINALE,
        }
    )

    def build_field(self, context: EffectContext) -> np.ndarray:
        return horizontal_field(context.width, context.height)

    def decorate_frame(
        self, frame: np.ndarray, context: FrameDecorationContext
    ) -> np.ndarray:
        result = frame
        for state in context.layers:
            if state.progress <= 0.0 or state.progress >= 1.0:
                continue
            if state.is_outline:
                band = gaussian_band(
                    state.field, state.progress, context.config.laser_width
                )
                aura = expand_mask(state.mask, 2)
                strength = band * aura * context.config.laser_intensity
                result = blend_glow(result, context.source, strength, (105, 235, 255))
            else:
                band = gaussian_band(
                    state.field, state.progress, context.config.screenprint_width
                )
                strength = band * state.mask * context.config.halo_intensity * 0.72
                result = blend_glow(result, context.source, strength, state.color)
        return result

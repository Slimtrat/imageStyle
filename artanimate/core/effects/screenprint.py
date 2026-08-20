from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .factory import register_effect
from .light_tools import blend_glow, gaussian_band, horizontal_field


@register_effect
class ScreenPrintEffect(AnimationEffect):
    """Lay down every analyzed color with a deliberate screen-printing pass."""

    key = "screenprint"
    config_fields = ("screenprint_width", "halo_intensity", "soft_edge")
    capabilities = frozenset(
        {
            EffectCapability.CHROMATIC_SEQUENCE,
            EffectCapability.FRAME_DECORATOR,
            EffectCapability.STRICT_SEQUENCE,
        }
    )

    def build_field(self, context: EffectContext) -> np.ndarray:
        return horizontal_field(context.width, context.height)

    def decorate_frame(
        self, frame: np.ndarray, context: FrameDecorationContext
    ) -> np.ndarray:
        result = frame
        for state in context.layers:
            if state.is_outline or state.progress <= 0.0 or state.progress >= 1.0:
                continue
            band = gaussian_band(
                state.field, state.progress, context.config.screenprint_width
            )
            strength = band * state.mask * context.config.halo_intensity * 0.72
            result = blend_glow(result, context.source, strength, state.color)
        return result

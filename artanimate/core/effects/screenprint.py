from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .factory import register_effect
from .light_tools import (
    blend_glow,
    blend_ink_edges,
    gaussian_band,
    horizontal_field,
)


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
        radius = max(4, min(10, round(context.source.shape[1] / 80)))
        outline = next((state for state in context.layers if state.is_outline), None)
        for state in context.layers:
            if state.is_outline or state.progress <= 0.0:
                continue
            result = blend_ink_edges(
                result,
                state.mask,
                state.field,
                state.progress,
                context.config.soft_edge,
                state.color,
                radius,
                outline.mask if outline is not None else None,
                outline.field if outline is not None else None,
                outline.progress if outline is not None else 0.0,
            )
            if state.progress >= 1.0:
                continue
            band = gaussian_band(
                state.field, state.progress, context.config.screenprint_width
            )
            strength = band * 0.42 * context.config.halo_intensity
            result = blend_glow(result, strength, state.color)
        return result

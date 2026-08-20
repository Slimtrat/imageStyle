from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .contour_laser import decorate_laser_trace
from .contour_paths import contour_path_field
from .factory import register_effect
from .light_tools import (
    blend_glow,
    blend_ink_edges,
    gaussian_band,
    horizontal_field,
)


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
        if context.is_outline and context.layer_mask is not None:
            return contour_path_field(context.layer_mask)
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

        if outline is not None and 0.0 < outline.progress < 1.0:
            result = decorate_laser_trace(
                result,
                outline.mask,
                outline.field,
                outline.progress,
                context.config.laser_width,
                context.config.laser_intensity,
            )
        return result

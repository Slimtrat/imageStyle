from __future__ import annotations

import numpy as np

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .contour_paths import contour_path_field
from .factory import register_effect
from .light_tools import blend_glow, expand_mask, feather_mask, gaussian_band


def decorate_laser_trace(
    frame: np.ndarray,
    mask: np.ndarray,
    field: np.ndarray,
    progress: float,
    width: float,
    intensity: float,
) -> np.ndarray:
    """Render a short hot cutting trail only around the current path position."""
    radius = max(3, min(9, round(frame.shape[1] / 180)))
    aura = feather_mask(expand_mask(mask, 1), radius)
    trail = gaussian_band(field, progress, width) * aura * intensity
    result = blend_glow(frame, trail * 0.62, (255, 72, 24))
    core = gaussian_band(field, progress, max(width * 0.16, 0.0015))
    return blend_glow(result, core * aura * intensity, (255, 244, 190))


@register_effect
class ContourLaserEffect(AnimationEffect):
    """Follow detected shape loops with a focused plotter-style laser cutter."""

    key = "contour_laser"
    config_fields = ("laser_width", "laser_intensity", "soft_edge")
    capabilities = frozenset(
        {
            EffectCapability.DETECTED_CONTOURS,
            EffectCapability.FRAME_DECORATOR,
        }
    )

    def build_field(self, context: EffectContext) -> np.ndarray:
        if context.layer_mask is None:
            return np.ones((context.height, context.width), dtype=np.float32)
        return contour_path_field(context.layer_mask)

    def decorate_frame(
        self, frame: np.ndarray, context: FrameDecorationContext
    ) -> np.ndarray:
        active = next(
            (state for state in context.layers if 0.0 < state.progress < 1.0),
            None,
        )
        if active is None:
            return frame
        return decorate_laser_trace(
            frame,
            active.mask,
            active.field,
            active.progress,
            context.config.laser_width,
            context.config.laser_intensity,
        )

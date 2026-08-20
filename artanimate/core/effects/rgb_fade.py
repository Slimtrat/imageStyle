from __future__ import annotations

import numpy as np

from ..quality import ease_in_out, linear_to_srgb, srgb_to_linear
from .base import (
    AnimationEffect,
    EffectCapability,
    EffectContext,
    FrameCompositionContext,
)
from .factory import register_effect


def rgb_channel_weights(progress: float, mode: str) -> np.ndarray:
    """Return linear-light RGB exposure weights for the selected build mode."""
    value = float(np.clip(progress, 0.0, 1.0))
    if mode == "together":
        weight = ease_in_out(value)
        return np.full(3, weight, dtype=np.float32)
    if mode != "channels":
        raise ValueError(f"Mode de fondu RGB inconnu : {mode}")

    # Each channel owns half of the timeline and overlaps the following channel.
    # The result reads clearly as R → G → B without three disconnected flashes.
    starts = (0.0, 0.25, 0.50)
    return np.asarray(
        [ease_in_out((value - start) / 0.50) for start in starts],
        dtype=np.float32,
    )


@register_effect
class RgbFadeEffect(AnimationEffect):
    """Raise the source exposure from black, together or channel by channel."""

    key = "rgb_fade"
    config_fields = ("rgb_mode",)
    capabilities = frozenset({EffectCapability.FRAME_COMPOSITOR})

    def build_field(self, context: EffectContext) -> np.ndarray:
        # A compositor still fulfils the field contract so tooling can inspect all
        # registered effects uniformly. The renderer skips this unused allocation.
        return np.zeros((context.height, context.width), dtype=np.float32)

    def compose_frame(
        self,
        context: FrameCompositionContext,
        progress: float,
    ) -> np.ndarray:
        if progress <= 0.0:
            return np.zeros_like(context.source)
        if progress >= 1.0:
            return context.source.copy()
        weights = rgb_channel_weights(progress, context.config.rgb_mode)
        linear_source = (
            context.linear_source
            if context.linear_source is not None
            else srgb_to_linear(context.source)
        )
        return linear_to_srgb(linear_source * weights[None, None, :])

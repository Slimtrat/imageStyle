from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from .base import AnimationEffect, EffectCapability, EffectContext, FrameDecorationContext
from .factory import register_effect
from .noise import fractal_noise


def paint_drop_target(mask: np.ndarray) -> tuple[int, int]:
    """Return a real mask pixel nearest the visual centre of one paint family."""
    coordinates = np.argwhere(mask)
    if not len(coordinates):
        height, width = mask.shape
        return width // 2, height // 2
    centre_y, centre_x = coordinates.mean(axis=0)
    scale_y = max(1.0, float(mask.shape[0]))
    scale_x = max(1.0, float(mask.shape[1]))
    distance = (
        ((coordinates[:, 0] - centre_y) / scale_y) ** 2
        + ((coordinates[:, 1] - centre_x) / scale_x) ** 2
    )
    y, x = coordinates[int(np.argmin(distance))]
    return int(x), int(y)


def paint_drop_field(
    width: int,
    height: int,
    mask: np.ndarray | None,
    fall_ratio: float,
    flow: float,
    seed: int,
) -> np.ndarray:
    """Delay reveal until impact, then spread organically from the true target."""
    active_mask = (
        np.ones((height, width), dtype=bool)
        if mask is None
        else np.asarray(mask, dtype=bool)
    )
    target_x, target_y = paint_drop_target(active_mask)
    y, x = np.indices((height, width), dtype=np.float32)
    radial = np.sqrt(
        ((x - target_x) / max(1.0, float(width))) ** 2
        + ((y - target_y) / max(1.0, float(height))) ** 2
    )
    inside = radial[active_mask]
    if not len(inside):
        return np.ones((height, width), dtype=np.float32)
    radial /= max(float(inside.max(initial=0.0)), 1e-6)
    organic = (fractal_noise(width, height, seed) - 0.5) * 2.0
    spread = radial * np.clip(1.0 + organic * float(flow), 0.35, 1.65)
    maximum = max(float(spread[active_mask].max(initial=0.0)), 1e-6)
    normalized = np.clip(spread / maximum, 0.0, 1.0)
    field = np.ones((height, width), dtype=np.float32)
    landing = float(np.clip(fall_ratio, 0.0, 0.9))
    field[active_mask] = landing + normalized[active_mask] * (1.0 - landing)
    return field


def _mix(
    color: tuple[int, int, int], target: int, amount: float
) -> tuple[int, int, int]:
    return tuple(
        int(round(channel * (1.0 - amount) + target * amount))
        for channel in color
    )


def _draw_paint_drop(
    frame: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    progress: float,
    drop_ratio: float,
    fall_ratio: float,
) -> np.ndarray:
    """Draw one large falling drop and a short impact splash, with no fake tool."""
    height, width = frame.shape[:2]
    target_x, target_y = paint_drop_target(mask)
    diameter = max(12.0, min(width, height) * float(drop_ratio))
    radius = diameter * 0.5
    landing = float(np.clip(fall_ratio, 0.05, 0.9))
    falling = progress < landing
    if falling:
        linear = float(np.clip(progress / landing, 0.0, 1.0))
        eased = linear**3 * (linear * (linear * 6.0 - 15.0) + 10.0)
        drop_y = -radius * 1.8 + (target_y + radius * 0.12) * eased
        impact = 0.0
        alpha = min(1.0, progress / 0.045)
    else:
        drop_y = float(target_y)
        impact = float(np.clip((progress - landing) / 0.28, 0.0, 1.0))
        alpha = max(0.0, 1.0 - impact)
    if alpha <= 0.0:
        return frame

    splash_radius = radius * (1.0 + 4.2 * math.sqrt(impact))
    margin = max(radius * 3.0, splash_radius + radius)
    x0 = max(0, int(math.floor(target_x - margin)))
    x1 = min(width, int(math.ceil(target_x + margin)))
    y1 = min(height, int(math.ceil(max(target_y + margin, drop_y + radius * 2.0))))
    if x1 <= x0 or y1 <= 0:
        return frame

    supersample = 3 if max(width, height) <= 1920 else 2
    overlay = Image.new("RGBA", ((x1 - x0) * supersample, y1 * supersample))
    draw = ImageDraw.Draw(overlay, "RGBA")

    def px(value: float) -> int:
        return int(round(value * supersample))

    local_x = float(target_x - x0)
    opacity = int(round(255 * alpha))
    dark = _mix(color, 12, 0.34)
    light = _mix(color, 255, 0.58)

    if falling:
        velocity = min(1.0, max(0.0, progress / landing))
        tail = radius * (1.25 + velocity * 1.2)
        draw.rounded_rectangle(
            (
                px(local_x - radius * 0.18),
                px(drop_y - tail),
                px(local_x + radius * 0.18),
                px(drop_y - radius * 0.36),
            ),
            radius=max(1, px(radius * 0.16)),
            fill=(*color, int(opacity * 0.52)),
        )
        draw.polygon(
            (
                (px(local_x), px(drop_y - radius * 1.52)),
                (px(local_x - radius * 0.78), px(drop_y - radius * 0.18)),
                (px(local_x + radius * 0.78), px(drop_y - radius * 0.18)),
            ),
            fill=(*color, opacity),
        )
        draw.ellipse(
            (
                px(local_x - radius),
                px(drop_y - radius),
                px(local_x + radius),
                px(drop_y + radius),
            ),
            fill=(*color, opacity),
            outline=(*dark, opacity),
            width=max(1, px(radius * 0.08)),
        )
        highlight = max(1.5, radius * 0.28)
        draw.ellipse(
            (
                px(local_x - radius * 0.46),
                px(drop_y - radius * 0.49),
                px(local_x - radius * 0.46 + highlight),
                px(drop_y - radius * 0.49 + highlight),
            ),
            fill=(*light, int(opacity * 0.88)),
        )
    else:
        ring_alpha = int(opacity * 0.86)
        draw.ellipse(
            (
                px(local_x - splash_radius),
                px(target_y - splash_radius * 0.30),
                px(local_x + splash_radius),
                px(target_y + splash_radius * 0.30),
            ),
            outline=(*light, ring_alpha),
            width=max(1, px(radius * 0.19 * (1.0 - impact * 0.55))),
        )
        for index in range(7):
            angle = -math.pi * 0.92 + index * math.pi * 0.31
            distance = radius * (0.9 + impact * (1.9 + (index % 3) * 0.35))
            dot = radius * max(0.10, 0.27 - impact * 0.15)
            dot_x = local_x + math.cos(angle) * distance
            dot_y = target_y + math.sin(angle) * distance * 0.42
            draw.ellipse(
                (
                    px(dot_x - dot),
                    px(dot_y - dot),
                    px(dot_x + dot),
                    px(dot_y + dot),
                ),
                fill=(*color, int(opacity * 0.80)),
            )

    if supersample > 1:
        overlay = overlay.resize((x1 - x0, y1), Image.Resampling.LANCZOS)
    crop = Image.fromarray(frame[:y1, x0:x1]).convert("RGBA")
    crop.alpha_composite(overlay)
    result = frame.copy()
    result[:y1, x0:x1] = np.asarray(crop.convert("RGB"), dtype=np.uint8)
    return result


@register_effect
class PaintDropEffect(AnimationEffect):
    """Drop one true layer color, then let it expand from its real impact zone."""

    key = "paint_drop"
    config_fields = (
        "paint_drop_size",
        "paint_fall_ratio",
        "paint_flow",
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
        return paint_drop_field(
            context.width,
            context.height,
            context.layer_mask,
            context.config.paint_fall_ratio,
            context.config.paint_flow,
            context.seed,
        )

    def decorate_frame(
        self, frame: np.ndarray, context: FrameDecorationContext
    ) -> np.ndarray:
        if context.presentation != "2d":
            return frame
        active = next(
            (state for state in context.layers if 0.0 < state.progress < 1.0),
            None,
        )
        if active is None:
            return frame
        return _draw_paint_drop(
            frame,
            active.mask,
            active.color,
            active.progress,
            context.config.paint_drop_size,
            context.config.paint_fall_ratio,
        )

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


def _mix(color: tuple[int, int, int], target: int, amount: float) -> tuple[int, int, int]:
    return tuple(
        int(round(channel * (1.0 - amount) + target * amount))
        for channel in color
    )


def _draw_paint_tool(
    frame: np.ndarray,
    mask: np.ndarray,
    color: tuple[int, int, int],
    progress: float,
    brush_ratio: float,
    drop_ratio: float,
    fall_ratio: float,
) -> np.ndarray:
    """Draw a polished transient brush/drop overlay for the flat 2D presentation."""
    height, width = frame.shape[:2]
    target_x, target_y = paint_drop_target(mask)
    brush_width = max(30.0, width * float(brush_ratio))
    half_brush = brush_width * 0.5
    centre_x = float(np.clip(target_x, half_brush + 2.0, width - half_brush - 2.0))
    tip_y = min(height * 0.12, max(height * 0.045, target_y - height * 0.06))
    drop_diameter = max(4.0, min(width, height) * float(drop_ratio))
    if progress < fall_ratio:
        linear = float(np.clip(progress / max(fall_ratio, 1e-6), 0.0, 1.0))
        eased = linear**3 * (linear * (linear * 6.0 - 15.0) + 10.0)
        drop_y = tip_y + (target_y - tip_y) * eased
    else:
        drop_y = float(target_y)

    margin = max(8.0, drop_diameter * 3.0)
    x0 = max(0, int(math.floor(min(centre_x - half_brush, target_x - margin))))
    x1 = min(width, int(math.ceil(max(centre_x + half_brush, target_x + margin))))
    y1 = min(height, int(math.ceil(max(tip_y + margin, drop_y + margin))))
    if x1 <= x0 or y1 <= 0:
        return frame

    supersample = 2 if max(width, height) <= 1920 else 1
    overlay = Image.new("RGBA", ((x1 - x0) * supersample, y1 * supersample))
    draw = ImageDraw.Draw(overlay, "RGBA")

    def px(value: float) -> int:
        return int(round(value * supersample))

    local_centre = centre_x - x0
    local_target = target_x - x0
    ferrule_top = -height * 0.018
    ferrule_bottom = tip_y * 0.47
    bristle_top = ferrule_bottom * 0.78
    fade_in = min(1.0, progress / 0.06)
    fade_out = min(1.0, (1.0 - progress) / 0.12)
    opacity = int(round(255 * fade_in * fade_out))
    if opacity <= 0:
        return frame

    handle_width = brush_width * 0.17
    draw.rounded_rectangle(
        (
            px(local_centre - handle_width / 2),
            px(-height * 0.09),
            px(local_centre + handle_width / 2),
            px(ferrule_top + height * 0.018),
        ),
        radius=px(handle_width * 0.24),
        fill=(112, 61, 32, opacity),
        outline=(176, 113, 65, opacity),
        width=max(1, px(1.0)),
    )
    ferrule_half = brush_width * 0.38
    draw.rounded_rectangle(
        (
            px(local_centre - ferrule_half),
            px(ferrule_top),
            px(local_centre + ferrule_half),
            px(ferrule_bottom),
        ),
        radius=px(max(2.0, brush_width * 0.025)),
        fill=(82, 91, 104, opacity),
        outline=(196, 207, 217, opacity),
        width=max(1, px(1.2)),
    )
    bristle_half_top = brush_width * 0.36
    bristle_half_tip = brush_width * 0.28
    bristle_points = [
        (px(local_centre - bristle_half_top), px(bristle_top)),
        (px(local_centre + bristle_half_top), px(bristle_top)),
        (px(local_centre + bristle_half_tip), px(tip_y)),
        (px(local_centre - bristle_half_tip), px(tip_y)),
    ]
    dark_paint = _mix(color, 12, 0.58)
    draw.polygon(bristle_points, fill=(*dark_paint, opacity))
    for fraction in np.linspace(-0.25, 0.25, 7):
        x_line = local_centre + brush_width * float(fraction)
        draw.line(
            (px(x_line), px(bristle_top), px(x_line * 0.98 + local_centre * 0.02), px(tip_y)),
            fill=(*_mix(color, 255, 0.22), int(opacity * 0.38)),
            width=max(1, px(0.7)),
        )
    draw.line(
        (
            px(local_centre - bristle_half_tip),
            px(tip_y),
            px(local_centre + bristle_half_tip),
            px(tip_y),
        ),
        fill=(*color, opacity),
        width=max(2, px(height * 0.006)),
    )

    if progress < fall_ratio:
        radius = drop_diameter * 0.5
        draw.polygon(
            [
                (px(local_target), px(drop_y - radius * 1.45)),
                (px(local_target - radius * 0.72), px(drop_y - radius * 0.20)),
                (px(local_target + radius * 0.72), px(drop_y - radius * 0.20)),
            ],
            fill=(*color, opacity),
        )
        draw.ellipse(
            (
                px(local_target - radius),
                px(drop_y - radius),
                px(local_target + radius),
                px(drop_y + radius),
            ),
            fill=(*color, opacity),
            outline=(*_mix(color, 12, 0.36), opacity),
            width=max(1, px(0.8)),
        )
        highlight = max(1.0, radius * 0.24)
        draw.ellipse(
            (
                px(local_target - radius * 0.42),
                px(drop_y - radius * 0.48),
                px(local_target - radius * 0.42 + highlight),
                px(drop_y - radius * 0.48 + highlight),
            ),
            fill=(255, 255, 255, int(opacity * 0.62)),
        )
    else:
        fill_progress = (progress - fall_ratio) / max(1.0 - fall_ratio, 1e-6)
        ring_alpha = int(opacity * max(0.0, 1.0 - fill_progress * 2.4) * 0.7)
        if ring_alpha > 0:
            ring = drop_diameter * (1.0 + 4.0 * math.sqrt(fill_progress))
            draw.ellipse(
                (
                    px(local_target - ring),
                    px(target_y - ring * 0.42),
                    px(local_target + ring),
                    px(target_y + ring * 0.42),
                ),
                outline=(*_mix(color, 255, 0.22), ring_alpha),
                width=max(1, px(drop_diameter * 0.16)),
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
        "paint_brush_width",
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
        return _draw_paint_tool(
            frame,
            active.mask,
            active.color,
            active.progress,
            context.config.paint_brush_width,
            context.config.paint_drop_size,
            context.config.paint_fall_ratio,
        )

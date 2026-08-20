from __future__ import annotations

import numpy as np


def horizontal_field(width: int, height: int) -> np.ndarray:
    """Return a stable left-to-right reveal field."""
    return np.broadcast_to(
        np.linspace(0.0, 1.0, width, dtype=np.float32),
        (height, width),
    ).copy()


def gaussian_band(field: np.ndarray, progress: float, width: float) -> np.ndarray:
    """Return a soft luminous band centred on one reveal-time value."""
    sigma = max(float(width), 1e-4)
    return np.exp(-0.5 * ((field - progress) / sigma) ** 2).astype(np.float32)


def boundary_mask(mask: np.ndarray) -> np.ndarray:
    """Extract the inner one-pixel boundary without wrapping image edges."""
    interior = mask.copy()
    interior[1:, :] &= mask[:-1, :]
    interior[:-1, :] &= mask[1:, :]
    interior[:, 1:] &= mask[:, :-1]
    interior[:, :-1] &= mask[:, 1:]
    return mask & ~interior


def expand_mask(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    """Dilate a boolean mask using a small square kernel implemented in NumPy."""
    result = mask.copy()
    height, width = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            source_y0 = max(0, -dy)
            source_y1 = min(height, height - dy)
            source_x0 = max(0, -dx)
            source_x1 = min(width, width - dx)
            target_y0 = source_y0 + dy
            target_y1 = source_y1 + dy
            target_x0 = source_x0 + dx
            target_x1 = source_x1 + dx
            result[target_y0:target_y1, target_x0:target_x1] |= mask[
                source_y0:source_y1, source_x0:source_x1
            ]
    return result


def blend_glow(
    frame: np.ndarray,
    source: np.ndarray,
    strength: np.ndarray,
    color: tuple[int, int, int],
) -> np.ndarray:
    """Blend a bounded additive-looking glow while preserving an RGB uint8 frame."""
    alpha = np.clip(strength.astype(np.float32), 0.0, 0.92)[..., None]
    if not np.any(alpha > 0.001):
        return frame
    tint = np.asarray(color, dtype=np.float32)
    luminous = np.clip(source.astype(np.float32) * 0.38 + tint * 0.78 + 38.0, 0, 255)
    result = frame.astype(np.float32) * (1.0 - alpha) + luminous * alpha
    return np.rint(np.clip(result, 0, 255)).astype(np.uint8)

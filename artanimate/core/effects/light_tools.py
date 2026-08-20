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


def feather_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    """Create a compact anti-aliased aura outside a hard segmentation mask."""
    radius = max(1, int(radius))
    result = mask.astype(np.float32)
    expanded = mask.copy()
    for distance in range(1, radius + 1):
        next_expanded = expand_mask(expanded, 1)
        shell = next_expanded & ~expanded
        weight = float(np.exp(-1.15 * distance))
        result[shell] = np.maximum(result[shell], weight)
        expanded = next_expanded
    return result


def blend_glow(
    frame: np.ndarray,
    strength: np.ndarray,
    color: tuple[int, int, int],
) -> np.ndarray:
    """Project colored light without exposing unrevealed source pixels."""
    alpha = np.clip(strength.astype(np.float32), 0.0, 0.88)[..., None]
    if not np.any(alpha > 0.001):
        return frame
    base = frame.astype(np.float32)
    tint = np.asarray(color, dtype=np.float32)
    luminous = np.clip(base * 0.62 + tint * 0.62 + 28.0, 0, 255)
    result = base * (1.0 - alpha) + luminous * alpha
    return np.rint(np.clip(result, 0, 255)).astype(np.uint8)


def blend_ink(
    frame: np.ndarray,
    strength: np.ndarray,
    color: tuple[int, int, int],
) -> np.ndarray:
    """Blend a representative ink color into a soft boundary shell."""
    alpha = np.clip(strength.astype(np.float32), 0.0, 1.0)[..., None]
    if not np.any(alpha > 0.001):
        return frame
    base = frame.astype(np.float32)
    ink = np.asarray(color, dtype=np.float32)
    target = np.broadcast_to(ink, base.shape)
    return np.rint(base * (1.0 - alpha) + target * alpha).astype(np.uint8)


def blend_ink_edges(
    frame: np.ndarray,
    mask: np.ndarray,
    field: np.ndarray,
    progress: float,
    soft_edge: float,
    color: tuple[int, int, int],
    radius: int,
    bridge_mask: np.ndarray | None = None,
    suppress_field: np.ndarray | None = None,
    suppress_progress: float = 0.0,
) -> np.ndarray:
    """Bridge segmentation seams with wet ink until a later outline replaces them."""
    if progress <= 0.0:
        return frame
    revealed = mask & (field <= progress + max(soft_edge, 0.001))
    feathered = feather_mask(revealed, radius)
    shell = feathered.copy()
    shell[revealed] = 0.0
    strength = shell * 0.72
    if bridge_mask is not None:
        bridge = bridge_mask & expand_mask(revealed, radius) & ~revealed
        strength[bridge] = 1.0
    if suppress_field is not None and suppress_progress > 0.0:
        transition = max(soft_edge * 2.0, 0.006)
        keep = np.clip(
            (suppress_field - suppress_progress + transition) / transition,
            0.0,
            1.0,
        )
        strength *= keep
    return blend_ink(frame, strength, color)

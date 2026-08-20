from __future__ import annotations

import numpy as np


def reveal_opacity(
    mask: np.ndarray,
    field: np.ndarray,
    progress: float,
    softness: float,
) -> np.ndarray:
    """Convert a normalized effect field into a smooth per-pixel opacity mask."""
    if progress <= 0.0:
        return np.zeros(mask.shape, dtype=np.float32)
    if progress >= 1.0:
        return mask.astype(np.float32)
    edge = max(float(softness), 1e-4)
    opacity = np.clip((progress - field) / edge + 0.5, 0.0, 1.0)
    # Cubic smoothstep avoids a digitally sharp leading edge.
    opacity = opacity * opacity * (3.0 - 2.0 * opacity)
    return opacity * mask

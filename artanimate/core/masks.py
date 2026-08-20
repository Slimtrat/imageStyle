from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def complete_family_labels(labels: np.ndarray, strength: int) -> np.ndarray:
    """Complete small holes in color-family regions without touching excluded pixels.

    ``labels`` is a 2-D integer map. Negative values represent background or
    outlines and are never changed. Repeated 3×3 majority passes remove isolated
    classification islands while preserving the disjoint partition of the image.
    """
    values = np.asarray(labels)
    if values.ndim != 2:
        raise ValueError("La carte de familles doit être une matrice 2D")
    if not 0 <= int(strength) <= 4:
        raise ValueError("La complétion des formes doit être comprise entre 0 et 4")
    if strength == 0 or not np.any(values >= 0):
        return values.copy()
    maximum = int(values.max(initial=-1))
    if maximum >= 255:
        raise ValueError("La carte contient trop de familles pour le filtre morphologique")

    active = values >= 0
    current = np.where(active, values, 255).astype(np.uint8)
    for _ in range(int(strength)):
        filtered = np.asarray(
            Image.fromarray(current).filter(ImageFilter.ModeFilter(size=3)),
            dtype=np.uint8,
        )
        usable = active & (filtered != 255)
        current = np.where(usable, filtered, current).astype(np.uint8)
        current[~active] = 255

    result = current.astype(values.dtype, copy=True)
    result[~active] = -1
    return result

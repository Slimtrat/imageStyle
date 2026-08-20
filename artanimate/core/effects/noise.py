from __future__ import annotations

import math

import numpy as np
from PIL import Image


def value_noise(width: int, height: int, seed: int, scale: float = 52.0) -> np.ndarray:
    """Generate inexpensive deterministic smooth value noise in ``[0, 1]``."""
    rng = np.random.default_rng(seed)
    coarse_width = max(3, int(math.ceil(width / max(4.0, scale))) + 2)
    coarse_height = max(3, int(math.ceil(height / max(4.0, scale))) + 2)
    coarse = rng.random((coarse_height, coarse_width), dtype=np.float32)
    image = Image.fromarray(coarse)
    resized = image.resize((width, height), Image.Resampling.BICUBIC)
    result = np.asarray(resized, dtype=np.float32)
    minimum = float(result.min())
    span = float(result.max() - minimum)
    return (result - minimum) / max(span, 1e-6)


def fractal_noise(width: int, height: int, seed: int) -> np.ndarray:
    """Blend three spatial frequencies into a stable organic-noise field."""
    broad = value_noise(width, height, seed, scale=max(width, height) / 8.0)
    medium = value_noise(width, height, seed + 1031, scale=max(width, height) / 22.0)
    fine = value_noise(width, height, seed + 2053, scale=max(width, height) / 55.0)
    return np.clip(broad * 0.58 + medium * 0.29 + fine * 0.13, 0.0, 1.0)


def normalized_coordinates(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized X/Y coordinate grids shared by field implementations."""
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    return np.meshgrid(x, y)

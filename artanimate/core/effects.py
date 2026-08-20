from __future__ import annotations

import math

import numpy as np
from PIL import Image


def value_noise(width: int, height: int, seed: int, scale: float = 52.0) -> np.ndarray:
    """Generate inexpensive, deterministic smooth value noise in [0, 1]."""
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
    broad = value_noise(width, height, seed, scale=max(width, height) / 8.0)
    medium = value_noise(width, height, seed + 1031, scale=max(width, height) / 22.0)
    fine = value_noise(width, height, seed + 2053, scale=max(width, height) / 55.0)
    return np.clip(broad * 0.58 + medium * 0.29 + fine * 0.13, 0.0, 1.0)


def _coordinates(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    return np.meshgrid(x, y)


def wave_field(
    width: int,
    height: int,
    direction: str,
    amplitude: float,
    frequency: float,
    turbulence: float,
    seed: int,
) -> np.ndarray:
    x, y = _coordinates(width, height)
    if direction == "right":
        base, across = 1.0 - x, y
    elif direction == "top":
        base, across = y, x
    elif direction == "bottom":
        base, across = 1.0 - y, x
    elif direction == "diagonal":
        base, across = (x + y) * 0.5, (x - y) * 0.5
    elif direction == "radial":
        dx, dy = x - 0.5, y - 0.5
        base = np.sqrt(dx * dx + dy * dy) / math.sqrt(0.5)
        across = np.arctan2(dy, dx) / (2.0 * math.pi)
    else:
        base, across = x, y

    oscillation = np.sin(across * frequency * 2.0 * math.pi + base * math.pi) * amplitude
    noise = (fractal_noise(width, height, seed) - 0.5) * turbulence
    field = base + oscillation + noise
    minimum = float(field.min())
    maximum = float(field.max())
    return np.clip((field - minimum) / max(maximum - minimum, 1e-6), 0.0, 1.0)


def sand_field(width: int, height: int, turbulence: float, seed: int) -> np.ndarray:
    _, y = _coordinates(width, height)
    noise = (fractal_noise(width, height, seed) - 0.5) * turbulence
    field = (1.0 - y) + noise
    minimum = float(field.min())
    maximum = float(field.max())
    return np.clip((field - minimum) / max(maximum - minimum, 1e-6), 0.0, 1.0)


def reveal_opacity(mask: np.ndarray, field: np.ndarray, progress: float, softness: float) -> np.ndarray:
    if progress <= 0.0:
        return np.zeros(mask.shape, dtype=np.float32)
    if progress >= 1.0:
        return mask.astype(np.float32)
    edge = max(float(softness), 1e-4)
    opacity = np.clip((progress - field) / edge + 0.5, 0.0, 1.0)
    # Cubic smoothstep avoids a digitally sharp leading edge.
    opacity = opacity * opacity * (3.0 - 2.0 * opacity)
    return opacity * mask

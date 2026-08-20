from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def ease_in_out(progress: float) -> float:
    """Quintic easing with zero velocity and acceleration at both ends."""
    value = float(np.clip(progress, 0.0, 1.0))
    return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)


def srgb_to_linear(frame: np.ndarray) -> np.ndarray:
    """Convert an 8-bit sRGB frame to linear-light float values."""
    values = np.asarray(frame, dtype=np.float32) / 255.0
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    ).astype(np.float32)


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    """Convert bounded linear-light values to an 8-bit sRGB frame."""
    bounded = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    encoded = np.where(
        bounded <= 0.0031308,
        bounded * 12.92,
        1.055 * np.power(bounded, 1.0 / 2.4) - 0.055,
    )
    return np.rint(np.clip(encoded, 0.0, 1.0) * 255.0).astype(np.uint8)


def exposure_average(frames: Iterable[np.ndarray]) -> np.ndarray:
    """Average temporal samples in linear light, like a camera exposure."""
    accumulator: np.ndarray | None = None
    count = 0
    expected_shape: tuple[int, ...] | None = None
    for frame in frames:
        values = np.asarray(frame)
        if expected_shape is None:
            expected_shape = values.shape
            accumulator = np.zeros(expected_shape, dtype=np.float32)
        elif values.shape != expected_shape:
            raise ValueError("Les sous-images temporelles doivent avoir la même taille")
        assert accumulator is not None
        accumulator += srgb_to_linear(values)
        count += 1
    if accumulator is None or count == 0:
        raise ValueError("Au moins une sous-image est nécessaire")
    return linear_to_srgb(accumulator / count)

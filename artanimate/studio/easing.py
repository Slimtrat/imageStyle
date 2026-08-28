from __future__ import annotations

from .model import Easing


def eased_progress(progress: float, easing: Easing) -> float:
    """Resolve a normalized, deterministic interpolation shared by Studio tools."""

    if not isinstance(easing, Easing):
        raise TypeError("L’interpolation doit être un Easing")
    value = min(1.0, max(0.0, float(progress)))
    if easing == Easing.LINEAR:
        return value
    if easing == Easing.EASE_IN:
        return value * value * value
    if easing == Easing.EASE_OUT:
        return 1.0 - (1.0 - value) ** 3
    if easing == Easing.EASE_IN_OUT:
        if value < 0.5:
            return 4.0 * value * value * value
        return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0
    raise ValueError(f"Interpolation Studio inconnue : {easing}")

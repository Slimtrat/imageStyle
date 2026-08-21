from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class CameraMotionPreset:
    """One honest camera behavior with an explicit final artwork framing."""

    key: str
    label: str
    description: str
    motion: str
    yaw: float
    pitch: float
    distance: float
    pivot_y: float
    rotation_turns: float
    strength: float


CAMERA_MOTIONS = (
    CameraMotionPreset(
        key="flyover",
        label="Signature · rase-motte → œuvre complète",
        description=(
            "Survole la matière au ras de l’œuvre, dessine une courbe d’un bord à "
            "l’autre puis monte en plongée pour verrouiller l’image complète."
        ),
        motion="flyover",
        yaw=0.0,
        pitch=78.0,
        distance=560.0,
        pivot_y=-8.0,
        rotation_turns=0.0,
        strength=1.0,
    ),
    CameraMotionPreset(
        key="top_drift",
        label="Plongée · dérive lente",
        description=(
            "Reste centré sur l’œuvre avec une dérive elliptique très légère, puis "
            "revient exactement au cadrage final."
        ),
        motion="top_drift",
        yaw=0.0,
        pitch=78.0,
        distance=560.0,
        pivot_y=-8.0,
        rotation_turns=0.0,
        strength=0.62,
    ),
    CameraMotionPreset(
        key="top_fixed",
        label="Plongée · fixe",
        description=(
            "Cadre l’œuvre complète sans mouvement caméra ; utile lorsque seul "
            "l’effet de matière doit attirer l’attention."
        ),
        motion="fixed",
        yaw=0.0,
        pitch=78.0,
        distance=560.0,
        pivot_y=-8.0,
        rotation_turns=0.0,
        strength=0.0,
    ),
)
CAMERA_MOTIONS_BY_KEY = {preset.key: preset for preset in CAMERA_MOTIONS}


@dataclass(frozen=True, slots=True)
class CameraMotionTiming:
    """Normalized timing shared by documentation, tests and the QML equations."""

    flight_progress: float
    settle_progress: float
    flyover_weight: float
    drift_envelope: float


def smootherstep(value: float) -> float:
    t = max(0.0, min(1.0, float(value)))
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def camera_motion_timing(
    motion: str,
    progress: float,
    strength: float,
) -> CameraMotionTiming:
    """Return the authored rail phases for deterministic camera-motion tests."""
    p = max(0.0, min(1.0, float(progress)))
    flight = smootherstep(p / 0.62)
    settle = smootherstep((p - 0.58) / 0.32)
    amount = max(0.0, min(1.25, float(strength)))
    return CameraMotionTiming(
        flight_progress=flight,
        settle_progress=settle,
        flyover_weight=amount * (1.0 - settle) if motion == "flyover" else 0.0,
        drift_envelope=(
            amount * math.sin(math.pi * p) if motion == "top_drift" else 0.0
        ),
    )


def final_fit_distance(
    artwork_width: float,
    artwork_depth: float,
    output_aspect: float,
    field_of_view: float = 39.0,
    minimum: float = 560.0,
) -> float:
    """Distance required to keep the complete horizontal artwork in any output ratio."""
    aspect = max(0.2, float(output_aspect))
    tangent = math.tan(math.radians(field_of_view) * 0.5)
    width_distance = artwork_width * 1.08 / (2.0 * tangent * aspect)
    depth_distance = artwork_depth * 1.08 / (2.0 * tangent)
    return max(float(minimum), width_distance, depth_distance)


def camera_motion(key: str) -> CameraMotionPreset:
    try:
        return CAMERA_MOTIONS_BY_KEY[key]
    except KeyError as exc:
        available = ", ".join(CAMERA_MOTIONS_BY_KEY)
        raise ValueError(
            f"Mouvement caméra inconnu {key!r}. Mouvements disponibles : {available}"
        ) from exc

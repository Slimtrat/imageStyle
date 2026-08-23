from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from hashlib import sha256
import random

from .model import CameraAnimation, CameraKeyframe, CameraPose, Easing


class CameraPreset(StrEnum):
    MACRO = "macro"
    INSPECT = "inspect"
    REVEAL = "reveal"
    DRIFT = "drift"
    HANDHELD = "handheld"


class PresetApplyMode(StrEnum):
    REPLACE = "replace"
    INSERT = "insert"


def _bounded_intensity(intensity: float) -> float:
    value = float(intensity)
    if not 0.0 <= value <= 1.0:
        raise ValueError("L’intensité d’un preset caméra doit être entre 0 et 1")
    return value


def _frame(start: int, duration: int, progress: float) -> int:
    return start + int(round((duration - 1) * progress))


def _aspect_zoom(artwork_ratio: float, project_ratio: float) -> float:
    if artwork_ratio <= 0 or project_ratio <= 0:
        raise ValueError("Les ratios œuvre/projet doivent être positifs")
    mismatch = max(artwork_ratio / project_ratio, project_ratio / artwork_ratio)
    return min(1.35, max(1.0, mismatch ** 0.12))


def _keyframe(
    frame: int,
    pose: CameraPose,
    easing: Easing = Easing.EASE_IN_OUT,
) -> CameraKeyframe:
    return CameraKeyframe(frame, pose.validate(), easing).validate()


def generate_camera_preset(
    preset: CameraPreset,
    *,
    start_frame: int,
    duration_frames: int,
    artwork_ratio: float,
    project_ratio: float,
    intensity: float = 0.5,
    seed: str = "artanimate",
) -> tuple[CameraKeyframe, ...]:
    preset = CameraPreset(preset)
    intensity = _bounded_intensity(intensity)
    start = int(start_frame)
    duration = int(duration_frames)
    if start < 0:
        raise ValueError("Le début du preset caméra ne peut pas être négatif")
    if duration < 2:
        raise ValueError("Un preset caméra doit durer au moins deux frames")
    aspect = _aspect_zoom(float(artwork_ratio), float(project_ratio))
    end = start + duration - 1

    if preset == CameraPreset.MACRO:
        zoom = aspect * (2.4 + 1.8 * intensity)
        return (
            _keyframe(start, CameraPose(x=0.38, y=0.42, zoom=zoom), Easing.EASE_OUT),
            _keyframe(
                _frame(start, duration, 0.55),
                CameraPose(x=0.53, y=0.48, zoom=zoom * 0.92),
            ),
            _keyframe(end, CameraPose(x=0.62, y=0.56, zoom=zoom * 0.84), Easing.EASE_IN),
        )

    if preset == CameraPreset.INSPECT:
        zoom = aspect * (1.55 + 0.85 * intensity)
        return (
            _keyframe(start, CameraPose(x=0.32, y=0.38, zoom=zoom), Easing.EASE_OUT),
            _keyframe(
                _frame(start, duration, 0.48),
                CameraPose(x=0.62, y=0.44, zoom=zoom * 1.08),
            ),
            _keyframe(end, CameraPose(x=0.55, y=0.67, zoom=zoom * 0.95), Easing.EASE_IN),
        )

    if preset == CameraPreset.REVEAL:
        zoom = aspect * (2.1 + 1.2 * intensity)
        whole = CameraPose(x=0.5, y=0.5, zoom=1.0)
        return (
            _keyframe(start, CameraPose(x=0.42, y=0.46, zoom=zoom), Easing.EASE_OUT),
            _keyframe(
                _frame(start, duration, 0.62),
                CameraPose(x=0.48, y=0.49, zoom=1.35),
                Easing.EASE_OUT,
            ),
            _keyframe(_frame(start, duration, 0.84), whole, Easing.EASE_IN_OUT),
            _keyframe(end, whole, Easing.LINEAR),
        )

    if preset == CameraPreset.DRIFT:
        zoom = aspect * (1.18 + 0.35 * intensity)
        rotation = 0.25 + 0.65 * intensity
        return (
            _keyframe(
                start,
                CameraPose(x=0.43, y=0.47, zoom=zoom, rotation_degrees=-rotation),
                Easing.EASE_IN_OUT,
            ),
            _keyframe(
                _frame(start, duration, 0.5),
                CameraPose(x=0.51, y=0.52, zoom=zoom * 1.02),
                Easing.EASE_IN_OUT,
            ),
            _keyframe(
                end,
                CameraPose(x=0.59, y=0.48, zoom=zoom, rotation_degrees=rotation),
                Easing.EASE_IN_OUT,
            ),
        )

    digest = sha256(
        f"{seed}|{preset.value}|{start}|{duration}|{intensity:.8f}".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    count = min(14, max(4, duration // 8))
    amplitude = 0.003 + 0.011 * intensity
    rotation_amplitude = 0.12 + 0.42 * intensity
    zoom = aspect * (1.08 + 0.16 * intensity)
    keyframes: list[CameraKeyframe] = []
    x = 0.5
    y = 0.5
    rotation = 0.0
    for index in range(count):
        progress = index / (count - 1)
        frame = _frame(start, duration, progress)
        x += rng.uniform(-amplitude, amplitude)
        y += rng.uniform(-amplitude, amplitude)
        rotation += rng.uniform(-rotation_amplitude, rotation_amplitude) * 0.45
        x = min(0.5 + amplitude * 2.2, max(0.5 - amplitude * 2.2, x))
        y = min(0.5 + amplitude * 2.2, max(0.5 - amplitude * 2.2, y))
        rotation = min(rotation_amplitude, max(-rotation_amplitude, rotation))
        keyframes.append(
            _keyframe(
                frame,
                CameraPose(
                    x=x,
                    y=y,
                    zoom=zoom * (1.0 + rng.uniform(-0.003, 0.003)),
                    rotation_degrees=rotation,
                ),
                Easing.EASE_IN_OUT,
            )
        )
    return tuple(keyframes)


def apply_camera_preset(
    animation: CameraAnimation | None,
    preset: CameraPreset,
    *,
    start_frame: int,
    duration_frames: int,
    clip_duration_frames: int,
    artwork_ratio: float,
    project_ratio: float,
    intensity: float = 0.5,
    seed: str = "artanimate",
    mode: PresetApplyMode = PresetApplyMode.REPLACE,
) -> CameraAnimation:
    start = int(start_frame)
    duration = int(duration_frames)
    clip_duration = int(clip_duration_frames)
    if start + duration > clip_duration:
        raise ValueError("Le preset caméra dépasse la durée locale du clip")
    generated = generate_camera_preset(
        CameraPreset(preset),
        start_frame=start,
        duration_frames=duration,
        artwork_ratio=artwork_ratio,
        project_ratio=project_ratio,
        intensity=intensity,
        seed=seed,
    )
    mode = PresetApplyMode(mode)
    existing = list(animation.keyframes if animation is not None else ())
    end = start + duration - 1
    if mode == PresetApplyMode.REPLACE:
        existing = [
            keyframe for keyframe in existing
            if not start <= keyframe.frame <= end
        ]
    generated_frames = {keyframe.frame for keyframe in generated}
    existing = [
        keyframe for keyframe in existing
        if keyframe.frame not in generated_frames
    ]
    merged = sorted((*existing, *generated), key=lambda keyframe: keyframe.frame)
    return CameraAnimation(tuple(merged)).validate(
        clip_duration_frames=clip_duration
    )


def golden_camera_path(keyframes: tuple[CameraKeyframe, ...]) -> tuple[tuple[float, ...], ...]:
    """Stable rounded representation used by tests and trajectory documentation."""

    return tuple(
        (
            float(keyframe.frame),
            round(keyframe.pose.x, 5),
            round(keyframe.pose.y, 5),
            round(keyframe.pose.zoom, 5),
            round(keyframe.pose.rotation_degrees, 5),
        )
        for keyframe in keyframes
    )


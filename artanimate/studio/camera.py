from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
from PIL import Image

from .easing import eased_progress
from .model import CameraAnimation, CameraKeyframe, CameraPose, Easing

def _shortest_rotation(start: float, end: float, progress: float) -> float:
    delta = (end - start + 180.0) % 360.0 - 180.0
    return start + delta * progress


def interpolate_camera_pose(
    start: CameraPose,
    end: CameraPose,
    progress: float,
    easing: Easing = Easing.LINEAR,
) -> CameraPose:
    start.validate()
    end.validate()
    t = eased_progress(progress, easing)

    def mix(a: float, b: float) -> float:
        return float(a) + (float(b) - float(a)) * t

    return CameraPose(
        x=mix(start.x, end.x),
        y=mix(start.y, end.y),
        zoom=mix(start.zoom, end.zoom),
        rotation_degrees=_shortest_rotation(
            start.rotation_degrees,
            end.rotation_degrees,
            t,
        ),
        perspective=mix(start.perspective, end.perspective),
        focus=mix(start.focus, end.focus),
    ).validate()


def resolve_camera_pose(
    animation: CameraAnimation | None,
    frame: int,
    *,
    default: CameraPose | None = None,
) -> CameraPose:
    fallback = default or CameraPose()
    fallback.validate()
    if animation is None or not animation.keyframes:
        return fallback
    animation.validate()
    if frame <= animation.keyframes[0].frame:
        return animation.keyframes[0].pose
    if frame >= animation.keyframes[-1].frame:
        return animation.keyframes[-1].pose
    for start, end in zip(animation.keyframes, animation.keyframes[1:]):
        if start.frame <= frame <= end.frame:
            span = end.frame - start.frame
            progress = (frame - start.frame) / span
            # The outgoing keyframe owns the segment easing.
            return interpolate_camera_pose(start.pose, end.pose, progress, start.easing)
    return fallback


def upsert_camera_keyframe(
    animation: CameraAnimation | None,
    frame: int,
    pose: CameraPose,
    *,
    easing: Easing = Easing.EASE_IN_OUT,
) -> CameraAnimation:
    if frame < 0:
        raise ValueError("Une keyframe caméra ne peut pas être négative")
    pose.validate()
    keyframes = list(animation.keyframes if animation is not None else ())
    replacement = CameraKeyframe(frame, pose, easing).validate()
    for index, keyframe in enumerate(keyframes):
        if keyframe.frame == frame:
            keyframes[index] = replace(replacement, easing=keyframe.easing)
            break
    else:
        keyframes.append(replacement)
    keyframes.sort(key=lambda item: item.frame)
    return CameraAnimation(tuple(keyframes)).validate()


def remove_camera_keyframe(
    animation: CameraAnimation | None,
    frame: int,
) -> CameraAnimation:
    if animation is None:
        return CameraAnimation()
    return CameraAnimation(
        tuple(keyframe for keyframe in animation.keyframes if keyframe.frame != frame)
    ).validate()


def _keyframe_index(animation: CameraAnimation, frame: int) -> int:
    for index, keyframe in enumerate(animation.keyframes):
        if keyframe.frame == frame:
            return index
    raise KeyError(f"Keyframe caméra introuvable à la frame {frame}")


def _validate_keyframe_target(
    animation: CameraAnimation,
    source_frame: int,
    target_frame: int,
    *,
    clip_duration_frames: int | None,
) -> None:
    if target_frame < 0:
        raise ValueError("La frame cible ne peut pas être négative")
    if clip_duration_frames is not None and target_frame >= clip_duration_frames:
        raise ValueError("La frame cible dépasse la durée locale du clip")
    if target_frame != source_frame and any(
        keyframe.frame == target_frame for keyframe in animation.keyframes
    ):
        raise ValueError(f"Une keyframe existe déjà à la frame {target_frame}")


def move_camera_keyframe(
    animation: CameraAnimation,
    source_frame: int,
    target_frame: int,
    *,
    clip_duration_frames: int | None = None,
) -> CameraAnimation:
    index = _keyframe_index(animation, source_frame)
    _validate_keyframe_target(
        animation,
        source_frame,
        target_frame,
        clip_duration_frames=clip_duration_frames,
    )
    keyframes = list(animation.keyframes)
    keyframes[index] = replace(keyframes[index], frame=target_frame)
    keyframes.sort(key=lambda keyframe: keyframe.frame)
    return CameraAnimation(tuple(keyframes)).validate(
        clip_duration_frames=clip_duration_frames
    )


def copy_camera_keyframe(
    animation: CameraAnimation,
    source_frame: int,
    target_frame: int,
    *,
    clip_duration_frames: int | None = None,
) -> CameraAnimation:
    index = _keyframe_index(animation, source_frame)
    _validate_keyframe_target(
        animation,
        source_frame,
        target_frame,
        clip_duration_frames=clip_duration_frames,
    )
    if source_frame == target_frame:
        raise ValueError("La copie doit cibler une autre frame")
    keyframes = [*animation.keyframes, replace(animation.keyframes[index], frame=target_frame)]
    keyframes.sort(key=lambda keyframe: keyframe.frame)
    return CameraAnimation(tuple(keyframes)).validate(
        clip_duration_frames=clip_duration_frames
    )


def set_camera_keyframe_easing(
    animation: CameraAnimation,
    frame: int,
    easing: Easing,
) -> CameraAnimation:
    if not isinstance(easing, Easing):
        raise TypeError("L’easing caméra doit être un Easing")
    index = _keyframe_index(animation, frame)
    keyframes = list(animation.keyframes)
    keyframes[index] = replace(keyframes[index], easing=easing)
    return CameraAnimation(tuple(keyframes)).validate()


def render_camera_frame(
    artwork: np.ndarray,
    output_width: int,
    output_height: int,
    pose: CameraPose,
    *,
    background: tuple[int, int, int] = (18, 18, 22),
) -> np.ndarray:
    """Render an artwork through a normalized camera into the Reel canvas."""

    pose.validate()
    array = np.asarray(artwork)
    if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
        raise TypeError("La caméra Studio attend une image RGB uint8")
    if output_width <= 0 or output_height <= 0:
        raise ValueError("Le canvas caméra doit avoir des dimensions positives")

    source_height, source_width = array.shape[:2]
    scale = min(output_width / source_width, output_height / source_height)
    base_width = max(1, int(round(source_width * scale)))
    base_height = max(1, int(round(source_height * scale)))
    left = (output_width - base_width) // 2
    top = (output_height - base_height) // 2

    canvas = Image.new("RGB", (output_width, output_height), background)
    resized = Image.fromarray(array, mode="RGB").resize(
        (base_width, base_height),
        Image.Resampling.LANCZOS,
    )
    canvas.paste(resized, (left, top))

    if (
        abs(pose.x - 0.5) < 1e-12
        and abs(pose.y - 0.5) < 1e-12
        and abs(pose.zoom - 1.0) < 1e-12
        and abs(pose.rotation_degrees) < 1e-12
    ):
        return np.asarray(canvas, dtype=np.uint8).copy()

    target_x = left + pose.x * base_width
    target_y = top + pose.y * base_height
    center_x = output_width / 2.0
    center_y = output_height / 2.0
    angle = math.radians(pose.rotation_degrees)
    cosine = math.cos(angle) / pose.zoom
    sine = math.sin(angle) / pose.zoom
    coefficients = (
        cosine,
        sine,
        target_x - cosine * center_x - sine * center_y,
        -sine,
        cosine,
        target_y + sine * center_x - cosine * center_y,
    )
    transformed = canvas.transform(
        (output_width, output_height),
        Image.Transform.AFFINE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=background,
    )
    return np.asarray(transformed, dtype=np.uint8).copy()


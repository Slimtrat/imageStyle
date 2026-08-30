from __future__ import annotations

import cv2
import numpy as np

from .camera import resolve_camera_pose
from .model import CameraAnimation, CameraPose


def normalized_homography_to_pixels(
    homography: tuple[tuple[float, float, float], ...] | list[list[float]],
    *,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> np.ndarray:
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("La projection sémantique exige des dimensions positives")
    normalized = np.asarray(homography, dtype=np.float64)
    if normalized.shape != (3, 3) or not np.all(np.isfinite(normalized)):
        raise ValueError("La projection sémantique exige une homographie 3×3 finie")
    source_to_normalized = np.asarray(
        (
            (1.0 / max(1, source_width - 1), 0.0, 0.0),
            (0.0, 1.0 / max(1, source_height - 1), 0.0),
            (0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    normalized_to_target = np.asarray(
        (
            (max(1, target_width - 1), 0.0, 0.0),
            (0.0, max(1, target_height - 1), 0.0),
            (0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )
    result = normalized_to_target @ normalized @ source_to_normalized
    result /= result[2, 2]
    return result


def _camera_inverse_matrix(
    pose: CameraPose,
    *,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    pose.validate()
    scale = min(output_width / source_width, output_height / source_height)
    base_width = max(1, int(round(source_width * scale)))
    base_height = max(1, int(round(source_height * scale)))
    left = (output_width - base_width) // 2
    top = (output_height - base_height) // 2
    target_x = left + pose.x * base_width
    target_y = top + pose.y * base_height
    center_x = output_width / 2.0
    center_y = output_height / 2.0
    angle = np.deg2rad(pose.rotation_degrees)
    cosine = float(np.cos(angle) / pose.zoom)
    sine = float(np.sin(angle) / pose.zoom)
    return np.asarray(
        (
            (cosine, sine, target_x - cosine * center_x - sine * center_y),
            (-sine, cosine, target_y + sine * center_x - cosine * center_y),
            (0.0, 0.0, 1.0),
        ),
        dtype=np.float64,
    )


def camera_view_delta(
    reference: CameraPose,
    current: CameraPose,
    *,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    reference_inverse = _camera_inverse_matrix(
        reference,
        source_width=source_width,
        source_height=source_height,
        output_width=output_width,
        output_height=output_height,
    )
    current_inverse = _camera_inverse_matrix(
        current,
        source_width=source_width,
        source_height=source_height,
        output_width=output_width,
        output_height=output_height,
    )
    return np.linalg.inv(current_inverse) @ reference_inverse


def project_canonical_mask(
    mask: np.ndarray,
    normalized_homography: tuple[tuple[float, float, float], ...] | list[list[float]],
    *,
    output_width: int,
    output_height: int,
    camera: CameraAnimation | None = None,
    reference_camera_frame: int = 0,
    current_camera_frame: int = 0,
    camera_source_width: int | None = None,
    camera_source_height: int | None = None,
) -> np.ndarray:
    canonical = np.asarray(mask, dtype=np.float32)
    if canonical.ndim != 2:
        raise TypeError("Le masque canonique doit être un plan scalaire")
    matrix = normalized_homography_to_pixels(
        normalized_homography,
        source_width=canonical.shape[1],
        source_height=canonical.shape[0],
        target_width=output_width,
        target_height=output_height,
    )
    projected = cv2.warpPerspective(
        canonical,
        matrix,
        (output_width, output_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0.0,
    )
    if camera is not None:
        if camera_source_width is None or camera_source_height is None:
            raise ValueError("La projection caméra exige les dimensions du média réel")
        delta = camera_view_delta(
            resolve_camera_pose(camera, reference_camera_frame),
            resolve_camera_pose(camera, current_camera_frame),
            source_width=camera_source_width,
            source_height=camera_source_height,
            output_width=output_width,
            output_height=output_height,
        )
        projected = cv2.warpPerspective(
            projected,
            delta,
            (output_width, output_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
    return np.ascontiguousarray(np.clip(projected, 0.0, 1.0), dtype=np.float32)


def blink_amount(
    frame_index: int,
    *,
    close_frames: int,
    hold_frames: int,
    open_frames: int,
    easing: str,
    intensity: float,
) -> float:
    if min(close_frames, open_frames) < 2 or hold_frames < 0:
        raise ValueError("Le blink exige au moins deux frames de fermeture et d’ouverture")
    total = close_frames + hold_frames + open_frames
    if not 0 <= frame_index < total:
        raise IndexError("Frame de blink hors limites")

    def curve(value: float) -> float:
        value = float(np.clip(value, 0.0, 1.0))
        if easing == "linear":
            return value
        if easing == "ease-in":
            return value * value
        if easing == "ease-out":
            return 1.0 - (1.0 - value) ** 2
        if easing == "ease-in-out":
            return value * value * (3.0 - 2.0 * value)
        raise ValueError(f"Easing de blink inconnu : {easing}")

    if frame_index < close_frames:
        amount = curve(frame_index / (close_frames - 1))
    elif frame_index < close_frames + hold_frames:
        amount = 1.0
    else:
        local = frame_index - close_frames - hold_frames
        amount = 1.0 - curve(local / (open_frames - 1))
    return float(np.clip(amount * intensity, 0.0, 1.0))


def compose_blink(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    frame = np.asarray(image)
    alpha = np.asarray(mask, dtype=np.float32)
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise TypeError("Le blink exige une frame RGB uint8")
    if alpha.shape != frame.shape[:2]:
        raise ValueError("Le masque du blink doit correspondre à la frame")
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount <= 1.0e-8 or not np.any(alpha > 0.02):
        return frame.copy()
    binary = (alpha > 0.04).astype(np.uint8)
    ys, xs = np.nonzero(binary)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    height = y1 - y0
    width = x1 - x0
    if height < 2 or width < 2:
        return frame.copy()
    radius = max(1, round(min(width, height) * 0.12))
    expanded = cv2.dilate(binary, np.ones((radius * 2 + 1, radius * 2 + 1), np.uint8))
    base = cv2.inpaint(
        cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
        expanded * 255,
        max(1.0, radius * 0.8),
        cv2.INPAINT_TELEA,
    )
    base = cv2.cvtColor(base, cv2.COLOR_BGR2RGB)
    source = frame[y0:y1, x0:x1]
    source_alpha = alpha[y0:y1, x0:x1]
    compressed_height = max(1, round(height * (1.0 - amount * 0.94)))
    compressed = cv2.resize(source, (width, compressed_height), interpolation=cv2.INTER_AREA)
    compressed_alpha = cv2.resize(
        source_alpha,
        (width, compressed_height),
        interpolation=cv2.INTER_AREA,
    )
    layer = np.zeros_like(frame)
    layer_alpha = np.zeros_like(alpha)
    center = (y0 + y1) // 2
    target_y0 = max(0, center - compressed_height // 2)
    target_y1 = min(frame.shape[0], target_y0 + compressed_height)
    used = target_y1 - target_y0
    layer[target_y0:target_y1, x0:x1] = compressed[:used]
    layer_alpha[target_y0:target_y1, x0:x1] = compressed_alpha[:used]
    result = base.astype(np.float32)
    blend = np.clip(layer_alpha, 0.0, 1.0)[..., None]
    result = result * (1.0 - blend) + layer.astype(np.float32) * blend
    outside = np.clip(alpha, 0.0, 1.0)[..., None]
    final = frame.astype(np.float32) * (1.0 - outside) + result * outside
    return np.ascontiguousarray(np.rint(np.clip(final, 0.0, 255.0)).astype(np.uint8))

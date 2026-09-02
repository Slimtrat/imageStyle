from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import cv2
import numpy as np


def _finite(value: Any, where: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} doit être fini")
    return number


@dataclass(frozen=True, slots=True)
class EyelidGeometry:
    """Editable eyelid geometry expressed inside the canonical eye region."""

    axis: tuple[float, float, float, float] = (0.06, 0.72, 0.94, 0.78)
    curvature: float = -0.06
    amplitude: float = 1.0
    protection: float = 0.10
    seam_width: float = 0.014

    def validate(self) -> EyelidGeometry:
        if len(self.axis) != 4:
            raise ValueError("blink.axis doit contenir [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (
            _finite(value, f"blink.axis[{index}]")
            for index, value in enumerate(self.axis)
        )
        if not all(0.0 <= value <= 1.0 for value in (x0, y0, x1, y1)):
            raise ValueError("blink.axis doit rester dans la région normalisée")
        if x1 - x0 < 0.1:
            raise ValueError("blink.axis doit être orienté de gauche à droite")
        if not -0.5 <= _finite(self.curvature, "blink.curvature") <= 0.5:
            raise ValueError("blink.curvature doit être compris entre -0,5 et 0,5")
        if not 0.0 <= _finite(self.amplitude, "blink.amplitude") <= 1.0:
            raise ValueError("blink.amplitude doit être compris entre 0 et 1")
        if not 0.0 <= _finite(self.protection, "blink.protection") <= 0.5:
            raise ValueError("blink.protection doit être compris entre 0 et 0,5")
        if not 0.002 <= _finite(self.seam_width, "blink.seam_width") <= 0.12:
            raise ValueError("blink.seam_width doit être compris entre 0,002 et 0,12")
        return self

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> EyelidGeometry:
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise TypeError("blink doit être un objet JSON")
        unknown = sorted(
            set(payload)
            - {"axis", "curvature", "amplitude", "protection", "seam_width"}
        )
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans blink : " + ", ".join(unknown)
            )
        defaults = cls()
        raw_axis = payload.get("axis", defaults.axis)
        if (
            not isinstance(raw_axis, (list, tuple))
            or len(raw_axis) != 4
            or any(isinstance(value, bool) for value in raw_axis)
        ):
            raise ValueError("blink.axis doit contenir [x0, y0, x1, y1]")
        return cls(
            axis=tuple(float(value) for value in raw_axis),
            curvature=float(payload.get("curvature", defaults.curvature)),
            amplitude=float(payload.get("amplitude", defaults.amplitude)),
            protection=float(payload.get("protection", defaults.protection)),
            seam_width=float(payload.get("seam_width", defaults.seam_width)),
        ).validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "axis": list(self.axis),
            "curvature": self.curvature,
            "amplitude": self.amplitude,
            "protection": self.protection,
            "seam_width": self.seam_width,
        }


def _smoothstep(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _dark_line_color(frame: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    selected = frame[alpha > 0.25]
    if not len(selected):
        return np.asarray((24.0, 24.0, 28.0), dtype=np.float32)
    luminance = (
        selected[:, 0].astype(np.float32) * 0.2126
        + selected[:, 1].astype(np.float32) * 0.7152
        + selected[:, 2].astype(np.float32) * 0.0722
    )
    count = max(4, int(math.ceil(len(selected) * 0.08)))
    darkest = selected[np.argpartition(luminance, min(count - 1, len(selected) - 1))[:count]]
    return np.median(darkest.astype(np.float32), axis=0)


def _dominant_surface_color(frame: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    selected = frame[alpha > 0.16]
    if not len(selected):
        return np.median(frame.reshape(-1, 3), axis=0).astype(np.float32)
    quantized = (selected.astype(np.uint16) // 20).astype(np.uint16)
    keys = (
        quantized[:, 0] * 256
        + quantized[:, 1] * 16
        + quantized[:, 2]
    )
    unique, counts = np.unique(keys, return_counts=True)
    dominant = unique[int(np.argmax(counts))]
    cluster = selected[keys == dominant]
    return np.median(cluster.astype(np.float32), axis=0)


def compose_eyelid_blink(
    image: np.ndarray,
    mask: np.ndarray,
    amount: float,
    geometry: EyelidGeometry | Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Close an eye with sampled eyelid flaps instead of compressing its pixels."""

    frame = np.asarray(image)
    alpha = np.asarray(mask, dtype=np.float32)
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise TypeError("Le blink exige une frame RGB uint8")
    if alpha.shape != frame.shape[:2]:
        raise ValueError("Le masque du blink doit correspondre à la frame")
    model = (
        geometry.validate()
        if isinstance(geometry, EyelidGeometry)
        else EyelidGeometry.from_mapping(geometry)
    )
    closure = float(np.clip(float(amount) * model.amplitude, 0.0, 1.0))
    if closure <= 1.0e-8 or not np.any(alpha > 0.04):
        return frame.copy()

    binary = alpha > 0.04
    ys, xs = np.nonzero(binary)
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    height = y1 - y0
    width = x1 - x0
    if height < 3 or width < 3:
        return frame.copy()

    patch_alpha = np.clip(alpha[y0:y1, x0:x1], 0.0, 1.0)
    local_y, local_x = np.mgrid[0:height, 0:width].astype(np.float32)
    axis_x0, axis_y0, axis_x1, axis_y1 = model.axis
    first = np.asarray(
        (axis_x0 * max(1, width - 1), axis_y0 * max(1, height - 1)),
        dtype=np.float32,
    )
    last = np.asarray(
        (axis_x1 * max(1, width - 1), axis_y1 * max(1, height - 1)),
        dtype=np.float32,
    )
    tangent = last - first
    axis_length = float(np.linalg.norm(tangent))
    if axis_length < 1.0:
        return frame.copy()
    tangent /= axis_length
    normal = np.asarray((-tangent[1], tangent[0]), dtype=np.float32)
    if normal[1] < 0.0:
        normal *= -1.0

    delta_x = local_x - first[0]
    delta_y = local_y - first[1]
    along_pixels = delta_x * tangent[0] + delta_y * tangent[1]
    along = along_pixels / axis_length
    curve_window = np.clip(1.0 - (2.0 * along - 1.0) ** 2, 0.0, 1.0)
    curve_offset = model.curvature * height * curve_window
    relative = delta_x * normal[0] + delta_y * normal[1] - curve_offset

    selected_relative = relative[binary[y0:y1, x0:x1]]
    upper_extent = max(1.0, float(-selected_relative.min()))
    lower_extent = max(1.0, float(selected_relative.max()))
    softness = max(0.65, min(width, height) * 0.025)
    upper_front = -upper_extent * (1.0 - closure)
    lower_front = lower_extent * (1.0 - closure)
    upper_coverage = 1.0 - _smoothstep(
        (relative - (upper_front - softness)) / (2.0 * softness)
    )
    lower_coverage = _smoothstep(
        (relative - (lower_front - softness)) / (2.0 * softness)
    )
    coverage = np.maximum(upper_coverage, lower_coverage)

    protection_pixels = model.protection * height
    upper_source_relative = (
        -upper_extent
        - protection_pixels
        - np.maximum(0.0, relative + upper_extent) * 0.12
    )
    lower_source_relative = (
        lower_extent
        + protection_pixels
        + np.maximum(0.0, lower_extent - relative) * 0.12
    )
    source_relative = np.where(
        relative <= 0.0,
        upper_source_relative,
        lower_source_relative,
    )
    axis_x = first[0] + along_pixels * tangent[0] + curve_offset * normal[0]
    axis_y = first[1] + along_pixels * tangent[1] + curve_offset * normal[1]
    map_x = axis_x + source_relative * normal[0] + x0
    map_y = axis_y + source_relative * normal[1] + y0
    lid_texture = cv2.remap(
        frame,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    ).astype(np.float32)

    original = frame[y0:y1, x0:x1].astype(np.float32)
    surface_color = _dominant_surface_color(
        frame[y0:y1, x0:x1],
        patch_alpha,
    )
    color_distance = np.linalg.norm(lid_texture - surface_color, axis=2)
    reliability = 1.0 - _smoothstep((color_distance - 22.0) / 34.0)
    blurred = cv2.GaussianBlur(
        original,
        (0, 0),
        sigmaX=max(0.8, min(width, height) * 0.018),
    )
    texture_detail = np.clip(original - blurred, -2.5, 2.5)
    protected_surface = np.clip(surface_color + texture_detail, 0.0, 255.0)
    lid_texture = (
        lid_texture * reliability[..., None]
        + protected_surface * (1.0 - reliability[..., None])
    )
    lid_alpha = (patch_alpha * coverage)[..., None]
    result_patch = original * (1.0 - lid_alpha) + lid_texture * lid_alpha

    seam_sigma = max(0.55, model.seam_width * height)
    seam = np.exp(-0.5 * (relative / seam_sigma) ** 2)
    seam_window = _smoothstep(along / 0.08) * _smoothstep((1.0 - along) / 0.08)
    seam_visibility = float(_smoothstep(np.asarray((closure - 0.52) / 0.48)))
    seam_alpha = np.clip(
        seam * seam_window * patch_alpha * seam_visibility,
        0.0,
        1.0,
    )[..., None]
    line_color = _dark_line_color(frame[y0:y1, x0:x1], patch_alpha)
    result_patch = result_patch * (1.0 - seam_alpha) + line_color * seam_alpha

    result = frame.copy()
    result[y0:y1, x0:x1] = np.rint(
        np.clip(result_patch, 0.0, 255.0)
    ).astype(np.uint8)
    return np.ascontiguousarray(result)

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import cv2
import numpy as np

from .studio3d_camera import final_fit_distance
from .studio3d_wave import artwork_dimensions


_DECK_YAW_DEGREES = -3.0
_ARTWORK_SURFACE_Y = -9.0
_ARTWORK_CENTER_Z = -8.0


def _rotation_y(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.asarray(((cosine, 0.0, sine), (0.0, 1.0, 0.0), (-sine, 0.0, cosine)))


def _object_corners(artwork_aspect: float) -> np.ndarray:
    width, depth = artwork_dimensions(artwork_aspect)
    # Rectangle texture order after the QML -90° X rotation: TL, TR, BR, BL.
    local = np.asarray(
        (
            (-width / 2.0, _ARTWORK_SURFACE_Y, -depth / 2.0),
            (width / 2.0, _ARTWORK_SURFACE_Y, -depth / 2.0),
            (width / 2.0, _ARTWORK_SURFACE_Y, depth / 2.0),
            (-width / 2.0, _ARTWORK_SURFACE_Y, depth / 2.0),
        ),
        dtype=np.float64,
    )
    deck = _rotation_y(math.radians(_DECK_YAW_DEGREES))
    return (deck @ local.T).T + np.asarray((0.0, 0.0, _ARTWORK_CENTER_Z))


def _intrinsics(width: int, height: int, field_of_view: float) -> np.ndarray:
    focal = height / (2.0 * math.tan(math.radians(field_of_view) / 2.0))
    return np.asarray(
        ((focal, 0.0, width / 2.0), (0.0, focal, height / 2.0), (0.0, 0.0, 1.0)),
        dtype=np.float64,
    )


@dataclass(frozen=True, slots=True)
class Studio3DCameraMatchPose:
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float
    distance: float
    field_of_view: float
    reprojection_error: float

    def to_dict(self, *, start_frame: int, end_frame: int) -> dict[str, float | int]:
        if start_frame < 0 or end_frame <= start_frame:
            raise ValueError("La fenêtre de raccord caméra 3D est invalide")
        return {
            "start_frame": int(start_frame),
            "end_frame": int(end_frame),
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "pitch": self.pitch,
            "yaw": self.yaw,
            "roll": self.roll,
            "distance": self.distance,
            "field_of_view": self.field_of_view,
            "reprojection_error": self.reprojection_error,
        }


def _solve_at_fov(
    object_points: np.ndarray,
    image_points: np.ndarray,
    width: int,
    height: int,
    field_of_view: float,
) -> tuple[float, np.ndarray, np.ndarray]:
    camera = _intrinsics(width, height, field_of_view)
    solved, rotation, translation = cv2.solvePnP(
        object_points,
        image_points,
        camera,
        None,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not solved:
        return float("inf"), np.empty((0,)), np.empty((0,))
    reprojection, _ = cv2.projectPoints(
        object_points,
        rotation,
        translation,
        camera,
        None,
    )
    delta = reprojection.reshape(-1, 2) - image_points
    error = float(np.sqrt(np.mean(np.sum(np.square(delta), axis=1))))
    return error, rotation, translation


def _best_perspective_pose(
    object_points: np.ndarray,
    image_points: np.ndarray,
    width: int,
    height: int,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    candidates: list[tuple[float, float, np.ndarray, np.ndarray]] = []
    for field_of_view in np.linspace(18.0, 118.0, 101):
        error, rotation, translation = _solve_at_fov(
            object_points, image_points, width, height, float(field_of_view)
        )
        candidates.append((error, float(field_of_view), rotation, translation))
    coarse = min(candidates, key=lambda item: item[0])
    fine: list[tuple[float, float, np.ndarray, np.ndarray]] = []
    for field_of_view in np.linspace(coarse[1] - 1.0, coarse[1] + 1.0, 81):
        error, rotation, translation = _solve_at_fov(
            object_points, image_points, width, height, float(field_of_view)
        )
        fine.append((error, float(field_of_view), rotation, translation))
    return min(fine, key=lambda item: item[0])


def solve_studio3d_camera_match(
    target_quad: Sequence[Sequence[float]],
    *,
    artwork_aspect: float,
    output_width: int,
    output_height: int,
) -> Studio3DCameraMatchPose:
    """Recover the actual 3D camera pose that sees the artwork like the real photo."""
    if artwork_aspect <= 0.0 or output_width <= 0 or output_height <= 0:
        raise ValueError("La géométrie du raccord caméra 3D doit être positive")
    normalized = np.asarray(target_quad, dtype=np.float64)
    if normalized.shape != (4, 2) or not np.isfinite(normalized).all():
        raise ValueError("Le raccord caméra 3D exige quatre coins normalisés finis")
    image_points = normalized * np.asarray(
        (output_width - 1.0, output_height - 1.0), dtype=np.float64
    )
    object_points = _object_corners(artwork_aspect)
    error, field_of_view, rotation_vector, translation = _best_perspective_pose(
        object_points,
        image_points,
        output_width,
        output_height,
    )
    if not math.isfinite(error) or error > max(output_width, output_height) * 0.02:
        raise ValueError(
            "La photo réelle ne permet pas de résoudre une pose caméra 3D fiable"
        )

    rotation_cv, _ = cv2.Rodrigues(rotation_vector)
    qt_flip = np.diag((1.0, -1.0, -1.0))
    rotation_rig = rotation_cv.T @ qt_flip
    pitch = math.degrees(math.asin(float(np.clip(-rotation_rig[1, 2], -1.0, 1.0))))
    yaw = math.degrees(math.atan2(rotation_rig[0, 2], rotation_rig[2, 2]))
    roll = math.degrees(math.atan2(rotation_rig[1, 0], rotation_rig[1, 1]))

    artwork_width, artwork_depth = artwork_dimensions(artwork_aspect)
    distance = final_fit_distance(
        artwork_width,
        artwork_depth,
        output_width / output_height,
        field_of_view=field_of_view,
        minimum=560.0,
    )
    camera_position = -rotation_cv.T @ translation.reshape(3)
    rig_position = camera_position - rotation_rig @ np.asarray((0.0, 0.0, distance))
    return Studio3DCameraMatchPose(
        x=float(rig_position[0]),
        y=float(rig_position[1]),
        z=float(rig_position[2]),
        pitch=pitch,
        yaw=yaw,
        roll=roll,
        distance=distance,
        field_of_view=field_of_view,
        reprojection_error=error,
    )

from __future__ import annotations

import colorsys
from collections.abc import Iterable

import numpy as np


FAMILY_LABELS = {
    "red": "rouges",
    "orange": "oranges",
    "yellow": "jaunes",
    "chartreuse": "jaunes-verts",
    "green": "verts",
    "turquoise": "turquoises",
    "cyan": "cyans",
    "blue": "bleus",
    "violet": "violets",
    "magenta": "magentas",
    "rose": "roses",
    "neutral": "neutres",
    "neutral_dark": "neutres sombres",
    "neutral_light": "neutres clairs",
    "outline": "contours",
}


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8/float pixels to CIE L*a*b* (D65), vectorized."""
    values = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = linear @ matrix.T
    xyz /= np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    delta = 6.0 / 29.0
    transformed = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    lab = np.empty_like(transformed)
    lab[..., 0] = 116.0 * transformed[..., 1] - 16.0
    lab[..., 1] = 500.0 * (transformed[..., 0] - transformed[..., 1])
    lab[..., 2] = 200.0 * (transformed[..., 1] - transformed[..., 2])
    return lab


def hue_and_saturation(rgb: Iterable[int | float]) -> tuple[float, float, float]:
    red, green, blue = (float(channel) / 255.0 for channel in rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return hue * 360.0, saturation, value


def family_for_color(rgb: Iterable[int | float], chroma: float) -> tuple[str, float]:
    hue, saturation, _ = hue_and_saturation(rgb)
    if chroma < 13.0 or saturation < 0.10:
        return "neutral", hue
    if hue < 15.0 or hue >= 345.0:
        return "red", hue
    if hue < 45.0:
        return "orange", hue
    if hue < 70.0:
        return "yellow", hue
    if hue < 100.0:
        return "chartreuse", hue
    if hue < 150.0:
        return "green", hue
    if hue < 185.0:
        return "turquoise", hue
    if hue < 210.0:
        return "cyan", hue
    if hue < 255.0:
        return "blue", hue
    if hue < 285.0:
        return "violet", hue
    if hue < 325.0:
        return "magenta", hue
    return "rose", hue


def kmeans_lab(
    samples: np.ndarray,
    requested_clusters: int,
    seed: int,
    iterations: int = 24,
) -> np.ndarray:
    """Small deterministic k-means++ implementation specialized for 3-D Lab data."""
    points = np.asarray(samples, dtype=np.float32).reshape(-1, 3)
    if len(points) == 0:
        raise ValueError("Impossible de quantifier une liste de pixels vide")

    rng = np.random.default_rng(seed)
    cluster_count = min(int(requested_clusters), len(points))
    centers = [points[int(rng.integers(0, len(points)))].copy()]
    min_distance = np.sum((points - centers[0]) ** 2, axis=1)

    for _ in range(1, cluster_count):
        total = float(min_distance.sum())
        if total <= 1e-8:
            break
        next_index = int(rng.choice(len(points), p=min_distance / total))
        centers.append(points[next_index].copy())
        candidate_distance = np.sum((points - centers[-1]) ** 2, axis=1)
        min_distance = np.minimum(min_distance, candidate_distance)

    result = np.stack(centers)
    for _ in range(iterations):
        labels = closest_centers(points, result)
        updated = result.copy()
        for index in range(len(result)):
            members = points[labels == index]
            if len(members):
                updated[index] = members.mean(axis=0)
            else:
                distances = np.min(
                    np.sum((points[:, None, :] - result[None, :, :]) ** 2, axis=2),
                    axis=1,
                )
                updated[index] = points[int(np.argmax(distances))]
        shift = float(np.max(np.linalg.norm(updated - result, axis=1)))
        result = updated
        if shift < 0.08:
            break
    return result


def closest_centers(points: np.ndarray, centers: np.ndarray, chunk_size: int = 120_000) -> np.ndarray:
    values = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    labels = np.empty(len(values), dtype=np.int16)
    for start in range(0, len(values), chunk_size):
        chunk = values[start : start + chunk_size]
        distances = np.sum((chunk[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        labels[start : start + len(chunk)] = np.argmin(distances, axis=1)
    return labels


def hex_color(rgb: Iterable[int | float]) -> str:
    channels = [max(0, min(255, int(round(value)))) for value in rgb]
    return "#" + "".join(f"{channel:02X}" for channel in channels)

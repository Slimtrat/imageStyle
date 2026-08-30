from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .image_io import load_normalized_image


RECTIFICATION_ALGORITHM = "border-quad-v1"


@dataclass(frozen=True, slots=True)
class LineFit:
    slope: float
    intercept: float
    residual: float
    support: int


@dataclass(frozen=True, slots=True)
class ArtworkRectification:
    source_width: int
    source_height: int
    corners: tuple[tuple[float, float], ...]
    output_width: int
    output_height: int
    confidence: float
    background_rgb: tuple[int, int, int]
    threshold: float
    foreground_coverage: float
    line_residual: float
    algorithm: str = RECTIFICATION_ALGORITHM

    def validate(self) -> ArtworkRectification:
        if self.source_width < 1 or self.source_height < 1:
            raise ValueError("La source de redressement doit avoir une taille positive")
        if self.output_width < 64 or self.output_height < 64:
            raise ValueError("L’œuvre redressée doit mesurer au moins 64 px")
        if len(self.corners) != 4:
            raise ValueError("Le redressement doit contenir quatre coins")
        for x, y in self.corners:
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("Les coins de redressement doivent être finis")
            if not -1.0 <= x <= self.source_width or not -1.0 <= y <= self.source_height:
                raise ValueError("Un coin de redressement sort de l’image")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("La confiance de redressement doit être comprise entre 0 et 1")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        labels = ("top_left", "top_right", "bottom_right", "bottom_left")
        return {
            "algorithm": self.algorithm,
            "source_resolution": [self.source_width, self.source_height],
            "output_resolution": [self.output_width, self.output_height],
            "corners": {
                label: [round(point[0], 3), round(point[1], 3)]
                for label, point in zip(labels, self.corners, strict=True)
            },
            "confidence": round(self.confidence, 4),
            "background_rgb": list(self.background_rgb),
            "threshold": round(self.threshold, 3),
            "foreground_coverage": round(self.foreground_coverage, 4),
            "line_residual": round(self.line_residual, 3),
        }


def _longest_run(values: np.ndarray) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    start: int | None = None
    for index, enabled in enumerate(values.tolist() + [False]):
        if enabled and start is None:
            start = index
        elif not enabled and start is not None:
            if best is None or index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    return best


def _border_prototypes(pixels: np.ndarray, band: int, segments: int = 8) -> np.ndarray:
    height, width = pixels.shape[:2]
    samples: list[np.ndarray] = []
    for index in range(segments):
        x0 = round(index * width / segments)
        x1 = max(x0 + 1, round((index + 1) * width / segments))
        y0 = round(index * height / segments)
        y1 = max(y0 + 1, round((index + 1) * height / segments))
        samples.extend(
            (
                pixels[:band, x0:x1],
                pixels[height - band :, x0:x1],
                pixels[y0:y1, :band],
                pixels[y0:y1, width - band :],
            )
        )
    return np.asarray(
        [np.median(sample.reshape(-1, 3), axis=0) for sample in samples],
        dtype=np.float32,
    )


def _distance_to_background(pixels: np.ndarray, prototypes: np.ndarray) -> np.ndarray:
    source = pixels.astype(np.float32)
    minimum = np.full(source.shape[:2], np.inf, dtype=np.float32)
    for prototype in prototypes:
        delta = source - prototype
        distance = np.sqrt(np.sum(delta * delta, axis=2))
        minimum = np.minimum(minimum, distance)
    return minimum


def _robust_line(independent: np.ndarray, dependent: np.ndarray) -> LineFit:
    if independent.size < 12:
        raise ValueError("Contour insuffisant pour ajuster une ligne")
    keep = np.ones(independent.size, dtype=bool)
    slope = 0.0
    intercept = float(np.median(dependent))
    for _iteration in range(5):
        if int(np.count_nonzero(keep)) < 12:
            break
        slope, intercept = np.polyfit(independent[keep], dependent[keep], 1)
        residuals = np.abs(dependent - (slope * independent + intercept))
        center = float(np.median(residuals[keep]))
        limit = max(1.5, center * 2.8)
        candidate = residuals <= limit
        if np.array_equal(candidate, keep):
            break
        keep = candidate
    residuals = np.abs(dependent - (slope * independent + intercept))
    selected = residuals[keep]
    return LineFit(
        float(slope),
        float(intercept),
        float(np.mean(selected)) if selected.size else float(np.mean(residuals)),
        int(np.count_nonzero(keep)),
    )


def _intersection(horizontal: LineFit, vertical: LineFit) -> tuple[float, float]:
    denominator = 1.0 - horizontal.slope * vertical.slope
    if abs(denominator) < 1.0e-6:
        raise ValueError("Les bords détectés ne forment pas un quadrilatère stable")
    y = (
        horizontal.slope * vertical.intercept + horizontal.intercept
    ) / denominator
    x = vertical.slope * y + vertical.intercept
    return float(x), float(y)


def _quad_area(corners: tuple[tuple[float, float], ...]) -> float:
    return abs(
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(corners, (*corners[1:], corners[0]), strict=True)
        )
    ) * 0.5


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def _inset_corners(
    corners: tuple[tuple[float, float], ...],
    ratio: float,
) -> tuple[tuple[float, float], ...]:
    if not 0.0 <= ratio <= 0.05:
        raise ValueError("L’inset de redressement doit être compris entre 0 et 0,05")
    center_x = sum(point[0] for point in corners) / 4.0
    center_y = sum(point[1] for point in corners) / 4.0
    return tuple(
        (
            x + (center_x - x) * ratio,
            y + (center_y - y) * ratio,
        )
        for x, y in corners
    )


def _refine_edge(profile: np.ndarray, estimate: int, radius: int) -> int:
    start = max(0, estimate - radius)
    end = min(profile.size, estimate + radius + 1)
    if end <= start:
        return estimate
    local = profile[start:end]
    position = int(np.argmax(local))
    if float(local[position]) < 10.0:
        return estimate
    return start + position


def detect_artwork_quad(
    image: Image.Image,
    *,
    analysis_max_edge: int = 720,
    inset_ratio: float = 0.003,
    max_output_edge: int = 2048,
) -> ArtworkRectification:
    source = image.convert("RGB")
    source_width, source_height = source.size
    scale = min(1.0, analysis_max_edge / max(source_width, source_height))
    analysis_width = max(64, round(source_width * scale))
    analysis_height = max(64, round(source_height * scale))
    analysis = source.resize(
        (analysis_width, analysis_height),
        Image.Resampling.LANCZOS,
    )
    pixels = np.asarray(analysis, dtype=np.uint8)
    band = max(2, round(min(analysis_width, analysis_height) * 0.012))
    prototypes = _border_prototypes(pixels, band)
    distances = _distance_to_background(pixels, prototypes)
    float_pixels = pixels.astype(np.float32)
    gradient_x = np.zeros((analysis_height, analysis_width), dtype=np.float32)
    gradient_y = np.zeros((analysis_height, analysis_width), dtype=np.float32)
    gradient_x[:, 1:-1] = np.linalg.norm(
        float_pixels[:, 2:] - float_pixels[:, :-2], axis=2
    )
    gradient_y[1:-1] = np.linalg.norm(
        float_pixels[2:] - float_pixels[:-2], axis=2
    )
    border_distances = np.concatenate(
        (
            distances[:band].ravel(),
            distances[-band:].ravel(),
            distances[:, :band].ravel(),
            distances[:, -band:].ravel(),
        )
    )
    threshold = float(np.clip(np.percentile(border_distances, 99.0) + 10.0, 22.0, 58.0))
    raw_mask = distances > threshold
    mask_image = Image.fromarray(raw_mask.astype(np.uint8) * 255, "L")
    closing = max(5, round(min(analysis_width, analysis_height) * 0.018))
    if closing % 2 == 0:
        closing += 1
    mask_image = mask_image.filter(ImageFilter.MaxFilter(closing))
    mask_image = mask_image.filter(ImageFilter.MinFilter(closing))
    mask = np.asarray(mask_image, dtype=np.uint8) > 0

    row_run = _longest_run(mask.sum(axis=1) >= max(10, analysis_width * 0.18))
    column_run = _longest_run(mask.sum(axis=0) >= max(10, analysis_height * 0.18))
    if row_run is None or column_run is None:
        raise ValueError("Aucun contour d’œuvre rectangulaire suffisamment grand n’a été détecté")
    y0, y1 = row_run
    x0, x1 = column_run
    box_width = x1 - x0
    box_height = y1 - y0
    if box_width < analysis_width * 0.2 or box_height < analysis_height * 0.2:
        raise ValueError("Le contour détecté est trop petit pour être une œuvre")

    horizontal_positions: list[int] = []
    top_values: list[int] = []
    bottom_values: list[int] = []
    edge_search = max(4, round(min(analysis_width, analysis_height) * 0.025))
    for x in range(x0, x1):
        positions = np.flatnonzero(mask[y0:y1, x])
        if positions.size:
            top_estimate = y0 + int(positions[0])
            bottom_estimate = y0 + int(positions[-1])
            top = _refine_edge(gradient_y[:, x], top_estimate, edge_search)
            bottom = _refine_edge(gradient_y[:, x], bottom_estimate, edge_search)
            if top <= y0 + box_height * 0.35 and bottom >= y1 - box_height * 0.35:
                horizontal_positions.append(x)
                top_values.append(top)
                bottom_values.append(bottom)

    vertical_positions: list[int] = []
    left_values: list[int] = []
    right_values: list[int] = []
    for y in range(y0, y1):
        positions = np.flatnonzero(mask[y, x0:x1])
        if positions.size:
            left_estimate = x0 + int(positions[0])
            right_estimate = x0 + int(positions[-1])
            left = _refine_edge(gradient_x[y], left_estimate, edge_search)
            right = _refine_edge(gradient_x[y], right_estimate, edge_search)
            if left <= x0 + box_width * 0.35 and right >= x1 - box_width * 0.35:
                vertical_positions.append(y)
                left_values.append(left)
                right_values.append(right)

    horizontal = np.asarray(horizontal_positions, dtype=np.float64)
    vertical = np.asarray(vertical_positions, dtype=np.float64)
    top_line = _robust_line(horizontal, np.asarray(top_values, dtype=np.float64))
    bottom_line = _robust_line(horizontal, np.asarray(bottom_values, dtype=np.float64))
    left_line = _robust_line(vertical, np.asarray(left_values, dtype=np.float64))
    right_line = _robust_line(vertical, np.asarray(right_values, dtype=np.float64))
    scaled_corners = (
        _intersection(top_line, left_line),
        _intersection(top_line, right_line),
        _intersection(bottom_line, right_line),
        _intersection(bottom_line, left_line),
    )
    area = _quad_area(scaled_corners)
    if area <= 0.0:
        raise ValueError("Le contour détecté ne forme pas un quadrilatère convexe")
    area_fraction = area / (analysis_width * analysis_height)
    if not 0.08 <= area_fraction <= 0.98:
        raise ValueError("La surface détectée n’est pas plausible pour une œuvre")

    mean_residual = float(
        np.mean(
            [
                top_line.residual,
                bottom_line.residual,
                left_line.residual,
                right_line.residual,
            ]
        )
    )
    support_ratio = min(
        1.0,
        (
            top_line.support
            + bottom_line.support
            + left_line.support
            + right_line.support
        )
        / max(1.0, 2.0 * box_width + 2.0 * box_height),
    )
    foreground_coverage = float(np.mean(mask[y0:y1, x0:x1]))
    residual_score = max(
        0.0,
        1.0 - mean_residual / max(2.0, min(analysis_width, analysis_height) * 0.018),
    )
    coverage_score = min(1.0, foreground_coverage / 0.55)
    area_score = min(1.0, area_fraction / 0.35)
    confidence = float(
        np.clip(
            residual_score * 0.5
            + support_ratio * 0.25
            + coverage_score * 0.15
            + area_score * 0.1,
            0.0,
            1.0,
        )
    )

    full_corners = tuple(
        (x / scale, y / scale)
        for x, y in scaled_corners
    )
    full_corners = _inset_corners(full_corners, inset_ratio)
    top_left, top_right, bottom_right, bottom_left = full_corners
    natural_width = (_distance(top_left, top_right) + _distance(bottom_left, bottom_right)) / 2.0
    natural_height = (_distance(top_left, bottom_left) + _distance(top_right, bottom_right)) / 2.0
    output_scale = min(1.0, max_output_edge / max(natural_width, natural_height))
    output_width = max(64, round(natural_width * output_scale))
    output_height = max(64, round(natural_height * output_scale))
    background = tuple(int(round(value)) for value in np.median(prototypes, axis=0))
    return ArtworkRectification(
        source_width,
        source_height,
        full_corners,
        output_width,
        output_height,
        confidence,
        background,
        threshold,
        foreground_coverage,
        mean_residual / scale,
    ).validate()


def _perspective_coefficients(
    output_width: int,
    output_height: int,
    corners: tuple[tuple[float, float], ...],
) -> tuple[float, ...]:
    destinations = (
        (0.0, 0.0),
        (float(output_width - 1), 0.0),
        (float(output_width - 1), float(output_height - 1)),
        (0.0, float(output_height - 1)),
    )
    matrix: list[list[float]] = []
    values: list[float] = []
    for (x, y), (u, v) in zip(destinations, corners, strict=True):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        values.append(u)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        values.append(v)
    coefficients = np.linalg.solve(
        np.asarray(matrix, dtype=np.float64),
        np.asarray(values, dtype=np.float64),
    )
    return tuple(float(value) for value in coefficients)


def rectify_image(
    image: Image.Image,
    rectification: ArtworkRectification,
) -> Image.Image:
    record = rectification.validate()
    coefficients = _perspective_coefficients(
        record.output_width,
        record.output_height,
        record.corners,
    )
    return image.convert("RGB").transform(
        (record.output_width, record.output_height),
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
    )


def _atomic_image(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}{destination.suffix}")
    try:
        image.save(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(destination: Path, payload: dict[str, Any]) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def rectify_artwork(
    source: str | Path,
    destination: str | Path,
    *,
    manifest_path: str | Path | None = None,
    preview_path: str | Path | None = None,
    minimum_confidence: float = 0.62,
    inset_ratio: float = 0.003,
    max_output_edge: int = 2048,
) -> ArtworkRectification:
    source_path = Path(source).resolve(strict=True)
    image, _inspection = load_normalized_image(source_path)
    record = detect_artwork_quad(
        image,
        inset_ratio=inset_ratio,
        max_output_edge=max_output_edge,
    )
    if record.confidence < minimum_confidence:
        raise ValueError(
            "Contour d’œuvre trop incertain pour un redressement automatique "
            f"({record.confidence:.2f} < {minimum_confidence:.2f})"
        )
    output = Path(destination)
    _atomic_image(rectify_image(image, record), output)
    if manifest_path is not None:
        manifest = Path(manifest_path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            manifest,
            {
                "source": source_path.name,
                "output": output.name,
                **record.to_dict(),
            },
        )
    if preview_path is not None:
        preview = image.copy()
        draw = ImageDraw.Draw(preview, "RGBA")
        polygon = [*record.corners, record.corners[0]]
        width = max(3, round(max(image.size) / 450))
        draw.line(polygon, fill=(40, 230, 170, 255), width=width, joint="curve")
        for index, (x, y) in enumerate(record.corners, start=1):
            radius = width * 2
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 210, 60, 255))
            draw.text((x + radius, y + radius), str(index), fill=(18, 18, 22, 255))
        _atomic_image(preview, Path(preview_path))
    return record

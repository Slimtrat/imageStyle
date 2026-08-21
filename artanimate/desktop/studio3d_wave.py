from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry

from ..core.config import DIRECTIONS, RenderConfig


@dataclass(frozen=True, slots=True)
class OrganicWaveSettings:
    """Validated bridge between the Wave effect and its 3D geometry."""

    amplitude: float = 0.055
    frequency: float = 2.7
    turbulence: float = 0.10
    soft_edge: float = 0.012
    density_contrast: float = 0.65

    @classmethod
    def from_config(cls, config: RenderConfig) -> "OrganicWaveSettings":
        """Create the physical settings from one validated render config."""
        config.validate()
        return cls(
            amplitude=config.wave_amplitude,
            frequency=config.wave_frequency,
            turbulence=config.turbulence,
            soft_edge=config.soft_edge,
            density_contrast=config.wave_density_contrast,
        )


def artwork_dimensions(aspect: float) -> tuple[float, float]:
    """Match the exact QML artwork footprint for a source aspect ratio."""
    normalized = max(0.01, float(aspect))
    if normalized >= 1.0:
        width = min(360.0, 210.0 * normalized)
        return width, width / normalized
    return 210.0 * normalized, 210.0


def pigment_density(rgb: np.ndarray) -> np.ndarray:
    """Estimate physical pigment density from normalized RGB samples.

    Dark pigments carry more body. Saturated and blue-dominant pigments gain
    a smaller weight so adjacent colors do not travel as one rigid sheet.
    """
    color = np.asarray(rgb, dtype=np.float32)
    luminance = (
        color[..., 0] * 0.2126
        + color[..., 1] * 0.7152
        + color[..., 2] * 0.0722
    )
    saturation = color.max(axis=-1) - color.min(axis=-1)
    cool_weight = np.maximum(0.0, color[..., 2] - color[..., 0] * 0.62)
    return np.clip(
        0.18 + (1.0 - luminance) * 0.52
        + saturation * 0.18 + cool_weight * 0.22,
        0.0,
        1.0,
    )


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    t = float(np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0))
    return t * t * (3.0 - 2.0 * t)


class OrganicWaveGeometry(QQuick3DGeometry):
    """Dense, dynamic artwork mesh with source-color-dependent viscosity."""

    columns = 96
    rows = 64
    _float_size = 4
    _stride_floats = 8  # position xyz, normal xyz, UV

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = OrganicWaveSettings()
        self._direction = "left"
        self._progress = 0.0
        self._width, self._depth = artwork_dimensions(1.6)
        self._u, self._v = np.meshgrid(
            np.linspace(0.0, 1.0, self.columns, dtype=np.float32),
            np.linspace(0.0, 1.0, self.rows, dtype=np.float32),
        )
        self._density = np.full((self.rows, self.columns), 0.5, dtype=np.float32)
        self._heights = np.zeros_like(self._density)
        self._initialize_topology()
        self._rebuild()

    @property
    def maximum_height(self) -> float:
        return float(self._heights.max(initial=0.0))

    @property
    def density_range(self) -> tuple[float, float]:
        return float(self._density.min()), float(self._density.max())

    def _initialize_topology(self) -> None:
        indices = np.empty(
            (self.rows - 1) * (self.columns - 1) * 6,
            dtype=np.uint16,
        )
        cursor = 0
        for row in range(self.rows - 1):
            for column in range(self.columns - 1):
                top_left = row * self.columns + column
                top_right = top_left + 1
                bottom_left = top_left + self.columns
                bottom_right = bottom_left + 1
                indices[cursor : cursor + 6] = (
                    top_left,
                    top_right,
                    bottom_left,
                    top_right,
                    bottom_right,
                    bottom_left,
                )
                cursor += 6

        self.clear()
        self.setStride(self._stride_floats * self._float_size)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.setIndexData(indices.tobytes())
        component = QQuick3DGeometry.Attribute.ComponentType
        semantic = QQuick3DGeometry.Attribute.Semantic
        self.addAttribute(semantic.PositionSemantic, 0, component.F32Type)
        self.addAttribute(semantic.NormalSemantic, 3 * self._float_size, component.F32Type)
        self.addAttribute(semantic.TexCoord0Semantic, 6 * self._float_size, component.F32Type)
        self.addAttribute(semantic.IndexSemantic, 0, component.U16Type)

    def configure(
        self,
        settings: OrganicWaveSettings,
        direction: str,
    ) -> None:
        if direction not in DIRECTIONS:
            raise ValueError(f"Direction de vague 3D inconnue : {direction}")
        self._settings = settings
        self._direction = direction
        self._rebuild()

    def set_dimensions(self, width: float, depth: float) -> None:
        width = max(1.0, float(width))
        depth = max(1.0, float(depth))
        if abs(width - self._width) < 0.01 and abs(depth - self._depth) < 0.01:
            return
        self._width = width
        self._depth = depth
        self._rebuild()

    def set_progress(self, progress: float) -> None:
        value = float(np.clip(progress, 0.0, 1.0))
        if abs(value - self._progress) < 1e-6:
            return
        self._progress = value
        self._rebuild()

    def set_source(self, image: QImage) -> None:
        if image.isNull():
            return
        scaled = image.scaled(
            self.columns,
            self.rows,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).convertToFormat(QImage.Format.Format_RGBA8888)
        raw = np.frombuffer(
            scaled.constBits(),
            dtype=np.uint8,
            count=scaled.sizeInBytes(),
        ).reshape(self.rows, scaled.bytesPerLine())
        rgb = raw[:, : self.columns * 4].reshape(self.rows, self.columns, 4)[..., :3]
        density = pigment_density(rgb.astype(np.float32) / 255.0)
        padded = np.pad(density, 1, mode="edge")
        self._density = (
            padded[1:-1, 1:-1] * 0.44
            + padded[1:-1, 2:] * 0.14
            + padded[1:-1, :-2] * 0.14
            + padded[2:, 1:-1] * 0.14
            + padded[:-2, 1:-1] * 0.14
        ).astype(np.float32)
        self._rebuild()

    def _direction_coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        if self._direction == "right":
            return 1.0 - self._u, self._v
        if self._direction == "top":
            return self._v, self._u
        if self._direction == "bottom":
            return 1.0 - self._v, self._u
        if self._direction == "diagonal":
            return (self._u + self._v) * 0.5, (self._u - self._v) * 0.5
        if self._direction == "radial":
            radial_x = self._u - 0.5
            radial_y = self._v - 0.5
            return (
                np.hypot(radial_x, radial_y) / np.sqrt(0.5),
                np.arctan2(radial_y, radial_x) / (2.0 * np.pi),
            )
        return self._u, self._v

    def _flow_direction(self) -> tuple[np.ndarray, np.ndarray]:
        shape = self._u.shape
        if self._direction == "right":
            return -np.ones(shape, dtype=np.float32), np.zeros(shape, dtype=np.float32)
        if self._direction == "top":
            return np.zeros(shape, dtype=np.float32), np.ones(shape, dtype=np.float32)
        if self._direction == "bottom":
            return np.zeros(shape, dtype=np.float32), -np.ones(shape, dtype=np.float32)
        if self._direction == "diagonal":
            value = np.float32(1.0 / np.sqrt(2.0))
            return np.full(shape, value), np.full(shape, value)
        if self._direction == "radial":
            radial_x = self._u - 0.5
            radial_y = self._v - 0.5
            length = np.maximum(np.hypot(radial_x, radial_y), 1e-4)
            return radial_x / length, radial_y / length
        return np.ones(shape, dtype=np.float32), np.zeros(shape, dtype=np.float32)

    def _rebuild(self) -> None:
        settings = self._settings
        axis, across = self._direction_coordinates()
        noise = (
            np.sin(self._u * 31.7 + self._v * 19.3 + self._progress * 5.1) * 0.52
            + np.sin(self._u * 73.1 - self._v * 41.9 - self._progress * 3.7) * 0.29
            + np.cos(self._u * 17.3 + self._v * 67.7 + self._progress * 2.2) * 0.19
        )
        oscillation = np.sin(
            across * settings.frequency * 2.0 * np.pi + axis * np.pi
        ) * settings.amplitude
        density_lag = (self._density - 0.5) * settings.density_contrast * 0.16
        field = axis + oscillation + noise * settings.turbulence * 0.24 + density_lag
        distance_to_front = self._progress - field
        front_width = 0.045 + settings.soft_edge * 3.1 + settings.turbulence * 0.045
        crest = np.exp(-np.square(distance_to_front / front_width))
        shoulder = np.exp(-np.square((distance_to_front - 0.10) / (front_width * 1.85)))
        filament = np.exp(-np.square((distance_to_front + 0.075) / (front_width * 0.72)))
        mass = np.clip(crest + shoulder * 0.42 + filament * 0.13, 0.0, 1.35)
        activity = _smoothstep(0.005, 0.055, self._progress) * (
            1.0 - _smoothstep(0.88, 0.995, self._progress)
        )
        height_scale = 14.0 + settings.amplitude * 220.0 + settings.turbulence * 35.0
        density_body = 0.72 + self._density * 0.62
        breathing = 1.0 + np.sin(
            (self._u + self._v) * 12.0 + self._progress * 8.0
        ) * 0.055
        self._heights = (mass * height_scale * density_body * breathing * activity).astype(
            np.float32
        )

        direction_x, direction_y = self._flow_direction()
        tangent_x, tangent_y = -direction_y, direction_x
        curl = np.sin(
            across * settings.frequency * 2.0 * np.pi
            + self._density * 4.7 + self._progress * 7.0
        )
        push = mass * (2.8 + self._density * 3.6) * activity
        curl_push = mass * curl * (1.2 + settings.turbulence * 8.0) * activity
        position_x = (
            (self._u - 0.5) * self._width
            + direction_x * push + tangent_x * curl_push
        )
        position_y = (
            (self._v - 0.5) * self._depth
            + direction_y * push + tangent_y * curl_push
        )

        step_y = self._depth / max(1, self.rows - 1)
        step_x = self._width / max(1, self.columns - 1)
        gradient_y, gradient_x = np.gradient(self._heights, step_y, step_x)
        normal_x = -gradient_x
        normal_y = -gradient_y
        normal_z = np.ones_like(self._heights)
        normal_length = np.sqrt(normal_x**2 + normal_y**2 + normal_z**2)

        vertices = np.empty(
            (self.rows, self.columns, self._stride_floats),
            dtype=np.float32,
        )
        vertices[..., 0] = position_x
        vertices[..., 1] = position_y
        vertices[..., 2] = self._heights
        vertices[..., 3] = normal_x / normal_length
        vertices[..., 4] = normal_y / normal_length
        vertices[..., 5] = normal_z / normal_length
        vertices[..., 6] = self._u
        vertices[..., 7] = self._v
        self.setVertexData(vertices.tobytes())
        margin = 18.0
        self.setBounds(
            QVector3D(-self._width / 2 - margin, -self._depth / 2 - margin, -1.0),
            QVector3D(
                self._width / 2 + margin,
                self._depth / 2 + margin,
                max(1.0, self.maximum_height + 8.0),
            ),
        )
        self.update()

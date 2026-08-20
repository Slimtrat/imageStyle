from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..core.effects import EffectCapability
from ..core.renderer import ArtworkRenderer


@dataclass(frozen=True, slots=True)
class StudioParticleRecord:
    """One 3D pigment grain tied to an exact analyzed source pixel."""

    target_u: float
    target_v: float
    color: tuple[int, int, int]
    birth_progress: float
    settle_progress: float
    drift_x: float
    drift_z: float
    size: float


@dataclass(frozen=True, slots=True)
class StudioSceneData:
    """Analysis metadata shared by the interactive preview and final export."""

    particles: tuple[StudioParticleRecord, ...]
    stage_count: int
    outline_stage: int


def _inverse_ease(values: np.ndarray) -> np.ndarray:
    """Numerically invert the renderer's quintic easing in a vectorized pass."""
    target = np.clip(values.astype(np.float32), 0.0, 1.0)
    lower = np.zeros_like(target)
    upper = np.ones_like(target)
    for _ in range(18):
        middle = (lower + upper) * 0.5
        eased = middle**3 * (middle * (middle * 6.0 - 15.0) + 10.0)
        lower = np.where(eased < target, middle, lower)
        upper = np.where(eased >= target, middle, upper)
    return (lower + upper) * 0.5


def build_studio_scene_data(
    renderer: ArtworkRenderer,
    particle_count: int = 240,
) -> StudioSceneData:
    """Map 3D grains to true pixels and to their true 2D settling instants."""
    outline_stage = next(
        (index for index, layer in enumerate(renderer.stages) if layer.is_outline),
        -1,
    )
    if not renderer.effect.supports(EffectCapability.FALLING_PARTICLES):
        return StudioSceneData((), len(renderer.stages), outline_stage)

    height, width = renderer.analysis.source.shape[:2]
    settlement = np.full((height, width), np.nan, dtype=np.float32)
    stride = renderer.stage_stride()
    timeline = 1.0 + max(0, len(renderer.stages) - 1) * stride
    staged_keys: set[str] = set()
    for index, layer in enumerate(renderer.stages):
        staged_keys.add(layer.key)
        local = _inverse_ease(renderer.fields[layer.key])
        global_time = (local + index * stride) / timeline
        settlement[layer.mask] = global_time[layer.mask]

    outline = renderer.analysis.outline
    if outline is not None and outline.key not in staged_keys:
        settlement[outline.mask] = renderer.fields[outline.key][outline.mask]

    coordinates = np.argwhere(np.isfinite(settlement))
    if not len(coordinates) or particle_count <= 0:
        return StudioSceneData((), len(renderer.stages), outline_stage)
    rng = np.random.default_rng(renderer.config.seed + 104729)
    count = min(int(particle_count), len(coordinates))
    selected = coordinates[rng.choice(len(coordinates), size=count, replace=False)]
    records: list[StudioParticleRecord] = []
    for y, x in selected:
        settle = float(settlement[y, x])
        flight = float(rng.uniform(0.10, 0.19))
        records.append(
            StudioParticleRecord(
                target_u=(float(x) + 0.5) / width,
                target_v=(float(y) + 0.5) / height,
                color=tuple(int(channel) for channel in renderer.analysis.source[y, x]),
                birth_progress=max(0.0, settle - flight),
                settle_progress=settle,
                drift_x=float(rng.uniform(-12.0, 12.0)),
                drift_z=float(rng.uniform(-9.0, 9.0)),
                size=float(rng.uniform(0.48, 0.92)),
            )
        )
    return StudioSceneData(tuple(records), len(renderer.stages), outline_stage)


class StudioParticleModel(QAbstractListModel):
    """Qt model exposing verified pigment data to the QML 3D scene."""

    TARGET_U = int(Qt.ItemDataRole.UserRole) + 1
    TARGET_V = TARGET_U + 1
    PARTICLE_COLOR = TARGET_U + 2
    BIRTH_PROGRESS = TARGET_U + 3
    SETTLE_PROGRESS = TARGET_U + 4
    DRIFT_X = TARGET_U + 5
    DRIFT_Z = TARGET_U + 6
    PARTICLE_SIZE = TARGET_U + 7

    def __init__(self) -> None:
        super().__init__()
        self._records: tuple[StudioParticleRecord, ...] = ()

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 - Qt API
        return {
            self.TARGET_U: b"targetU",
            self.TARGET_V: b"targetV",
            self.PARTICLE_COLOR: b"particleColor",
            self.BIRTH_PROGRESS: b"birthProgress",
            self.SETTLE_PROGRESS: b"settleProgress",
            self.DRIFT_X: b"driftX",
            self.DRIFT_Z: b"driftZ",
            self.PARTICLE_SIZE: b"particleSize",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        item = self._records[index.row()]
        values = {
            self.TARGET_U: item.target_u,
            self.TARGET_V: item.target_v,
            self.PARTICLE_COLOR: QColor(*item.color),
            self.BIRTH_PROGRESS: item.birth_progress,
            self.SETTLE_PROGRESS: item.settle_progress,
            self.DRIFT_X: item.drift_x,
            self.DRIFT_Z: item.drift_z,
            self.PARTICLE_SIZE: item.size,
        }
        return values.get(role)

    def replace(self, records: tuple[StudioParticleRecord, ...]) -> None:
        self.beginResetModel()
        self._records = tuple(records)
        self.endResetModel()

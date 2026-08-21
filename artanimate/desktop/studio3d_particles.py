from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..core.effects import EffectCapability
from ..core.effects.contour_paths import sample_laser_path
from ..core.effects.paint_drop import paint_drop_target
from ..core.quality import ease_in_out
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
    origin_u: float = 0.0
    origin_v: float = 0.0
    overshoot_u: float = 0.0
    overshoot_v: float = 0.0
    curl_u: float = 0.0
    curl_v: float = 0.0
    motion_phase: float = 0.0


@dataclass(frozen=True, slots=True)
class StudioToolStageRecord:
    """One physical tool target derived from an analyzed renderer stage."""

    target_u: float
    target_v: float
    color: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class StudioLaserPathRecord:
    """One uniformly timed position on the analyzed contour route."""

    target_u: float
    target_v: float
    laser_on: bool


@dataclass(frozen=True, slots=True)
class StudioSceneData:
    """Analysis metadata shared by the interactive preview and final export."""

    particles: tuple[StudioParticleRecord, ...]
    stage_count: int
    outline_stage: int
    tool_stages: tuple[StudioToolStageRecord, ...] = ()
    paint_drop_size: float = 0.12
    paint_fall_ratio: float = 0.38
    laser_path: tuple[StudioLaserPathRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class StudioLaserCursor:
    """Exact artwork-local cursor published to the QML sky ray."""

    target_u: float = 0.5
    target_v: float = 0.5
    beam_on: bool = False


def studio_laser_cursor(
    data: StudioSceneData | None,
    effect: str,
    global_progress: float,
) -> StudioLaserCursor:
    """Resolve the laser cursor on the renderer's exact eased stage timeline.

    The beam is disabled across connector segments between detected shapes. This
    prevents a visible diagonal jump from being mistaken for a drawn contour.
    """
    if data is None or len(data.laser_path) < 2:
        return StudioLaserCursor()
    progress = float(np.clip(global_progress, 0.0, 1.0))
    active = effect == "contour_laser"
    local_linear = progress
    if effect == "screenprint_laser":
        stage_count = max(1, data.stage_count)
        timeline = min(stage_count - 0.0001, progress * stage_count)
        stage = int(np.floor(timeline))
        active = stage == data.outline_stage
        local_linear = timeline - stage
    if not active:
        return StudioLaserCursor(beam_on=False)

    local_progress = ease_in_out(local_linear)
    path_position = local_progress * (len(data.laser_path) - 1)
    index = min(len(data.laser_path) - 2, max(0, int(np.floor(path_position))))
    mix = path_position - index
    before = data.laser_path[index]
    after = data.laser_path[index + 1]
    return StudioLaserCursor(
        target_u=before.target_u + (after.target_u - before.target_u) * mix,
        target_v=before.target_v + (after.target_v - before.target_v) * mix,
        beam_on=(
            0.005 < local_progress < 0.995
            and before.laser_on
            and after.laser_on
        ),
    )


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
    particle_count: int = 720,
) -> StudioSceneData:
    """Map 3D grains to true pixels and to their true 2D settling instants."""
    outline_stage = next(
        (index for index, layer in enumerate(renderer.stages) if layer.is_outline),
        -1,
    )
    height, width = renderer.analysis.source.shape[:2]
    tool_stages: tuple[StudioToolStageRecord, ...] = ()
    if renderer.config.effect == "paint_drop":
        records: list[StudioToolStageRecord] = []
        for layer in renderer.stages:
            x, y = paint_drop_target(layer.mask)
            records.append(
                StudioToolStageRecord(
                    target_u=(x + 0.5) / width,
                    target_v=(y + 0.5) / height,
                    color=tuple(int(channel) for channel in layer.color),
                )
            )
        tool_stages = tuple(records)

    laser_path: tuple[StudioLaserPathRecord, ...] = ()
    if renderer.config.effect in {"contour_laser", "screenprint_laser"}:
        laser_stage = next(
            (layer for layer in renderer.stages if layer.is_outline),
            None,
        )
        if laser_stage is not None:
            laser_path = tuple(
                StudioLaserPathRecord(
                    target_u=(point.x + 0.5) / width,
                    target_v=(point.y + 0.5) / height,
                    laser_on=point.laser_on,
                )
                for point in sample_laser_path(laser_stage.mask)
            )

    def scene(particles: tuple[StudioParticleRecord, ...]) -> StudioSceneData:
        return StudioSceneData(
            particles=particles,
            stage_count=len(renderer.stages),
            outline_stage=outline_stage,
            tool_stages=tool_stages,
            paint_drop_size=renderer.config.paint_drop_size,
            paint_fall_ratio=renderer.config.paint_fall_ratio,
            laser_path=laser_path,
        )

    if renderer.effect.supports(EffectCapability.TARGETED_PARTICLES):
        bank = next(iter(renderer.particles.values()), None)
        if bank is None or particle_count <= 0:
            return scene(())
        if (
            bank.origin_x is None
            or bank.origin_y is None
            or bank.overshoot_x is None
            or bank.overshoot_y is None
            or bank.curl_x is None
            or bank.curl_y is None
        ):
            raise ValueError("La banque de pigments ciblés est incomplète")
        available = len(bank.target_x)
        count = min(int(particle_count), available)
        rng = np.random.default_rng(renderer.config.seed + 104729)
        selected = np.sort(rng.choice(available, size=count, replace=False))
        records: list[StudioParticleRecord] = []
        for index in selected:
            phase = float(bank.phase[index])
            records.append(
                StudioParticleRecord(
                    target_u=(float(bank.target_x[index]) + 0.5) / width,
                    target_v=(float(bank.target_y[index]) + 0.5) / height,
                    color=tuple(int(channel) for channel in bank.colors[index]),
                    birth_progress=max(
                        0.0,
                        float(bank.settle[index] - bank.flight[index]),
                    ),
                    settle_progress=float(bank.settle[index]),
                    drift_x=float(bank.sway[index]),
                    drift_z=0.0,
                    size=0.62 + 0.34 * (0.5 + 0.5 * np.sin(phase * 1.71)),
                    origin_u=(float(bank.origin_x[index]) + 0.5) / width,
                    origin_v=(float(bank.origin_y[index]) + 0.5) / height,
                    overshoot_u=float(bank.overshoot_x[index]) / width,
                    overshoot_v=float(bank.overshoot_y[index]) / height,
                    curl_u=float(bank.curl_x[index]) / width,
                    curl_v=float(bank.curl_y[index]) / height,
                    motion_phase=phase,
                )
            )
        return scene(tuple(records))

    if not renderer.effect.supports(EffectCapability.FALLING_PARTICLES):
        return scene(())

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
        return scene(())
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
    return scene(tuple(records))


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
    ORIGIN_U = TARGET_U + 8
    ORIGIN_V = TARGET_U + 9
    OVERSHOOT_U = TARGET_U + 10
    OVERSHOOT_V = TARGET_U + 11
    CURL_U = TARGET_U + 12
    CURL_V = TARGET_U + 13
    MOTION_PHASE = TARGET_U + 14

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
            self.ORIGIN_U: b"originU",
            self.ORIGIN_V: b"originV",
            self.OVERSHOOT_U: b"overshootU",
            self.OVERSHOOT_V: b"overshootV",
            self.CURL_U: b"curlU",
            self.CURL_V: b"curlV",
            self.MOTION_PHASE: b"motionPhase",
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
            self.ORIGIN_U: item.origin_u,
            self.ORIGIN_V: item.origin_v,
            self.OVERSHOOT_U: item.overshoot_u,
            self.OVERSHOOT_V: item.overshoot_v,
            self.CURL_U: item.curl_u,
            self.CURL_V: item.curl_v,
            self.MOTION_PHASE: item.motion_phase,
        }
        return values.get(role)

    def replace(self, records: tuple[StudioParticleRecord, ...]) -> None:
        self.beginResetModel()
        self._records = tuple(records)
        self.endResetModel()

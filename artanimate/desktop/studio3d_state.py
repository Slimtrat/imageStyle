from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from typing import Any, Mapping

from ..core.config import RenderConfig
from ..studio.clock import StudioClock
from ..studio.color_fidelity import ArtworkColorPolicy
from .studio3d_camera import CameraMotionTiming, camera_motion_timing, smootherstep
from .studio3d_particles import (
    StudioLaserCursor,
    StudioSceneData,
    studio_laser_cursor,
)
from .studio3d_wave import OrganicWaveSettings, artwork_dimensions


def _finite(value: float, where: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where} doit être fini")
    return number


def _quaternion_multiply(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    aw, ax, ay, az = first
    bw, bx, by, bz = second
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def _orientation_quaternion(
    pitch: float,
    yaw: float,
    roll: float,
) -> tuple[float, float, float, float]:
    half_x = math.radians(pitch) * 0.5
    half_y = math.radians(yaw) * 0.5
    half_z = math.radians(roll) * 0.5
    qx = (math.cos(half_x), math.sin(half_x), 0.0, 0.0)
    qy = (math.cos(half_y), 0.0, math.sin(half_y), 0.0)
    qz = (math.cos(half_z), 0.0, 0.0, math.sin(half_z))
    return _quaternion_multiply(qy, _quaternion_multiply(qx, qz))


def _slerp(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    weight: float,
) -> tuple[float, float, float, float]:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    target = second
    if dot < 0.0:
        dot = -dot
        target = tuple(-value for value in second)
    if dot > 0.9995:
        blended = tuple(
            a + (b - a) * weight
            for a, b in zip(first, target, strict=True)
        )
        length = math.sqrt(sum(value * value for value in blended))
        return tuple(value / length for value in blended)
    angle = math.acos(max(-1.0, min(1.0, dot)))
    scale = math.sin(angle)
    first_weight = math.sin((1.0 - weight) * angle) / scale
    second_weight = math.sin(weight * angle) / scale
    return tuple(
        a * first_weight + b * second_weight
        for a, b in zip(first, target, strict=True)
    )


def _rotation_matrix(
    quaternion: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float], ...]:
    w, x, y, z = quaternion
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def _euler_angles(
    matrix: tuple[tuple[float, float, float], ...],
) -> tuple[float, float, float]:
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -matrix[1][2]))))
    yaw = math.degrees(math.atan2(matrix[0][2], matrix[2][2]))
    roll = math.degrees(math.atan2(matrix[1][0], matrix[1][1]))
    return pitch, yaw, roll


@dataclass(frozen=True, slots=True)
class Studio3DCameraMatchSettings:
    start_frame: int
    end_frame: int
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float
    distance: float
    field_of_view: float

    def __post_init__(self) -> None:
        if self.start_frame < 0 or self.end_frame <= self.start_frame:
            raise ValueError("La fenêtre de raccord caméra 3D est invalide")
        for field, value in (
            ("camera.match.x", self.x),
            ("camera.match.y", self.y),
            ("camera.match.z", self.z),
            ("camera.match.pitch", self.pitch),
            ("camera.match.yaw", self.yaw),
            ("camera.match.roll", self.roll),
            ("camera.match.distance", self.distance),
            ("camera.match.field_of_view", self.field_of_view),
        ):
            _finite(value, field)
        if self.distance <= 0.0 or not 5.0 <= self.field_of_view <= 140.0:
            raise ValueError("La pose cible du raccord caméra 3D est invalide")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "Studio3DCameraMatchSettings":
        return cls(
            start_frame=int(values["start_frame"]),
            end_frame=int(values["end_frame"]),
            x=float(values["x"]),
            y=float(values["y"]),
            z=float(values["z"]),
            pitch=float(values["pitch"]),
            yaw=float(values["yaw"]),
            roll=float(values["roll"]),
            distance=float(values["distance"]),
            field_of_view=float(values["field_of_view"]),
        )

    def weight_at(self, frame_index: int) -> float:
        if frame_index <= self.start_frame:
            return 0.0
        if frame_index >= self.end_frame:
            return 1.0
        return smootherstep(
            (frame_index - self.start_frame) / (self.end_frame - self.start_frame)
        )


@dataclass(frozen=True, slots=True)
class Studio3DCameraSettings:
    """Authored camera controls captured independently from the live widget."""

    yaw: float = 0.0
    pitch: float = -78.0
    roll: float = 0.0
    distance: float = 560.0
    pivot_y: float = -8.0
    x: float = 0.0
    z: float = 0.0
    field_of_view: float = 39.0
    orbit_turns: float = 0.0
    motion: str = "flyover"
    motion_strength: float = 1.0
    match: Studio3DCameraMatchSettings | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("camera.yaw", self.yaw),
            ("camera.pitch", self.pitch),
            ("camera.roll", self.roll),
            ("camera.distance", self.distance),
            ("camera.pivot_y", self.pivot_y),
            ("camera.x", self.x),
            ("camera.z", self.z),
            ("camera.field_of_view", self.field_of_view),
            ("camera.orbit_turns", self.orbit_turns),
            ("camera.motion_strength", self.motion_strength),
        ):
            _finite(value, field)
        if self.distance <= 0.0:
            raise ValueError("camera.distance doit être strictement positive")
        if not 5.0 <= self.field_of_view <= 140.0:
            raise ValueError("camera.field_of_view doit être compris entre 5 et 140")
        if self.motion not in {"flyover", "top_drift", "fixed"}:
            raise ValueError(f"Mouvement caméra 3D inconnu : {self.motion!r}")
        if not 0.0 <= self.motion_strength <= 1.25:
            raise ValueError("camera.motion_strength doit être compris entre 0 et 1.25")

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, Any]
    ) -> "Studio3DCameraSettings":
        raw_match = values.get("match")
        match = (
            Studio3DCameraMatchSettings.from_mapping(raw_match)
            if isinstance(raw_match, Mapping)
            else None
        )
        return cls(
            yaw=float(values.get("yaw", 0.0)),
            pitch=float(values.get("pitch", -78.0)),
            roll=float(values.get("roll", 0.0)),
            distance=float(values.get("distance", 560.0)),
            pivot_y=float(values.get("pivot_y", -8.0)),
            x=float(values.get("x", 0.0)),
            z=float(values.get("z", 0.0)),
            field_of_view=float(values.get("field_of_view", 39.0)),
            orbit_turns=float(values.get("orbit_turns", 0.0)),
            motion=str(values.get("motion", "flyover")),
            motion_strength=float(values.get("motion_strength", 1.0)),
            match=match,
        )


@dataclass(frozen=True, slots=True)
class Studio3DSceneSettings:
    """Complete authored settings required to restore a Studio 3D shot."""

    effect: str
    rgb_mode: str
    direction: str
    camera: Studio3DCameraSettings
    lamp_brightness: float
    lamp_motion: float
    output_aspect: float
    wave: OrganicWaveSettings
    color_policy: ArtworkColorPolicy = ArtworkColorPolicy()

    def __post_init__(self) -> None:
        if not isinstance(self.effect, str) or not self.effect:
            raise ValueError("L’effet Studio 3D doit être renseigné")
        if not isinstance(self.rgb_mode, str) or not self.rgb_mode:
            raise ValueError("Le mode RGB Studio 3D doit être renseigné")
        if not isinstance(self.direction, str) or not self.direction:
            raise ValueError("La direction Studio 3D doit être renseignée")
        if not isinstance(self.camera, Studio3DCameraSettings):
            raise TypeError("La scène Studio 3D doit contenir ses réglages caméra")
        if _finite(self.lamp_brightness, "lamp_brightness") <= 0.0:
            raise ValueError("lamp_brightness doit être strictement positive")
        lamp_motion = _finite(self.lamp_motion, "lamp_motion")
        if not 0.0 <= lamp_motion <= 1.0:
            raise ValueError("lamp_motion doit être compris entre 0 et 1")
        if _finite(self.output_aspect, "output_aspect") <= 0.0:
            raise ValueError("output_aspect doit être strictement positif")
        if not isinstance(self.color_policy, ArtworkColorPolicy):
            raise TypeError("La scène 3D doit contenir sa politique colorimétrique")
        if not isinstance(self.wave, OrganicWaveSettings):
            raise TypeError("La scène Studio 3D doit contenir ses réglages de vague")

    @classmethod
    def from_config(
        cls,
        config: RenderConfig,
        *,
        camera: Mapping[str, Any] | Studio3DCameraSettings,
        output_aspect: float,
        color_policy: Mapping[str, Any] | str | ArtworkColorPolicy | None = None,
    ) -> "Studio3DSceneSettings":
        config.validate()
        camera_settings = (
            camera
            if isinstance(camera, Studio3DCameraSettings)
            else Studio3DCameraSettings.from_mapping(camera)
        )
        aspect = float(output_aspect)
        if aspect <= 0.0:
            raise ValueError("Le ratio de sortie 3D doit être strictement positif")
        direction = (
            config.halo_direction
            if config.effect == "vertical_halo"
            else config.direction
        )
        camera_values = camera if isinstance(camera, Mapping) else {}
        resolved_color_policy = (
            color_policy
            if isinstance(color_policy, ArtworkColorPolicy)
            else ArtworkColorPolicy.from_mapping(color_policy)
        )
        return cls(
            effect=config.effect,
            rgb_mode=config.rgb_mode,
            direction=direction,
            camera=camera_settings,
            lamp_brightness=float(camera_values.get("lamp", 2.4)),
            lamp_motion=float(camera_values.get("lamp_motion", 0.65)),
            output_aspect=aspect,
            wave=OrganicWaveSettings.from_config(config),
            color_policy=resolved_color_policy,
        )


@dataclass(frozen=True, slots=True)
class Studio3DCameraPose:
    """Resolved camera rig at one exact project frame."""

    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float
    distance: float
    field_of_view: float
    match_weight: float = 0.0


@dataclass(frozen=True, slots=True)
class Studio3DToolState:
    """Addressable state of the artwork-specific physical tool timeline."""

    stage: int
    linear_progress: float
    eased_progress: float
    is_outline: bool


@dataclass(frozen=True, slots=True)
class Studio3DSceneState:
    """Immutable restoration point for one frame of an artwork presentation."""

    frame_index: int
    frame_count: int
    time: Fraction
    timecode: str
    timeline_progress: float
    effect_progress: float
    artwork_aspect: float
    settings: Studio3DSceneSettings
    camera_timing: CameraMotionTiming
    camera_pose: Studio3DCameraPose
    tool: Studio3DToolState
    laser: StudioLaserCursor

    def qml_properties(self) -> dict[str, object]:
        """Return the complete frame-varying QML input state in one snapshot."""
        camera = self.settings.camera
        pose = self.camera_pose
        match = camera.match
        return {
            "artworkAspect": self.artwork_aspect,
            "cameraYaw": camera.yaw,
            "cameraPitch": camera.pitch,
            "cameraRoll": camera.roll,
            "cameraDistance": camera.distance,
            "cameraPivotY": camera.pivot_y,
            "cameraX": camera.x,
            "cameraZ": camera.z,
            "cameraFieldOfView": camera.field_of_view,
            "cameraOrbitTurns": camera.orbit_turns,
            "cameraMotion": camera.motion,
            "cameraMotionStrength": camera.motion_strength,
            "cameraMatchWeight": pose.match_weight,
            "cameraMatchX": match.x if match is not None else pose.x,
            "cameraMatchY": match.y if match is not None else pose.y,
            "cameraMatchZ": match.z if match is not None else pose.z,
            "cameraMatchPitch": match.pitch if match is not None else pose.pitch,
            "cameraMatchYaw": match.yaw if match is not None else pose.yaw,
            "cameraMatchRoll": match.roll if match is not None else pose.roll,
            "cameraMatchDistance": (
                match.distance if match is not None else pose.distance
            ),
            "cameraMatchFieldOfView": (
                match.field_of_view if match is not None else pose.field_of_view
            ),
            "cameraResolvedPoseEnabled": match is not None,
            "cameraResolvedX": pose.x,
            "cameraResolvedY": pose.y,
            "cameraResolvedZ": pose.z,
            "cameraResolvedPitch": pose.pitch,
            "cameraResolvedYaw": pose.yaw,
            "cameraResolvedRoll": pose.roll,
            "cameraResolvedDistance": pose.distance,
            "cameraResolvedFieldOfView": pose.field_of_view,
            "lampBrightness": self.settings.lamp_brightness,
            "lampMotion": self.settings.lamp_motion,
            "effectKind": self.settings.effect,
            "rgbMode": self.settings.rgb_mode,
            "effectDirection": self.settings.direction,
            "effectProgress": self.effect_progress,
            "laserCursorU": self.laser.target_u,
            "laserCursorV": self.laser.target_v,
            "laserCursorOn": self.laser.beam_on,
            "outputAspect": self.settings.output_aspect,
            **self.settings.color_policy.qml_properties(),
        }


def _as_fraction(value: float) -> Fraction:
    return Fraction(str(float(value)))


def _timeline_progress(clock: StudioClock, frame_index: int, frame_count: int) -> float:
    if frame_count < 2:
        raise ValueError("Une scène Studio 3D doit contenir au moins deux frames")
    if not 0 <= frame_index < frame_count:
        raise IndexError(f"Frame 3D {frame_index} hors plage 0 à {frame_count - 1}")
    elapsed = clock.frame_to_fraction(frame_index)
    span = clock.frame_to_fraction(frame_count - 1)
    return float(elapsed / span)


def effect_progress_at(
    config: RenderConfig,
    frame_index: int,
    frame_count: int,
    *,
    clock: StudioClock | None = None,
) -> float:
    """Resolve effect time from the exact Studio clock, excluding authored holds."""
    selected_clock = clock or StudioClock(config.fps)
    normalized = _timeline_progress(selected_clock, frame_index, frame_count)
    duration = _as_fraction(config.duration)
    seconds = duration * _as_fraction(normalized)
    active_start = _as_fraction(config.hold_start)
    active_end = duration - _as_fraction(config.hold_end)
    if seconds <= active_start:
        return 0.0
    if seconds >= active_end:
        return 1.0
    return float((seconds - active_start) / (active_end - active_start))


def _tool_state(
    effect: str,
    progress: float,
    scene_data: StudioSceneData | None,
) -> Studio3DToolState:
    stage_count = max(1, scene_data.stage_count if scene_data is not None else 1)
    outline_stage = scene_data.outline_stage if scene_data is not None else -1
    strict = effect in {"screenprint", "screenprint_laser", "paint_drop"}
    if strict:
        timeline = min(stage_count - 0.0001, progress * stage_count)
        stage = int(math.floor(timeline))
        linear = timeline - stage
        eased = smootherstep(linear)
    else:
        stage = 0
        linear = progress
        eased = progress
    return Studio3DToolState(
        stage=stage,
        linear_progress=linear,
        eased_progress=eased,
        is_outline=stage == outline_stage,
    )


def _camera_pose(
    settings: Studio3DSceneSettings,
    artwork_aspect: float,
    progress: float,
    timing: CameraMotionTiming,
    frame_index: int,
) -> Studio3DCameraPose:
    camera = settings.camera
    artwork_width, artwork_depth = artwork_dimensions(artwork_aspect)
    center_z = -8.0
    surface_y = -9.0
    flight = timing.flight_progress
    flyover = timing.flyover_weight
    drift = timing.drift_envelope
    rail_x = artwork_width * (
        -0.32 + 0.62 * flight + math.sin(flight * math.pi * 2.0) * 0.055
    )
    rail_z = center_z + artwork_depth * (0.30 - 0.52 * flight)
    rail_pitch = -25.0 - math.sin(flight * math.pi) * 4.0
    rail_yaw = -8.0 + math.sin(flight * math.pi * 1.15) * 13.0
    rail_distance = 330.0 - math.sin(flight * math.pi) * 15.0
    tangent = math.tan(math.radians(camera.field_of_view) * 0.5)
    fit_distance = max(
        camera.distance,
        artwork_width * 1.08 / (2.0 * tangent * max(0.2, settings.output_aspect)),
        artwork_depth * 1.08 / (2.0 * tangent),
    )
    wave = progress * math.pi * 2.0
    base = Studio3DCameraPose(
        x=(
            camera.x + rail_x * flyover
            + artwork_width * 0.075 * math.sin(wave) * drift
        ),
        y=camera.pivot_y + flyover * (surface_y + 3.0 - camera.pivot_y),
        z=camera.z + rail_z * flyover + artwork_depth * 0.055 * math.cos(wave) * drift,
        pitch=(
            camera.pitch
            + flyover * (rail_pitch - camera.pitch)
            - drift * 2.5 * math.sin(wave)
        ),
        yaw=(
            camera.yaw
            + flyover * (rail_yaw - camera.yaw)
            + drift * 4.0 * math.sin(wave)
            + camera.orbit_turns * 360.0 * progress
        ),
        roll=camera.roll,
        distance=fit_distance + flyover * (rail_distance - fit_distance) - drift * 26.0,
        field_of_view=camera.field_of_view + flyover * 7.0 + drift * 1.5,
    )
    match = camera.match
    if match is None:
        return base
    weight = match.weight_at(frame_index)
    if weight <= 0.0:
        return base

    def blend(first: float, second: float) -> float:
        return first + (second - first) * weight

    base_quaternion = _orientation_quaternion(base.pitch, base.yaw, base.roll)
    target_quaternion = _orientation_quaternion(match.pitch, match.yaw, match.roll)
    orientation = _slerp(base_quaternion, target_quaternion, weight)
    rotation = _rotation_matrix(orientation)
    pitch, yaw, roll = _euler_angles(rotation)

    def camera_position(
        x: float,
        y: float,
        z: float,
        distance: float,
        quaternion: tuple[float, float, float, float],
    ) -> tuple[float, float, float]:
        matrix = _rotation_matrix(quaternion)
        return (
            x + matrix[0][2] * distance,
            y + matrix[1][2] * distance,
            z + matrix[2][2] * distance,
        )

    base_position = camera_position(
        base.x, base.y, base.z, base.distance, base_quaternion
    )
    target_position = camera_position(
        match.x, match.y, match.z, match.distance, target_quaternion
    )
    position = tuple(
        blend(first, second)
        for first, second in zip(base_position, target_position, strict=True)
    )
    distance = blend(base.distance, match.distance)
    rig_position = (
        position[0] - rotation[0][2] * distance,
        position[1] - rotation[1][2] * distance,
        position[2] - rotation[2][2] * distance,
    )
    return Studio3DCameraPose(
        x=rig_position[0],
        y=rig_position[1],
        z=rig_position[2],
        pitch=pitch,
        yaw=yaw,
        roll=roll,
        distance=distance,
        field_of_view=blend(base.field_of_view, match.field_of_view),
        match_weight=weight,
    )


class Studio3DSceneStateResolver:
    """Pure random-access resolver shared by preview, export and timeline clips."""

    def __init__(
        self,
        config: RenderConfig,
        *,
        frame_count: int,
        artwork_aspect: float,
        settings: Studio3DSceneSettings,
        scene_data: StudioSceneData | None = None,
    ) -> None:
        config.validate()
        if frame_count < 2:
            raise ValueError("Une scène Studio 3D doit contenir au moins deux frames")
        if artwork_aspect <= 0.0:
            raise ValueError("Le ratio de l’œuvre doit être strictement positif")
        if config.fps != int(config.fps):
            raise ValueError("Le FPS du Studio 3D doit être entier")
        self._clock = StudioClock(int(config.fps))
        self._config = config.with_overrides({})
        if not isinstance(settings, Studio3DSceneSettings):
            raise TypeError("settings doit être un Studio3DSceneSettings")
        self._frame_count = int(frame_count)
        self._artwork_aspect = float(artwork_aspect)
        self._settings = settings
        self._scene_data = scene_data

    @property
    def clock(self) -> StudioClock:
        return self._clock

    def state_at(self, frame_index: int) -> Studio3DSceneState:
        normalized = _timeline_progress(
            self._clock, frame_index, self._frame_count
        )
        progress = effect_progress_at(
            self._config,
            frame_index,
            self._frame_count,
            clock=self._clock,
        )
        timing = camera_motion_timing(
            self._settings.camera.motion,
            progress,
            self._settings.camera.motion_strength,
        )
        return Studio3DSceneState(
            frame_index=frame_index,
            frame_count=self._frame_count,
            time=self._clock.frame_to_fraction(frame_index),
            timecode=self._clock.format_timecode(frame_index),
            timeline_progress=normalized,
            effect_progress=progress,
            artwork_aspect=self._artwork_aspect,
            settings=self._settings,
            camera_timing=timing,
            camera_pose=_camera_pose(
                self._settings,
                self._artwork_aspect,
                progress,
                timing,
                frame_index,
            ),
            tool=_tool_state(
                self._settings.effect,
                progress,
                self._scene_data,
            ),
            laser=studio_laser_cursor(
                self._scene_data,
                self._settings.effect,
                progress,
            ),
        )

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import Event
from typing import Any, Protocol

import numpy as np

from ..core.config import RenderConfig
from ..studio.artwork_source import (
    DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
    ArtworkTimedFrameSource,
    ArtworkTimedSourceFactory,
)
from ..studio.semantic import (
    FrozenJsonObject,
    RendererDescriptor,
    RendererEvaluation,
    RenderFrame,
    RenderRequest,
)
from ..studio.sources import validate_frame_index, validate_timed_frame
from .studio3d_particles import StudioSceneData, build_studio_scene_data
from .studio3d_state import (
    Studio3DSceneSettings,
    Studio3DSceneState,
    Studio3DSceneStateResolver,
)


STUDIO_3D_SETTINGS_SCHEMA_VERSION = 1
STUDIO_3D_TEXTURE_WIDTH = 720


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{where} doit être un objet")
    return value


def _render_config_for(request: RenderRequest) -> RenderConfig:
    parameters = request.invocation.parameters
    settings = _mapping(parameters.get("settings", FrozenJsonObject()), "settings 3D")
    version = settings.get("schema_version", STUDIO_3D_SETTINGS_SCHEMA_VERSION)
    if version != STUDIO_3D_SETTINGS_SCHEMA_VERSION:
        raise ValueError(f"Version de réglages Studio 3D non prise en charge : {version!r}")
    raw_config = _mapping(settings.get("render_config", {}), "settings.render_config")
    values = dict(raw_config)
    source_in = int(parameters.get("source_in_frame", 0))
    source_frames = source_in + request.invocation.duration_frames
    if "duration" not in values:
        values["duration"] = source_frames / request.constraints.fps
    duration = float(values["duration"])
    if "hold_start" not in values:
        values["hold_start"] = duration * 0.06
    if "hold_end" not in values:
        values["hold_end"] = duration * 0.10
    values.update(
        fps=request.constraints.fps,
        width=max(64, min(request.constraints.width, STUDIO_3D_TEXTURE_WIDTH)),
        quality=request.constraints.quality,
    )
    config = RenderConfig.from_dict(values)
    if max(2, int(round(config.duration * config.fps))) < source_frames:
        raise ValueError("Le clip 3D dépasse la durée de sa source de texture")
    return config


def _camera_settings_for(request: RenderRequest) -> dict[str, float | str]:
    settings = _mapping(
        request.invocation.parameters.get("settings", FrozenJsonObject()),
        "settings 3D",
    )
    raw_camera = _mapping(settings.get("camera", {}), "settings.camera")
    camera: dict[str, float | str] = {
        str(key): value for key, value in raw_camera.items()
    }
    if "lamp_brightness" in settings:
        camera["lamp"] = float(settings["lamp_brightness"])
    if "lamp_motion" in settings:
        camera["lamp_motion"] = float(settings["lamp_motion"])
    return camera


def _state_metadata(state: Studio3DSceneState) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "frame_index": state.frame_index,
            "source_frame_count": state.frame_count,
            "timecode": state.timecode,
            "timeline_progress": state.timeline_progress,
            "effect_progress": state.effect_progress,
            "qml_properties": state.qml_properties(),
            "camera_pose": {
                "x": state.camera_pose.x,
                "y": state.camera_pose.y,
                "z": state.camera_pose.z,
                "pitch": state.camera_pose.pitch,
                "yaw": state.camera_pose.yaw,
                "distance": state.camera_pose.distance,
                "field_of_view": state.camera_pose.field_of_view,
            },
            "tool": {
                "stage": state.tool.stage,
                "linear_progress": state.tool.linear_progress,
                "eased_progress": state.tool.eased_progress,
                "is_outline": state.tool.is_outline,
            },
        },
        where="studio3d.render_frame.metadata",
    )


class Studio3DCapturePort(Protocol):
    def capture(
        self,
        prepared: "PreparedStudio3DRender",
        frame_index: int,
        *,
        cancelled: Event | None = None,
    ) -> np.ndarray: ...

    def release(self, prepared: "PreparedStudio3DRender") -> None: ...


class PreparedStudio3DRender:
    """Random-access texture and complete QML state for one semantic 3D shot."""

    def __init__(
        self,
        request: RenderRequest,
        source: ArtworkTimedFrameSource,
        resolver: Studio3DSceneStateResolver,
        scene_data: StudioSceneData,
    ) -> None:
        self.request = request
        self.source = source
        self.resolver = resolver
        self.scene_data = scene_data
        self.width = request.constraints.width
        self.height = request.constraints.height
        self.fps = request.constraints.fps
        self.frame_count = request.invocation.duration_frames
        self.source_in_frame = int(request.invocation.parameters.get("source_in_frame", 0))
        self.closed = False

    def _source_index(self, frame_index: int) -> int:
        if self.closed:
            raise RuntimeError("Le renderer Studio 3D préparé est fermé")
        local = validate_frame_index(frame_index, self.frame_count)
        return self.source_in_frame + local

    def state_at(self, frame_index: int) -> Studio3DSceneState:
        return self.resolver.state_at(self._source_index(frame_index))

    def frame_at(self, frame_index: int) -> RenderFrame:
        source_index = self._source_index(frame_index)
        state = self.resolver.state_at(source_index)
        texture = np.ascontiguousarray(self.source.frame_at(source_index), dtype=np.uint8)
        return RenderFrame(
            image=texture,
            blend_mode="scene.3d.packet",
            metadata=_state_metadata(state),
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.source.clear_frame_cache()


class CapturedStudio3DRender:
    """Final RGB source backed by a UI-thread capture port with backpressure."""

    def __init__(
        self,
        prepared: PreparedStudio3DRender,
        capture_port: Studio3DCapturePort,
        cancelled: Event | None,
    ) -> None:
        self.prepared = prepared
        self.capture_port = capture_port
        self.cancelled = cancelled
        self.width = prepared.width
        self.height = prepared.height
        self.fps = prepared.fps
        self.frame_count = prepared.frame_count
        self.closed = False

    def frame_at(self, frame_index: int) -> RenderFrame:
        if self.closed:
            raise RuntimeError("La source de capture Studio 3D est fermée")
        validate_frame_index(frame_index, self.frame_count)
        image = self.capture_port.capture(
            self.prepared,
            frame_index,
            cancelled=self.cancelled,
        )
        image = validate_timed_frame(self, np.ascontiguousarray(image))
        state = self.prepared.state_at(frame_index)
        return RenderFrame(
            image=image,
            blend_mode="normal",
            metadata=_state_metadata(state),
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.capture_port.release(self.prepared)
        self.prepared.close()


class ClassicStudio3DRenderer:
    descriptor = RendererDescriptor(
        "classic.studio-3d",
        "Studio 3D local Artanimate",
        ("scene.depth_present",),
        version="1",
        deterministic=True,
        offline=True,
        priority=100,
    )

    def __init__(
        self,
        artwork_path: str | Path,
        *,
        fingerprint: str | None = None,
        source_factory: ArtworkTimedSourceFactory | None = None,
        capture_port: Studio3DCapturePort,
        cancelled: Event | None = None,
    ) -> None:
        self.artwork_path = Path(artwork_path)
        self.fingerprint = fingerprint
        self.source_factory = source_factory or ArtworkTimedSourceFactory()
        self.capture_port = capture_port
        self.cancelled = cancelled

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        try:
            if not self.artwork_path.is_file():
                return RendererEvaluation(False, reasons=("fichier œuvre introuvable",))
            _render_config_for(request)
            _camera_settings_for(request)
        except (OSError, TypeError, ValueError) as exc:
            return RendererEvaluation(False, reasons=(str(exc),))
        return RendererEvaluation(True, 100)

    def prepare_state(self, request: RenderRequest) -> PreparedStudio3DRender:
        evaluation = self.evaluate(request)
        if not evaluation.compatible:
            raise ValueError("Renderer Studio 3D incompatible : " + "; ".join(evaluation.reasons))
        config = _render_config_for(request)
        source = self.source_factory.source(
            self.artwork_path,
            config,
            fingerprint=self.fingerprint,
            presentation="texture",
            max_cache_bytes=DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
        )
        scene_data = build_studio_scene_data(source.renderer)
        settings = Studio3DSceneSettings.from_config(
            config,
            camera=_camera_settings_for(request),
            output_aspect=request.constraints.width / request.constraints.height,
        )
        resolver = Studio3DSceneStateResolver(
            config,
            frame_count=source.frame_count,
            artwork_aspect=source.width / source.height,
            settings=settings,
            scene_data=scene_data,
        )
        prepared = PreparedStudio3DRender(
            request,
            source,
            resolver,
            scene_data,
        )
        return prepared

    def prepare(self, request: RenderRequest) -> CapturedStudio3DRender:
        return CapturedStudio3DRender(
            self.prepare_state(request),
            self.capture_port,
            self.cancelled,
        )

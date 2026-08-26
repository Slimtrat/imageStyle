from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from ...core.config import RenderConfig
from ..camera import resolve_camera_pose
from ..effect_2d import Effect2DClipSettings
from ..model import CameraAnimation, CameraKeyframe, CameraPose, Easing, StudioProject
from ..source_registry import ArtworkSourceRegistry, StaticArtworkSource
from ..sources import TimedFrameSource, validate_frame_index, validate_timed_frame
from ..semantic import (
    CapabilityRegistry,
    CapabilityRenderer,
    FrozenJsonObject,
    RendererDescriptor,
    RendererEvaluation,
    RendererRegistry,
    RenderFrame,
    RenderPlan,
    RenderPlanEntry,
    RenderRequest,
)
from ..semantic_actions import semantic_action_catalog
from .catalog import effect_capability_id, legacy_capability_catalog
from .semantic_actions import LocalSemanticActionRenderer
from .local_media import LocalMediaCapabilityRenderer


class ClosedPreparedRenderError(RuntimeError):
    pass


class _PreparedBase:
    def __init__(self, width: int, height: int, fps: int, frame_count: int) -> None:
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.frame_count = int(frame_count)
        self.closed = False

    def _validate(self, frame_index: int) -> int:
        if self.closed:
            raise ClosedPreparedRenderError("Ce rendu préparé a déjà été fermé")
        return validate_frame_index(frame_index, self.frame_count)

    def close(self) -> None:
        self.closed = True


class _TimedPreparedRender(_PreparedBase):
    def __init__(
        self,
        source: TimedFrameSource,
        *,
        frame_count: int,
        source_in_frame: int = 0,
        reference: np.ndarray | None = None,
        blend_mode: str = "normal",
    ) -> None:
        super().__init__(source.width, source.height, source.fps, frame_count)
        self.source = source
        self.source_in_frame = int(source_in_frame)
        self.reference = reference
        self.blend_mode = blend_mode
        if self.source_in_frame < 0 or self.source_in_frame + self.frame_count > source.frame_count:
            raise ValueError("La plage de l'invocation dépasse sa source native")

    def frame_at(self, frame_index: int) -> RenderFrame:
        local = self._validate(frame_index)
        source_index = self.source_in_frame + local
        image = validate_timed_frame(self.source, self.source.frame_at(source_index))
        return RenderFrame(
            image=image,
            reference=self.reference,
            blend_mode=self.blend_mode,
        )


def _camera_animation(values: list[dict[str, Any]]) -> CameraAnimation:
    keyframes: list[CameraKeyframe] = []
    for value in values:
        pose = value["pose"]
        keyframes.append(
            CameraKeyframe(
                int(value["frame"]),
                CameraPose(
                    x=float(pose["x"]),
                    y=float(pose["y"]),
                    zoom=float(pose["zoom"]),
                    rotation_degrees=float(pose["rotation_degrees"]),
                    perspective=float(pose["perspective"]),
                    focus=float(pose["focus"]),
                ),
                Easing(value["easing"]),
            )
        )
    return CameraAnimation(tuple(keyframes)).validate()


class _CameraPreparedRender(_PreparedBase):
    def __init__(self, request: RenderRequest) -> None:
        super().__init__(
            request.constraints.width,
            request.constraints.height,
            request.constraints.fps,
            request.invocation.duration_frames,
        )
        parameters = request.invocation.parameters.to_dict()
        self.animation = _camera_animation(parameters["keyframes"])
        self.target_invocation_id = parameters["target_invocation_id"]

    def frame_at(self, frame_index: int) -> RenderFrame:
        local = self._validate(frame_index)
        pose = resolve_camera_pose(self.animation, local)
        return RenderFrame(
            image=None,
            blend_mode="transform.camera",
            metadata=FrozenJsonObject({
                "target_invocation_id": self.target_invocation_id,
                "pose": {
                    "x": pose.x,
                    "y": pose.y,
                    "zoom": pose.zoom,
                    "rotation_degrees": pose.rotation_degrees,
                    "perspective": pose.perspective,
                    "focus": pose.focus,
                },
            }),
        )


class ClassicArtworkCapabilityRenderer:
    descriptor = RendererDescriptor(
        "classic.artwork.static",
        "Œuvre locale statique",
        ("artwork.present",),
        supports_alpha=True,
        priority=100,
    )

    def __init__(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        sources: ArtworkSourceRegistry,
    ) -> None:
        self.project = project
        self.artwork_path = Path(artwork_path)
        self.sources = sources

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        return RendererEvaluation(True, 100)

    def prepare(self, request: RenderRequest) -> _TimedPreparedRender:
        image = self.sources.artwork(
            self.artwork_path,
            self.project.artwork.fingerprint,
        )
        source = StaticArtworkSource(
            image,
            self.project.settings.fps,
            self.project.settings.duration_frames,
        )
        parameters = request.invocation.parameters.to_dict()
        return _TimedPreparedRender(
            source,
            frame_count=request.invocation.duration_frames,
            source_in_frame=int(parameters["source_in_frame"]),
        )


class ClassicEffectCapabilityRenderer:
    def __init__(
        self,
        effect_key: str,
        project: StudioProject,
        artwork_path: str | Path,
        sources: ArtworkSourceRegistry,
    ) -> None:
        self.effect_key = effect_key
        self.project = project
        self.artwork_path = Path(artwork_path)
        self.sources = sources
        self.descriptor = RendererDescriptor(
            f"classic.effect.{effect_key}",
            "Moteur natif · " + effect_key.replace("_", " "),
            (effect_capability_id(effect_key),),
            supports_alpha=True,
            priority=100,
        )

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        values = request.invocation.parameters.to_dict()
        try:
            config = RenderConfig.from_dict(values["render_config"])
        except Exception as exc:
            return RendererEvaluation(False, reasons=(f"configuration invalide : {exc}",))
        if config.effect != self.effect_key:
            return RendererEvaluation(
                False,
                reasons=(
                    f"snapshot {config.effect!r} incompatible avec {self.effect_key!r}",
                ),
            )
        return RendererEvaluation(True, 100)

    def prepare(self, request: RenderRequest) -> _TimedPreparedRender:
        values = request.invocation.parameters.to_dict()
        config = RenderConfig.from_dict(values["render_config"])
        settings = Effect2DClipSettings(
            json.dumps(
                config.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            float(values["intensity"]),
            str(values["target_clip_id"]),
        ).validate()
        source = self.sources.effect_source(
            self.artwork_path,
            self.project.artwork.fingerprint,
            settings,
        )
        return _TimedPreparedRender(
            source,
            frame_count=request.invocation.duration_frames,
            reference=source.reference_frame,
            blend_mode="artwork.delta",
        )


class ClassicCameraCapabilityRenderer:
    descriptor = RendererDescriptor(
        "classic.camera-2d",
        "Caméra normalisée native",
        ("camera.animate",),
        priority=100,
    )

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        return RendererEvaluation(True, 100)

    def prepare(self, request: RenderRequest) -> _CameraPreparedRender:
        return _CameraPreparedRender(request)


def _create_legacy_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability in legacy_capability_catalog():
        registry.register(capability)
    return registry.freeze()

def _create_studio_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability in (*legacy_capability_catalog(), *semantic_action_catalog()):
        registry.register(capability)
    return registry.freeze()


_STUDIO_CAPABILITY_REGISTRY = _create_studio_capability_registry()


def build_studio_capability_registry() -> CapabilityRegistry:
    return _STUDIO_CAPABILITY_REGISTRY




_LEGACY_CAPABILITY_REGISTRY = _create_legacy_capability_registry()


def build_legacy_capability_registry() -> CapabilityRegistry:
    """Return the immutable process-wide catalog shared by render sessions."""
    return _LEGACY_CAPABILITY_REGISTRY

def build_classic_2d_renderer_registry(
    project: StudioProject,
    artwork_path: str | Path,
    *,
    resource_base: str | Path | None = None,
    sources: ArtworkSourceRegistry | None = None,
    extra_renderers: tuple[CapabilityRenderer, ...] = (),
) -> RendererRegistry:
    project.validate()
    source_registry = sources or ArtworkSourceRegistry()
    registry = RendererRegistry()
    registry.register(
        ClassicArtworkCapabilityRenderer(project, artwork_path, source_registry)
    )
    registry.register(
        LocalSemanticActionRenderer(
            project,
            artwork_path,
            resource_base=resource_base,
        )
    )
    registry.register(
        LocalMediaCapabilityRenderer(
            project,
            artwork_path,
            source_registry,
            resource_base=resource_base,
        )
    )
    registry.register(ClassicCameraCapabilityRenderer())
    for capability in legacy_capability_catalog():
        if not capability.capability_id.startswith("reveal."):
            continue
        renderer_id = capability.renderer_candidates[0]
        effect_key = renderer_id.removeprefix("classic.effect.")
        registry.register(
            ClassicEffectCapabilityRenderer(
                effect_key,
                project,
                artwork_path,
                source_registry,
            )
        )
    for renderer in extra_renderers:
        registry.register(renderer)
    return registry.freeze()


@dataclass(slots=True)
class PreparedRenderPlanEntry:
    plan_entry: RenderPlanEntry
    prepared: Any


class PreparedRenderPlan:
    """Own all prepared native resources and close them as one atomic session."""

    def __init__(
        self,
        plan: RenderPlan,
        entries: tuple[PreparedRenderPlanEntry, ...],
    ) -> None:
        self.plan = plan
        self.entries = entries
        self.closed = False

    def by_invocation_id(self, invocation_id: str) -> PreparedRenderPlanEntry:
        if self.closed:
            raise ClosedPreparedRenderError("Le plan préparé est fermé")
        try:
            return next(
                item
                for item in self.entries
                if item.plan_entry.request.invocation.invocation_id == invocation_id
            )
        except StopIteration as exc:
            raise KeyError(f"Invocation préparée introuvable : {invocation_id}") from exc

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for entry in reversed(self.entries):
            entry.prepared.close()

    def __enter__(self) -> "PreparedRenderPlan":
        if self.closed:
            raise ClosedPreparedRenderError("Le plan préparé est fermé")
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def prepare_render_plan(
    plan: RenderPlan,
    renderers: RendererRegistry,
) -> PreparedRenderPlan:
    prepared: list[PreparedRenderPlanEntry] = []
    try:
        for entry in plan.entries:
            renderer = renderers.get(entry.renderer_id)
            prepared.append(
                PreparedRenderPlanEntry(entry, renderer.prepare(entry.request))
            )
    except Exception:
        for item in reversed(prepared):
            item.prepared.close()
        raise
    return PreparedRenderPlan(plan, tuple(prepared))

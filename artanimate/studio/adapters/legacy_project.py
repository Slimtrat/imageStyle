from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Any

from ..effect_2d import settings_for_effect_clip
from ..model import Clip, ClipKind, StudioProject
from ..semantic import (
    Affordance,
    Bounds,
    CapabilityInvocation,
    FrozenJsonObject,
    RendererPolicy,
    RendererPolicyMode,
    ResourceRef,
    SceneObject,
    SceneRelation,
    SemanticScene,
)
from .catalog import effect_capability_id


@dataclass(frozen=True, slots=True)
class LegacyInvocationBinding:
    invocation_id: str
    track_id: str
    clip_id: str
    role: str


@dataclass(frozen=True, slots=True)
class LegacySemanticProject:
    """Read-only semantic projection of a V1 project during the migration window."""

    project_id: str
    source_schema_version: int
    scene: SemanticScene
    invocations: tuple[CapabilityInvocation, ...]
    bindings: tuple[LegacyInvocationBinding, ...]

    def __post_init__(self) -> None:
        invocation_ids = tuple(item.invocation_id for item in self.invocations)
        binding_ids = tuple(item.invocation_id for item in self.bindings)
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("La projection legacy contient une invocation dupliquée")
        if set(invocation_ids) != set(binding_ids):
            raise ValueError("Chaque invocation legacy doit posséder exactement un binding")

    def binding_for(self, invocation_id: str) -> LegacyInvocationBinding:
        try:
            return next(item for item in self.bindings if item.invocation_id == invocation_id)
        except StopIteration as exc:
            raise KeyError(f"Binding legacy introuvable : {invocation_id}") from exc


def _stable_invocation_id(project_id: str, track_id: str, clip_id: str, role: str) -> str:
    digest = hashlib.sha256(
        f"{project_id}\0{track_id}\0{clip_id}\0{role}".encode("utf-8")
    ).hexdigest()[:24]
    return f"legacy:{role}:{digest}"


def _pinned(renderer_id: str) -> RendererPolicy:
    return RendererPolicy(RendererPolicyMode.PINNED, (renderer_id,))


def minimal_scene_for_project(project: StudioProject) -> SemanticScene:
    project.validate()
    artwork_metadata: dict[str, Any] = {}
    if project.artwork.fingerprint is not None:
        artwork_metadata["fingerprint"] = project.artwork.fingerprint
    if project.artwork.width is not None:
        artwork_metadata["width"] = project.artwork.width
    if project.artwork.height is not None:
        artwork_metadata["height"] = project.artwork.height
    return SemanticScene(
        f"scene:{project.project_id}",
        project.artwork.asset_id,
        (
            SceneObject(
                "artwork", "artwork", "Œuvre", bounds=Bounds(0, 0, 1, 1),
                resource_refs=(ResourceRef("artwork-source", "image", project.artwork.asset_id),),
                attributes=FrozenJsonObject(artwork_metadata),
                affordances=(
                    Affordance("presentable", source="adapter.legacy-project"),
                    Affordance("camera-inspectable", source="adapter.legacy-project"),
                    Affordance("effect-applicable", source="adapter.legacy-project"),
                ),
            ),
            SceneObject(
                "background", "scene.background", "Arrière-plan", bounds=Bounds(0, 0, 1, 1),
                affordances=(Affordance("presentable", source="adapter.legacy-project"),),
            ),
            SceneObject(
                "camera", "scene.camera", "Caméra",
                affordances=(Affordance("animatable", source="adapter.legacy-project"),),
            ),
        ),
        relations=(SceneRelation("camera-observes-artwork", "observes", "camera", "artwork"),),
    )


def _camera_parameters(clip: Clip, target_invocation_id: str) -> FrozenJsonObject:
    assert clip.camera is not None
    return FrozenJsonObject(
        {
            "target_invocation_id": target_invocation_id,
            "keyframes": [
                {
                    "frame": keyframe.frame,
                    "easing": keyframe.easing.value,
                    "pose": {
                        "x": keyframe.pose.x,
                        "y": keyframe.pose.y,
                        "zoom": keyframe.pose.zoom,
                        "rotation_degrees": keyframe.pose.rotation_degrees,
                        "perspective": keyframe.pose.perspective,
                        "focus": keyframe.pose.focus,
                    },
                }
                for keyframe in clip.camera.keyframes
            ],
        },
        where="legacy.camera.parameters",
    )


def project_as_semantic(project: StudioProject) -> LegacySemanticProject:
    """Project V1 → semantic view; pure, deterministic and non-mutating."""
    project.validate()
    before = project.to_dict()
    invocations: list[CapabilityInvocation] = []
    bindings: list[LegacyInvocationBinding] = []

    def append(track_id: str, clip: Clip, role: str, capability_id: str,
               target_id: str | None, parameters: dict[str, Any], renderer_id: str) -> str:
        invocation_id = _stable_invocation_id(project.project_id, track_id, clip.clip_id, role)
        invocations.append(
            CapabilityInvocation(
                invocation_id, capability_id, clip.start_frame, clip.duration_frames,
                target_id=target_id, parameters=FrozenJsonObject(parameters, where="legacy.invocation.parameters"),
                renderer_policy=_pinned(renderer_id), enabled=clip.enabled,
            )
        )
        bindings.append(LegacyInvocationBinding(invocation_id, track_id, clip.clip_id, role))
        return invocation_id

    for track in project.tracks:
        for clip in track.clips:
            visual = {
                "source_in_frame": clip.source_in_frame,
                "opacity": clip.opacity,
                "fit": clip.fit.value,
            }
            if clip.kind == ClipKind.ARTWORK_2D:
                content_id = append(track.track_id, clip, "content", "artwork.present", "artwork", visual, "classic.artwork.static")
            elif clip.kind == ClipKind.ARTWORK_3D:
                content_id = append(
                    track.track_id, clip, "content", "scene.depth_present", "artwork",
                    {**visual, "settings": clip.parameters or {}}, "classic.studio-3d",
                )
            elif clip.kind == ClipKind.EFFECT_2D:
                settings = settings_for_effect_clip(clip)
                content_id = append(
                    track.track_id, clip, "effect", effect_capability_id(settings.effect), "artwork",
                    {
                        "render_config": settings.config.to_dict(),
                        "intensity": settings.intensity,
                        "target_clip_id": settings.target_clip_id,
                        "opacity": clip.opacity,
                    },
                    f"classic.effect.{settings.effect}",
                )
            elif clip.kind in {ClipKind.STILL, ClipKind.VIDEO}:
                assert clip.asset_id is not None
                content_id = append(
                    track.track_id, clip, "content", "media.present", None,
                    {**visual, "asset_id": clip.asset_id}, "local.media",
                )
            elif clip.kind == ClipKind.AUDIO:
                assert clip.asset_id is not None
                content_id = append(
                    track.track_id, clip, "audio", "audio.play", None,
                    {"asset_id": clip.asset_id, "source_in_frame": clip.source_in_frame}, "local.audio",
                )
            else:
                raise ValueError(f"Type de clip V1 non mappable : {clip.kind}")

            if clip.camera is not None and clip.kind != ClipKind.ARTWORK_3D:
                camera_id = _stable_invocation_id(project.project_id, track.track_id, clip.clip_id, "camera")
                invocations.append(
                    CapabilityInvocation(
                        camera_id, "camera.animate", clip.start_frame, clip.duration_frames,
                        target_id="camera", parameters=_camera_parameters(clip, content_id),
                        renderer_policy=_pinned("classic.camera-2d"), enabled=clip.enabled,
                    )
                )
                bindings.append(LegacyInvocationBinding(camera_id, track.track_id, clip.clip_id, "camera"))

    if project.to_dict() != before:
        raise RuntimeError("La projection sémantique a modifié le projet V1 source")
    return LegacySemanticProject(
        project.project_id,
        project.schema_version,
        minimal_scene_for_project(project),
        tuple(invocations),
        tuple(bindings),
    )

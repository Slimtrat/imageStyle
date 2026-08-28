from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
from typing import TYPE_CHECKING, Any

from .model import Clip, ClipKind, Track, TrackKind
from .semantic import (
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


if TYPE_CHECKING:
    from .model import StudioProject


def stable_legacy_invocation_id(
    project_id: str,
    track_id: str,
    clip_id: str,
    role: str,
) -> str:
    digest = hashlib.sha256(
        f"{project_id}\0{track_id}\0{clip_id}\0{role}".encode("utf-8")
    ).hexdigest()[:24]
    return f"legacy:{role}:{digest}"


def _pinned(renderer_id: str) -> RendererPolicy:
    return RendererPolicy(RendererPolicyMode.PINNED, (renderer_id,))


def minimal_scene_for_project(project: StudioProject) -> SemanticScene:
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
                "artwork",
                "artwork",
                "Œuvre",
                bounds=Bounds(0, 0, 1, 1),
                resource_refs=(
                    ResourceRef(
                        "artwork-source",
                        "image",
                        project.artwork.asset_id,
                    ),
                ),
                attributes=FrozenJsonObject(artwork_metadata),
                affordances=(
                    Affordance("presentable", source="adapter.legacy-project"),
                    Affordance(
                        "camera-inspectable",
                        source="adapter.legacy-project",
                    ),
                    Affordance(
                        "effect-applicable",
                        source="adapter.legacy-project",
                    ),
                ),
            ),
            SceneObject(
                "background",
                "scene.background",
                "Arrière-plan",
                bounds=Bounds(0, 0, 1, 1),
                affordances=(
                    Affordance("presentable", source="adapter.legacy-project"),
                ),
            ),
            SceneObject(
                "camera",
                "scene.camera",
                "Caméra",
                affordances=(
                    Affordance("animatable", source="adapter.legacy-project"),
                ),
            ),
        ),
        relations=(
            SceneRelation(
                "camera-observes-artwork",
                "observes",
                "camera",
                "artwork",
            ),
        ),
    )


def _camera_parameters(
    clip: Clip,
    target_invocation_id: str,
    *,
    pre_handle_frames: int = 0,
    post_handle_frames: int = 0,
) -> FrozenJsonObject:
    assert clip.camera is not None
    keyframes = [
        {
            "frame": keyframe.frame + pre_handle_frames,
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
    ]
    if pre_handle_frames > 0:
        keyframes.insert(0, {**keyframes[0], "frame": 0})
    if post_handle_frames > 0:
        final_frame = pre_handle_frames + clip.duration_frames + post_handle_frames - 1
        if keyframes[-1]["frame"] != final_frame:
            keyframes.append({**keyframes[-1], "frame": final_frame})
    return FrozenJsonObject(
        {
            "target_invocation_id": target_invocation_id,
            "keyframes": keyframes,
        },
        where="legacy.camera.parameters",
    )


def _effect_identity(parameters: Mapping[str, Any] | None) -> tuple[str, str]:
    values = parameters or {}
    effect = values.get("effect")
    if not isinstance(effect, str) or not effect.strip():
        render_config = values.get("render_config")
        if isinstance(render_config, Mapping):
            effect = render_config.get("effect")
    if not isinstance(effect, str) or not effect.strip():
        effect = "unknown"
    capability_id = "reveal.chromatic" if effect == "rgb_fade" else f"reveal.{effect}"
    return capability_id, f"classic.effect.{effect}"


def _content_spec(
    clip: Clip,
    *,
    source_in_frame: int | None = None,
) -> tuple[str, str, str | None, dict[str, Any], str]:
    visual = {
        "source_in_frame": clip.source_in_frame if source_in_frame is None else source_in_frame,
        "opacity": clip.opacity,
        "fit": clip.fit.value,
    }
    if clip.kind == ClipKind.ARTWORK_2D:
        return (
            "content",
            "artwork.present",
            "artwork",
            visual,
            "classic.artwork.static",
        )
    if clip.kind == ClipKind.ARTWORK_3D:
        return (
            "content",
            "scene.depth_present",
            "artwork",
            {**visual, "settings": clip.parameters or {}},
            "classic.studio-3d",
        )
    if clip.kind == ClipKind.EFFECT_2D:
        values = clip.parameters or {}
        capability_id, renderer_id = _effect_identity(values)
        render_config = values.get("render_config", {})
        if not isinstance(render_config, Mapping):
            render_config = {}
        return (
            "effect",
            capability_id,
            "artwork",
            {
                "render_config": dict(render_config),
                "intensity": values.get("intensity", 1.0),
                "target_clip_id": values.get("target_clip_id", "artwork-main"),
                "opacity": clip.opacity,
            },
            renderer_id,
        )
    if clip.kind in {ClipKind.STILL, ClipKind.VIDEO}:
        return (
            "content",
            "media.present",
            None,
            {**visual, "asset_id": clip.asset_id, "settings": clip.parameters or {}},
            "local.media",
        )
    if clip.kind == ClipKind.AUDIO:
        return (
            "audio",
            "audio.play",
            None,
            {
                **(clip.parameters or {}),
                "asset_id": clip.asset_id,
                "source_in_frame": clip.source_in_frame,
            },
            "local.audio",
        )
    raise ValueError(f"Type de clip V1 non mappable : {clip.kind}")


def _legacy_clip_invocations(
    project_id: str,
    track_id: str,
    clip: Clip,
    project: StudioProject,
) -> tuple[Clip, tuple[CapabilityInvocation, ...]]:
    from .transitions import render_source_in_frame, render_window_for_clip

    render_start, render_end = render_window_for_clip(project, clip)
    source_in = render_source_in_frame(project, clip, render_start)
    role, capability_id, target_id, parameters, renderer_id = _content_spec(
        clip,
        source_in_frame=source_in,
    )
    render_duration = render_end - render_start
    content_id = stable_legacy_invocation_id(
        project_id,
        track_id,
        clip.clip_id,
        role,
    )
    updated = replace(
        clip,
        invocation_id=content_id,
        legacy_kind=clip.kind.value,
    )
    invocations = [
        CapabilityInvocation(
            content_id,
            capability_id,
            render_start,
            render_duration,
            target_id=target_id,
            parameters=FrozenJsonObject(
                parameters,
                where="legacy.invocation.parameters",
            ),
            renderer_policy=_pinned(renderer_id),
            enabled=clip.enabled,
        )
    ]
    if clip.camera is not None and clip.kind != ClipKind.ARTWORK_3D:
        camera_id = stable_legacy_invocation_id(
            project_id,
            track_id,
            clip.clip_id,
            "camera",
        )
        invocations.append(
            CapabilityInvocation(
                camera_id,
                "camera.animate",
                render_start,
                render_duration,
                target_id="camera",
                parameters=_camera_parameters(
                    clip,
                    content_id,
                    pre_handle_frames=clip.start_frame - render_start,
                    post_handle_frames=render_end - clip.end_frame,
                ),
                renderer_policy=_pinned("classic.camera-2d"),
                enabled=clip.enabled,
            )
        )
    return updated, tuple(invocations)


def synchronize_legacy_fields(
    project: StudioProject,
) -> tuple[SemanticScene, tuple[CapabilityInvocation, ...], tuple[Track, ...]]:
    """Normalize legacy-linked clips without touching semantic-native invocations."""
    generated: list[CapabilityInvocation] = []
    tracks: list[Track] = []
    for track in project.tracks:
        clips: list[Clip] = []
        for clip in track.clips:
            semantic_native = clip.invocation_id is not None and clip.legacy_kind is None
            if semantic_native:
                clips.append(clip)
                continue
            updated, clip_invocations = _legacy_clip_invocations(
                project.project_id,
                track.track_id,
                clip,
                project,
            )
            clips.append(updated)
            generated.extend(clip_invocations)
        tracks.append(replace(track, clips=tuple(clips)))

    generated_by_id = {item.invocation_id: item for item in generated}
    normalized: list[CapabilityInvocation] = []
    seen: set[str] = set()
    for invocation in project.invocations:
        replacement = generated_by_id.get(invocation.invocation_id)
        if replacement is not None:
            if invocation.capability_id == replacement.capability_id:
                parameters = invocation.parameters.to_dict()
                parameters.update(replacement.parameters.to_dict())
                replacement = replace(
                    replacement,
                    parameters=FrozenJsonObject(
                        parameters,
                        where="legacy.invocation.parameters",
                    ),
                    renderer_policy=invocation.renderer_policy,
                )
            normalized.append(replacement)
            seen.add(replacement.invocation_id)
        elif not invocation.invocation_id.startswith("legacy:"):
            normalized.append(invocation)
            seen.add(invocation.invocation_id)
    normalized.extend(
        invocation
        for invocation in generated
        if invocation.invocation_id not in seen
    )
    scene = project.scene or minimal_scene_for_project(project)
    return scene, tuple(normalized), tuple(tracks)


def invocation_bindings(
    project: StudioProject,
) -> tuple[tuple[str, str, str, str], ...]:
    """Return invocation_id, track_id, clip_id and role for timeline-backed intents."""
    known = {item.invocation_id for item in project.invocations}
    bindings: list[tuple[str, str, str, str]] = []
    for track in project.tracks:
        for clip in track.clips:
            if clip.invocation_id is None or clip.invocation_id not in known:
                continue
            role = {
                TrackKind.EFFECT: "effect",
                TrackKind.AUDIO: "audio",
            }.get(track.kind, "content")
            bindings.append((clip.invocation_id, track.track_id, clip.clip_id, role))
            camera_id = stable_legacy_invocation_id(
                project.project_id,
                track.track_id,
                clip.clip_id,
                "camera",
            )
            if camera_id in known:
                bindings.append((camera_id, track.track_id, clip.clip_id, "camera"))
    return tuple(bindings)

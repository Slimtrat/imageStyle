from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Mapping

from .camera_presets import CameraPreset, generate_camera_preset
from .media import StillClipSettings
from .model import (
    AssetKind,
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Clip,
    ClipKind,
    Easing,
    FitMode,
    StudioProject,
    Track,
    TrackKind,
)
from .semantic import Bounds, SceneObject
from .transitions import add_dissolve
from .video import VideoClipSettings, video_source_frame_count


class ExplorePlanRole(StrEnum):
    MACRO = "macro"
    INSPECTION = "inspection"
    REVEAL = "reveal"
    REAL_PLACEHOLDER = "real_placeholder"


@dataclass(frozen=True, slots=True)
class ExploreBuildResult:
    project: StudioProject
    macro_clip_id: str
    inspection_clip_id: str
    reveal_clip_id: str
    real_clip_id: str


@dataclass(frozen=True, slots=True)
class ExploreZoneRecommendation:
    macro_zone_id: str
    inspection_zone_id: str
    rationale: tuple[str, ...]


_ROLE_LABELS = {
    ExplorePlanRole.MACRO: "Macro",
    ExplorePlanRole.INSPECTION: "Inspection",
    ExplorePlanRole.REVEAL: "Reveal",
    ExplorePlanRole.REAL_PLACEHOLDER: "Réel · média à choisir",
}

SMART_MAX_ZOOM = 5.5
SMART_MAX_ROTATION_DEGREES = 1.5
SMART_BREATHING_RATIO = 0.08


def explore_clip_role(clip: Clip) -> ExplorePlanRole | None:
    values = clip.parameters or {}
    explore = values.get("explore") if isinstance(values, Mapping) else None
    role = explore.get("role") if isinstance(explore, Mapping) else None
    try:
        return ExplorePlanRole(role) if role is not None else None
    except (TypeError, ValueError):
        return None


def explore_clip_label(clip: Clip) -> str | None:
    role = explore_clip_role(clip)
    return _ROLE_LABELS.get(role) if role is not None else None


def explore_clip(
    project: StudioProject,
    role: ExplorePlanRole,
) -> Clip | None:
    expected = ExplorePlanRole(role)
    return next(
        (
            clip
            for track in project.tracks
            for clip in track.clips
            if explore_clip_role(clip) == expected
        ),
        None,
    )


def is_explore_project(project: StudioProject) -> bool:
    roles = {
        role
        for track in project.tracks
        for clip in track.clips
        if (role := explore_clip_role(clip)) is not None
    }
    return {
        ExplorePlanRole.MACRO,
        ExplorePlanRole.INSPECTION,
        ExplorePlanRole.REVEAL,
    }.issubset(roles)


def _proposal_score(scene_object: SceneObject) -> float:
    scores = scene_object.attributes.get("scores", {})
    if isinstance(scores, Mapping):
        try:
            return float(scores.get("global", scene_object.confidence))
        except (TypeError, ValueError):
            pass
    return float(scene_object.confidence)


def _proposal_rank(scene_object: SceneObject) -> int:
    try:
        return int(scene_object.attributes.get("rank", 10_000))
    except (TypeError, ValueError):
        return 10_000


def _bounds_center(bounds: Bounds) -> tuple[float, float]:
    return bounds.x + bounds.width / 2, bounds.y + bounds.height / 2


def recommend_explore_zones(project: StudioProject) -> ExploreZoneRecommendation:
    """Choose two explainable, spatially distinct details without editing the project."""

    source = project.validate()
    assert source.scene is not None
    proposals = [
        scene_object
        for scene_object in source.scene.objects
        if scene_object.bounds is not None
        and scene_object.attributes.get("proposal_status") == "proposed"
        and "camera-inspectable" in scene_object.affordance_ids
    ]
    proposals.sort(
        key=lambda item: (
            _proposal_rank(item),
            -_proposal_score(item),
            item.object_id,
        )
    )
    if not proposals:
        manual = [
            scene_object
            for scene_object in source.scene.objects
            if scene_object.bounds is not None
            and scene_object.attributes.get("manual") is True
        ]
        manual.sort(key=lambda item: item.object_id)
        proposals = manual
    if not proposals:
        return ExploreZoneRecommendation(
            "artwork",
            "artwork",
            (
                "Aucune région locale validée : cadrage prudent sur l’œuvre entière.",
            ),
        )

    macro = proposals[0]
    macro_center = _bounds_center(macro.bounds)

    def inspection_value(scene_object: SceneObject) -> tuple[float, float, str]:
        center = _bounds_center(scene_object.bounds)
        distance = (
            (center[0] - macro_center[0]) ** 2
            + (center[1] - macro_center[1]) ** 2
        ) ** 0.5
        return (
            distance * 0.72 + _proposal_score(scene_object) * 0.28,
            _proposal_score(scene_object),
            scene_object.object_id,
        )

    alternatives = [item for item in proposals if item.object_id != macro.object_id]
    inspection = max(alternatives, key=inspection_value) if alternatives else macro
    return ExploreZoneRecommendation(
        macro.object_id,
        inspection.object_id,
        (
            f"Macro : {macro.label}, proposition la mieux classée.",
            (
                f"Inspection : {inspection.label}, choisie pour sa distance "
                "visuelle et son score."
                if inspection.object_id != macro.object_id
                else "Inspection : même région, aucune seconde zone n’est disponible."
            ),
        ),
    )


def _frame_durations(total_frames: int) -> tuple[int, int, int, int]:
    total = int(total_frames)
    if total < 24:
        raise ValueError("Explore exige au moins 24 frames de projet")
    macro = round(total * 5 / 24)
    inspection = round(total * 6 / 24)
    reveal = round(total * 7 / 24)
    real = total - macro - inspection - reveal
    durations = (macro, inspection, reveal, real)
    if any(value < 2 for value in durations):
        raise ValueError("Chaque plan Explore doit durer au moins deux frames")
    return durations


def _zone_bounds(project: StudioProject, object_id: str) -> Bounds:
    assert project.scene is not None
    scene_object = project.scene.object_by_id(str(object_id))
    if scene_object is None:
        raise KeyError(f"Zone Explore introuvable : {object_id}")
    if scene_object.bounds is None:
        raise ValueError(f"La zone {object_id} ne possède pas de limites éditables")
    return scene_object.bounds


def _focus_animation(
    project: StudioProject,
    preset: CameraPreset,
    duration_frames: int,
    zone: Bounds,
) -> CameraAnimation:
    artwork_width = project.artwork.width or project.settings.width
    artwork_height = project.artwork.height or project.settings.height
    keyframes = generate_camera_preset(
        preset,
        start_frame=0,
        duration_frames=duration_frames,
        artwork_ratio=artwork_width / artwork_height,
        project_ratio=project.settings.width / project.settings.height,
        intensity=0.35,
        seed=project.project_id,
    )
    center_x = zone.x + zone.width / 2
    center_y = zone.y + zone.height / 2
    zone_zoom = min(
        SMART_MAX_ZOOM,
        max(1.15, 0.82 / max(zone.width, zone.height)),
    )
    focused = tuple(
        replace(
            keyframe,
            pose=replace(
                keyframe.pose,
                x=min(
                    0.98,
                    max(0.02, center_x + (keyframe.pose.x - 0.5) * zone.width),
                ),
                y=min(
                    0.98,
                    max(0.02, center_y + (keyframe.pose.y - 0.5) * zone.height),
                ),
                zoom=min(
                    SMART_MAX_ZOOM,
                    max(keyframe.pose.zoom, zone_zoom),
                ),
                rotation_degrees=min(
                    SMART_MAX_ROTATION_DEGREES,
                    max(
                        -SMART_MAX_ROTATION_DEGREES,
                        keyframe.pose.rotation_degrees,
                    ),
                ),
            ).validate(),
        ).validate()
        for keyframe in keyframes
    )
    focused = _with_breathing(focused, duration_frames)
    return CameraAnimation(focused).validate(
        clip_duration_frames=duration_frames
    )


def _with_breathing(
    keyframes: tuple[CameraKeyframe, ...],
    duration_frames: int,
) -> tuple[CameraKeyframe, ...]:
    if len(keyframes) < 2 or duration_frames < 8:
        return keyframes
    occupied = {item.frame for item in keyframes}
    final_frame = duration_frames - 1
    additions: list[CameraKeyframe] = []
    entrance_hold = max(1, round(final_frame * SMART_BREATHING_RATIO))
    exit_hold = min(
        final_frame - 1,
        round(final_frame * (1.0 - SMART_BREATHING_RATIO)),
    )
    if entrance_hold not in occupied and entrance_hold < keyframes[1].frame:
        additions.append(
            CameraKeyframe(
                entrance_hold,
                keyframes[0].pose,
                Easing.EASE_IN_OUT,
            )
        )
    if exit_hold not in occupied and exit_hold > keyframes[-2].frame:
        additions.append(
            CameraKeyframe(
                exit_hold,
                keyframes[-1].pose,
                Easing.EASE_IN_OUT,
            )
        )
    return tuple(
        sorted((*keyframes, *additions), key=lambda item: item.frame)
    )


def _reveal_animation(
    project: StudioProject,
    duration_frames: int,
) -> CameraAnimation:
    artwork_width = project.artwork.width or project.settings.width
    artwork_height = project.artwork.height or project.settings.height
    keyframes = generate_camera_preset(
        CameraPreset.REVEAL,
        start_frame=0,
        duration_frames=duration_frames,
        artwork_ratio=artwork_width / artwork_height,
        project_ratio=project.settings.width / project.settings.height,
        intensity=0.3,
        seed=project.project_id,
    )
    return CameraAnimation(keyframes).validate(
        clip_duration_frames=duration_frames
    )


def _parameters(
    role: ExplorePlanRole,
    *,
    zone_object_id: str | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "role": role.value,
        "label": _ROLE_LABELS[role],
    }
    if zone_object_id is not None:
        values["zone_object_id"] = str(zone_object_id)
    if role == ExplorePlanRole.REAL_PLACEHOLDER:
        values["accepts"] = [AssetKind.IMAGE.value, AssetKind.VIDEO.value]
    return {"explore": values}


def create_explore_project(
    project: StudioProject,
    *,
    macro_zone_id: str | None = None,
    inspection_zone_id: str | None = None,
) -> ExploreBuildResult:
    """Compose an editable 12-second narrative using only standard Studio fields."""

    source = project.validate()
    recommendation = recommend_explore_zones(source)
    macro_zone_id = macro_zone_id or recommendation.macro_zone_id
    inspection_zone_id = inspection_zone_id or recommendation.inspection_zone_id
    target_frames = source.settings.fps * 12
    durations = _frame_durations(target_frames)
    macro_duration, inspection_duration, reveal_duration, real_duration = durations
    macro_zone = _zone_bounds(source, macro_zone_id)
    inspection_zone = _zone_bounds(source, inspection_zone_id)
    starts = (
        0,
        macro_duration,
        macro_duration + inspection_duration,
        macro_duration + inspection_duration + reveal_duration,
    )
    clips = (
        Clip(
            "explore-macro",
            ClipKind.ARTWORK_2D,
            starts[0],
            macro_duration,
            camera=_focus_animation(
                source,
                CameraPreset.MACRO,
                macro_duration,
                macro_zone,
            ),
            parameters=_parameters(
                ExplorePlanRole.MACRO,
                zone_object_id=macro_zone_id,
            ),
        ),
        Clip(
            "explore-inspection",
            ClipKind.ARTWORK_2D,
            starts[1],
            inspection_duration,
            camera=_focus_animation(
                source,
                CameraPreset.INSPECT,
                inspection_duration,
                inspection_zone,
            ),
            parameters=_parameters(
                ExplorePlanRole.INSPECTION,
                zone_object_id=inspection_zone_id,
            ),
        ),
        Clip(
            "explore-reveal",
            ClipKind.ARTWORK_2D,
            starts[2],
            reveal_duration,
            camera=_reveal_animation(source, reveal_duration),
            parameters=_parameters(ExplorePlanRole.REVEAL),
        ),
        Clip(
            "explore-real",
            ClipKind.ARTWORK_2D,
            starts[3],
            real_duration,
            camera=CameraAnimation((CameraKeyframe(0, CameraPose()),)),
            parameters=_parameters(ExplorePlanRole.REAL_PLACEHOLDER),
        ),
    )
    track_ids = {
        kind: next(
            (track.track_id for track in source.tracks if track.kind == kind),
            fallback,
        )
        for kind, fallback in (
            (TrackKind.VIDEO, "video-main"),
            (TrackKind.EFFECT, "effects-main"),
            (TrackKind.AUDIO, "audio-main"),
        )
    }
    tracks = (
        Track(track_ids[TrackKind.VIDEO], TrackKind.VIDEO, "Explore · plans", clips),
        Track(
            track_ids[TrackKind.EFFECT],
            TrackKind.EFFECT,
            "Actions · optionnelles",
        ),
        Track(
            track_ids[TrackKind.AUDIO],
            TrackKind.AUDIO,
            "Musique · à choisir",
        ),
    )
    candidate = replace(
        source,
        settings=replace(source.settings, duration_frames=target_frames),
        tracks=tracks,
        transitions=(),
        invocations=(),
        triggers=(),
    ).validate()
    transition_duration = max(2, round(source.settings.fps * 0.4))
    for first, second in zip(clips, clips[1:]):
        candidate, _transition = add_dissolve(
            candidate,
            first.clip_id,
            second.clip_id,
            duration_frames=transition_duration,
            easing=Easing.EASE_IN_OUT,
        )
    candidate = candidate.validate()
    return ExploreBuildResult(
        candidate,
        clips[0].clip_id,
        clips[1].clip_id,
        clips[2].clip_id,
        clips[3].clip_id,
    )


def replace_explore_real_placeholder(
    project: StudioProject,
    placeholder_clip_id: str,
    asset_id: str,
) -> tuple[StudioProject, Clip]:
    asset = next(
        (item for item in project.assets if item.asset_id == asset_id),
        None,
    )
    if asset is None:
        raise KeyError(f"Média réel introuvable : {asset_id}")
    location = next(
        (
            (track_index, clip_index, clip)
            for track_index, track in enumerate(project.tracks)
            for clip_index, clip in enumerate(track.clips)
            if clip.clip_id == placeholder_clip_id
        ),
        None,
    )
    if location is None:
        raise KeyError(f"Placeholder Explore introuvable : {placeholder_clip_id}")
    track_index, clip_index, placeholder = location
    if explore_clip_role(placeholder) != ExplorePlanRole.REAL_PLACEHOLDER:
        raise ValueError("Le plan sélectionné n’est pas le placeholder réel Explore")
    if asset.kind == AssetKind.IMAGE:
        replacement = replace(
            placeholder,
            kind=ClipKind.STILL,
            asset_id=asset.asset_id,
            source_in_frame=0,
            camera=None,
            fit=FitMode.COVER,
            parameters={"still": StillClipSettings().to_dict()},
        )
    elif asset.kind == AssetKind.VIDEO:
        pre_handle = max(
            (
                placeholder.start_frame - transition.start_frame
                for transition in project.transitions
                if transition.to_clip_id == placeholder.clip_id
            ),
            default=0,
        )
        available = video_source_frame_count(project, asset.asset_id) - pre_handle
        duration = min(placeholder.duration_frames, available)
        if duration < 2:
            raise ValueError("La vidéo réelle est trop courte pour le plan Explore")
        replacement = replace(
            placeholder,
            kind=ClipKind.VIDEO,
            duration_frames=duration,
            asset_id=asset.asset_id,
            source_in_frame=pre_handle,
            camera=None,
            fit=FitMode.COVER,
            parameters={"video": VideoClipSettings().to_dict()},
        )
    else:
        raise ValueError("Explore attend une photo ou une vidéo pour le plan réel")
    tracks = list(project.tracks)
    clips = list(tracks[track_index].clips)
    clips[clip_index] = replacement.validate()
    tracks[track_index] = replace(tracks[track_index], clips=tuple(clips))
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        clip
        for track in updated.tracks
        for clip in track.clips
        if clip.clip_id == placeholder_clip_id
    )
    return updated, effective


def mark_explore_music_attached(project: StudioProject) -> StudioProject:
    if not is_explore_project(project):
        return project
    tracks = tuple(
        replace(track, name="Musique")
        if track.kind == TrackKind.AUDIO and track.clips
        else track
        for track in project.tracks
    )
    return replace(project, tracks=tracks).validate()

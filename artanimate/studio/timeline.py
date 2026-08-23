from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .camera import resolve_camera_pose
from .model import CameraAnimation, CameraKeyframe, Clip, StudioProject, Track, TrackKind

OVERLAP_POLICY = "layered"


def track_by_id(project: StudioProject, track_id: str) -> tuple[int, Track]:
    for index, track in enumerate(project.tracks):
        if track.track_id == track_id:
            return index, track
    raise KeyError(f"Piste Studio introuvable : {track_id}")


def add_track(
    project: StudioProject,
    kind: TrackKind,
    *,
    name: str | None = None,
    index: int | None = None,
) -> tuple[StudioProject, Track]:
    if not isinstance(kind, TrackKind):
        raise TypeError("Le type de piste doit être un TrackKind")
    if index is None:
        index = len(project.tracks)
    if not 0 <= index <= len(project.tracks):
        raise IndexError("La position de la nouvelle piste est hors du projet")
    labels = {
        TrackKind.VIDEO: "Plan",
        TrackKind.EFFECT: "Effets",
        TrackKind.AUDIO: "Audio",
    }
    number = 1 + sum(track.kind == kind for track in project.tracks)
    track = Track(
        track_id=f"{kind.value}-{uuid4().hex[:12]}",
        kind=kind,
        name=(name or f"{labels[kind]} {number}").strip(),
    ).validate()
    tracks = list(project.tracks)
    tracks.insert(index, track)
    return replace(project, tracks=tuple(tracks)).validate(), track


def set_track_state(
    project: StudioProject,
    track_id: str,
    *,
    muted: bool | None = None,
    locked: bool | None = None,
    hidden: bool | None = None,
) -> StudioProject:
    index, track = track_by_id(project, track_id)
    values = {"muted": muted, "locked": locked, "hidden": hidden}
    for field, value in values.items():
        if value is not None and not isinstance(value, bool):
            raise TypeError(f"track.{field} doit être un booléen")
    updated_track = replace(
        track,
        muted=track.muted if muted is None else muted,
        locked=track.locked if locked is None else locked,
        hidden=track.hidden if hidden is None else hidden,
    ).validate()
    tracks = list(project.tracks)
    tracks[index] = updated_track
    return replace(project, tracks=tuple(tracks)).validate()


def clip_location(project: StudioProject, clip_id: str) -> tuple[int, int, Track, Clip]:
    for track_index, track in enumerate(project.tracks):
        for clip_index, clip in enumerate(track.clips):
            if clip.clip_id == clip_id:
                return track_index, clip_index, track, clip
    raise KeyError(f"Clip Studio introuvable : {clip_id}")


def _replace_track(project: StudioProject, index: int, track: Track) -> StudioProject:
    tracks = list(project.tracks)
    tracks[index] = track.validate()
    return replace(project, tracks=tuple(tracks)).validate()


def _require_editable(track: Track) -> None:
    if track.locked:
        raise PermissionError(f"La piste {track.name} est verrouillée")


def snap_frame(
    proposed_frame: int,
    targets: tuple[int, ...] | list[int] | set[int],
    *,
    threshold_frames: int = 3,
    enabled: bool = True,
) -> int:
    proposed = int(proposed_frame)
    if not enabled or threshold_frames < 0:
        return proposed
    candidates = sorted({int(target) for target in targets})
    if not candidates:
        return proposed
    nearest = min(candidates, key=lambda target: (abs(target - proposed), target))
    return nearest if abs(nearest - proposed) <= threshold_frames else proposed


def timeline_snap_targets(
    project: StudioProject,
    *,
    playhead: int | None = None,
    exclude_clip_ids: tuple[str, ...] = (),
) -> tuple[int, ...]:
    excluded = set(exclude_clip_ids)
    targets = {0, project.settings.duration_frames}
    if playhead is not None:
        targets.add(int(playhead))
    for track in project.tracks:
        for clip in track.clips:
            if clip.clip_id in excluded:
                continue
            targets.add(clip.start_frame)
            targets.add(clip.end_frame)
            if clip.camera is not None:
                targets.update(
                    clip.start_frame + keyframe.frame
                    for keyframe in clip.camera.keyframes
                )
    return tuple(sorted(targets))


def move_clip(
    project: StudioProject,
    clip_id: str,
    target_frame: int,
    *,
    target_track_id: str | None = None,
) -> StudioProject:
    source_track_index, _clip_index, source_track, clip = clip_location(project, clip_id)
    _require_editable(source_track)
    target_frame = int(target_frame)
    if target_frame < 0 or target_frame + clip.duration_frames > project.settings.duration_frames:
        raise ValueError("Le déplacement sortirait le clip de la durée du projet")
    destination_id = target_track_id or source_track.track_id
    target_track_index, target_track = track_by_id(project, destination_id)
    _require_editable(target_track)

    source_clips = [item for item in source_track.clips if item.clip_id != clip_id]
    moved = replace(clip, start_frame=target_frame).validate()
    if target_track_index == source_track_index:
        source_clips.append(moved)
        source_clips.sort(key=lambda item: (item.start_frame, item.clip_id))
        return _replace_track(
            project,
            source_track_index,
            replace(source_track, clips=tuple(source_clips)),
        )

    target_clips = [*target_track.clips, moved]
    target_clips.sort(key=lambda item: (item.start_frame, item.clip_id))
    updated_source = replace(source_track, clips=tuple(source_clips)).validate()
    updated_target = replace(target_track, clips=tuple(target_clips)).validate()
    tracks = list(project.tracks)
    tracks[source_track_index] = updated_source
    tracks[target_track_index] = updated_target
    return replace(project, tracks=tuple(tracks)).validate()


def _trim_camera(
    animation: CameraAnimation | None,
    source_delta: int,
    new_duration: int,
) -> CameraAnimation | None:
    if animation is None:
        return None
    pose_at_start = resolve_camera_pose(animation, max(0, source_delta))
    keyframes = [
        replace(keyframe, frame=keyframe.frame - source_delta)
        for keyframe in animation.keyframes
        if source_delta <= keyframe.frame < source_delta + new_duration
    ]
    if not keyframes or keyframes[0].frame != 0:
        keyframes.insert(0, CameraKeyframe(0, pose_at_start))
    return CameraAnimation(tuple(keyframes)).validate(
        clip_duration_frames=new_duration
    )


def trim_clip(
    project: StudioProject,
    clip_id: str,
    new_start_frame: int,
    new_end_frame: int,
) -> StudioProject:
    track_index, clip_index, track, clip = clip_location(project, clip_id)
    _require_editable(track)
    start = int(new_start_frame)
    end = int(new_end_frame)
    if not 0 <= start < end <= project.settings.duration_frames:
        raise ValueError("Le trim doit rester dans la durée du projet")
    delta = start - clip.start_frame
    source_in = clip.source_in_frame + delta
    if source_in < 0:
        raise ValueError("Le trim étendrait le clip avant le début de sa source")
    duration = end - start
    trimmed = replace(
        clip,
        start_frame=start,
        duration_frames=duration,
        source_in_frame=source_in,
        camera=_trim_camera(clip.camera, delta, duration),
    ).validate()
    clips = list(track.clips)
    clips[clip_index] = trimmed
    clips.sort(key=lambda item: (item.start_frame, item.clip_id))
    return _replace_track(project, track_index, replace(track, clips=tuple(clips)))


def _split_camera(
    animation: CameraAnimation | None,
    split_local_frame: int,
    right_duration: int,
) -> tuple[CameraAnimation | None, CameraAnimation | None]:
    if animation is None:
        return None, None
    left_keys = tuple(
        keyframe for keyframe in animation.keyframes
        if keyframe.frame < split_local_frame
    )
    split_pose = resolve_camera_pose(animation, split_local_frame)
    right_keys = [CameraKeyframe(0, split_pose)]
    right_keys.extend(
        replace(keyframe, frame=keyframe.frame - split_local_frame)
        for keyframe in animation.keyframes
        if keyframe.frame > split_local_frame
    )
    left = CameraAnimation(left_keys).validate(
        clip_duration_frames=split_local_frame
    )
    right = CameraAnimation(tuple(right_keys)).validate(
        clip_duration_frames=right_duration
    )
    return left, right


def split_clip(
    project: StudioProject,
    clip_id: str,
    project_frame: int,
) -> tuple[StudioProject, Clip]:
    track_index, clip_index, track, clip = clip_location(project, clip_id)
    _require_editable(track)
    frame = int(project_frame)
    if not clip.start_frame < frame < clip.end_frame:
        raise ValueError("Le split doit être strictement à l’intérieur du clip")
    left_duration = frame - clip.start_frame
    right_duration = clip.end_frame - frame
    left_camera, right_camera = _split_camera(
        clip.camera, left_duration, right_duration
    )
    left = replace(
        clip,
        duration_frames=left_duration,
        camera=left_camera,
    ).validate()
    right = replace(
        clip,
        clip_id=f"{clip.clip_id}-split-{uuid4().hex[:8]}",
        start_frame=frame,
        duration_frames=right_duration,
        source_in_frame=clip.source_in_frame + left_duration,
        camera=right_camera,
    ).validate()
    clips = list(track.clips)
    clips[clip_index : clip_index + 1] = (left, right)
    clips.sort(key=lambda item: (item.start_frame, item.clip_id))
    updated = _replace_track(project, track_index, replace(track, clips=tuple(clips)))
    return updated, right


def duplicate_clip(
    project: StudioProject,
    clip_id: str,
    *,
    target_frame: int | None = None,
    target_track_id: str | None = None,
) -> tuple[StudioProject, Clip]:
    _track_index, _clip_index, track, clip = clip_location(project, clip_id)
    _require_editable(track)
    if target_frame is None:
        target_frame = (
            clip.end_frame
            if clip.end_frame + clip.duration_frames <= project.settings.duration_frames
            else clip.start_frame
        )
    duplicate = replace(
        clip,
        clip_id=f"{clip.clip_id}-copy-{uuid4().hex[:8]}",
        start_frame=int(target_frame),
    ).validate()
    temporary_track = replace(track, clips=(*track.clips, duplicate))
    temporary = _replace_track(
        project,
        track_by_id(project, track.track_id)[0],
        temporary_track,
    )
    if target_track_id is not None and target_track_id != track.track_id:
        temporary = move_clip(
            temporary,
            duplicate.clip_id,
            int(target_frame),
            target_track_id=target_track_id,
        )
    return temporary, duplicate


def delete_clips(project: StudioProject, clip_ids: tuple[str, ...]) -> StudioProject:
    selected = set(clip_ids)
    if not selected:
        return project
    known = {clip.clip_id for track in project.tracks for clip in track.clips}
    missing = selected - known
    if missing:
        raise KeyError(f"Clips Studio introuvables : {', '.join(sorted(missing))}")
    tracks: list[Track] = []
    for track in project.tracks:
        if any(clip.clip_id in selected for clip in track.clips):
            _require_editable(track)
        tracks.append(
            replace(
                track,
                clips=tuple(clip for clip in track.clips if clip.clip_id not in selected),
            )
        )
    transitions = tuple(
        transition
        for transition in project.transitions
        if transition.from_clip_id not in selected
        and transition.to_clip_id not in selected
    )
    return replace(project, tracks=tuple(tracks), transitions=transitions).validate()


def reorder_track(
    project: StudioProject,
    track_id: str,
    target_index: int,
) -> StudioProject:
    source_index, track = track_by_id(project, track_id)
    target = int(target_index)
    if not 0 <= target < len(project.tracks):
        raise IndexError("La nouvelle position de piste est hors du projet")
    tracks = list(project.tracks)
    tracks.pop(source_index)
    tracks.insert(target, track)
    return replace(project, tracks=tuple(tracks)).validate()


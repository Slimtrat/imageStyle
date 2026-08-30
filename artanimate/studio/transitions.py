from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from .easing import eased_progress
from .model import (
    Clip,
    ClipKind,
    Easing,
    StudioProject,
    Track,
    TrackKind,
    Transition,
    TransitionKind,
)
from .video import video_source_frame_count


@dataclass(frozen=True, slots=True)
class DissolveSettings:
    easing: Easing = Easing.EASE_IN_OUT

    def validate(self) -> DissolveSettings:
        if not isinstance(self.easing, Easing):
            raise TypeError("L’interpolation du fondu doit être un Easing")
        return self

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {"easing": self.easing.value}

    @classmethod
    def from_transition(cls, transition: Transition) -> DissolveSettings:
        if transition.kind != TransitionKind.DISSOLVE:
            raise ValueError("Les réglages demandés ne concernent pas un fondu")
        values = transition.parameters or {}
        raw = values.get("easing", Easing.EASE_IN_OUT.value)
        try:
            easing = Easing(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Interpolation de fondu inconnue : {raw!r}") from exc
        return cls(easing).validate()


@dataclass(frozen=True, slots=True)
class TransitionClipPair:
    track: Track
    from_clip: Clip
    to_clip: Clip


def transition_end_frame(transition: Transition) -> int:
    return transition.start_frame + transition.duration_frames


def _transition_easing(transition: Transition) -> Easing:
    if transition.kind == TransitionKind.DISSOLVE:
        return DissolveSettings.from_transition(transition).easing
    if transition.kind == TransitionKind.MATCH:
        from .manual_match import ManualMatchSettings

        return ManualMatchSettings.from_transition(transition).easing
    raise ValueError("La progression exige une transition visuelle")


def transition_progress(transition: Transition, project_frame: int) -> float:
    """Return B's exact weight, including exact zero/one endpoint frames."""

    if transition.kind not in {TransitionKind.DISSOLVE, TransitionKind.MATCH}:
        raise ValueError("La progression exige un fondu ou un match manuel")
    if not transition.start_frame <= project_frame < transition_end_frame(transition):
        raise ValueError("La frame demandée est hors de la transition")
    if transition.duration_frames < 2:
        raise ValueError("Une transition visuelle doit contenir au moins deux frames")
    linear = (project_frame - transition.start_frame) / (
        transition.duration_frames - 1
    )
    return eased_progress(linear, _transition_easing(transition))


def dissolve_progress(transition: Transition, project_frame: int) -> float:
    if transition.kind != TransitionKind.DISSOLVE:
        raise ValueError("La progression demandée ne concerne pas un fondu")
    return transition_progress(transition, project_frame)


def dissolve_weights(transition: Transition, project_frame: int) -> tuple[float, float]:
    to_weight = dissolve_progress(transition, project_frame)
    return 1.0 - to_weight, to_weight


def transition_by_id(project: StudioProject, transition_id: str) -> Transition:
    try:
        return next(
            item for item in project.transitions if item.transition_id == transition_id
        )
    except StopIteration as exc:
        raise KeyError(f"Transition Studio introuvable : {transition_id}") from exc


def _clip_pair(project: StudioProject, transition: Transition) -> TransitionClipPair:
    from_match: tuple[Track, Clip] | None = None
    to_match: tuple[Track, Clip] | None = None
    for track in project.tracks:
        for clip in track.clips:
            if clip.clip_id == transition.from_clip_id:
                from_match = (track, clip)
            if clip.clip_id == transition.to_clip_id:
                to_match = (track, clip)
    if from_match is None or to_match is None:
        raise ValueError(
            f"La transition {transition.transition_id} référence un clip introuvable"
        )
    if from_match[0].track_id != to_match[0].track_id:
        raise ValueError("Un fondu doit relier deux clips de la même piste")
    return TransitionClipPair(from_match[0], from_match[1], to_match[1])


def transition_clip_pair(
    project: StudioProject,
    transition: Transition | str,
) -> TransitionClipPair:
    resolved = (
        transition_by_id(project, transition)
        if isinstance(transition, str)
        else transition
    )
    return _clip_pair(project, resolved)


def _source_frame_count(project: StudioProject, clip: Clip) -> int | None:
    if clip.kind in {ClipKind.STILL, ClipKind.ARTWORK_2D}:
        return None
    if clip.kind == ClipKind.VIDEO:
        if clip.asset_id is None:
            raise ValueError(f"Le plan vidéo {clip.clip_id} ne référence aucun asset")
        return video_source_frame_count(project, clip.asset_id)
    if clip.kind == ClipKind.ARTWORK_3D:
        values: dict[str, Any] = clip.parameters or {}
        settings = values.get("settings", values)
        render_config = (
            settings.get("render_config", {})
            if isinstance(settings, dict)
            else {}
        )
        if isinstance(render_config, dict) and "duration" in render_config:
            return max(
                2,
                int(round(float(render_config["duration"]) * project.settings.fps)),
            )
        return project.settings.duration_frames
    raise ValueError("Un fondu ne peut relier que des plans visuels")


def _validate_source_handles(
    project: StudioProject,
    transition: Transition,
    pair: TransitionClipPair,
) -> None:
    end = transition_end_frame(transition)
    from_count = _source_frame_count(project, pair.from_clip)
    if from_count is not None:
        required_end = (
            pair.from_clip.source_in_frame + end - pair.from_clip.start_frame
        )
        if required_end > from_count:
            missing = required_end - from_count
            raise ValueError(
                f"Poignée de sortie insuffisante sur {pair.from_clip.clip_id} "
                f"({missing} frame(s) manquante(s))"
            )
    to_count = _source_frame_count(project, pair.to_clip)
    if to_count is not None:
        required_start = (
            pair.to_clip.source_in_frame
            + transition.start_frame
            - pair.to_clip.start_frame
        )
        if required_start < 0:
            raise ValueError(
                f"Poignée d’entrée insuffisante sur {pair.to_clip.clip_id} "
                f"({-required_start} frame(s) manquante(s))"
            )


def _validate_visual_transition_topology(
    project: StudioProject,
    transition: Transition,
    *,
    validate_sources: bool,
) -> TransitionClipPair:
    if transition.duration_frames < 2:
        raise ValueError("Une transition visuelle doit durer au moins deux frames")
    if transition.kind == TransitionKind.DISSOLVE:
        DissolveSettings.from_transition(transition)
    elif transition.kind == TransitionKind.MATCH:
        from .manual_match import validate_manual_match_transition

        validate_manual_match_transition(project, transition)
    else:
        raise ValueError("Cette transition n’est ni un fondu ni un match manuel")
    pair = _clip_pair(project, transition)
    if pair.track.kind != TrackKind.VIDEO:
        raise ValueError("Une transition visuelle doit être placée sur une piste image")
    if pair.from_clip.end_frame != pair.to_clip.start_frame:
        raise ValueError(
            "Les deux plans d’une transition doivent partager le même point de cut"
        )
    cut = pair.from_clip.end_frame
    end = transition_end_frame(transition)
    ordered = sorted(
        pair.track.clips,
        key=lambda clip: (clip.start_frame, clip.end_frame, clip.clip_id),
    )
    from_index = next(
        index
        for index, clip in enumerate(ordered)
        if clip.clip_id == pair.from_clip.clip_id
    )
    if (
        from_index + 1 >= len(ordered)
        or ordered[from_index + 1].clip_id != pair.to_clip.clip_id
    ):
        raise ValueError("Une transition doit relier deux plans consécutifs")
    for clip in pair.track.clips:
        if clip.clip_id in {pair.from_clip.clip_id, pair.to_clip.clip_id}:
            continue
        if max(transition.start_frame, clip.start_frame) < min(end, clip.end_frame):
            raise ValueError(
                f"Le plan {clip.clip_id} occupe déjà la fenêtre du fondu"
            )
    if not (
        pair.from_clip.start_frame <= transition.start_frame < cut
        and cut < end <= pair.to_clip.end_frame
    ):
        raise ValueError(
            "La fenêtre de transition doit entourer le cut et rester dans les deux plans"
        )
    if validate_sources:
        _validate_source_handles(project, transition, pair)
    return pair


def validate_project_transitions(
    project: StudioProject,
    *,
    validate_sources: bool = False,
) -> StudioProject:
    windows_by_track: dict[str, list[tuple[int, int, str]]] = {}
    endpoints: set[tuple[str, str]] = set()
    for transition in project.transitions:
        if transition.kind not in {TransitionKind.DISSOLVE, TransitionKind.MATCH}:
            continue
        pair = _validate_visual_transition_topology(
            project,
            transition,
            validate_sources=validate_sources,
        )
        endpoint = (transition.from_clip_id, transition.to_clip_id)
        if endpoint in endpoints:
            raise ValueError("Deux transitions visuelles relient les mêmes plans")
        endpoints.add(endpoint)
        start = transition.start_frame
        end = transition_end_frame(transition)
        for other_start, other_end, other_id in windows_by_track.setdefault(
            pair.track.track_id,
            [],
        ):
            if max(start, other_start) < min(end, other_end):
                raise ValueError(
                    f"Les transitions {other_id} et {transition.transition_id} se chevauchent"
                )
        windows_by_track[pair.track.track_id].append(
            (start, end, transition.transition_id)
        )
    return project


def _available_window(
    project: StudioProject,
    pair: TransitionClipPair,
) -> tuple[int, int]:
    cut = pair.from_clip.end_frame
    minimum = pair.from_clip.start_frame
    maximum = pair.to_clip.end_frame
    if _source_frame_count(project, pair.to_clip) is not None:
        minimum = max(minimum, cut - pair.to_clip.source_in_frame)
    from_count = _source_frame_count(project, pair.from_clip)
    if from_count is not None:
        maximum = min(
            maximum,
            pair.from_clip.start_frame
            + from_count
            - pair.from_clip.source_in_frame,
        )
    return minimum, maximum


def _fit_window_around_cut(
    pair: TransitionClipPair,
    minimum: int,
    maximum: int,
    duration: int,
) -> tuple[int, int]:
    cut = pair.from_clip.end_frame
    start = cut - duration // 2
    end = start + duration
    if start < minimum:
        end += minimum - start
        start = minimum
    if end > maximum:
        start -= end - maximum
        end = maximum
    if start < minimum or not start < cut < end or end - start != duration:
        raise ValueError("Les sources ne possèdent pas assez de poignées autour du cut")
    return start, end


def add_dissolve(
    project: StudioProject,
    first_clip_id: str,
    second_clip_id: str,
    *,
    duration_frames: int | None = None,
    easing: Easing = Easing.EASE_IN_OUT,
) -> tuple[StudioProject, Transition]:
    if first_clip_id == second_clip_id:
        raise ValueError("Sélectionnez deux plans différents")
    candidates = []
    for track in project.tracks:
        for clip in track.clips:
            if clip.clip_id in {first_clip_id, second_clip_id}:
                candidates.append(clip)
    if len(candidates) != 2:
        raise KeyError("Les deux plans sélectionnés sont introuvables")
    candidates.sort(key=lambda clip: (clip.start_frame, clip.end_frame, clip.clip_id))
    from_clip, to_clip = candidates
    provisional = Transition(
        f"dissolve-{uuid4().hex[:12]}",
        TransitionKind.DISSOLVE,
        from_clip.clip_id,
        to_clip.clip_id,
        max(from_clip.start_frame, from_clip.end_frame - 1),
        2,
        DissolveSettings(easing).to_dict(),
    )
    pair = _clip_pair(project, provisional)
    if pair.from_clip.end_frame != pair.to_clip.start_frame:
        raise ValueError("Le fondu exige deux plans adjacents sur la même piste")
    minimum, maximum = _available_window(project, pair)
    available = maximum - minimum
    requested = (
        max(2, int(round(project.settings.fps * 0.4)))
        if duration_frames is None
        else duration_frames
    )
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 2:
        raise ValueError("La durée du fondu doit être un entier d’au moins deux frames")
    duration = min(requested, available) if duration_frames is None else requested
    start, _end = _fit_window_around_cut(pair, minimum, maximum, duration)
    transition = replace(
        provisional,
        start_frame=start,
        duration_frames=duration,
    ).validate()
    candidate = replace(project, transitions=(*project.transitions, transition))
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate(), transition


def update_dissolve(
    project: StudioProject,
    transition_id: str,
    *,
    start_frame: int | None = None,
    end_frame: int | None = None,
    duration_frames: int | None = None,
    easing: Easing | None = None,
) -> StudioProject:
    current = transition_by_id(project, transition_id)
    if current.kind != TransitionKind.DISSOLVE:
        raise ValueError("Seul un fondu peut être réglé ici")
    start = current.start_frame if start_frame is None else int(start_frame)
    if end_frame is not None and duration_frames is not None:
        raise ValueError("Indiquez une fin ou une durée, pas les deux")
    if end_frame is not None:
        end = int(end_frame)
    elif duration_frames is not None and start_frame is None:
        duration = int(duration_frames)
        if duration == current.duration_frames:
            end = transition_end_frame(current)
        else:
            pair = _clip_pair(project, current)
            minimum, maximum = _available_window(project, pair)
            start, end = _fit_window_around_cut(
                pair,
                minimum,
                maximum,
                duration,
            )
    else:
        duration = (
            current.duration_frames
            if duration_frames is None
            else int(duration_frames)
        )
        end = start + duration
    settings = DissolveSettings.from_transition(current)
    if easing is not None:
        settings = DissolveSettings(Easing(easing)).validate()
    updated = replace(
        current,
        start_frame=start,
        duration_frames=end - start,
        parameters=settings.to_dict(),
    ).validate()
    transitions = tuple(
        updated if item.transition_id == transition_id else item
        for item in project.transitions
    )
    candidate = replace(project, transitions=transitions)
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate()


def delete_transition(project: StudioProject, transition_id: str) -> StudioProject:
    transition_by_id(project, transition_id)
    return replace(
        project,
        transitions=tuple(
            item for item in project.transitions if item.transition_id != transition_id
        ),
    ).validate()


def without_clip_transitions(
    project: StudioProject,
    clip_ids: tuple[str, ...] | set[str],
) -> StudioProject:
    selected = set(clip_ids)
    transitions = tuple(
        item
        for item in project.transitions
        if item.from_clip_id not in selected and item.to_clip_id not in selected
    )
    return project if transitions == project.transitions else replace(
        project,
        transitions=transitions,
    )


def render_window_for_clip(project: StudioProject, clip: Clip) -> tuple[int, int]:
    start = clip.start_frame
    end = clip.end_frame
    for transition in project.transitions:
        if transition.kind not in {TransitionKind.DISSOLVE, TransitionKind.MATCH}:
            continue
        if transition.from_clip_id == clip.clip_id:
            end = max(end, transition_end_frame(transition))
        if transition.to_clip_id == clip.clip_id:
            start = min(start, transition.start_frame)
    return start, end


def render_source_in_frame(project: StudioProject, clip: Clip, render_start: int) -> int:
    if clip.kind in {ClipKind.STILL, ClipKind.ARTWORK_2D}:
        return 0
    return clip.source_in_frame + render_start - clip.start_frame


def active_visual_transition(
    project: StudioProject,
    track_id: str,
    project_frame: int,
) -> Transition | None:
    matches = []
    for transition in project.transitions:
        if transition.kind not in {TransitionKind.DISSOLVE, TransitionKind.MATCH}:
            continue
        if not transition.start_frame <= project_frame < transition_end_frame(transition):
            continue
        if _clip_pair(project, transition).track.track_id == track_id:
            matches.append(transition)
    if len(matches) > 1:
        raise ValueError("Deux transitions sont actives simultanément sur la même piste")
    return matches[0] if matches else None


def active_dissolve(
    project: StudioProject,
    track_id: str,
    project_frame: int,
) -> Transition | None:
    transition = active_visual_transition(project, track_id, project_frame)
    return (
        transition
        if transition is not None and transition.kind == TransitionKind.DISSOLVE
        else None
    )

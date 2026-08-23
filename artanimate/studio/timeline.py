from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .model import StudioProject, Track, TrackKind


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


from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from .model import ClipKind, StudioProject
from .music_analysis import MusicAnalysis, MusicEventKind
from .semantic import FrozenJsonObject


MARKER_SCHEMA_VERSION = 1
MARKER_PROJECT_EXTENSION = "timeline_markers"


class MarkerKind(StrEnum):
    BEAT = "beat"
    DOWNBEAT = "downbeat"
    DROP = "drop"
    CUSTOM = "custom"


class MarkerOrigin(StrEnum):
    DETECTED = "detected"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class TimelineMarker:
    marker_id: str
    frame: int
    kind: MarkerKind
    label: str
    origin: MarkerOrigin = MarkerOrigin.MANUAL
    confidence: float | None = None
    uncertain: bool = False
    adjusted: bool = False
    source_asset_id: str | None = None
    source_fingerprint: str | None = None
    source_sample: int | None = None
    source_sample_rate: int | None = None

    def validate(self, *, duration_frames: int) -> TimelineMarker:
        if not isinstance(self.marker_id, str) or not self.marker_id.strip():
            raise ValueError("Un marqueur exige un identifiant")
        if (
            isinstance(self.frame, bool)
            or not isinstance(self.frame, int)
            or not 0 <= self.frame < duration_frames
        ):
            raise ValueError("La frame du marqueur est hors du projet")
        if not isinstance(self.kind, MarkerKind):
            raise TypeError("Le type du marqueur est invalide")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Le libellé du marqueur est vide")
        if len(self.label) > 120:
            raise ValueError("Le libellé du marqueur dépasse 120 caractères")
        if not isinstance(self.origin, MarkerOrigin):
            raise TypeError("L’origine du marqueur est invalide")
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, int | float)
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("La confiance du marqueur est hors limites")
        if not isinstance(self.uncertain, bool) or not isinstance(
            self.adjusted, bool
        ):
            raise TypeError("Les états du marqueur doivent être booléens")
        source_values = (
            self.source_asset_id,
            self.source_fingerprint,
            self.source_sample,
            self.source_sample_rate,
        )
        if any(value is not None for value in source_values):
            if not all(value is not None for value in source_values):
                raise ValueError("La provenance audio du marqueur est incomplète")
            if (
                not isinstance(self.source_asset_id, str)
                or not self.source_asset_id
                or not isinstance(self.source_fingerprint, str)
                or not self.source_fingerprint
                or isinstance(self.source_sample, bool)
                or not isinstance(self.source_sample, int)
                or self.source_sample < 0
                or isinstance(self.source_sample_rate, bool)
                or not isinstance(self.source_sample_rate, int)
                or self.source_sample_rate <= 0
            ):
                raise ValueError("La provenance audio du marqueur est invalide")
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.marker_id,
            "frame": self.frame,
            "kind": self.kind.value,
            "label": self.label,
            "origin": self.origin.value,
            "confidence": (
                round(float(self.confidence), 6)
                if self.confidence is not None
                else None
            ),
            "uncertain": self.uncertain,
            "adjusted": self.adjusted,
            "source_asset_id": self.source_asset_id,
            "source_fingerprint": self.source_fingerprint,
            "source_sample": self.source_sample,
            "source_sample_rate": self.source_sample_rate,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> TimelineMarker:
        uncertain = payload.get("uncertain", False)
        adjusted = payload.get("adjusted", False)
        if not isinstance(uncertain, bool) or not isinstance(adjusted, bool):
            raise TypeError("Les états du marqueur doivent être booléens")
        confidence = payload.get("confidence")
        return cls(
            marker_id=str(payload["id"]),
            frame=int(payload["frame"]),
            kind=MarkerKind(str(payload["kind"])),
            label=str(payload["label"]),
            origin=MarkerOrigin(
                str(payload.get("origin", MarkerOrigin.MANUAL.value))
            ),
            confidence=(float(confidence) if confidence is not None else None),
            uncertain=uncertain,
            adjusted=adjusted,
            source_asset_id=(
                str(payload["source_asset_id"])
                if payload.get("source_asset_id") is not None
                else None
            ),
            source_fingerprint=(
                str(payload["source_fingerprint"])
                if payload.get("source_fingerprint") is not None
                else None
            ),
            source_sample=(
                int(payload["source_sample"])
                if payload.get("source_sample") is not None
                else None
            ),
            source_sample_rate=(
                int(payload["source_sample_rate"])
                if payload.get("source_sample_rate") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class TimelineMarkerState:
    markers: tuple[TimelineMarker, ...] = ()
    visible_kind: MarkerKind | None = None

    def validate(self, *, duration_frames: int) -> TimelineMarkerState:
        if self.visible_kind is not None and not isinstance(
            self.visible_kind, MarkerKind
        ):
            raise TypeError("Le filtre de marqueurs est invalide")
        identities: set[str] = set()
        previous: tuple[int, str] | None = None
        for marker in self.markers:
            marker.validate(duration_frames=duration_frames)
            if marker.marker_id in identities:
                raise ValueError("Un identifiant de marqueur est dupliqué")
            identities.add(marker.marker_id)
            position = (marker.frame, marker.marker_id)
            if previous is not None and position < previous:
                raise ValueError("Les marqueurs doivent être triés")
            previous = position
        return self

    def visible_markers(self) -> tuple[TimelineMarker, ...]:
        if self.visible_kind is None:
            return self.markers
        return tuple(
            marker for marker in self.markers
            if marker.kind == self.visible_kind
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MARKER_SCHEMA_VERSION,
            "visible_kind": (
                self.visible_kind.value if self.visible_kind is not None else None
            ),
            "markers": [marker.to_dict() for marker in self.markers],
        }

    @classmethod
    def from_project(cls, project: StudioProject) -> TimelineMarkerState:
        payload = project.extensions.to_dict().get(
            MARKER_PROJECT_EXTENSION, {}
        )
        if not isinstance(payload, Mapping):
            raise TypeError("L’extension timeline_markers doit être un objet")
        version = payload.get("schema_version", MARKER_SCHEMA_VERSION)
        if isinstance(version, bool) or version != MARKER_SCHEMA_VERSION:
            raise ValueError(f"Version de marqueurs inconnue : {version}")
        raw_markers = payload.get("markers", [])
        if not isinstance(raw_markers, list) or not all(
            isinstance(item, Mapping) for item in raw_markers
        ):
            raise TypeError("timeline_markers.markers doit être une liste d’objets")
        raw_filter = payload.get("visible_kind")
        return cls(
            markers=tuple(
                sorted(
                    (TimelineMarker.from_mapping(item) for item in raw_markers),
                    key=lambda marker: (marker.frame, marker.marker_id),
                )
            ),
            visible_kind=(
                MarkerKind(str(raw_filter)) if raw_filter is not None else None
            ),
        ).validate(duration_frames=project.settings.duration_frames)


def set_timeline_marker_state(
    project: StudioProject,
    state: TimelineMarkerState,
) -> StudioProject:
    validated = state.validate(
        duration_frames=project.settings.duration_frames
    )
    values = project.extensions.to_dict()
    values[MARKER_PROJECT_EXTENSION] = validated.to_dict()
    return replace(
        project,
        extensions=FrozenJsonObject(values, where="project.extensions"),
    ).validate()


def marker_by_id(project: StudioProject, marker_id: str) -> TimelineMarker:
    state = TimelineMarkerState.from_project(project)
    try:
        return next(
            marker for marker in state.markers if marker.marker_id == marker_id
        )
    except StopIteration as exc:
        raise KeyError(f"Marqueur introuvable : {marker_id}") from exc


def add_custom_marker(
    project: StudioProject,
    frame: int,
    *,
    label: str = "Repère",
) -> tuple[StudioProject, TimelineMarker]:
    marker = TimelineMarker(
        marker_id=f"marker-{uuid4().hex[:16]}",
        frame=int(frame),
        kind=MarkerKind.CUSTOM,
        label=label.strip() or "Repère",
    ).validate(duration_frames=project.settings.duration_frames)
    state = TimelineMarkerState.from_project(project)
    markers = tuple(
        sorted(
            (*state.markers, marker),
            key=lambda item: (item.frame, item.marker_id),
        )
    )
    return (
        set_timeline_marker_state(
            project,
            replace(state, markers=markers),
        ),
        marker,
    )


def update_timeline_marker(
    project: StudioProject,
    marker_id: str,
    *,
    frame: int | None = None,
    kind: MarkerKind | None = None,
    label: str | None = None,
) -> StudioProject:
    state = TimelineMarkerState.from_project(project)
    existing = marker_by_id(project, marker_id)
    if kind is not None and not isinstance(kind, MarkerKind):
        raise TypeError("Le type de marqueur est invalide")
    updated = replace(
        existing,
        frame=existing.frame if frame is None else int(frame),
        kind=existing.kind if kind is None else kind,
        label=existing.label if label is None else (label.strip() or "Repère"),
        uncertain=False,
        adjusted=True,
    ).validate(duration_frames=project.settings.duration_frames)
    markers = tuple(
        sorted(
            (
                updated if marker.marker_id == marker_id else marker
                for marker in state.markers
            ),
            key=lambda item: (item.frame, item.marker_id),
        )
    )
    return set_timeline_marker_state(
        project,
        replace(state, markers=markers),
    )


def delete_timeline_marker(
    project: StudioProject,
    marker_id: str,
) -> StudioProject:
    state = TimelineMarkerState.from_project(project)
    markers = tuple(
        marker for marker in state.markers if marker.marker_id != marker_id
    )
    if len(markers) == len(state.markers):
        raise KeyError(f"Marqueur introuvable : {marker_id}")
    return set_timeline_marker_state(
        project,
        replace(state, markers=markers),
    )


def set_marker_visibility(
    project: StudioProject,
    kind: MarkerKind | None,
) -> StudioProject:
    if kind is not None and not isinstance(kind, MarkerKind):
        raise TypeError("Le filtre de marqueurs est invalide")
    state = TimelineMarkerState.from_project(project)
    return set_timeline_marker_state(
        project,
        replace(state, visible_kind=kind),
    )


def adjacent_marker(
    project: StudioProject,
    playhead: int,
    direction: int,
) -> TimelineMarker | None:
    if direction not in {-1, 1}:
        raise ValueError("La navigation de marqueurs exige -1 ou +1")
    markers = TimelineMarkerState.from_project(project).visible_markers()
    if not markers:
        return None
    if direction > 0:
        return next(
            (marker for marker in markers if marker.frame > playhead),
            markers[0],
        )
    return next(
        (marker for marker in reversed(markers) if marker.frame < playhead),
        markers[-1],
    )


_ANALYSIS_KIND_TO_MARKER = {
    MusicEventKind.BEAT: MarkerKind.BEAT,
    MusicEventKind.DOWNBEAT: MarkerKind.DOWNBEAT,
    MusicEventKind.DROP: MarkerKind.DROP,
}

_DETECTED_LABELS = {
    MarkerKind.BEAT: "Beat détecté",
    MarkerKind.DOWNBEAT: "Temps fort détecté",
    MarkerKind.DROP: "Drop détecté",
}


def _detected_marker_id(
    asset_id: str,
    fingerprint: str,
    clip_id: str,
    kind: MarkerKind,
    source_sample: int,
) -> str:
    digest = sha256(
        (
            f"{asset_id}\0{fingerprint}\0{clip_id}\0"
            f"{kind.value}\0{source_sample}"
        ).encode("utf-8")
    ).hexdigest()
    return f"music-{digest[:20]}"


def import_music_analysis_markers(
    project: StudioProject,
    asset_id: str,
    analysis: MusicAnalysis,
) -> tuple[StudioProject, tuple[TimelineMarker, ...]]:
    analysis.validate()
    if analysis.fps != project.settings.fps:
        raise ValueError(
            "L’analyse musicale et le projet doivent partager le même FPS"
        )
    clips = tuple(
        clip
        for track in project.tracks
        for clip in track.clips
        if clip.kind == ClipKind.AUDIO and clip.asset_id == asset_id
    )
    if not clips:
        raise ValueError(
            "Placez cette piste audio sur la timeline avant d’ajouter ses repères"
        )
    state = TimelineMarkerState.from_project(project)
    identities = {marker.marker_id for marker in state.markers}
    added: list[TimelineMarker] = []
    for clip in clips:
        source_end = clip.source_in_frame + clip.duration_frames
        for event in analysis.events:
            if not clip.source_in_frame <= event.frame < source_end:
                continue
            kind = _ANALYSIS_KIND_TO_MARKER[event.kind]
            marker_id = _detected_marker_id(
                asset_id,
                analysis.source_fingerprint,
                clip.clip_id,
                kind,
                event.source_sample,
            )
            if marker_id in identities:
                continue
            marker = TimelineMarker(
                marker_id=marker_id,
                frame=(
                    clip.start_frame + event.frame - clip.source_in_frame
                ),
                kind=kind,
                label=_DETECTED_LABELS[kind],
                origin=MarkerOrigin.DETECTED,
                confidence=event.confidence,
                uncertain=event.uncertain,
                source_asset_id=asset_id,
                source_fingerprint=analysis.source_fingerprint,
                source_sample=event.source_sample,
                source_sample_rate=analysis.sample_rate,
            ).validate(duration_frames=project.settings.duration_frames)
            identities.add(marker_id)
            added.append(marker)
    if not added:
        return project, ()
    markers = tuple(
        sorted(
            (*state.markers, *added),
            key=lambda item: (item.frame, item.marker_id),
        )
    )
    updated = set_timeline_marker_state(
        project,
        replace(state, markers=markers),
    )
    return updated, tuple(
        sorted(added, key=lambda item: (item.frame, item.marker_id))
    )

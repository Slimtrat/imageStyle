from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

import numpy as np

from ..core.config import RenderConfig
from ..core.effects import effect_keys
from .artwork_source import (
    DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
    ArtworkTimedFrameSource,
    ArtworkTimedSourceFactory,
)
from .sources import validate_frame_index


if TYPE_CHECKING:
    from .model import Clip, StudioProject


EFFECT_2D_SCHEMA_VERSION = 1
MIN_EFFECT_DURATION_SECONDS = 0.5
MAX_EFFECT_DURATION_SECONDS = 2.0


def _finite_ratio(value: float, field: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field} doit être numérique")
    number = float(value)
    if not np.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} doit être compris entre 0 et 1")
    return number


def _snapshot_for_duration(
    config: RenderConfig,
    *,
    duration_seconds: float,
    fps: int,
) -> RenderConfig:
    if not MIN_EFFECT_DURATION_SECONDS <= duration_seconds <= MAX_EFFECT_DURATION_SECONDS:
        raise ValueError(
            "La durée d’un calque 2D doit être comprise entre 0,5 et 2 secondes"
        )
    if fps <= 0:
        raise ValueError("Le framerate du calque 2D doit être positif")
    values = config.to_dict()
    original_duration = max(float(values["duration"]), 1e-6)
    hold_start_ratio = float(values["hold_start"]) / original_duration
    hold_end_ratio = float(values["hold_end"]) / original_duration
    values.update(
        duration=float(duration_seconds),
        fps=int(fps),
        hold_start=float(duration_seconds) * hold_start_ratio,
        hold_end=float(duration_seconds) * hold_end_ratio,
    )
    return RenderConfig.from_dict(values)


@dataclass(frozen=True, slots=True)
class Effect2DClipSettings:
    """Deeply snapshotted settings owned by one temporal artwork effect clip."""

    config_json: str
    intensity: float = 1.0
    target_clip_id: str = "artwork-main"

    @classmethod
    def from_config(
        cls,
        config: RenderConfig,
        *,
        duration_seconds: float,
        fps: int,
        intensity: float = 1.0,
        target_clip_id: str = "artwork-main",
    ) -> Effect2DClipSettings:
        snapshot = _snapshot_for_duration(
            config,
            duration_seconds=duration_seconds,
            fps=fps,
        )
        return cls(
            json.dumps(
                snapshot.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            _finite_ratio(intensity, "L’intensité du calque 2D"),
            str(target_clip_id),
        ).validate()

    @property
    def config(self) -> RenderConfig:
        values = json.loads(self.config_json)
        if not isinstance(values, dict):
            raise ValueError("Le snapshot du calque 2D doit contenir un objet JSON")
        return RenderConfig.from_dict(values)

    @property
    def effect(self) -> str:
        return self.config.effect

    def validate(self) -> Effect2DClipSettings:
        config = self.config
        _finite_ratio(self.intensity, "L’intensité du calque 2D")
        if not self.target_clip_id or not self.target_clip_id.strip():
            raise ValueError("Le calque 2D doit cibler un clip de l’œuvre")
        if config.effect not in effect_keys():
            raise ValueError(f"Effet 2D inconnu : {config.effect}")
        if not MIN_EFFECT_DURATION_SECONDS <= config.duration <= MAX_EFFECT_DURATION_SECONDS:
            raise ValueError(
                "La durée source d’un calque 2D doit être comprise entre 0,5 et 2 secondes"
            )
        return self

    def to_parameters(self) -> dict[str, Any]:
        config = self.config
        return {
            "schema_version": EFFECT_2D_SCHEMA_VERSION,
            "effect": config.effect,
            "intensity": self.intensity,
            "target_clip_id": self.target_clip_id,
            "render_config": config.to_dict(),
        }

    @classmethod
    def from_parameters(cls, parameters: Mapping[str, Any] | None) -> Effect2DClipSettings:
        if not isinstance(parameters, Mapping):
            raise ValueError("Le clip d’effet 2D ne contient pas ses réglages")
        version = parameters.get("schema_version")
        if version != EFFECT_2D_SCHEMA_VERSION:
            raise ValueError(f"Version de calque 2D non prise en charge : {version!r}")
        known = {
            "schema_version",
            "effect",
            "intensity",
            "target_clip_id",
            "render_config",
        }
        unknown = sorted(str(key) for key in set(parameters) - known)
        if unknown:
            raise ValueError(f"Réglage(s) de calque 2D inconnu(s) : {', '.join(unknown)}")
        raw_config = parameters.get("render_config")
        if not isinstance(raw_config, dict):
            raise ValueError("Le calque 2D doit figer une configuration de rendu complète")
        config = RenderConfig.from_dict(dict(raw_config))
        if parameters.get("effect") != config.effect:
            raise ValueError("La clé d’effet ne correspond pas au snapshot du calque 2D")
        return cls(
            json.dumps(
                config.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            _finite_ratio(parameters.get("intensity", 1.0), "L’intensité du calque 2D"),
            str(parameters.get("target_clip_id", "")),
        ).validate()


class Effect2DTimedFrameSource:
    """Artwork-relative effect frames plus their exact reference presentation."""

    def __init__(
        self,
        source: ArtworkTimedFrameSource,
        settings: Effect2DClipSettings,
    ):
        self.source = source
        self.settings = settings.validate()
        self.width = source.width
        self.height = source.height
        self.fps = source.fps
        self.frame_count = source.frame_count
        reference = np.ascontiguousarray(source.renderer.analysis.source, dtype=np.uint8).copy()
        reference.setflags(write=False)
        self.reference_frame = reference

    def frame_at(self, frame_index: int) -> np.ndarray:
        index = validate_frame_index(frame_index, self.frame_count)
        return self.source.frame_at(index)


class Effect2DSourceFactory:
    def __init__(self, artwork_factory: ArtworkTimedSourceFactory | None = None):
        self.artwork_factory = artwork_factory or ArtworkTimedSourceFactory()

    def source(
        self,
        path: str | Path,
        settings: Effect2DClipSettings,
        *,
        fingerprint: str | None = None,
        max_cache_bytes: int = DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
    ) -> Effect2DTimedFrameSource:
        validated = settings.validate()
        source = self.artwork_factory.source(
            path,
            validated.config,
            fingerprint=fingerprint,
            presentation="2d",
            max_cache_bytes=max_cache_bytes,
        )
        return Effect2DTimedFrameSource(source, validated)

    def clear(self) -> None:
        self.artwork_factory.clear()


def settings_for_effect_clip(clip: Clip) -> Effect2DClipSettings:
    from .model import ClipKind

    if clip.kind != ClipKind.EFFECT_2D:
        raise ValueError(f"Le clip {clip.clip_id} n’est pas un calque d’effet 2D")
    return Effect2DClipSettings.from_parameters(clip.parameters)


def add_effect_clip(
    project: StudioProject,
    config: RenderConfig,
    *,
    start_frame: int,
    duration_seconds: float = 1.0,
    intensity: float = 1.0,
    opacity: float = 1.0,
    target_clip_id: str = "artwork-main",
) -> tuple[StudioProject, Clip]:
    from .model import Clip, ClipKind, TrackKind

    project.validate()
    if isinstance(start_frame, bool) or not isinstance(start_frame, int):
        raise TypeError("La position du calque 2D doit être une frame entière")
    start = start_frame
    duration = float(duration_seconds)
    if not MIN_EFFECT_DURATION_SECONDS <= duration <= MAX_EFFECT_DURATION_SECONDS:
        raise ValueError(
            "La durée d’un calque 2D doit être comprise entre 0,5 et 2 secondes"
        )
    duration_frames = max(2, int(round(duration * project.settings.fps)))
    if start < 0 or start + duration_frames > project.settings.duration_frames:
        raise ValueError("Le calque d’effet 2D dépasse la durée du projet")
    target = next(
        (
            clip
            for track in project.tracks
            for clip in track.clips
            if clip.clip_id == target_clip_id
            and clip.kind in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}
        ),
        None,
    )
    if target is None:
        raise ValueError("Le calque d’effet 2D doit cibler un plan de l’œuvre existant")
    if start < target.start_frame or start + duration_frames > target.end_frame:
        raise ValueError("Le calque d’effet 2D doit rester dans le plan de l’œuvre ciblé")
    settings = Effect2DClipSettings.from_config(
        config,
        duration_seconds=duration_frames / project.settings.fps,
        fps=project.settings.fps,
        intensity=intensity,
        target_clip_id=target_clip_id,
    )
    clip = Clip(
        clip_id=f"effect-{settings.effect}-{uuid4().hex[:8]}",
        kind=ClipKind.EFFECT_2D,
        start_frame=start,
        duration_frames=duration_frames,
        opacity=_finite_ratio(opacity, "L’opacité du calque 2D"),
        parameters=settings.to_parameters(),
    ).validate()
    track_index = next(
        (
            index
            for index, track in enumerate(project.tracks)
            if track.kind == TrackKind.EFFECT and not track.locked
        ),
        None,
    )
    if track_index is None:
        raise ValueError("Le projet ne contient aucune piste d’effets 2D modifiable")
    tracks = list(project.tracks)
    track = tracks[track_index]
    clips = tuple(sorted((*track.clips, clip), key=lambda item: (item.start_frame, item.clip_id)))
    tracks[track_index] = replace(track, clips=clips)
    return replace(project, tracks=tuple(tracks)).validate(), clip


def update_effect_clip(
    project: StudioProject,
    clip_id: str,
    *,
    config: RenderConfig,
    duration_seconds: float,
    intensity: float,
    opacity: float,
    enabled: bool,
) -> tuple[StudioProject, Clip]:
    from .timeline import clip_location

    track_index, clip_index, track, clip = clip_location(project, clip_id)
    if track.locked:
        raise PermissionError("La piste du calque d’effet 2D est verrouillée")
    previous = settings_for_effect_clip(clip)
    duration = float(duration_seconds)
    if not MIN_EFFECT_DURATION_SECONDS <= duration <= MAX_EFFECT_DURATION_SECONDS:
        raise ValueError(
            "La durée d’un calque 2D doit être comprise entre 0,5 et 2 secondes"
        )
    if not isinstance(enabled, bool):
        raise TypeError("L’état du calque d’effet 2D doit être booléen")
    duration_frames = max(2, int(round(duration * project.settings.fps)))
    if clip.start_frame + duration_frames > project.settings.duration_frames:
        raise ValueError("Le calque d’effet 2D dépasse la durée du projet")
    target = next(
        (
            candidate
            for candidate_track in project.tracks
            for candidate in candidate_track.clips
            if candidate.clip_id == previous.target_clip_id
        ),
        None,
    )
    if target is None or clip.start_frame + duration_frames > target.end_frame:
        raise ValueError("Le calque d’effet 2D doit rester dans le plan de l’œuvre ciblé")
    settings = Effect2DClipSettings.from_config(
        config,
        duration_seconds=duration_frames / project.settings.fps,
        fps=project.settings.fps,
        intensity=intensity,
        target_clip_id=previous.target_clip_id,
    )
    updated = replace(
        clip,
        duration_frames=duration_frames,
        source_in_frame=0,
        opacity=_finite_ratio(opacity, "L’opacité du calque 2D"),
        enabled=enabled,
        parameters=settings.to_parameters(),
    ).validate()
    clips = list(track.clips)
    clips[clip_index] = updated
    tracks = list(project.tracks)
    tracks[track_index] = replace(track, clips=tuple(clips))
    return replace(project, tracks=tuple(tracks)).validate(), updated

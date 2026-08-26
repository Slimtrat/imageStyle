from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
from uuid import uuid4

from .assets import resolve_asset_path
from .clock import StudioClock
from .model import (
    AssetKind,
    Clip,
    ClipKind,
    MediaAsset,
    StudioProject,
    Track,
    TrackKind,
)


AUDIO_SETTINGS_VERSION = 1


@dataclass(frozen=True, slots=True)
class AudioClipSettings:
    """Serialized audio intent shared by monitoring, waveform and final mixing."""

    gain_db: float = 0.0
    fade_in_frames: int = 0
    fade_out_frames: int = 0

    def validate(self, *, duration_frames: int | None = None) -> AudioClipSettings:
        if isinstance(self.gain_db, bool) or not isinstance(self.gain_db, int | float):
            raise TypeError("audio.gain_db doit être un nombre")
        if not -60.0 <= float(self.gain_db) <= 12.0:
            raise ValueError("audio.gain_db doit être compris entre -60 et +12 dB")
        for name, value in (
            ("fade_in_frames", self.fade_in_frames),
            ("fade_out_frames", self.fade_out_frames),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"audio.{name} doit être une durée positive en frames")
        if (
            duration_frames is not None
            and self.fade_in_frames + self.fade_out_frames > duration_frames
        ):
            raise ValueError("Les fondus audio dépassent la durée du clip")
        return self

    def to_dict(self) -> dict[str, int | float]:
        return {
            "schema_version": AUDIO_SETTINGS_VERSION,
            "gain_db": float(self.gain_db),
            "fade_in_frames": self.fade_in_frames,
            "fade_out_frames": self.fade_out_frames,
        }

    @classmethod
    def from_clip(cls, clip: Clip) -> AudioClipSettings:
        if clip.kind != ClipKind.AUDIO:
            raise ValueError("Les réglages audio exigent un clip audio")
        values = clip.parameters or {}
        version = values.get("schema_version", AUDIO_SETTINGS_VERSION)
        if version != AUDIO_SETTINGS_VERSION:
            raise ValueError(f"Version de réglages audio inconnue : {version}")
        return cls(
            gain_db=float(values.get("gain_db", 0.0)),
            fade_in_frames=int(values.get("fade_in_frames", 0)),
            fade_out_frames=int(values.get("fade_out_frames", 0)),
        ).validate(duration_frames=clip.duration_frames)


@dataclass(frozen=True, slots=True)
class AudioPlaybackTarget:
    track_id: str
    clip_id: str
    asset_id: str
    path: Path
    source_frame: int
    position_ms: int
    gain_db: float


@dataclass(frozen=True, slots=True)
class AudioMonitorFrame:
    project_frame: int
    targets: tuple[AudioPlaybackTarget, ...] = ()
    missing_asset_ids: tuple[str, ...] = ()


def _audio_asset(project: StudioProject, asset_id: str) -> MediaAsset:
    try:
        asset = next(item for item in project.assets if item.asset_id == asset_id)
    except StopIteration as exc:
        raise KeyError(f"Asset audio introuvable : {asset_id}") from exc
    if asset.kind != AssetKind.AUDIO:
        raise ValueError(f"L’asset {asset_id} n’est pas un média audio")
    return asset


def _asset_duration_frames(asset: MediaAsset, clock: StudioClock) -> int | None:
    metadata = asset.metadata or {}
    seconds = metadata.get("duration_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
        return None
    return max(1, ceil(float(seconds) * clock.fps))


def add_audio_clip(
    project: StudioProject,
    asset_id: str,
    *,
    track_id: str | None = None,
    start_frame: int,
    source_in_frame: int = 0,
    duration_frames: int | None = None,
) -> tuple[StudioProject, Clip]:
    """Place a local audio reference on an editable audio track."""

    asset = _audio_asset(project, asset_id)
    clock = StudioClock(project.settings.fps)
    clock.validate_frame(start_frame)
    clock.validate_frame(source_in_frame)
    if start_frame >= project.settings.duration_frames:
        raise ValueError("Le clip audio doit commencer dans la durée du projet")
    remaining = project.settings.duration_frames - start_frame
    available = _asset_duration_frames(
        asset, clock,
    )
    if available is not None:
        available = max(0, available - source_in_frame)
        remaining = min(remaining, available)
    if duration_frames is not None and (
        isinstance(duration_frames, bool) or not isinstance(duration_frames, int)
    ):
        raise TypeError("La durée d’un clip audio doit être un entier de frames")
    duration = remaining if duration_frames is None else duration_frames
    duration = min(duration, remaining)
    if duration <= 0:
        raise ValueError("La plage audio sélectionnée est vide")

    if track_id is None:
        track_index = next(
            (
                index
                for index, track in enumerate(project.tracks)
                if track.kind == TrackKind.AUDIO and not track.locked
            ),
            None,
        )
    else:
        track_index = next(
            (
                index for index, track in enumerate(project.tracks)
                if track.track_id == track_id
            ),
            None,
        )
        if track_index is None:
            raise KeyError(f"Piste audio introuvable : {track_id}")
        if project.tracks[track_index].kind != TrackKind.AUDIO:
            raise ValueError("Le clip audio exige une piste audio")
        if project.tracks[track_index].locked:
            raise PermissionError("La piste audio ciblée est verrouillée")
    tracks = list(project.tracks)
    if track_index is None:
        tracks.append(
            Track(
                f"audio-{uuid4().hex[:12]}",
                TrackKind.AUDIO,
                "Musique",
            )
        )
        track_index = len(tracks) - 1
    settings = AudioClipSettings().validate(duration_frames=duration)
    clip = Clip(
        f"audio-clip-{uuid4().hex[:12]}",
        ClipKind.AUDIO,
        start_frame,
        duration,
        source_in_frame=source_in_frame,
        asset_id=asset_id,
        parameters=settings.to_dict(),
    ).validate()
    track = tracks[track_index]
    tracks[track_index] = replace(
        track,
        clips=tuple(
            sorted(
                (*track.clips, clip),
                key=lambda item: (item.start_frame, item.clip_id),
            )
        ),
    )
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        item
        for track in updated.tracks
        for item in track.clips
        if item.clip_id == clip.clip_id
    )
    return updated, effective


def audio_monitor_frame(
    project: StudioProject,
    frame: int,
    project_path: str | Path | None,
) -> AudioMonitorFrame:
    """Resolve the exact audible source positions for one Studio project frame."""

    clock = StudioClock(project.settings.fps)
    clock.validate_frame(frame)
    if frame >= project.settings.duration_frames:
        raise ValueError("La frame audio dépasse la durée du projet")
    assets = {item.asset_id: item for item in project.assets}
    targets: list[AudioPlaybackTarget] = []
    missing: set[str] = set()
    for track in project.tracks:
        if track.kind != TrackKind.AUDIO or track.muted:
            continue
        for clip in track.clips:
            if not clip.enabled or not clip.start_frame <= frame < clip.end_frame:
                continue
            if clip.asset_id is None:
                continue
            asset = assets.get(clip.asset_id)
            if asset is None or asset.kind != AssetKind.AUDIO:
                missing.add(clip.asset_id)
                continue
            if project_path is not None:
                path = resolve_asset_path(asset.path, project_path)
            else:
                stored = Path(asset.path)
                artwork = Path(project.artwork.path)
                path = (
                    stored
                    if stored.is_absolute()
                    else artwork.resolve(strict=False).parent / stored
                ).resolve(strict=False)
            if not path.is_file():
                missing.add(asset.asset_id)
                continue
            source_frame = clip.source_in_frame + frame - clip.start_frame
            settings = AudioClipSettings.from_clip(clip)
            targets.append(
                AudioPlaybackTarget(
                    track.track_id,
                    clip.clip_id,
                    asset.asset_id,
                    path,
                    source_frame,
                    source_frame * 1000 // clock.fps,
                    settings.gain_db,
                )
            )
    return AudioMonitorFrame(
        frame,
        tuple(targets),
        tuple(sorted(missing)),
    )

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from math import ceil
import math
from pathlib import Path
from uuid import uuid4

from .assets import resolve_asset_path
from .clock import StudioClock
from .semantic import FrozenJsonObject
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
AUDIO_PROJECT_EXTENSION = "audio"
AUDIO_MIX_VERSION = 1


class AudioFadeCurve(StrEnum):
    LINEAR = "linear"
    EQUAL_POWER = "equal_power"


@dataclass(frozen=True, slots=True)
class AudioClipSettings:
    """Serialized audio intent shared by monitoring, waveform and final mixing."""

    gain_db: float = 0.0
    fade_in_frames: int = 0
    fade_out_frames: int = 0
    fade_in_curve: AudioFadeCurve = AudioFadeCurve.EQUAL_POWER
    fade_out_curve: AudioFadeCurve = AudioFadeCurve.EQUAL_POWER

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
        if not isinstance(self.fade_in_curve, AudioFadeCurve):
            raise TypeError("audio.fade_in_curve doit être une AudioFadeCurve")
        if not isinstance(self.fade_out_curve, AudioFadeCurve):
            raise TypeError("audio.fade_out_curve doit être une AudioFadeCurve")
        return self

    def clamped(self, duration_frames: int) -> AudioClipSettings:
        duration = max(1, int(duration_frames))
        if self.fade_in_frames + self.fade_out_frames <= duration:
            return self.validate(duration_frames=duration)
        total = self.fade_in_frames + self.fade_out_frames
        fade_in = int(round(self.fade_in_frames * duration / total)) if total else 0
        fade_in = min(duration, max(0, fade_in))
        return replace(
            self,
            fade_in_frames=fade_in,
            fade_out_frames=duration - fade_in,
        ).validate(duration_frames=duration)

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "schema_version": AUDIO_SETTINGS_VERSION,
            "gain_db": float(self.gain_db),
            "fade_in_frames": self.fade_in_frames,
            "fade_out_frames": self.fade_out_frames,
            "fade_in_curve": self.fade_in_curve.value,
            "fade_out_curve": self.fade_out_curve.value,
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
            fade_in_curve=AudioFadeCurve(
                values.get("fade_in_curve", AudioFadeCurve.EQUAL_POWER.value)
            ),
            fade_out_curve=AudioFadeCurve(
                values.get("fade_out_curve", AudioFadeCurve.EQUAL_POWER.value)
            ),
        ).validate(duration_frames=clip.duration_frames)


@dataclass(frozen=True, slots=True)
class AudioTrackSettings:
    track_id: str
    gain_db: float = 0.0

    def validate(self) -> AudioTrackSettings:
        if not isinstance(self.track_id, str) or not self.track_id.strip():
            raise ValueError("audio.track_id doit être renseigné")
        if isinstance(self.gain_db, bool) or not isinstance(self.gain_db, int | float):
            raise TypeError("audio.track.gain_db doit être un nombre")
        if not -60.0 <= float(self.gain_db) <= 12.0:
            raise ValueError("audio.track.gain_db doit être compris entre -60 et +12 dB")
        return self


@dataclass(frozen=True, slots=True)
class AudioMixSettings:
    """Forward-compatible project mix contract stored in the `audio` extension."""

    tracks: tuple[AudioTrackSettings, ...] = ()
    limiter_ceiling_db: float = -1.0

    def validate(self) -> AudioMixSettings:
        if (
            isinstance(self.limiter_ceiling_db, bool)
            or not isinstance(self.limiter_ceiling_db, int | float)
            or not -12.0 <= float(self.limiter_ceiling_db) <= 0.0
        ):
            raise ValueError("audio.limiter_ceiling_db doit être compris entre -12 et 0 dB")
        identifiers: set[str] = set()
        for track in self.tracks:
            track.validate()
            if track.track_id in identifiers:
                raise ValueError(f"Réglages audio de piste dupliqués : {track.track_id}")
            identifiers.add(track.track_id)
        return self

    def track(self, track_id: str) -> AudioTrackSettings:
        return next(
            (item for item in self.tracks if item.track_id == track_id),
            AudioTrackSettings(track_id),
        )

    def with_track_gain(self, track_id: str, gain_db: float) -> AudioMixSettings:
        updated = AudioTrackSettings(track_id, float(gain_db)).validate()
        tracks = [item for item in self.tracks if item.track_id != track_id]
        if updated.gain_db != 0.0:
            tracks.append(updated)
        return replace(
            self,
            tracks=tuple(sorted(tracks, key=lambda item: item.track_id)),
        ).validate()

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": AUDIO_MIX_VERSION,
            "limiter_ceiling_db": float(self.limiter_ceiling_db),
            "tracks": {
                item.track_id: {"gain_db": float(item.gain_db)}
                for item in self.tracks
            },
        }

    @classmethod
    def from_project(cls, project: StudioProject) -> AudioMixSettings:
        payload = project.extensions.to_dict().get(AUDIO_PROJECT_EXTENSION, {})
        if not isinstance(payload, Mapping):
            raise TypeError("L’extension audio du projet doit être un objet")
        version = payload.get("schema_version", AUDIO_MIX_VERSION)
        if version != AUDIO_MIX_VERSION:
            raise ValueError(f"Version de mix audio inconnue : {version}")
        raw_tracks = payload.get("tracks", {})
        if not isinstance(raw_tracks, Mapping):
            raise TypeError("audio.tracks doit être un objet indexé par piste")
        tracks: list[AudioTrackSettings] = []
        for track_id, values in raw_tracks.items():
            if not isinstance(track_id, str) or not isinstance(values, Mapping):
                raise TypeError("Chaque réglage de piste audio doit être un objet")
            tracks.append(
                AudioTrackSettings(
                    track_id,
                    float(values.get("gain_db", 0.0)),
                ).validate()
            )
        return cls(
            tuple(sorted(tracks, key=lambda item: item.track_id)),
            float(payload.get("limiter_ceiling_db", -1.0)),
        ).validate()


def set_audio_mix_settings(
    project: StudioProject,
    settings: AudioMixSettings,
) -> StudioProject:
    values = project.extensions.to_dict()
    values[AUDIO_PROJECT_EXTENSION] = settings.validate().to_dict()
    return replace(
        project,
        extensions=FrozenJsonObject(values, where="project.extensions"),
    ).validate()


def set_audio_track_gain(
    project: StudioProject,
    track_id: str,
    gain_db: float,
) -> StudioProject:
    track = next((item for item in project.tracks if item.track_id == track_id), None)
    if track is None:
        raise KeyError(f"Piste audio introuvable : {track_id}")
    if track.kind != TrackKind.AUDIO:
        raise ValueError("Le gain audio exige une piste audio")
    if track.locked:
        raise PermissionError("La piste audio ciblée est verrouillée")
    settings = AudioMixSettings.from_project(project).with_track_gain(track_id, gain_db)
    return set_audio_mix_settings(project, settings)


@dataclass(frozen=True, slots=True)
class AudioPlaybackTarget:
    track_id: str
    clip_id: str
    asset_id: str
    path: Path
    source_frame: int
    position_ms: int
    gain_db: float
    envelope_gain: float
    linear_gain: float
    master_gain: float


@dataclass(frozen=True, slots=True)
class AudioMonitorFrame:
    project_frame: int
    targets: tuple[AudioPlaybackTarget, ...] = ()
    missing_asset_ids: tuple[str, ...] = ()
    master_gain: float = 1.0


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


def _audio_clip_location(
    project: StudioProject,
    clip_id: str,
) -> tuple[int, int, Track, Clip]:
    for track_index, track in enumerate(project.tracks):
        for clip_index, clip in enumerate(track.clips):
            if clip.clip_id == clip_id:
                if track.kind != TrackKind.AUDIO or clip.kind != ClipKind.AUDIO:
                    raise ValueError("Les réglages audio exigent un clip audio")
                return track_index, clip_index, track, clip
    raise KeyError(f"Clip audio introuvable : {clip_id}")


def validate_audio_source_range(
    project: StudioProject,
    asset_id: str,
    source_in_frame: int,
    duration_frames: int,
) -> None:
    source_in = int(source_in_frame)
    duration = int(duration_frames)
    if source_in < 0 or duration <= 0:
        raise ValueError("La plage source audio doit être positive et non vide")
    asset = _audio_asset(project, asset_id)
    available = _asset_duration_frames(asset, StudioClock(project.settings.fps))
    if available is not None and source_in + duration > available:
        raise ValueError("La plage source dépasse la durée du média audio")


def update_audio_clip(
    project: StudioProject,
    clip_id: str,
    *,
    source_in_frame: int | None = None,
    duration_frames: int | None = None,
    settings: AudioClipSettings | None = None,
    enabled: bool | None = None,
) -> tuple[StudioProject, Clip]:
    track_index, clip_index, track, clip = _audio_clip_location(project, clip_id)
    if track.locked:
        raise PermissionError("La piste audio ciblée est verrouillée")
    source_in = clip.source_in_frame if source_in_frame is None else int(source_in_frame)
    duration = clip.duration_frames if duration_frames is None else int(duration_frames)
    if clip.start_frame + duration > project.settings.duration_frames:
        raise ValueError("Le clip audio dépasserait la durée du projet")
    if clip.asset_id is None:
        raise ValueError("Le clip audio doit référencer un asset")
    validate_audio_source_range(project, clip.asset_id, source_in, duration)
    resolved_settings = settings or AudioClipSettings.from_clip(clip)
    resolved_settings.validate(duration_frames=duration)
    updated_clip = replace(
        clip,
        source_in_frame=source_in,
        duration_frames=duration,
        parameters=resolved_settings.to_dict(),
        enabled=clip.enabled if enabled is None else bool(enabled),
    ).validate()
    clips = list(track.clips)
    clips[clip_index] = updated_clip
    clips.sort(key=lambda item: (item.start_frame, item.clip_id))
    tracks = list(project.tracks)
    tracks[track_index] = replace(track, clips=tuple(clips)).validate()
    updated = replace(project, tracks=tuple(tracks)).validate()
    return updated, updated_clip


def set_audio_clip_fades(
    project: StudioProject,
    clip_id: str,
    fade_in_frames: int,
    fade_out_frames: int,
) -> StudioProject:
    _track_index, _clip_index, _track, clip = _audio_clip_location(project, clip_id)
    settings = replace(
        AudioClipSettings.from_clip(clip),
        fade_in_frames=int(fade_in_frames),
        fade_out_frames=int(fade_out_frames),
    ).validate(duration_frames=clip.duration_frames)
    return update_audio_clip(project, clip_id, settings=settings)[0]


def db_to_linear(gain_db: float) -> float:
    return pow(10.0, float(gain_db) / 20.0)


def _curve_gain(progress: float, curve: AudioFadeCurve) -> float:
    position = min(1.0, max(0.0, float(progress)))
    if curve == AudioFadeCurve.LINEAR:
        return position
    if curve == AudioFadeCurve.EQUAL_POWER:
        return math.sin(position * math.pi / 2.0)
    raise ValueError(f"Courbe de fade audio inconnue : {curve}")


def audio_envelope_gain(
    settings: AudioClipSettings,
    local_frame: int,
    duration_frames: int,
) -> float:
    if not 0 <= local_frame < duration_frames:
        return 0.0
    gain = 1.0
    if settings.fade_in_frames:
        gain *= _curve_gain(
            local_frame / settings.fade_in_frames,
            settings.fade_in_curve,
        )
    if settings.fade_out_frames:
        gain *= _curve_gain(
            (duration_frames - local_frame) / settings.fade_out_frames,
            settings.fade_out_curve,
        )
    return min(1.0, max(0.0, gain))


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
    mix = AudioMixSettings.from_project(project)
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
            envelope_gain = audio_envelope_gain(
                settings,
                frame - clip.start_frame,
                clip.duration_frames,
            )
            combined_gain_db = settings.gain_db + mix.track(track.track_id).gain_db
            linear_gain = db_to_linear(combined_gain_db) * envelope_gain
            targets.append(
                AudioPlaybackTarget(
                    track.track_id,
                    clip.clip_id,
                    asset.asset_id,
                    path,
                    source_frame,
                    source_frame * 1000 // clock.fps,
                    combined_gain_db,
                    envelope_gain,
                    linear_gain,
                    1.0,
                )
            )
    ceiling = db_to_linear(mix.limiter_ceiling_db)
    summed_gain = sum(item.linear_gain for item in targets)
    master_gain = min(1.0, ceiling / summed_gain) if summed_gain > 0.0 else 1.0
    if master_gain < 1.0:
        targets = [
            replace(
                item,
                linear_gain=item.linear_gain * master_gain,
                master_gain=master_gain,
            )
            for item in targets
        ]
    return AudioMonitorFrame(
        frame,
        tuple(targets),
        tuple(sorted(missing)),
        master_gain,
    )

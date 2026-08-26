from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import StrEnum
import math
from pathlib import Path
from threading import RLock
from typing import Generator
from uuid import uuid4

import imageio_ffmpeg
import numpy as np

from .media import StillClipSettings, transform_still_frame
from .model import AssetKind, Clip, ClipKind, FitMode, MediaAsset, StudioProject, Track, TrackKind
from .sources import validate_frame_index


DEFAULT_VIDEO_CACHE_BYTES = 128 * 1024 * 1024
DEFAULT_VIDEO_CACHE_FRAMES = 48
MAX_SEQUENTIAL_DECODE_GAP = 90


class NativeAudioMode(StrEnum):
    IGNORE = "ignore"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class VideoInspection:
    width: int
    height: int
    native_fps: float
    duration_seconds: float
    native_frame_count: int
    codec: str

    def validate(self) -> VideoInspection:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("La vidéo doit exposer des dimensions positives")
        if not math.isfinite(self.native_fps) or self.native_fps <= 0:
            raise ValueError("Le framerate natif de la vidéo est invalide")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("La durée native de la vidéo est invalide")
        if self.native_frame_count <= 0:
            raise ValueError("La vidéo ne contient aucune frame décodable")
        return self

    def metadata(self) -> dict[str, object]:
        self.validate()
        return {
            "codec": self.codec,
            "native_fps": float(self.native_fps),
            "duration_seconds": float(self.duration_seconds),
            "native_frame_count": int(self.native_frame_count),
            "decoder": "imageio-ffmpeg-bundled",
            "native_audio_policy": NativeAudioMode.IGNORE.value,
        }


@dataclass(frozen=True, slots=True)
class VideoClipSettings:
    transform: StillClipSettings = StillClipSettings()
    native_audio_mode: NativeAudioMode = NativeAudioMode.IGNORE

    def validate(self) -> VideoClipSettings:
        if not isinstance(self.transform, StillClipSettings):
            raise TypeError("La transformation vidéo doit être un StillClipSettings")
        self.transform.validate()
        if not isinstance(self.native_audio_mode, NativeAudioMode):
            raise TypeError("La politique audio native doit être un NativeAudioMode")
        return self

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "video": {
                **self.transform.to_dict(),
                "native_audio_mode": self.native_audio_mode.value,
            }
        }

    @classmethod
    def from_mapping(cls, value: object) -> VideoClipSettings:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise TypeError("Les réglages vidéo doivent être un objet JSON")
        nested = value.get("video", value)
        if not isinstance(nested, dict):
            raise TypeError("clip.parameters.video doit être un objet JSON")
        allowed = {
            "crop_x",
            "crop_y",
            "crop_width",
            "crop_height",
            "rotation_degrees",
            "native_audio_mode",
        }
        unknown = set(nested) - allowed
        if unknown:
            raise ValueError("Réglage vidéo inconnu : " + ", ".join(sorted(unknown)))
        transform_values = {
            key: item
            for key, item in nested.items()
            if key != "native_audio_mode"
        }
        try:
            audio_mode = NativeAudioMode(
                nested.get("native_audio_mode", NativeAudioMode.IGNORE.value)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Politique audio native vidéo inconnue") from exc
        return cls(
            StillClipSettings.from_mapping(transform_values),
            audio_mode,
        ).validate()

    @classmethod
    def from_clip(cls, clip: Clip) -> VideoClipSettings:
        if clip.kind != ClipKind.VIDEO:
            raise ValueError("Les réglages vidéo exigent un clip vidéo")
        return cls.from_mapping(clip.parameters)


def inspect_video(path: str | Path, *, count_frames: bool = True) -> VideoInspection:
    """Inspect a local video using only the FFmpeg binary shipped by imageio-ffmpeg."""

    source = Path(path).resolve(strict=True)
    generator = imageio_ffmpeg.read_frames(str(source), pix_fmt="rgb24")
    try:
        metadata = next(generator)
    except Exception as exc:
        raise ValueError(f"Vidéo locale illisible : {source}") from exc
    finally:
        generator.close()
    try:
        width, height = metadata["size"]
        fps = float(metadata["fps"])
        duration = float(metadata["duration"])
        codec = str(metadata.get("codec") or "inconnu")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Métadonnées vidéo locales invalides : {source}") from exc
    if count_frames:
        try:
            frame_count, counted_duration = imageio_ffmpeg.count_frames_and_secs(source)
        except Exception as exc:
            raise ValueError(f"Comptage des frames vidéo impossible : {source}") from exc
        if counted_duration > 0:
            duration = float(counted_duration)
    else:
        frame_count = max(1, int(round(duration * fps)))
    return VideoInspection(
        int(width),
        int(height),
        fps,
        duration,
        int(frame_count),
        codec,
    ).validate()


def project_source_frame_count(
    native_frame_count: int,
    native_fps: float,
    project_fps: int,
) -> int:
    if native_frame_count <= 0 or native_fps <= 0 or project_fps <= 0:
        raise ValueError("Les horloges vidéo doivent être positives")
    return max(1, int(math.ceil(native_frame_count * project_fps / native_fps)))


def native_frame_for_project_frame(
    project_frame: int,
    project_fps: int,
    native_fps: float,
    native_frame_count: int,
) -> int:
    validate_frame_index(project_frame, project_source_frame_count(
        native_frame_count,
        native_fps,
        project_fps,
    ))
    # Hold the most recent native frame. This never displays future content early.
    native = int(math.floor(project_frame * native_fps / project_fps + 1e-12))
    return min(native_frame_count - 1, max(0, native))


class VideoFrameSource:
    """Seekable frame-exact local video source with a bounded decoded-frame LRU."""

    def __init__(
        self,
        asset: MediaAsset,
        path: str | Path,
        project_fps: int,
        settings: VideoClipSettings,
        *,
        max_cache_bytes: int = DEFAULT_VIDEO_CACHE_BYTES,
        max_cache_frames: int = DEFAULT_VIDEO_CACHE_FRAMES,
    ) -> None:
        if asset.kind != AssetKind.VIDEO:
            raise ValueError("VideoFrameSource exige un asset vidéo")
        metadata = asset.metadata or {}
        try:
            native_fps = float(metadata["native_fps"])
            native_frame_count = int(metadata["native_frame_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("L’asset vidéo ne contient pas son horloge native") from exc
        if asset.width is None or asset.height is None:
            raise ValueError("L’asset vidéo ne contient pas ses dimensions")
        self.asset_id = asset.asset_id
        self.path = Path(path).resolve(strict=True)
        self.fingerprint = asset.fingerprint
        self.diagnostic = False
        self.diagnostic_message: str | None = None
        self.width = int(asset.width)
        self.height = int(asset.height)
        self.fps = int(project_fps)
        self.native_fps = native_fps
        self.native_frame_count = native_frame_count
        self.frame_count = project_source_frame_count(
            native_frame_count,
            native_fps,
            self.fps,
        )
        self.settings = settings.validate()
        self.max_cache_bytes = max(1, int(max_cache_bytes))
        self.max_cache_frames = max(1, int(max_cache_frames))
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._cache_bytes = 0
        self._generator: Generator | None = None
        self._cursor_native_frame = 0
        self._closed = False
        self._lock = RLock()

    @property
    def cache_frame_count(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def cache_bytes(self) -> int:
        with self._lock:
            return self._cache_bytes

    @property
    def decoder_open(self) -> bool:
        with self._lock:
            return self._generator is not None

    def _close_generator(self) -> None:
        generator = self._generator
        self._generator = None
        if generator is not None:
            generator.close()

    @staticmethod
    def _seconds(value: float) -> str:
        return f"{max(0.0, value):.9f}"

    def _open_at(self, native_frame: int) -> None:
        self._close_generator()
        target_seconds = native_frame / self.native_fps
        preseek_seconds = max(0.0, target_seconds - 2.0)
        output_seek_seconds = target_seconds - preseek_seconds
        input_params = (
            ["-ss", self._seconds(preseek_seconds)]
            if preseek_seconds > 0
            else []
        )
        output_params = ["-an", "-sn", "-ss", self._seconds(output_seek_seconds)]
        generator = imageio_ffmpeg.read_frames(
            str(self.path),
            pix_fmt="rgb24",
            input_params=input_params,
            output_params=output_params,
        )
        metadata = next(generator)
        decoded_width, decoded_height = metadata["size"]
        self.width = int(decoded_width)
        self.height = int(decoded_height)
        self._generator = generator
        self._cursor_native_frame = native_frame

    def _remember(self, native_frame: int, frame: np.ndarray) -> np.ndarray:
        immutable = np.ascontiguousarray(frame, dtype=np.uint8)
        immutable.setflags(write=False)
        previous = self._cache.pop(native_frame, None)
        if previous is not None:
            self._cache_bytes -= int(previous.nbytes)
        if immutable.nbytes <= self.max_cache_bytes:
            self._cache[native_frame] = immutable
            self._cache_bytes += int(immutable.nbytes)
            while (
                len(self._cache) > self.max_cache_frames
                or self._cache_bytes > self.max_cache_bytes
            ):
                _key, removed = self._cache.popitem(last=False)
                self._cache_bytes -= int(removed.nbytes)
        return immutable

    def _decode_native(self, native_frame: int) -> np.ndarray:
        cached = self._cache.get(native_frame)
        if cached is not None:
            self._cache.move_to_end(native_frame)
            return cached
        if (
            self._generator is None
            or native_frame < self._cursor_native_frame
            or native_frame - self._cursor_native_frame > MAX_SEQUENTIAL_DECODE_GAP
        ):
            self._open_at(native_frame)
        assert self._generator is not None
        while self._cursor_native_frame <= native_frame:
            current = self._cursor_native_frame
            try:
                raw = next(self._generator)
            except StopIteration as exc:
                raise IndexError("Frame vidéo native hors de la source") from exc
            decoded = np.frombuffer(raw, dtype=np.uint8).reshape(
                self.height,
                self.width,
                3,
            )
            transformed = transform_still_frame(decoded, self.settings.transform)
            remembered = self._remember(current, transformed)
            self._cursor_native_frame += 1
        return remembered

    def frame_at(self, frame_index: int) -> np.ndarray:
        with self._lock:
            if self._closed:
                raise RuntimeError("La source vidéo locale est fermée")
            project_frame = validate_frame_index(frame_index, self.frame_count)
            native = native_frame_for_project_frame(
                project_frame,
                self.fps,
                self.native_fps,
                self.native_frame_count,
            )
            return self._decode_native(native)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_generator()
            self._cache.clear()
            self._cache_bytes = 0


def _video_asset(project: StudioProject, asset_id: str) -> MediaAsset:
    try:
        asset = next(item for item in project.assets if item.asset_id == asset_id)
    except StopIteration as exc:
        raise KeyError(f"Vidéo locale introuvable : {asset_id}") from exc
    if asset.kind != AssetKind.VIDEO:
        raise ValueError("Un clip vidéo exige un asset vidéo")
    return asset


def video_source_frame_count(project: StudioProject, asset_id: str) -> int:
    asset = _video_asset(project, asset_id)
    metadata = asset.metadata or {}
    try:
        return project_source_frame_count(
            int(metadata["native_frame_count"]),
            float(metadata["native_fps"]),
            project.settings.fps,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("L’asset vidéo ne contient pas une horloge exploitable") from exc


def validate_video_source_range(
    project: StudioProject,
    asset_id: str,
    source_in_frame: int,
    duration_frames: int,
) -> None:
    source_in = int(source_in_frame)
    duration = int(duration_frames)
    if source_in < 0 or duration <= 0:
        raise ValueError("La plage source vidéo doit être positive et non vide")
    if source_in + duration > video_source_frame_count(project, asset_id):
        raise ValueError("La plage source dépasse la durée du média vidéo")


def add_video_clip(
    project: StudioProject,
    asset_id: str,
    *,
    start_frame: int,
    source_in_frame: int = 0,
    duration_frames: int | None = None,
    track_id: str | None = None,
) -> tuple[StudioProject, Clip]:
    _video_asset(project, asset_id)
    if isinstance(start_frame, bool) or not isinstance(start_frame, int):
        raise TypeError("La frame de départ du plan vidéo doit être un entier")
    if isinstance(source_in_frame, bool) or not isinstance(source_in_frame, int):
        raise TypeError("Le point d’entrée vidéo doit être un entier de frames")
    if not 0 <= start_frame < project.settings.duration_frames or source_in_frame < 0:
        raise ValueError("Le plan vidéo commence hors de sa plage valide")
    available = video_source_frame_count(project, asset_id) - source_in_frame
    remaining = project.settings.duration_frames - start_frame
    if duration_frames is not None and (
        isinstance(duration_frames, bool) or not isinstance(duration_frames, int)
    ):
        raise TypeError("La durée du plan vidéo doit être un entier de frames")
    duration = min(
        available,
        remaining,
        duration_frames if duration_frames is not None else remaining,
    )
    if duration <= 0:
        raise ValueError("La plage vidéo sélectionnée est vide")
    tracks = list(project.tracks)
    if track_id is None:
        track_index = next(
            (
                index
                for index, track in enumerate(tracks)
                if track.kind == TrackKind.VIDEO and not track.locked
            ),
            None,
        )
    else:
        track_index = next(
            (index for index, track in enumerate(tracks) if track.track_id == track_id),
            None,
        )
        if track_index is None:
            raise KeyError(f"Piste vidéo introuvable : {track_id}")
        if tracks[track_index].kind != TrackKind.VIDEO:
            raise ValueError("Une vidéo exige une piste vidéo")
        if tracks[track_index].locked:
            raise PermissionError("La piste vidéo ciblée est verrouillée")
    if track_index is None:
        tracks.append(Track(f"video-{uuid4().hex[:12]}", TrackKind.VIDEO, "Réel"))
        track_index = len(tracks) - 1
    clip = Clip(
        f"video-clip-{uuid4().hex[:12]}",
        ClipKind.VIDEO,
        start_frame,
        duration,
        source_in_frame=source_in_frame,
        asset_id=asset_id,
        fit=FitMode.COVER,
        parameters=VideoClipSettings().to_dict(),
    ).validate()
    track = tracks[track_index]
    tracks[track_index] = replace(
        track,
        clips=tuple(sorted((*track.clips, clip), key=lambda item: (item.start_frame, item.clip_id))),
    )
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        item for item_track in updated.tracks for item in item_track.clips if item.clip_id == clip.clip_id
    )
    return updated, effective


def update_video_clip(
    project: StudioProject,
    clip_id: str,
    *,
    source_in_frame: int,
    duration_frames: int,
    fit: FitMode,
    opacity: float,
    enabled: bool,
    settings: VideoClipSettings,
) -> tuple[StudioProject, Clip]:
    location = next(
        (
            (track_index, clip_index, track, clip)
            for track_index, track in enumerate(project.tracks)
            for clip_index, clip in enumerate(track.clips)
            if clip.clip_id == clip_id
        ),
        None,
    )
    if location is None:
        raise KeyError(f"Clip vidéo introuvable : {clip_id}")
    track_index, clip_index, track, clip = location
    if track.locked:
        raise PermissionError("La piste du plan vidéo est verrouillée")
    if clip.kind != ClipKind.VIDEO or clip.asset_id is None:
        raise ValueError("Les réglages exigent un clip vidéo")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (source_in_frame, duration_frames)
    ):
        raise TypeError("La plage vidéo doit être exprimée en frames entières")
    validate_video_source_range(project, clip.asset_id, source_in_frame, duration_frames)
    if clip.start_frame + duration_frames > project.settings.duration_frames:
        raise ValueError("La durée du plan vidéo dépasse le projet")
    if not isinstance(fit, FitMode):
        raise TypeError("Le cadrage doit être un FitMode")
    if isinstance(opacity, bool) or not isinstance(opacity, int | float):
        raise TypeError("L’opacité du plan vidéo doit être numérique")
    if not math.isfinite(float(opacity)) or not 0 <= float(opacity) <= 1:
        raise ValueError("L’opacité du plan vidéo doit être comprise entre 0 et 1")
    if not isinstance(enabled, bool):
        raise TypeError("La visibilité du plan vidéo doit être un booléen")
    if not isinstance(settings, VideoClipSettings):
        raise TypeError("Les réglages vidéo doivent être des VideoClipSettings")
    settings.validate()
    updated_clip = replace(
        clip,
        source_in_frame=source_in_frame,
        duration_frames=duration_frames,
        fit=fit,
        opacity=float(opacity),
        enabled=enabled,
        parameters=settings.to_dict(),
    ).validate()
    clips = list(track.clips)
    clips[clip_index] = updated_clip
    tracks = list(project.tracks)
    tracks[track_index] = replace(track, clips=tuple(clips))
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        item for item_track in updated.tracks for item in item_track.clips if item.clip_id == clip_id
    )
    return updated, effective

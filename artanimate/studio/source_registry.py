from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock

import numpy as np
from PIL import Image, ImageOps

from .effect_2d import (
    Effect2DClipSettings,
    Effect2DSourceFactory,
    Effect2DTimedFrameSource,
    settings_for_effect_clip,
)
from .media import StillClipSettings, StillImageSource
from .model import ClipKind, MediaAsset, StudioProject
from .sources import TimedFrameSource
from .video import VideoClipSettings, VideoFrameSource


DEFAULT_ARTWORK_CACHE_BYTES = 96 * 1024 * 1024
DEFAULT_STILL_CACHE_BYTES = 128 * 1024 * 1024
DEFAULT_EFFECT_CACHE_BYTES = 128 * 1024 * 1024
DEFAULT_VIDEO_CACHE_BYTES = 128 * 1024 * 1024


class StaticArtworkSource:
    def __init__(self, frame: np.ndarray, fps: int, frame_count: int):
        array = np.ascontiguousarray(frame, dtype=np.uint8)
        if array.ndim != 3 or array.shape[2] != 3:
            raise ValueError("La source proxy de l’œuvre doit être RGB")
        self._frame = array
        self.width = int(array.shape[1])
        self.height = int(array.shape[0])
        self.fps = int(fps)
        self.frame_count = int(frame_count)

    def frame_at(self, frame_index: int) -> np.ndarray:
        if not 0 <= int(frame_index) < self.frame_count:
            raise IndexError("Frame hors de la source œuvre")
        return self._frame


class ArtworkSourceRegistry:
    """Shared, bounded artwork source registry for preview and final render."""

    def __init__(
        self,
        max_effect_sources: int = 8,
        max_media_sources: int = 8,
        max_video_sources: int = 2,
        max_artwork_cache_bytes: int = DEFAULT_ARTWORK_CACHE_BYTES,
        max_still_cache_bytes: int = DEFAULT_STILL_CACHE_BYTES,
        max_effect_cache_bytes: int = DEFAULT_EFFECT_CACHE_BYTES,
        max_video_cache_bytes: int = DEFAULT_VIDEO_CACHE_BYTES,
    ):
        if min(max_effect_sources, max_media_sources, max_video_sources) < 1:
            raise ValueError("Le registre doit conserver au moins une source par famille")
        if min(
            max_artwork_cache_bytes,
            max_still_cache_bytes,
            max_effect_cache_bytes,
            max_video_cache_bytes,
        ) < 1:
            raise ValueError("Les budgets mémoire du registre doivent être positifs")
        self.max_effect_sources = int(max_effect_sources)
        self.max_media_sources = int(max_media_sources)
        self.max_video_sources = int(max_video_sources)
        self.max_artwork_cache_bytes = int(max_artwork_cache_bytes)
        self.max_still_cache_bytes = int(max_still_cache_bytes)
        self.max_effect_cache_bytes = int(max_effect_cache_bytes)
        self.max_video_cache_bytes = int(max_video_cache_bytes)
        self._sources: OrderedDict[str, np.ndarray] = OrderedDict()
        self._effect_sources: OrderedDict[str, Effect2DTimedFrameSource] = OrderedDict()
        self._media_sources: OrderedDict[str, StillImageSource] = OrderedDict()
        self._video_sources: OrderedDict[str, VideoFrameSource] = OrderedDict()
        self._artwork_bytes = 0
        self._media_bytes = 0
        self.decode_count = 0
        self.media_decode_count = 0
        self.effect_factory = Effect2DSourceFactory()
        self._lock = RLock()

    @property
    def effect_source_count(self) -> int:
        with self._lock:
            return len(self._effect_sources)

    @property
    def media_source_count(self) -> int:
        with self._lock:
            return len(self._media_sources)

    @property
    def video_source_count(self) -> int:
        with self._lock:
            return len(self._video_sources)

    @property
    def artwork_cache_bytes(self) -> int:
        with self._lock:
            return self._artwork_bytes

    @property
    def still_cache_bytes(self) -> int:
        with self._lock:
            return self._media_bytes

    @property
    def effect_cache_bytes(self) -> int:
        with self._lock:
            return sum(
                int(source.reference_frame.nbytes) + source.source.cache_bytes
                for source in self._effect_sources.values()
            )

    @property
    def video_cache_bytes(self) -> int:
        with self._lock:
            return sum(source.cache_bytes for source in self._video_sources.values())

    @property
    def cache_bytes(self) -> int:
        return (
            self.artwork_cache_bytes
            + self.still_cache_bytes
            + self.effect_cache_bytes
            + self.video_cache_bytes
        )

    @property
    def cache_budget_bytes(self) -> int:
        return (
            self.max_artwork_cache_bytes
            + self.max_still_cache_bytes
            + self.max_effect_cache_bytes
            + self.max_video_cache_bytes
        )

    @staticmethod
    def _key(path: Path, fingerprint: str | None) -> str:
        resolved = path.resolve(strict=False)
        stat = resolved.stat()
        identity = fingerprint or f"{stat.st_size}:{stat.st_mtime_ns}"
        return f"{resolved}|{identity}"

    def artwork(self, path: str | Path, fingerprint: str | None) -> np.ndarray:
        source = Path(path)
        key = self._key(source, fingerprint)
        with self._lock:
            cached = self._sources.get(key)
            if cached is not None:
                self._sources.move_to_end(key)
                return cached
        with Image.open(source) as image:
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"), dtype=np.uint8)
        rgb = np.ascontiguousarray(rgb)
        rgb.setflags(write=False)
        with self._lock:
            existing = self._sources.get(key)
            self.decode_count += 1
            if existing is not None:
                self._sources.move_to_end(key)
                return existing
            size = int(rgb.nbytes)
            if size <= self.max_artwork_cache_bytes:
                self._sources[key] = rgb
                self._artwork_bytes += size
                while self._artwork_bytes > self.max_artwork_cache_bytes:
                    _old_key, removed = self._sources.popitem(last=False)
                    self._artwork_bytes -= int(removed.nbytes)
            return rgb

    def effect_source(
        self,
        path: str | Path,
        fingerprint: str | None,
        settings: Effect2DClipSettings,
    ) -> Effect2DTimedFrameSource:
        key = f"{self._key(Path(path), fingerprint)}|{settings.config_json}"
        with self._lock:
            cached = self._effect_sources.get(key)
            if cached is not None:
                self._effect_sources.move_to_end(key)
                return cached
            source = self.effect_factory.source(
                path,
                settings,
                fingerprint=fingerprint,
                max_cache_bytes=max(
                    1,
                    self.max_effect_cache_bytes // (2 * self.max_effect_sources),
                ),
            )
            self._effect_sources[key] = source
            reference_budget = self.max_effect_cache_bytes // 2
            while self._effect_sources and (
                len(self._effect_sources) > self.max_effect_sources
                or sum(
                    int(item.reference_frame.nbytes)
                    for item in self._effect_sources.values()
                ) > reference_budget
            ):
                _old_key, removed = self._effect_sources.popitem(last=False)
                removed.source.clear_frame_cache()
            return source

    def still_image(
        self,
        asset: MediaAsset,
        path: str | Path,
        settings: StillClipSettings,
        fps: int,
    ) -> StillImageSource:
        settings.validate()
        key = (
            f"{self._key(Path(path), asset.fingerprint)}|fps={int(fps)}|"
            f"{settings.crop_x}:{settings.crop_y}:{settings.crop_width}:"
            f"{settings.crop_height}:{settings.rotation_degrees}"
        )
        with self._lock:
            cached = self._media_sources.get(key)
            if cached is not None:
                self._media_sources.move_to_end(key)
                return cached
        source = StillImageSource.open(asset, path, fps, settings)
        with self._lock:
            existing = self._media_sources.get(key)
            self.media_decode_count += 1
            if existing is not None:
                self._media_sources.move_to_end(key)
                return existing
            self._media_sources[key] = source
            source_bytes = int(source.frame_at(0).nbytes)
            if source_bytes > self.max_still_cache_bytes:
                self._media_sources.pop(key, None)
                return source
            self._media_bytes += source_bytes
            while (
                len(self._media_sources) > self.max_media_sources
                or self._media_bytes > self.max_still_cache_bytes
            ):
                _old_key, removed = self._media_sources.popitem(last=False)
                self._media_bytes -= int(removed.frame_at(0).nbytes)
        return source

    def video(
        self,
        asset: MediaAsset,
        path: str | Path,
        settings: VideoClipSettings,
        fps: int,
    ) -> VideoFrameSource:
        settings.validate()
        transform = settings.transform
        key = (
            f"{self._key(Path(path), asset.fingerprint)}|fps={int(fps)}|video|"
            f"{transform.crop_x}:{transform.crop_y}:{transform.crop_width}:"
            f"{transform.crop_height}:{transform.rotation_degrees}:"
            f"{settings.native_audio_mode.value}"
        )
        with self._lock:
            cached = self._video_sources.get(key)
            if cached is not None:
                self._video_sources.move_to_end(key)
                return cached
        source = VideoFrameSource(
            asset,
            path,
            fps,
            settings,
            max_cache_bytes=max(
                1,
                self.max_video_cache_bytes // self.max_video_sources,
            ),
        )
        evicted: list[VideoFrameSource] = []
        duplicate: VideoFrameSource | None = None
        with self._lock:
            existing = self._video_sources.get(key)
            if existing is not None:
                self._video_sources.move_to_end(key)
                duplicate = source
                source = existing
            else:
                self._video_sources[key] = source
            while len(self._video_sources) > self.max_video_sources:
                _evicted_key, removed = self._video_sources.popitem(last=False)
                evicted.append(removed)
        if duplicate is not None:
            duplicate.close()
        for removed in evicted:
            removed.close()
        return source

    def sources_for(
        self,
        project: StudioProject,
        artwork_path: str | Path,
    ) -> dict[str, TimedFrameSource]:
        project.validate()
        artwork = self.artwork(artwork_path, project.artwork.fingerprint)
        static = StaticArtworkSource(
            artwork,
            project.settings.fps,
            project.settings.duration_frames,
        )
        sources: dict[str, TimedFrameSource] = {}
        for track in project.tracks:
            for clip in track.clips:
                if clip.kind in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
                    sources[clip.clip_id] = static
                elif clip.kind == ClipKind.EFFECT_2D:
                    settings = settings_for_effect_clip(clip)
                    source = self.effect_source(
                        artwork_path,
                        project.artwork.fingerprint,
                        settings,
                    )
                    if clip.source_in_frame + clip.duration_frames > source.frame_count:
                        raise ValueError(
                            f"Le clip {clip.clip_id} dépasse sa source d’effet 2D figée"
                        )
                    sources[clip.clip_id] = source
        return sources

    def clear(self) -> None:
        videos: tuple[VideoFrameSource, ...]
        effects: tuple[Effect2DTimedFrameSource, ...]
        with self._lock:
            self._sources.clear()
            self._artwork_bytes = 0
            effects = tuple(self._effect_sources.values())
            self._effect_sources.clear()
            self._media_sources.clear()
            self._media_bytes = 0
            videos = tuple(self._video_sources.values())
            self._video_sources.clear()
        for source in effects:
            source.source.clear_frame_cache()
        for source in videos:
            source.close()
        self.effect_factory.clear()

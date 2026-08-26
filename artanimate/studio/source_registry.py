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

    def __init__(self, max_effect_sources: int = 8, max_media_sources: int = 8):
        if max_effect_sources < 1 or max_media_sources < 1:
            raise ValueError("Le registre doit conserver au moins une source par famille")
        self.max_effect_sources = int(max_effect_sources)
        self.max_media_sources = int(max_media_sources)
        self._sources: dict[str, np.ndarray] = {}
        self._effect_sources: OrderedDict[str, Effect2DTimedFrameSource] = OrderedDict()
        self._media_sources: OrderedDict[str, StillImageSource] = OrderedDict()
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
                return cached
        with Image.open(source) as image:
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"), dtype=np.uint8)
        rgb = np.ascontiguousarray(rgb)
        rgb.setflags(write=False)
        with self._lock:
            existing = self._sources.setdefault(key, rgb)
            if existing is rgb:
                self.decode_count += 1
            return existing

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
            )
            self._effect_sources[key] = source
            while len(self._effect_sources) > self.max_effect_sources:
                self._effect_sources.popitem(last=False)
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
            self._media_sources[key] = source
            self.media_decode_count += 1
            while len(self._media_sources) > self.max_media_sources:
                self._media_sources.popitem(last=False)
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
        with self._lock:
            self._sources.clear()
            self._effect_sources.clear()
            self._media_sources.clear()
        self.effect_factory.clear()

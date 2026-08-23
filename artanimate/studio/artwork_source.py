from __future__ import annotations

from collections import OrderedDict
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock

import numpy as np

from ..core.analysis import ArtworkAnalysis, analyze_artwork
from ..core.config import RenderConfig
from ..core.renderer import ArtworkRenderer
from .sources import TimedFrameSource, validate_frame_index


DEFAULT_ARTWORK_FRAME_CACHE_BYTES = 64 * 1024 * 1024
_PRESENTATIONS = {"2d", "texture"}
_ANALYSIS_FIELDS = (
    "width",
    "colors",
    "background_tolerance",
    "outline_luma",
    "outline_chroma",
    "shape_completion",
    "seed",
)


def _snapshot_config(config: RenderConfig) -> RenderConfig:
    return RenderConfig.from_dict(config.to_dict())


class ArtworkTimedFrameSource:
    """Random-access, cached view of an existing ``ArtworkRenderer``."""

    def __init__(
        self,
        renderer: ArtworkRenderer,
        *,
        presentation: str = "2d",
        max_cache_bytes: int = DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
    ):
        if presentation not in _PRESENTATIONS:
            raise ValueError("La présentation doit être '2d' ou 'texture'")
        if max_cache_bytes <= 0:
            raise ValueError("La limite du cache de frames 2D doit être positive")
        self.renderer = renderer
        self.presentation = presentation
        self.width = renderer.width
        self.height = renderer.height
        self.fps = renderer.config.fps
        self.frame_count = renderer.frame_count
        self.max_cache_bytes = int(max_cache_bytes)
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._cache_bytes = 0
        self._lock = RLock()

    @property
    def cache_entry_count(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def cache_bytes(self) -> int:
        with self._lock:
            return self._cache_bytes

    def frame_at(self, frame_index: int) -> np.ndarray:
        index = validate_frame_index(frame_index, self.frame_count)
        with self._lock:
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached
            frame = np.ascontiguousarray(
                self.renderer.indexed_frame_at(
                    index,
                    presentation=self.presentation,
                ),
                dtype=np.uint8,
            ).copy()
            frame.setflags(write=False)
            size = int(frame.nbytes)
            if size <= self.max_cache_bytes:
                self._cache[index] = frame
                self._cache_bytes += size
                while self._cache_bytes > self.max_cache_bytes and self._cache:
                    _old_index, old = self._cache.popitem(last=False)
                    self._cache_bytes -= int(old.nbytes)
            return frame

    def clear_frame_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0


class ArtworkTimedSourceFactory:
    """Caches expensive artwork analysis while snapshotting every render config."""

    def __init__(self, max_analysis_entries: int = 4):
        if max_analysis_entries < 1:
            raise ValueError("Le cache d’analyse doit conserver au moins une œuvre")
        self.max_analysis_entries = int(max_analysis_entries)
        self._analyses: OrderedDict[str, ArtworkAnalysis] = OrderedDict()
        self._lock = RLock()
        self.analysis_count = 0

    @property
    def analysis_entry_count(self) -> int:
        with self._lock:
            return len(self._analyses)

    @staticmethod
    def _analysis_key(
        path: Path,
        config: RenderConfig,
        fingerprint: str | None,
    ) -> str:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        payload = {
            "path": str(resolved),
            "source": [fingerprint, stat.st_size, stat.st_mtime_ns],
            "analysis": {
                field: getattr(config, field)
                for field in _ANALYSIS_FIELDS
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def source(
        self,
        path: str | Path,
        config: RenderConfig,
        *,
        fingerprint: str | None = None,
        presentation: str = "2d",
        max_cache_bytes: int = DEFAULT_ARTWORK_FRAME_CACHE_BYTES,
    ) -> ArtworkTimedFrameSource:
        source_path = Path(path)
        snapshot = _snapshot_config(config)
        key = self._analysis_key(source_path, snapshot, fingerprint)
        with self._lock:
            analysis = self._analyses.get(key)
            if analysis is None:
                analysis = analyze_artwork(source_path, snapshot)
                self._analyses[key] = analysis
                self.analysis_count += 1
                while len(self._analyses) > self.max_analysis_entries:
                    self._analyses.popitem(last=False)
            else:
                self._analyses.move_to_end(key)
        renderer = ArtworkRenderer(analysis, snapshot)
        timed = ArtworkTimedFrameSource(
            renderer,
            presentation=presentation,
            max_cache_bytes=max_cache_bytes,
        )
        if not isinstance(timed, TimedFrameSource):
            raise TypeError("La source œuvre ne respecte pas TimedFrameSource")
        return timed

    def clear(self) -> None:
        with self._lock:
            self._analyses.clear()

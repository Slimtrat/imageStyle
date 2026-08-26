from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock

import numpy as np

from .model import StudioProject
from .persistence import project_digest
from .render_session import StudioRenderSession
from .source_registry import ArtworkSourceRegistry, StaticArtworkSource


DEFAULT_PROXY_WIDTH = 360
DEFAULT_CACHE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PreviewFrameKey:
    project_id: str
    composite_digest: str
    frame: int
    width: int
    height: int


class StudioProxyCache:
    """Thread-safe byte-bounded LRU of immutable composited proxy frames."""

    def __init__(self, max_bytes: int = DEFAULT_CACHE_BYTES):
        if max_bytes <= 0:
            raise ValueError("La limite mémoire du cache proxy doit être positive")
        self.max_bytes = int(max_bytes)
        self._bytes = 0
        self._frames: OrderedDict[PreviewFrameKey, np.ndarray] = OrderedDict()
        self._lock = RLock()

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._bytes

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._frames)

    def get(self, key: PreviewFrameKey) -> np.ndarray | None:
        with self._lock:
            frame = self._frames.get(key)
            if frame is None:
                return None
            self._frames.move_to_end(key)
            return frame

    def put(self, key: PreviewFrameKey, frame: np.ndarray) -> None:
        array = np.ascontiguousarray(frame, dtype=np.uint8).copy()
        array.setflags(write=False)
        size = int(array.nbytes)
        with self._lock:
            previous = self._frames.pop(key, None)
            if previous is not None:
                self._bytes -= int(previous.nbytes)
            if size > self.max_bytes:
                return
            self._frames[key] = array
            self._bytes += size
            while self._bytes > self.max_bytes and self._frames:
                _old_key, old = self._frames.popitem(last=False)
                self._bytes -= int(old.nbytes)

    def invalidate_project(self, project_id: str) -> int:
        with self._lock:
            keys = [key for key in self._frames if key.project_id == project_id]
            for key in keys:
                self._bytes -= int(self._frames.pop(key).nbytes)
            return len(keys)

    def invalidate_frames(self, project_id: str, frames: set[int]) -> int:
        with self._lock:
            keys = [
                key
                for key in self._frames
                if key.project_id == project_id and key.frame in frames
            ]
            for key in keys:
                self._bytes -= int(self._frames.pop(key).nbytes)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._bytes = 0


def proxy_size(project: StudioProject, requested_width: int) -> tuple[int, int]:
    width_unit = project.settings.width // np.gcd(
        project.settings.width,
        project.settings.height,
    )
    height_unit = project.settings.height // np.gcd(
        project.settings.width,
        project.settings.height,
    )
    units = max(1, int(round(int(requested_width) / width_unit)))
    return int(width_unit * units), int(height_unit * units)


def preview_frame_key(
    project: StudioProject,
    frame: int,
    width: int,
    height: int,
) -> PreviewFrameKey:
    digest = sha256(project_digest(project).encode("ascii")).hexdigest()
    return PreviewFrameKey(
        project.project_id,
        digest,
        int(frame),
        int(width),
        int(height),
    )


def render_studio_preview_frame(
    project: StudioProject,
    artwork_path: str | Path,
    frame: int,
    *,
    requested_width: int = DEFAULT_PROXY_WIDTH,
    cache: StudioProxyCache | None = None,
    source_registry: ArtworkSourceRegistry | None = None,
    cancelled: Event | None = None,
) -> tuple[np.ndarray | None, bool]:
    project.validate()
    width, height = proxy_size(project, requested_width)
    key = preview_frame_key(project, frame, width, height)
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached, True
    if cancelled is not None and cancelled.is_set():
        return None, False
    registry = source_registry or ArtworkSourceRegistry()
    with StudioRenderSession(
        project,
        artwork_path,
        output_width=width,
        output_height=height,
        source_registry=registry,
    ) as session:
        rendered = session.frame_at(int(frame))
    if cancelled is not None and cancelled.is_set():
        return None, False
    if cache is not None:
        cache.put(key, rendered)
        cached = cache.get(key)
        if cached is not None:
            rendered = cached
    return rendered, False

from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image

from artanimate.studio.model import CameraAnimation, CameraKeyframe, CameraPose, StudioProject
from artanimate.studio.preview import (
    ArtworkSourceRegistry,
    PreviewFrameKey,
    StudioProxyCache,
    proxy_size,
    render_studio_preview_frame,
)


def test_proxy_cache_has_explicit_lru_memory_limit() -> None:
    cache = StudioProxyCache(max_bytes=200)
    frame = np.zeros((5, 5, 3), dtype=np.uint8)
    keys = [PreviewFrameKey("p", str(index), index, 5, 5) for index in range(4)]
    for key in keys:
        cache.put(key, frame)

    assert cache.current_bytes <= 200
    assert cache.entry_count == 2
    assert cache.get(keys[0]) is None
    assert cache.get(keys[-1]) is not None
    assert cache.invalidate_frames("p", {3}) == 1


def test_camera_change_invalidates_composite_not_decoded_artwork(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (320, 180), "red").save(artwork)
    project = StudioProject.new(artwork)
    cache = StudioProxyCache(max_bytes=8 * 1024 * 1024)
    registry = ArtworkSourceRegistry()

    first, first_cached = render_studio_preview_frame(
        project,
        artwork,
        10,
        cache=cache,
        source_registry=registry,
    )
    second, second_cached = render_studio_preview_frame(
        project,
        artwork,
        10,
        cache=cache,
        source_registry=registry,
    )
    clip = project.tracks[0].clips[0]
    changed_clip = replace(
        clip,
        camera=CameraAnimation((CameraKeyframe(0, CameraPose(zoom=2.0)),)),
    )
    changed_track = replace(project.tracks[0], clips=(changed_clip,))
    changed = replace(
        project,
        tracks=(changed_track, *project.tracks[1:]),
    ).validate()
    third, third_cached = render_studio_preview_frame(
        changed,
        artwork,
        10,
        cache=cache,
        source_registry=registry,
    )

    assert first is not None and third is not None
    assert not first_cached and second_cached and not third_cached
    assert np.array_equal(first, second)
    assert not np.array_equal(first, third)
    assert registry.decode_count == 1


def test_preview_uses_project_ratio_and_honors_pre_cancel(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 100), "blue").save(artwork)
    project = StudioProject.new(artwork)
    assert proxy_size(project, 355) == (351, 624)
    cancelled = Event()
    cancelled.set()

    frame, cached = render_studio_preview_frame(
        project,
        artwork,
        0,
        cancelled=cancelled,
    )

    assert frame is None
    assert not cached


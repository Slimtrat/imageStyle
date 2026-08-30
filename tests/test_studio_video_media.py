from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.core.video import VideoFrameEncoder
from artanimate.studio.assets import import_media_asset, register_media_asset
from artanimate.studio.model import AssetKind, ClipKind, StudioProject
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.source_registry import ArtworkSourceRegistry
from artanimate.studio.timeline import trim_clip
from artanimate.studio.video import (
    VideoClipSettings,
    VideoFrameSource,
    add_video_clip,
    native_frame_for_project_frame,
    project_source_frame_count,
)


def encode_test_video(path: Path, fps: int = 24, frame_count: int = 12) -> tuple[np.ndarray, ...]:
    frames = tuple(
        np.full(
            (48, 64, 3),
            ((index * 17) % 256, 20, (220 - index * 13) % 256),
            dtype=np.uint8,
        )
        for index in range(frame_count)
    )
    encoder = VideoFrameEncoder(
        path,
        64,
        48,
        fps,
        quality="fast",
        total_frames=frame_count,
    )
    try:
        for frame in frames:
            encoder.write(frame)
        encoder.finish()
    except Exception:
        encoder.abort()
        raise
    return frames


def make_video_project(tmp_path: Path, *, project_fps: int = 30):
    artwork = tmp_path / "artwork.png"
    video = tmp_path / "capture.mp4"
    Image.new("RGB", (90, 160), (10, 20, 30)).save(artwork)
    native_frames = encode_test_video(video)
    project = StudioProject.new(artwork, fps=project_fps)
    project, asset, _created = register_media_asset(
        project,
        video,
        tmp_path / "reel.artanimate",
    )
    project, clip = add_video_clip(project, asset.asset_id, start_frame=0)
    return project, artwork, video, asset, clip, native_frames


def assert_color_close(actual: np.ndarray, expected: np.ndarray, tolerance: float = 12.0) -> None:
    assert np.abs(actual.astype(np.float32).mean(axis=(0, 1)) - expected[0, 0]).max() < tolerance


def test_video_import_uses_bundled_ffmpeg_and_records_exact_clock(tmp_path: Path) -> None:
    source = tmp_path / "capture.mp4"
    encode_test_video(source, fps=24, frame_count=12)

    asset = import_media_asset(
        source,
        AssetKind.VIDEO,
        tmp_path / "reel.artanimate",
        asset_id="capture",
    )

    assert (asset.width, asset.height) == (64, 48)
    assert asset.metadata["native_fps"] == pytest.approx(24.0)
    assert asset.metadata["native_frame_count"] == 12
    assert asset.metadata["decoder"] == "imageio-ffmpeg-bundled"
    assert asset.metadata["native_audio_policy"] == "ignore"


def test_project_to_native_fps_sampling_rule_is_explicit() -> None:
    assert project_source_frame_count(4, 24.0, 30) == 5
    assert [
        native_frame_for_project_frame(index, 30, 24.0, 4)
        for index in range(5)
    ] == [0, 0, 1, 2, 3]
    assert [
        native_frame_for_project_frame(index, 30, 60.0, 8)
        for index in range(4)
    ] == [0, 2, 4, 6]


def test_video_source_is_frame_exact_seekable_cached_and_closable(tmp_path: Path) -> None:
    project, _artwork, video, asset, _clip, native_frames = make_video_project(tmp_path)
    source = VideoFrameSource(asset, video, 30, VideoClipSettings(), max_cache_frames=2)

    first = source.frame_at(0)
    same = source.frame_at(0)
    later = source.frame_at(3)
    backwards = source.frame_at(1)

    assert first is same
    assert_color_close(first, native_frames[0])
    assert_color_close(later, native_frames[2])
    assert_color_close(backwards, native_frames[0])
    assert source.cache_frame_count <= 2
    assert source.decoder_open
    source.close()
    assert not source.decoder_open
    assert source.cache_frame_count == 0
    with pytest.raises(RuntimeError, match="fermée"):
        source.frame_at(0)

    moved = tmp_path / "capture-moved.mp4"
    video.replace(moved)
    assert moved.is_file()


def test_repeated_random_seeks_stay_inside_byte_and_frame_budgets(
    tmp_path: Path,
) -> None:
    project, _artwork, video, asset, _clip, _frames = make_video_project(tmp_path)
    source = VideoFrameSource(
        asset,
        video,
        project.settings.fps,
        VideoClipSettings(),
        max_cache_bytes=2 * 48 * 64 * 3,
        max_cache_frames=2,
    )
    try:
        sequence = tuple(
            (index * 7) % source.frame_count
            for index in range(300)
        )
        for frame in sequence:
            decoded = source.frame_at(frame)
            assert decoded.shape == (48, 64, 3)
            assert source.cache_frame_count <= 2
            assert source.cache_bytes <= source.max_cache_bytes
    finally:
        source.close()
    assert source.cache_bytes == 0


def test_video_source_long_seek_stays_on_requested_native_frame(tmp_path: Path) -> None:
    video = tmp_path / "long.mp4"
    native_frames = encode_test_video(video, fps=24, frame_count=120)
    asset = import_media_asset(
        video,
        AssetKind.VIDEO,
        tmp_path / "reel.artanimate",
        asset_id="long",
    )
    source = VideoFrameSource(asset, video, 30, VideoClipSettings())
    try:
        target_project_frame = 140
        target_native_frame = native_frame_for_project_frame(target_project_frame, 30, 24.0, 120)
        assert target_native_frame == 112
        assert_color_close(source.frame_at(target_project_frame), native_frames[112], tolerance=18.0)
    finally:
        source.close()


def test_video_trim_updates_source_range_exactly(tmp_path: Path) -> None:
    project, _artwork, _video, _asset, clip, _frames = make_video_project(tmp_path)
    assert clip.kind == ClipKind.VIDEO
    assert clip.duration_frames == 15

    trimmed = trim_clip(project, clip.clip_id, 3, 11)
    effective = next(
        item
        for track in trimmed.tracks
        for item in track.clips
        if item.clip_id == clip.clip_id
    )

    assert effective.start_frame == 3
    assert effective.duration_frames == 8
    assert effective.source_in_frame == 3
    with pytest.raises(ValueError, match="dépasse"):
        trim_clip(trimmed, clip.clip_id, 3, 20)


def test_video_composes_same_project_frame_deterministically(tmp_path: Path) -> None:
    project, artwork, _video, _asset, _clip, native_frames = make_video_project(tmp_path)

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
        resource_base=tmp_path,
    ) as session:
        first = session.frame_at(3)
        repeated = session.frame_at(3)

    assert np.array_equal(first, repeated)
    assert_color_close(first, native_frames[2])


def test_missing_video_uses_visible_diagnostic_instead_of_crashing(tmp_path: Path) -> None:
    project, artwork, video, _asset, _clip, _frames = make_video_project(tmp_path)
    video.unlink()

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
        resource_base=tmp_path,
    ) as session:
        frame = session.frame_at(2)

    assert frame.shape == (160, 90, 3)
    assert np.any(frame[..., 0] > 220)


def test_video_registry_evicts_and_closes_decoders(tmp_path: Path) -> None:
    first_path = tmp_path / "first.mp4"
    second_path = tmp_path / "second.mp4"
    encode_test_video(first_path, frame_count=3)
    encode_test_video(second_path, frame_count=3)
    project_path = tmp_path / "reel.artanimate"
    first_asset = import_media_asset(first_path, AssetKind.VIDEO, project_path, asset_id="first")
    second_asset = import_media_asset(second_path, AssetKind.VIDEO, project_path, asset_id="second")
    registry = ArtworkSourceRegistry(max_video_sources=1)
    first = registry.video(first_asset, first_path, VideoClipSettings(), 30)
    first.frame_at(0)

    registry.video(second_asset, second_path, VideoClipSettings(), 30)

    assert registry.video_source_count == 1
    assert not first.decoder_open
    with pytest.raises(RuntimeError, match="fermée"):
        first.frame_at(0)
    registry.clear()

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.core.video import RenderCancelled, VideoFrameEncoder
from artanimate.studio.export import export_studio_video, frame_digest
from artanimate.studio.model import (
    AssetKind,
    Clip,
    ClipKind,
    Easing,
    ExportSettings,
    MediaAsset,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
)
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.transitions import add_dissolve
from artanimate.studio.video import VideoClipSettings, VideoFrameSource, inspect_video


def _project(tmp_path: Path, *, fps: int = 30, frames: int = 6) -> tuple[StudioProject, Path]:
    artwork = tmp_path / f"artwork-{fps}.png"
    Image.new("RGB", (64, 64), (170, 70, 25)).save(artwork)
    base = StudioProject.new(artwork, fps=fps, duration_seconds=1)
    clip = replace(base.tracks[0].clips[0], duration_frames=frames)
    track = replace(base.tracks[0], clips=(clip,))
    project = replace(
        base,
        artwork=replace(base.artwork, width=64, height=64),
        settings=ProjectSettings(
            width=64,
            height=64,
            fps=fps,
            duration_frames=frames,
        ),
        tracks=(track, *base.tracks[1:]),
        export=ExportSettings(container="mp4", crf=18, quality="fast"),
    ).validate()
    return project, artwork


@pytest.mark.parametrize("fps", (30, 60))
def test_export_writes_exact_frame_count_and_preview_endpoints(
    tmp_path: Path,
    fps: int,
) -> None:
    project, artwork = _project(tmp_path, fps=fps, frames=8)
    destination = tmp_path / f"reel-{fps}.mp4"
    progress: list[tuple[int, int]] = []
    with StudioRenderSession(project, artwork) as preview:
        expected_first = frame_digest(preview.frame_at(0))
        expected_last = frame_digest(preview.frame_at(7))

    result = export_studio_video(
        project,
        artwork,
        destination,
        progress=lambda done, total: progress.append((done, total)),
    )
    inspection = inspect_video(destination)

    assert result.path == destination.resolve()
    assert result.frame_count == 8
    assert result.fps == fps
    assert result.first_frame_digest == expected_first
    assert result.last_frame_digest == expected_last
    assert inspection.native_frame_count == 8
    assert inspection.native_fps == pytest.approx(float(fps), rel=0.01)
    assert progress[0] == (0, 8)
    assert progress[-1] == (8, 8)


def test_cancel_keeps_previous_export_and_cleans_partial_file(tmp_path: Path) -> None:
    project, artwork = _project(tmp_path, frames=8)
    destination = tmp_path / "existing.mp4"
    export_studio_video(project, artwork, destination)
    previous = destination.read_bytes()
    completed = 0

    def progress(done: int, _total: int) -> None:
        nonlocal completed
        completed = done

    with pytest.raises(RenderCancelled):
        export_studio_video(
            project,
            artwork,
            destination,
            progress=progress,
            should_cancel=lambda: completed >= 3,
        )

    assert destination.read_bytes() == previous
    assert not (tmp_path / "existing.part.mp4").exists()
def test_cancel_after_last_frame_still_prevents_atomic_replacement(tmp_path: Path) -> None:
    project, artwork = _project(tmp_path, frames=3)
    destination = tmp_path / "last-frame-race.mp4"
    export_studio_video(project, artwork, destination)
    previous = destination.read_bytes()
    completed = 0

    def progress(done: int, _total: int) -> None:
        nonlocal completed
        completed = done

    with pytest.raises(RenderCancelled):
        export_studio_video(
            project,
            artwork,
            destination,
            progress=progress,
            should_cancel=lambda: completed >= project.settings.duration_frames,
        )

    assert destination.read_bytes() == previous
    assert not (tmp_path / "last-frame-race.part.mp4").exists()




@pytest.mark.parametrize("container", ("mov", "webm"))
def test_mov_and_webm_profiles_remain_available(
    tmp_path: Path,
    container: str,
) -> None:
    project, artwork = _project(tmp_path, frames=2)
    project = replace(
        project,
        export=replace(project.export, container=container),
    ).validate()
    destination = tmp_path / f"reel.{container}"

    result = export_studio_video(project, artwork, destination)

    assert result.path == destination.resolve()
    assert result.frame_count == 2
    assert destination.stat().st_size > 0


def test_export_rejects_a_destination_that_disagrees_with_project(tmp_path: Path) -> None:
    project, artwork = _project(tmp_path)

    with pytest.raises(ValueError, match="demande .mp4"):
        export_studio_video(project, artwork, tmp_path / "reel.mov")


def _client_video_source(path: Path, *, asset_id: str = "export") -> VideoFrameSource:
    inspection = inspect_video(path)
    asset = MediaAsset(
        asset_id,
        AssetKind.VIDEO,
        str(path),
        width=inspection.width,
        height=inspection.height,
        metadata={
            "native_frame_count": inspection.native_frame_count,
            "native_fps": inspection.native_fps,
        },
    )
    return VideoFrameSource(
        asset,
        path,
        int(round(inspection.native_fps)),
        VideoClipSettings(),
    )


def test_export_composes_artwork_photo_video_and_dissolves(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork-red.png"
    photo = tmp_path / "photo-blue.png"
    source_video = tmp_path / "source-green.mp4"
    Image.new("RGB", (64, 64), (220, 20, 20)).save(artwork)
    Image.new("RGB", (64, 64), (20, 20, 220)).save(photo)
    encoder = VideoFrameEncoder(source_video, 64, 64, 30, quality="fast")
    try:
        encoder.open()
        for index in range(8):
            encoder.write(
                np.full((64, 64, 3), (20, 150 + index * 5, 20), dtype=np.uint8)
            )
        encoder.finish()
    except BaseException:
        encoder.abort()
        raise
    source_inspection = inspect_video(source_video)
    photo_asset = MediaAsset(
        "photo",
        AssetKind.IMAGE,
        str(photo),
        width=64,
        height=64,
    )
    video_asset = MediaAsset(
        "video",
        AssetKind.VIDEO,
        str(source_video),
        width=64,
        height=64,
        metadata={
            "native_frame_count": source_inspection.native_frame_count,
            "native_fps": source_inspection.native_fps,
        },
    )
    base = StudioProject.new(artwork, duration_seconds=1)
    artwork_clip = replace(
        base.tracks[0].clips[0],
        clip_id="artwork",
        duration_frames=4,
    )
    main = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre, photo et vidéo",
        (
            artwork_clip,
            Clip("photo", ClipKind.STILL, 4, 4, asset_id=photo_asset.asset_id),
            Clip(
                "video",
                ClipKind.VIDEO,
                8,
                4,
                source_in_frame=1,
                asset_id=video_asset.asset_id,
            ),
        ),
    )
    project = replace(
        base,
        artwork=replace(base.artwork, width=64, height=64),
        settings=ProjectSettings(64, 64, 30, 12),
        assets=(photo_asset, video_asset),
        tracks=(main, *base.tracks[1:]),
        export=ExportSettings(container="mp4", crf=18, quality="fast"),
    ).validate()
    project, _first = add_dissolve(
        project, "artwork", "photo", duration_frames=3, easing=Easing.LINEAR
    )
    project, _second = add_dissolve(
        project, "photo", "video", duration_frames=3, easing=Easing.LINEAR
    )
    destination = tmp_path / "composite.mp4"

    result = export_studio_video(project, artwork, destination)
    decoded = _client_video_source(destination)
    try:
        first = decoded.frame_at(0).mean(axis=(0, 1))
        photo_frame = decoded.frame_at(5).mean(axis=(0, 1))
        last = decoded.frame_at(11).mean(axis=(0, 1))
    finally:
        decoded.close()

    assert result.frame_count == 12
    assert first[0] > first[1] * 4 and first[0] > first[2] * 4
    assert photo_frame[2] > photo_frame[0] * 4
    assert last[1] > last[0] * 4 and last[1] > last[2] * 4


def test_vertical_1080p_export_is_playable_by_the_client_decoder(tmp_path: Path) -> None:
    project, artwork = _project(tmp_path, frames=2)
    project = replace(
        project,
        settings=replace(project.settings, width=1080, height=1920),
    ).validate()
    destination = tmp_path / "vertical-reel.mp4"

    result = export_studio_video(project, artwork, destination)
    decoded = _client_video_source(destination)
    try:
        frame = decoded.frame_at(1)
    finally:
        decoded.close()

    assert (result.width, result.height) == (1080, 1920)
    assert frame.shape == (1920, 1080, 3)

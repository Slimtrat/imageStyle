from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import wave

import imageio_ffmpeg
import numpy as np
from PIL import Image
import pytest

from artanimate.core.video import RenderCancelled
from artanimate.studio.audio import (
    AudioClipSettings,
    AudioFadeCurve,
    add_audio_clip,
    set_audio_track_gain,
    update_audio_clip,
)
from artanimate.studio.audio_export import AUDIO_EXPORT_SAMPLE_RATE, mix_studio_audio
from artanimate.studio.assets import import_media_asset
from artanimate.studio.export import export_studio_project
from artanimate.studio.model import (
    AssetKind,
    AudioExportMode,
    ExportSettings,
    MediaAsset,
    ProjectSettings,
    StudioProject,
)
from artanimate.studio.video import VideoClipSettings, VideoFrameSource, inspect_video


def _write_tone(
    path: Path,
    *,
    seconds: float = 2.0,
    sample_rate: int = AUDIO_EXPORT_SAMPLE_RATE,
    frequency: float = 440.0,
) -> None:
    samples = np.arange(int(seconds * sample_rate), dtype=np.float64)
    tone = np.sin(samples * (2.0 * np.pi * frequency / sample_rate)) * 0.5
    pcm = np.round(tone * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def _project(tmp_path: Path, *, mode: AudioExportMode) -> tuple[StudioProject, Path, Path]:
    artwork = tmp_path / "artwork.png"
    music = tmp_path / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (64, 64), (120, 60, 180)).save(artwork)
    _write_tone(music)
    base = StudioProject.new(artwork, fps=30, duration_seconds=1)
    video_clip = replace(base.tracks[0].clips[0], duration_frames=30)
    asset = import_media_asset(music, AssetKind.AUDIO, project_path, asset_id="music")
    project = replace(
        base,
        artwork=replace(base.artwork, width=64, height=64),
        settings=ProjectSettings(64, 64, 30, 30),
        assets=(asset,),
        tracks=(replace(base.tracks[0], clips=(video_clip,)), *base.tracks[1:]),
        export=ExportSettings(
            container="mp4",
            crf=18,
            quality="fast",
            audio_mode=mode,
        ),
    ).validate()
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=6,
        source_in_frame=3,
        duration_frames=18,
    )
    project, _clip = update_audio_clip(
        project,
        clip.clip_id,
        settings=AudioClipSettings(
            gain_db=3.0,
            fade_in_frames=3,
            fade_out_frames=3,
            fade_in_curve=AudioFadeCurve.LINEAR,
            fade_out_curve=AudioFadeCurve.LINEAR,
        ),
    )
    project = set_audio_track_gain(project, "audio-main", -3.0)
    return project, artwork, project_path


def _video_source(path: Path) -> VideoFrameSource:
    inspection = inspect_video(path)
    asset = MediaAsset(
        "rendered",
        AssetKind.VIDEO,
        str(path),
        width=inspection.width,
        height=inspection.height,
        metadata={
            "native_frame_count": inspection.native_frame_count,
            "native_fps": inspection.native_fps,
        },
    )
    return VideoFrameSource(asset, path, 30, VideoClipSettings())


def _decode_audio(path: Path) -> tuple[int, np.ndarray]:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "2",
        "-ar",
        str(AUDIO_EXPORT_SAMPLE_RATE),
        "pipe:1",
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    return completed.returncode, samples[: samples.size - samples.size % 2].reshape((-1, 2))


def test_pcm_mix_follows_project_clock_trim_gain_fades_and_silence(tmp_path: Path) -> None:
    project, artwork, project_path = _project(tmp_path, mode=AudioExportMode.EMBEDDED)

    result = mix_studio_audio(
        project,
        artwork,
        resource_base=project_path.parent,
    )
    samples_per_frame = AUDIO_EXPORT_SAMPLE_RATE // 30

    assert result.sample_count == AUDIO_EXPORT_SAMPLE_RATE
    assert result.channels == 2
    assert result.clip_count == 1
    assert np.all(result.samples[: 6 * samples_per_frame] == 0.0)
    assert np.all(result.samples[6 * samples_per_frame: 7 * samples_per_frame] == 0.0)
    assert np.max(np.abs(result.samples[9 * samples_per_frame: 10 * samples_per_frame])) > 0.2
    assert np.all(result.samples[24 * samples_per_frame:] == 0.0)
    assert result.peak <= 10 ** (-1.0 / 20.0) + 1e-6

def test_pcm_mix_overlaps_tracks_under_the_saved_limiter_ceiling(tmp_path: Path) -> None:
    project, artwork, project_path = _project(tmp_path, mode=AudioExportMode.EMBEDDED)
    project, _second = add_audio_clip(
        project,
        "music",
        start_frame=6,
        source_in_frame=3,
        duration_frames=18,
    )

    result = mix_studio_audio(
        project,
        artwork,
        resource_base=project_path.parent,
    )

    assert result.clip_count == 2
    assert 0.3 < result.peak <= 10 ** (-1.0 / 20.0) + 1e-6



def test_reference_and_embedded_modes_keep_identical_video_frames(tmp_path: Path) -> None:
    reference, artwork, project_path = _project(
        tmp_path,
        mode=AudioExportMode.REFERENCE,
    )
    embedded = replace(
        reference,
        export=replace(reference.export, audio_mode=AudioExportMode.EMBEDDED),
    ).validate()
    reference_path = tmp_path / "reference.mp4"
    embedded_path = tmp_path / "embedded.mp4"
    phases: list[str] = []

    reference_result = export_studio_project(
        reference,
        artwork,
        reference_path,
        resource_base=project_path.parent,
    )
    embedded_result = export_studio_project(
        embedded,
        artwork,
        embedded_path,
        resource_base=project_path.parent,
        phase=phases.append,
    )
    reference_video = _video_source(reference_path)
    embedded_video = _video_source(embedded_path)
    try:
        for frame in (0, 15, 29):
            assert np.array_equal(
                reference_video.frame_at(frame),
                embedded_video.frame_at(frame),
            )
    finally:
        reference_video.close()
        embedded_video.close()
    reference_code, reference_audio = _decode_audio(reference_path)
    embedded_code, embedded_audio = _decode_audio(embedded_path)

    assert reference_result.audio_mode == AudioExportMode.REFERENCE
    assert embedded_result.audio_mode == AudioExportMode.EMBEDDED
    assert embedded_result.audio_sample_count == AUDIO_EXPORT_SAMPLE_RATE
    assert reference_code != 0
    assert reference_audio.size == 0
    assert embedded_code == 0
    assert embedded_audio.shape[0] >= AUDIO_EXPORT_SAMPLE_RATE
    assert np.max(np.abs(embedded_audio[9 * 1600: 10 * 1600])) > 0.15
    assert phases == ["video", "audio", "mux", "complete"]
    assert tuple(tmp_path.glob(".*.audio.wav")) == ()
    assert tuple(tmp_path.glob(".*.video.mp4")) == ()
    assert tuple(tmp_path.glob(".*.mux.mp4")) == ()


def test_embedded_cancel_and_missing_media_preserve_destination_and_clean_stages(
    tmp_path: Path,
) -> None:
    project, artwork, project_path = _project(tmp_path, mode=AudioExportMode.EMBEDDED)
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"previous-valid-export")
    current_phase = ""

    def phase(value: str) -> None:
        nonlocal current_phase
        current_phase = value

    with pytest.raises(RenderCancelled):
        export_studio_project(
            project,
            artwork,
            destination,
            resource_base=project_path.parent,
            phase=phase,
            should_cancel=lambda: current_phase == "audio",
        )
    assert destination.read_bytes() == b"previous-valid-export"
    assert tuple(tmp_path.glob(".*.part.mp4")) == ()
    assert tuple(tmp_path.glob(".*.audio.wav")) == ()
    assert tuple(tmp_path.glob(".*.video.mp4")) == ()

    (tmp_path / "music.wav").unlink()
    with pytest.raises(FileNotFoundError, match="Média audio introuvable"):
        export_studio_project(
            project,
            artwork,
            destination,
            resource_base=project_path.parent,
        )
    assert destination.read_bytes() == b"previous-valid-export"
    assert tuple(tmp_path.glob(".*.part.mp4")) == ()
    assert tuple(tmp_path.glob(".*.audio.wav")) == ()
    assert tuple(tmp_path.glob(".*.video.mp4")) == ()

    reference = replace(
        project,
        export=replace(project.export, audio_mode=AudioExportMode.REFERENCE),
    ).validate()
    reference_path = tmp_path / "missing-reference.mp4"
    result = export_studio_project(
        reference,
        artwork,
        reference_path,
        resource_base=project_path.parent,
    )
    assert result.audio_mode == AudioExportMode.REFERENCE
    assert reference_path.is_file()

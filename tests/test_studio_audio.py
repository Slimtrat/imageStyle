from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import wave

from PIL import Image
import pytest

from artanimate.studio.audio import (
    AudioClipSettings,
    add_audio_clip,
    audio_monitor_frame,
)
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, ClipKind, StudioProject, Track, TrackKind
from artanimate.studio.render_session import StudioRenderSession


def _write_wav(path: Path, *, seconds: float = 2.0, sample_rate: int = 48_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0\0" * frame_count)


def _project_with_audio(tmp_path: Path) -> tuple[StudioProject, Path, Path]:
    artwork = tmp_path / "artwork.png"
    audio = tmp_path / "audio" / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (96, 64), (90, 130, 180)).save(artwork)
    _write_wav(audio)
    project = StudioProject.new(artwork, duration_seconds=5)
    asset = import_media_asset(audio, AssetKind.AUDIO, project_path, asset_id="music")
    project = replace(project, assets=(asset,)).validate()
    return project, audio, project_path


def test_wav_import_records_local_timing_and_places_a_bounded_clip(
    tmp_path: Path,
) -> None:
    project, _audio, _project_path = _project_with_audio(tmp_path)
    asset = project.assets[0]

    assert asset.metadata["duration_seconds"] == 2.0
    assert asset.metadata["sample_rate"] == 48_000
    assert asset.metadata["channels"] == 1

    updated, clip = add_audio_clip(project, "music", start_frame=15)

    assert clip.kind == ClipKind.AUDIO
    assert clip.start_frame == 15
    assert clip.duration_frames == 60
    assert AudioClipSettings.from_clip(clip) == AudioClipSettings()
    assert next(
        track for track in updated.tracks if track.track_id == "audio-main"
    ).clips == (clip,)


def test_audio_resolution_uses_source_trim_project_frames_and_track_mute(
    tmp_path: Path,
) -> None:
    project, audio, project_path = _project_with_audio(tmp_path)
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=10,
        source_in_frame=6,
        duration_frames=30,
    )

    state = audio_monitor_frame(project, 19, project_path)

    assert state.missing_asset_ids == ()
    assert len(state.targets) == 1
    target = state.targets[0]
    assert target.path == audio.resolve()
    assert target.source_frame == 15
    assert target.position_ms == 500
    assert target.clip_id == clip.clip_id

    tracks = tuple(
        replace(track, muted=True) if track.track_id == "audio-main" else track
        for track in project.tracks
    )
    muted = replace(project, tracks=tracks).validate()
    assert audio_monitor_frame(muted, 19, project_path).targets == ()


def test_multiple_audio_tracks_resolve_together_and_missing_media_is_nonfatal(
    tmp_path: Path,
) -> None:
    project, audio, project_path = _project_with_audio(tmp_path)
    project = replace(
        project,
        tracks=project.tracks + (
            Track("audio-second", TrackKind.AUDIO, "Ambiance"),
        ),
    ).validate()
    project, first = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=30,
        track_id="audio-main",
    )
    project, second = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=30,
        track_id="audio-second",
    )

    state = audio_monitor_frame(project, 12, project_path)
    assert {item.clip_id for item in state.targets} == {
        first.clip_id,
        second.clip_id,
    }

    audio.unlink()
    missing = audio_monitor_frame(project, 12, project_path)
    assert missing.targets == ()
    assert missing.missing_asset_ids == ("music",)

    with StudioRenderSession(
        project,
        project.artwork.path,
        output_width=90,
        output_height=160,
    ) as session:
        assert session.frame_at(12).shape == (160, 90, 3)


def test_invalid_wav_is_rejected_during_local_import(tmp_path: Path) -> None:
    invalid = tmp_path / "broken.wav"
    invalid.write_bytes(b"not a wav")
    with pytest.raises(ValueError, match="WAV local illisible"):
        import_media_asset(
            invalid,
            AssetKind.AUDIO,
            tmp_path / "reel.artanimate",
        )

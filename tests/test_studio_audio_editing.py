from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import wave

from PIL import Image
import pytest

from artanimate.studio.audio import (
    AudioClipSettings,
    AudioFadeCurve,
    AudioMixSettings,
    add_audio_clip,
    audio_monitor_frame,
    db_to_linear,
    set_audio_mix_settings,
    set_audio_track_gain,
    update_audio_clip,
)
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, ClipKind, StudioProject
from artanimate.studio.timeline import split_clip, trim_clip


def _project(tmp_path: Path) -> tuple[StudioProject, str, Path]:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (100, 80), "navy").save(artwork)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1_000)
        output.writeframes(b"\0\x20" * 5_000)
    asset = import_media_asset(audio, AssetKind.AUDIO, project_path, asset_id="music")
    project = replace(
        StudioProject.new(artwork, fps=30, duration_seconds=5),
        assets=(asset,),
    ).validate()
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=20,
    )
    return project, clip.clip_id, project_path


def _audio_clip(project: StudioProject, clip_id: str):
    return next(
        clip
        for track in project.tracks
        for clip in track.clips
        if clip.clip_id == clip_id and clip.kind == ClipKind.AUDIO
    )


def test_audio_settings_and_track_mix_round_trip_in_project_extension(tmp_path: Path) -> None:
    project, clip_id, _project_path = _project(tmp_path)
    settings = AudioClipSettings(
        gain_db=4.5,
        fade_in_frames=3,
        fade_out_frames=5,
        fade_in_curve=AudioFadeCurve.LINEAR,
        fade_out_curve=AudioFadeCurve.EQUAL_POWER,
    )

    project, clip = update_audio_clip(project, clip_id, settings=settings)
    project = set_audio_track_gain(project, "audio-main", -3.0)
    restored = StudioProject.from_dict(project.to_dict())

    assert AudioClipSettings.from_clip(clip) == settings
    assert AudioClipSettings.from_clip(_audio_clip(restored, clip_id)) == settings
    assert AudioMixSettings.from_project(restored).track("audio-main").gain_db == -3.0
    assert restored.to_dict()["audio"]["tracks"]["audio-main"]["gain_db"] == -3.0


def test_frame_mix_applies_fades_track_gain_and_conservative_headroom(tmp_path: Path) -> None:
    project, clip_id, project_path = _project(tmp_path)
    settings = AudioClipSettings(
        gain_db=6.0,
        fade_in_frames=4,
        fade_out_frames=4,
        fade_in_curve=AudioFadeCurve.LINEAR,
        fade_out_curve=AudioFadeCurve.LINEAR,
    )
    project, _clip = update_audio_clip(project, clip_id, settings=settings)
    project = set_audio_track_gain(project, "audio-main", -6.0)

    assert audio_monitor_frame(project, 0, project_path).targets[0].linear_gain == 0.0
    full = audio_monitor_frame(project, 4, project_path)
    assert full.targets[0].envelope_gain == 1.0
    assert full.targets[0].gain_db == 0.0
    assert full.master_gain == pytest.approx(db_to_linear(-1.0))
    tail = audio_monitor_frame(project, 19, project_path)
    assert tail.targets[0].envelope_gain == pytest.approx(0.25)
    assert tail.targets[0].linear_gain == pytest.approx(0.25)

    project, second = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=20,
    )
    project, _second = update_audio_clip(
        project,
        second.clip_id,
        settings=AudioClipSettings(),
    )
    overlap = audio_monitor_frame(project, 5, project_path)
    assert len(overlap.targets) == 2
    assert sum(item.linear_gain for item in overlap.targets) == pytest.approx(
        db_to_linear(-1.0)
    )
    assert all(0.0 <= item.linear_gain <= 1.0 for item in overlap.targets)


def test_trim_and_split_keep_audio_source_and_outer_fades_frame_exact(tmp_path: Path) -> None:
    project, clip_id, _project_path = _project(tmp_path)
    project, _clip = update_audio_clip(
        project,
        clip_id,
        settings=AudioClipSettings(
            fade_in_frames=8,
            fade_out_frames=8,
            fade_in_curve=AudioFadeCurve.LINEAR,
            fade_out_curve=AudioFadeCurve.LINEAR,
        ),
    )

    trimmed_project = trim_clip(project, clip_id, 8, 12)
    trimmed = _audio_clip(trimmed_project, clip_id)
    trimmed_settings = AudioClipSettings.from_clip(trimmed)
    assert (trimmed.start_frame, trimmed.source_in_frame, trimmed.duration_frames) == (8, 8, 4)
    assert (trimmed_settings.fade_in_frames, trimmed_settings.fade_out_frames) == (2, 2)

    split_project, right = split_clip(trimmed_project, clip_id, 10)
    left = _audio_clip(split_project, clip_id)
    left_settings = AudioClipSettings.from_clip(left)
    right_settings = AudioClipSettings.from_clip(right)
    assert (left_settings.fade_in_frames, left_settings.fade_out_frames) == (2, 0)
    assert (right_settings.fade_in_frames, right_settings.fade_out_frames) == (0, 2)
    assert right.source_in_frame == 10


def test_audio_range_and_mix_validation_reject_invalid_edits(tmp_path: Path) -> None:
    project, clip_id, _project_path = _project(tmp_path)

    with pytest.raises(ValueError, match="durée du média"):
        update_audio_clip(project, clip_id, source_in_frame=145, duration_frames=10)
    with pytest.raises(ValueError, match="dépassent"):
        update_audio_clip(
            project,
            clip_id,
            settings=AudioClipSettings(fade_in_frames=15, fade_out_frames=15),
        )
    with pytest.raises(ValueError, match="limiter"):
        set_audio_mix_settings(project, AudioMixSettings(limiter_ceiling_db=1.0))

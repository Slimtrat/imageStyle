from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
import wave

import numpy as np
from PIL import Image
import pytest

from artanimate.studio.model import StudioProject
from artanimate.studio.clock import StudioClock
from artanimate.studio.music_analysis import (
    MusicAnalysis,
    MusicAnalysisCache,
    MusicAnalysisCancelled,
    MusicAnalysisSettings,
    MusicEventKind,
    analyze_music,
    set_music_analysis_settings,
)


def _write_rhythm_fixture(
    path: Path,
    *,
    sample_rate: int = 8_000,
    seconds: float = 12.0,
) -> None:
    sample_count = int(sample_rate * seconds)
    timeline = np.arange(sample_count, dtype=np.float64) / sample_rate
    samples = 0.003 * np.sin(2.0 * np.pi * 311.0 * timeline)
    for beat_index, start_seconds in enumerate(
        np.arange(0.5, seconds - 0.2, 0.5)
    ):
        start = int(round(float(start_seconds) * sample_rate))
        length = min(int(sample_rate * 0.055), sample_count - start)
        local = np.arange(length, dtype=np.float64) / sample_rate
        amplitude = 0.92 if beat_index % 4 == 0 else 0.52
        click = amplitude * np.exp(-local * 55.0) * np.sin(
            2.0 * np.pi * (82.0 if beat_index % 4 == 0 else 970.0) * local
        )
        samples[start : start + length] += click
    drop_start = int(6.0 * sample_rate)
    drop_time = timeline[drop_start:] - 6.0
    samples[drop_start:] += (
        0.30
        * (1.0 - np.exp(-drop_time * 8.0))
        * np.sin(2.0 * np.pi * 91.0 * drop_time)
    )
    encoded = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(encoded.tobytes())


def test_detects_stable_clock_events_tempo_downbeats_and_drop(
    tmp_path: Path,
) -> None:
    source = tmp_path / "rhythm.wav"
    _write_rhythm_fixture(source)
    original = source.read_bytes()
    settings = MusicAnalysisSettings(0.85)

    first = analyze_music(
        source,
        "fixture-fingerprint",
        fps=30,
        settings=settings,
    )
    second = analyze_music(
        source,
        "fixture-fingerprint",
        fps=30,
        settings=settings,
    )

    assert first == second
    assert 115.0 <= (first.tempo_bpm or 0.0) <= 125.0
    assert len(first.events_of(MusicEventKind.BEAT)) >= 18
    assert len(first.events_of(MusicEventKind.DOWNBEAT)) >= 4
    drops = first.events_of(MusicEventKind.DROP)
    assert drops and any(abs(event.frame - 180) <= 18 for event in drops)
    assert all(isinstance(event.frame, int) for event in first.events)
    assert all(isinstance(event.uncertain, bool) for event in first.events)
    assert source.read_bytes() == original

    at_sixty = analyze_music(
        source,
        "fixture-fingerprint",
        fps=60,
        settings=settings,
    )
    assert [
        (event.kind, event.source_sample) for event in at_sixty.events
    ] == [
        (event.kind, event.source_sample) for event in first.events
    ]
    clock = StudioClock(60)
    assert all(
        event.frame
        == clock.seconds_to_frame(event.source_sample / at_sixty.sample_rate)
        for event in at_sixty.events
    )


def test_cache_keys_fingerprint_settings_and_fps_atomically(
    tmp_path: Path,
) -> None:
    source = tmp_path / "cached.wav"
    _write_rhythm_fixture(source, seconds=6.0)
    cache = MusicAnalysisCache(tmp_path / "cache")
    regular = MusicAnalysisSettings(0.55)
    first = cache.load_or_analyze(
        source,
        "fingerprint-a",
        fps=30,
        settings=regular,
        cancelled=Event(),
    )
    source.unlink()
    reused = cache.load_or_analyze(
        source,
        "fingerprint-a",
        fps=30,
        settings=regular,
        cancelled=Event(),
    )

    assert not first.cache_hit
    assert reused.cache_hit
    assert reused == first
    assert cache.load("fingerprint-a", MusicAnalysisSettings(0.8), 30) is None
    assert cache.load("fingerprint-a", regular, 60) is None


def test_sensitivity_is_versioned_persisted_and_changes_candidate_filter(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (80, 60), "purple").save(artwork)
    project = StudioProject.new(artwork)
    settings = MusicAnalysisSettings(0.82)
    updated = set_music_analysis_settings(project, settings)
    reopened = StudioProject.from_dict(updated.to_dict())

    assert MusicAnalysisSettings.from_project(reopened) == settings
    assert MusicAnalysisSettings(0.1).candidate_threshold > settings.candidate_threshold

    source = tmp_path / "sensitivity.wav"
    _write_rhythm_fixture(source, seconds=6.0)
    selective = analyze_music(
        source,
        "sensitivity",
        fps=30,
        settings=MusicAnalysisSettings(0.1),
    )
    broad = analyze_music(
        source,
        "sensitivity",
        fps=30,
        settings=MusicAnalysisSettings(1.0),
    )
    assert len(broad.events) > len(selective.events)


def test_analysis_is_cancellable_and_silent_audio_stays_empty(
    tmp_path: Path,
) -> None:
    source = tmp_path / "silence.wav"
    samples = np.zeros(8_000, dtype="<i2")
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(samples.tobytes())
    cancelled = Event()
    cancelled.set()

    with pytest.raises(MusicAnalysisCancelled):
        analyze_music(
            source,
            "silence",
            fps=30,
            cancelled=cancelled,
        )

    result = analyze_music(source, "silence", fps=30)
    restored = MusicAnalysis.from_mapping(result.to_dict())
    assert restored == result
    assert result.tempo_bpm is None
    assert result.events == ()


def test_uncertainty_survives_cache_serialization(tmp_path: Path) -> None:
    source = tmp_path / "rhythm.wav"
    _write_rhythm_fixture(source, seconds=6.0)
    result = analyze_music(
        source,
        "uncertain-fixture",
        fps=30,
        settings=MusicAnalysisSettings(1.0),
    )
    cache = MusicAnalysisCache(tmp_path / "cache")
    cache.store(result)
    restored = cache.load(
        result.source_fingerprint,
        result.settings,
        result.fps,
    )

    assert restored is not None
    assert [item.uncertain for item in restored.events] == [
        item.uncertain for item in result.events
    ]
    assert any(item.uncertain for item in result.events)

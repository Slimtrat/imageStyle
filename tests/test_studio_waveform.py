from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
import wave

import numpy as np
from PIL import Image

from artanimate.studio.audio import add_audio_clip
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, StudioProject
from artanimate.studio.waveform import (
    WaveformCache,
    extract_waveform,
    waveform_peaks_for_clip,
)


def _write_pcm(path: Path, samples: np.ndarray, sample_rate: int = 8_000) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    encoded = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(encoded.tobytes())


def test_pcm_extraction_builds_ordered_multiresolution_peaks(tmp_path: Path) -> None:
    source = tmp_path / "pulse.wav"
    samples = np.concatenate(
        (
            np.full(800, -0.25, dtype=np.float32),
            np.full(800, 0.75, dtype=np.float32),
        )
    )
    _write_pcm(source, samples)

    envelope = extract_waveform(source, "fingerprint-a")

    assert envelope.sample_rate == 8_000
    assert envelope.sample_count == 1_600
    assert len(envelope.levels) >= 3
    assert tuple(level.samples_per_peak for level in envelope.levels) == tuple(
        sorted(level.samples_per_peak for level in envelope.levels)
    )
    assert envelope.levels[0].minimums[0] < -0.24
    assert envelope.levels[0].maximums[-1] > 0.74
    assert len(envelope.levels[-1].minimums) == 1


def test_clip_projection_follows_source_trim_and_zoom(tmp_path: Path) -> None:
    source = tmp_path / "sections.wav"
    samples = np.concatenate(
        (
            np.full(8_000, 0.1, dtype=np.float32),
            np.full(8_000, 0.8, dtype=np.float32),
        )
    )
    _write_pcm(source, samples)
    envelope = extract_waveform(source, "fingerprint-b")

    artwork = tmp_path / "art.png"
    Image.new("RGB", (80, 80), "navy").save(artwork)
    asset = import_media_asset(
        source,
        AssetKind.AUDIO,
        tmp_path / "reel.artanimate",
        asset_id="music",
    )
    project = replace(
        StudioProject.new(artwork, fps=30, duration_seconds=3),
        assets=(asset,),
    ).validate()
    project, first_half = add_audio_clip(
        project,
        "music",
        start_frame=0,
        source_in_frame=0,
        duration_frames=30,
    )
    second_half = replace(first_half, source_in_frame=30)

    quiet = waveform_peaks_for_clip(envelope, first_half, 30, 20)
    loud = waveform_peaks_for_clip(envelope, second_half, 30, 20)
    zoomed = waveform_peaks_for_clip(envelope, second_half, 30, 100)

    # A single edge pixel may share the coarser cache bucket across the trim.
    assert max(peak[1] for peak in quiet[:-1]) < 0.2
    assert min(peak[1] for peak in loud) > 0.7
    assert len(zoomed) == 100


def test_silent_and_very_short_waveforms_remain_renderable(tmp_path: Path) -> None:
    source = tmp_path / "short.wav"
    _write_pcm(source, np.zeros(4, dtype=np.float32))

    envelope = extract_waveform(source, "short")

    assert envelope.sample_count == 4
    assert envelope.levels[0].minimums == (0.0,)
    assert envelope.levels[0].maximums == (0.0,)


def test_cache_reuses_fingerprint_and_prunes_old_entries(tmp_path: Path) -> None:
    source = tmp_path / "cached.wav"
    _write_pcm(source, np.linspace(-1, 1, 2_000, dtype=np.float32))
    cache = WaveformCache(tmp_path / "cache", max_entries=2)

    first = cache.load_or_extract(
        source,
        "fingerprint-1",
        cancelled=Event(),
    )
    source.unlink()
    reused = cache.load_or_extract(
        source,
        "fingerprint-1",
        cancelled=Event(),
    )

    assert reused == first
    assert cache.load("changed-fingerprint") is None

    for fingerprint in ("fingerprint-2", "fingerprint-3"):
        cache.store(replace(first, source_fingerprint=fingerprint))
    assert len(tuple((tmp_path / "cache").glob("*.npz"))) <= 2

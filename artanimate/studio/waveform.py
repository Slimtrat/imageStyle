from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event

import numpy as np

from .audio_decode import AudioDecodeCancelled, decode_mono_audio
from .model import Clip, ClipKind


WAVEFORM_SCHEMA_VERSION = 1
BASE_SAMPLES_PER_PEAK = 64


class WaveformCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WaveformLevel:
    samples_per_peak: int
    minimums: tuple[float, ...]
    maximums: tuple[float, ...]

    def validate(self) -> WaveformLevel:
        if self.samples_per_peak <= 0:
            raise ValueError("Une résolution waveform doit couvrir des échantillons")
        if len(self.minimums) != len(self.maximums) or not self.minimums:
            raise ValueError("Une résolution waveform doit contenir des pics min/max")
        return self


@dataclass(frozen=True, slots=True)
class WaveformEnvelope:
    source_fingerprint: str
    sample_rate: int
    sample_count: int
    levels: tuple[WaveformLevel, ...]

    def validate(self) -> WaveformEnvelope:
        if not self.source_fingerprint:
            raise ValueError("La waveform doit référencer une empreinte source")
        if self.sample_rate <= 0 or self.sample_count < 0:
            raise ValueError("La waveform contient une durée PCM invalide")
        if not self.levels:
            raise ValueError("La waveform doit contenir au moins une résolution")
        previous = 0
        for level in self.levels:
            level.validate()
            if level.samples_per_peak <= previous:
                raise ValueError("Les résolutions waveform doivent être croissantes")
            previous = level.samples_per_peak
        return self

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate

    def level_for(self, samples_per_pixel: float) -> WaveformLevel:
        target = max(1.0, float(samples_per_pixel))
        candidates = [
            level for level in self.levels
            if level.samples_per_peak <= target
        ]
        return candidates[-1] if candidates else self.levels[0]


class _PeakBuilder:
    def __init__(self, block_size: int = BASE_SAMPLES_PER_PEAK) -> None:
        self.block_size = block_size
        self.sample_count = 0
        self._remainder = np.empty(0, dtype=np.float32)
        self._minimums: list[np.ndarray] = []
        self._maximums: list[np.ndarray] = []

    def consume(self, samples: np.ndarray) -> None:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.sample_count += len(values)
        if self._remainder.size:
            values = np.concatenate((self._remainder, values))
            self._remainder = np.empty(0, dtype=np.float32)
        complete = len(values) // self.block_size * self.block_size
        if complete:
            blocks = values[:complete].reshape(-1, self.block_size)
            self._minimums.append(blocks.min(axis=1))
            self._maximums.append(blocks.max(axis=1))
        if complete < len(values):
            self._remainder = values[complete:].copy()

    def finish(self, fingerprint: str, sample_rate: int) -> WaveformEnvelope:
        if self._remainder.size:
            self._minimums.append(np.array([self._remainder.min()], dtype=np.float32))
            self._maximums.append(np.array([self._remainder.max()], dtype=np.float32))
        if self._minimums:
            minimums = np.concatenate(self._minimums)
            maximums = np.concatenate(self._maximums)
        else:
            minimums = np.array([0.0], dtype=np.float32)
            maximums = np.array([0.0], dtype=np.float32)
        levels: list[WaveformLevel] = []
        block = self.block_size
        while True:
            levels.append(
                WaveformLevel(
                    block,
                    tuple(float(value) for value in minimums),
                    tuple(float(value) for value in maximums),
                )
            )
            if len(minimums) <= 1:
                break
            if len(minimums) % 2:
                minimums = np.append(minimums, minimums[-1])
                maximums = np.append(maximums, maximums[-1])
            minimums = minimums.reshape(-1, 2).min(axis=1)
            maximums = maximums.reshape(-1, 2).max(axis=1)
            block *= 2
        return WaveformEnvelope(
            fingerprint,
            sample_rate,
            self.sample_count,
            tuple(levels),
        ).validate()


def extract_waveform(
    path: str | Path,
    source_fingerprint: str,
    *,
    cancelled: Event | None = None,
) -> WaveformEnvelope:
    source = Path(os.path.abspath(path))
    cancellation = cancelled or Event()
    builder = _PeakBuilder()
    try:
        info = decode_mono_audio(source, builder.consume, cancelled=cancellation)
    except AudioDecodeCancelled as exc:
        raise WaveformCancelled("Calcul waveform annulé") from exc
    if cancellation.is_set():
        raise WaveformCancelled("Calcul waveform annulé")
    return builder.finish(source_fingerprint, info.sample_rate)


def waveform_peaks_for_clip(
    envelope: WaveformEnvelope,
    clip: Clip,
    fps: int,
    pixel_count: int,
) -> tuple[tuple[float, float], ...]:
    if clip.kind != ClipKind.AUDIO:
        raise ValueError("La projection waveform exige un clip audio")
    if fps <= 0 or pixel_count <= 0:
        raise ValueError("La projection waveform exige un FPS et une largeur positifs")
    sample_start = clip.source_in_frame * envelope.sample_rate / fps
    sample_end = (
        clip.source_in_frame + clip.duration_frames
    ) * envelope.sample_rate / fps
    sample_end = min(float(envelope.sample_count), sample_end)
    samples_per_pixel = max(1.0, (sample_end - sample_start) / pixel_count)
    level = envelope.level_for(samples_per_pixel)
    minimums = np.asarray(level.minimums, dtype=np.float32)
    maximums = np.asarray(level.maximums, dtype=np.float32)
    peaks: list[tuple[float, float]] = []
    for pixel in range(pixel_count):
        left_sample = sample_start + pixel * samples_per_pixel
        right_sample = sample_start + (pixel + 1) * samples_per_pixel
        left = max(0, int(left_sample // level.samples_per_peak))
        right = min(
            len(minimums),
            max(left + 1, int(np.ceil(right_sample / level.samples_per_peak))),
        )
        if left >= len(minimums) or sample_end <= sample_start:
            peaks.append((0.0, 0.0))
        else:
            peaks.append((float(minimums[left:right].min()), float(maximums[left:right].max())))
    return tuple(peaks)


class WaveformCache:
    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = 128 * 1024 * 1024,
        max_entries: int = 128,
    ) -> None:
        self.root = Path(root)
        self.max_bytes = max(1, int(max_bytes))
        self.max_entries = max(1, int(max_entries))

    def _path(self, fingerprint: str) -> Path:
        key = sha256(
            f"{WAVEFORM_SCHEMA_VERSION}\0{fingerprint}".encode("utf-8")
        ).hexdigest()
        return self.root / f"{key}.npz"

    def load(self, fingerprint: str) -> WaveformEnvelope | None:
        path = self._path(fingerprint)
        if not path.is_file():
            return None
        try:
            with np.load(path, allow_pickle=False) as values:
                metadata = json.loads(str(values["metadata"].item()))
                if (
                    metadata.get("schema_version") != WAVEFORM_SCHEMA_VERSION
                    or metadata.get("source_fingerprint") != fingerprint
                ):
                    return None
                levels = tuple(
                    WaveformLevel(
                        int(block),
                        tuple(float(item) for item in values[f"minimums_{index}"]),
                        tuple(float(item) for item in values[f"maximums_{index}"]),
                    )
                    for index, block in enumerate(metadata["blocks"])
                )
                envelope = WaveformEnvelope(
                    fingerprint,
                    int(metadata["sample_rate"]),
                    int(metadata["sample_count"]),
                    levels,
                ).validate()
            os.utime(path, None)
            return envelope
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def store(self, envelope: WaveformEnvelope) -> Path:
        envelope.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._path(envelope.source_fingerprint)
        metadata = {
            "schema_version": WAVEFORM_SCHEMA_VERSION,
            "source_fingerprint": envelope.source_fingerprint,
            "sample_rate": envelope.sample_rate,
            "sample_count": envelope.sample_count,
            "blocks": [item.samples_per_peak for item in envelope.levels],
        }
        arrays: dict[str, np.ndarray] = {
            "metadata": np.array(json.dumps(metadata, sort_keys=True)),
        }
        for index, level in enumerate(envelope.levels):
            arrays[f"minimums_{index}"] = np.asarray(level.minimums, dtype=np.float32)
            arrays[f"maximums_{index}"] = np.asarray(level.maximums, dtype=np.float32)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                prefix="waveform-",
                suffix=".npz",
                dir=self.root,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                np.savez_compressed(handle, **arrays)
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.prune(keep=(destination,))
        return destination

    def load_or_extract(
        self,
        path: str | Path,
        fingerprint: str,
        *,
        cancelled: Event,
    ) -> WaveformEnvelope:
        cached = self.load(fingerprint)
        if cached is not None:
            return cached
        envelope = extract_waveform(path, fingerprint, cancelled=cancelled)
        if cancelled.is_set():
            raise WaveformCancelled("Calcul waveform annulé")
        self.store(envelope)
        return envelope

    def prune(self, *, keep: tuple[Path, ...] = ()) -> None:
        if not self.root.exists():
            return
        preserved = {item.resolve(strict=False) for item in keep}
        entries = sorted(
            (item for item in self.root.glob("*.npz") if item.is_file()),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        total = sum(item.stat().st_size for item in entries)
        for index, path in enumerate(entries):
            if index < self.max_entries and total <= self.max_bytes:
                continue
            if path.resolve(strict=False) in preserved:
                continue
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            total -= size

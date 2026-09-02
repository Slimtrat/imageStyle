from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from threading import Event
import wave

import imageio_ffmpeg
import numpy as np


class AudioDecodeCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedAudioInfo:
    sample_rate: int
    sample_count: int


def _pcm_bytes(values: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (
            np.frombuffer(values, dtype=np.uint8).astype(np.float32) - 128.0
        ) / 128.0
    if sample_width == 2:
        return np.frombuffer(values, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 3:
        raw = np.frombuffer(values, dtype=np.uint8).reshape(-1, 3)
        integers = (
            raw[:, 0].astype(np.int32)
            | raw[:, 1].astype(np.int32) << 8
            | raw[:, 2].astype(np.int32) << 16
        )
        integers = np.where(integers & 0x800000, integers - 0x1000000, integers)
        return integers.astype(np.float32) / 8_388_608.0
    if sample_width == 4:
        return (
            np.frombuffer(values, dtype="<i4").astype(np.float32)
            / 2_147_483_648.0
        )
    raise ValueError(
        f"Largeur PCM WAV non prise en charge : {sample_width} octets"
    )


def decode_mono_audio(
    path: str | Path,
    consume: Callable[[np.ndarray], None],
    *,
    cancelled: Event,
    ffmpeg_sample_rate: int = 48_000,
) -> DecodedAudioInfo:
    """Stream a local audio file as normalized mono PCM without mutating it."""

    source = Path(os.path.abspath(path))
    if cancelled.is_set():
        raise AudioDecodeCancelled("Décodage audio annulé")
    if source.suffix.casefold() == ".wav":
        return _decode_wav(source, consume, cancelled)
    return _decode_ffmpeg(
        source,
        consume,
        cancelled,
        sample_rate=ffmpeg_sample_rate,
    )


def _decode_wav(
    path: Path,
    consume: Callable[[np.ndarray], None],
    cancelled: Event,
) -> DecodedAudioInfo:
    sample_count = 0
    with wave.open(str(path), "rb") as source:
        sample_rate = source.getframerate()
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        while True:
            if cancelled.is_set():
                raise AudioDecodeCancelled("Décodage audio annulé")
            raw = source.readframes(16_384)
            if not raw:
                break
            samples = _pcm_bytes(raw, sample_width)
            if channels > 1:
                samples = samples.reshape(-1, channels).mean(axis=1)
            values = np.asarray(samples, dtype=np.float32)
            sample_count += len(values)
            consume(values)
    return DecodedAudioInfo(sample_rate, sample_count)


def _decode_ffmpeg(
    path: Path,
    consume: Callable[[np.ndarray], None],
    cancelled: Event,
    *,
    sample_rate: int,
) -> DecodedAudioInfo:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
        "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1",
        "-ar", str(sample_rate), "pipe:1",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    assert process.stdout is not None
    sample_count = 0
    try:
        while True:
            if cancelled.is_set():
                process.terminate()
                raise AudioDecodeCancelled("Décodage audio annulé")
            raw = process.stdout.read(65_536)
            if not raw:
                break
            values = np.frombuffer(raw, dtype="<f4")
            sample_count += len(values)
            consume(values)
        return_code = process.wait()
        if return_code:
            assert process.stderr is not None
            message = process.stderr.read().decode("utf-8", errors="replace").strip()
            raise ValueError(f"Décodage PCM local impossible : {message}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return DecodedAudioInfo(sample_rate, sample_count)

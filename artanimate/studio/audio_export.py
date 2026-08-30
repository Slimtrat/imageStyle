from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Event
from typing import Callable
import wave

import imageio_ffmpeg
import numpy as np

from ..core.video import RenderCancelled
from .audio import AudioClipSettings, AudioMixSettings, audio_envelope_gain, db_to_linear
from .model import AssetKind, Clip, MediaAsset, StudioProject, Track, TrackKind


AUDIO_EXPORT_SAMPLE_RATE = 48_000
AUDIO_EXPORT_CHANNELS = 2


@dataclass(frozen=True, slots=True)
class StudioAudioMixResult:
    samples: np.ndarray
    sample_rate: int
    channels: int
    clip_count: int
    peak: float

    @property
    def sample_count(self) -> int:
        return int(self.samples.shape[0])


def _cancelled(cancelled: Event | Callable[[], bool] | None) -> bool:
    if cancelled is None:
        return False
    if isinstance(cancelled, Event):
        return cancelled.is_set()
    return bool(cancelled())


def _communicate_cancellable(
    command: list[str],
    *,
    cancelled: Event | Callable[[], bool] | None,
) -> tuple[bytes, bytes]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if _cancelled(cancelled):
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise RenderCancelled("Export audio Studio annulé")
    if _cancelled(cancelled):
        raise RenderCancelled("Export audio Studio annulé")
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Traitement audio FFmpeg impossible : {message}")
    return stdout, stderr


def _frame_sample(frame: int, fps: int, sample_rate: int) -> int:
    return int(frame) * int(sample_rate) // int(fps)


def _resolve_audio_path(
    asset: MediaAsset,
    resource_base: str | Path | None,
    artwork_path: str | Path,
) -> Path:
    stored = Path(asset.path)
    if stored.is_absolute():
        return stored.resolve(strict=False)
    base = (
        Path(resource_base)
        if resource_base is not None
        else Path(artwork_path).resolve(strict=False).parent
    )
    return (base / stored).resolve(strict=False)


def _decode_clip(
    path: Path,
    clip: Clip,
    *,
    fps: int,
    sample_rate: int,
    channels: int,
    cancelled: Event | Callable[[], bool] | None,
) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"Média audio introuvable : {path}")
    start_seconds = clip.source_in_frame / fps
    duration_seconds = clip.duration_frames / fps
    filter_graph = (
        f"atrim=start={start_seconds:.12f}:duration={duration_seconds:.12f},"
        f"aresample={sample_rate},asetpts=PTS-STARTPTS"
    )
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-af",
        filter_graph,
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    raw, _stderr = _communicate_cancellable(command, cancelled=cancelled)
    decoded = np.frombuffer(raw, dtype="<f4")
    usable = decoded.size - decoded.size % channels
    decoded = decoded[:usable].reshape((-1, channels)).copy()
    expected = _frame_sample(clip.duration_frames, fps, sample_rate)
    if decoded.shape[0] < expected:
        decoded = np.pad(decoded, ((0, expected - decoded.shape[0]), (0, 0)))
    elif decoded.shape[0] > expected:
        decoded = decoded[:expected]
    return np.asarray(decoded, dtype=np.float32)


def mix_studio_audio(
    project: StudioProject,
    artwork_path: str | Path,
    *,
    resource_base: str | Path | None = None,
    sample_rate: int = AUDIO_EXPORT_SAMPLE_RATE,
    channels: int = AUDIO_EXPORT_CHANNELS,
    cancelled: Event | Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> StudioAudioMixResult:
    """Decode and mix active audio clips on the exact Studio frame clock."""

    validated = project.validate()
    fps = validated.settings.fps
    if sample_rate <= 0 or channels not in {1, 2}:
        raise ValueError("Le mix audio exige une fréquence positive et un ou deux canaux")
    if sample_rate % fps:
        raise ValueError("La fréquence audio doit contenir un nombre entier d’échantillons par frame")
    total_samples = _frame_sample(
        validated.settings.duration_frames,
        fps,
        sample_rate,
    )
    output = np.zeros((total_samples, channels), dtype=np.float32)
    gain_budget = np.zeros(validated.settings.duration_frames, dtype=np.float32)
    assets = {item.asset_id: item for item in validated.assets}
    mix_settings = AudioMixSettings.from_project(validated)
    active: list[tuple[Track, Clip, MediaAsset, Path]] = []
    for track in validated.tracks:
        if track.kind != TrackKind.AUDIO or track.muted:
            continue
        for clip in track.clips:
            if not clip.enabled or clip.asset_id is None:
                continue
            asset = assets.get(clip.asset_id)
            if asset is None:
                raise KeyError(f"Asset audio introuvable : {clip.asset_id}")
            if asset.kind != AssetKind.AUDIO:
                raise ValueError(f"L’asset {clip.asset_id} n’est pas un média audio")
            active.append(
                (
                    track,
                    clip,
                    asset,
                    _resolve_audio_path(asset, resource_base, artwork_path),
                )
            )
    total_clips = len(active)
    if progress is not None:
        progress(0, total_clips)
    samples_per_frame = sample_rate // fps
    for clip_index, (track, clip, _asset, path) in enumerate(active, start=1):
        if _cancelled(cancelled):
            raise RenderCancelled("Export audio Studio annulé")
        decoded = _decode_clip(
            path,
            clip,
            fps=fps,
            sample_rate=sample_rate,
            channels=channels,
            cancelled=cancelled,
        )
        clip_settings = AudioClipSettings.from_clip(clip)
        track_settings = mix_settings.track(track.track_id)
        base_gain = db_to_linear(clip_settings.gain_db + track_settings.gain_db)
        for local_frame in range(clip.duration_frames):
            project_frame = clip.start_frame + local_frame
            if project_frame >= validated.settings.duration_frames:
                break
            gain = base_gain * audio_envelope_gain(
                clip_settings,
                local_frame,
                clip.duration_frames,
            )
            destination_start = project_frame * samples_per_frame
            destination_end = destination_start + samples_per_frame
            source_start = local_frame * samples_per_frame
            source_end = source_start + samples_per_frame
            output[destination_start:destination_end] += decoded[source_start:source_end] * gain
            gain_budget[project_frame] += gain
        if progress is not None:
            progress(clip_index, total_clips)
    ceiling = db_to_linear(mix_settings.limiter_ceiling_db)
    for project_frame, summed_gain in enumerate(gain_budget):
        if summed_gain <= 0.0:
            continue
        master = min(1.0, ceiling / float(summed_gain))
        if master < 1.0:
            start = project_frame * samples_per_frame
            output[start:start + samples_per_frame] *= master
    np.clip(output, -ceiling, ceiling, out=output)
    if _cancelled(cancelled):
        raise RenderCancelled("Export audio Studio annulé")
    output.setflags(write=False)
    peak = float(np.max(np.abs(output))) if output.size else 0.0
    return StudioAudioMixResult(output, sample_rate, channels, total_clips, peak)


def write_pcm_wav(mix: StudioAudioMixResult, destination: str | Path) -> Path:
    path = Path(destination)
    pcm = np.round(np.asarray(mix.samples) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(mix.channels)
        output.setsampwidth(2)
        output.setframerate(mix.sample_rate)
        output.writeframes(pcm.tobytes())
    return path


def mux_studio_audio(
    video_path: str | Path,
    audio_path: str | Path,
    destination: str | Path,
    *,
    duration_seconds: float,
    cancelled: Event | Callable[[], bool] | None = None,
) -> Path:
    video = Path(video_path)
    audio = Path(audio_path)
    output = Path(destination)
    suffix = output.suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm"}:
        raise ValueError("Le mux audio Studio exige une destination MP4, MOV ou WebM")
    audio_codec = "libopus" if suffix == ".webm" else "aac"
    bitrate = "192k" if suffix == ".webm" else "256k"
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        audio_codec,
        "-b:a",
        bitrate,
        "-t",
        f"{duration_seconds:.12f}",
    ]
    if suffix in {".mp4", ".mov"}:
        command.extend(["-movflags", "+faststart"])
    command.append(str(output))
    _communicate_cancellable(command, cancelled=cancelled)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("FFmpeg n’a pas produit le fichier muxé attendu")
    return output

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Callable

from uuid import uuid4
import numpy as np

from ..core.video import RenderCancelled, VideoFrameEncoder
from .audio_export import (
    mix_studio_audio,
    mux_studio_audio,
    write_pcm_wav,
)
from .model import AudioExportMode, StudioProject
from .render_session import StudioRenderSession
from .semantic import CapabilityRenderer


@dataclass(frozen=True, slots=True)
class StudioExportResult:
    path: Path
    frame_count: int
    width: int
    height: int
    fps: int
    first_frame_digest: str
    last_frame_digest: str
    audio_mode: AudioExportMode = AudioExportMode.REFERENCE
    audio_sample_count: int = 0


def frame_digest(frame: np.ndarray) -> str:
    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
        raise TypeError("Le digest d’export attend une frame RGB uint8")
    return sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def export_studio_video(
    project: StudioProject,
    artwork_path: str | Path,
    destination: str | Path,
    *,
    resource_base: str | Path | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    extra_renderers: tuple[CapabilityRenderer, ...] = (),
) -> StudioExportResult:
    """Render and atomically encode every Studio frame through the preview pipeline."""

    validated = project.validate()
    output = Path(destination)
    expected_suffix = f".{validated.export.container}"
    if output.suffix.lower() != expected_suffix:
        raise ValueError(
            f"Le projet demande {expected_suffix}, pas {output.suffix or 'sans extension'}"
        )
    total = validated.settings.duration_frames
    if should_cancel is not None and should_cancel():
        raise RenderCancelled("Export Studio annulé")
    encoder: VideoFrameEncoder | None = None
    first_digest = ""
    last_digest = ""
    with StudioRenderSession(
        validated,
        artwork_path,
        output_width=output_width,
        output_height=output_height,
        extra_renderers=extra_renderers,
        resource_base=resource_base,
    ) as session:
        encoder = VideoFrameEncoder(
            output,
            session.width,
            session.height,
            session.fps,
            crf=validated.export.crf,
            quality=validated.export.quality,
            total_frames=total,
        )
        try:
            encoder.open()
            if progress is not None:
                progress(0, total)
            for frame_index in range(total):
                if should_cancel is not None and should_cancel():
                    raise RenderCancelled("Export Studio annulé")
                frame = session.frame_at(frame_index)
                digest = frame_digest(frame)
                if frame_index == 0:
                    first_digest = digest
                last_digest = digest
                encoder.write(frame)
                if progress is not None:
                    progress(frame_index + 1, total)
            if should_cancel is not None and should_cancel():
                raise RenderCancelled("Export Studio annulé")
            path = encoder.finish()
        except BaseException:
            encoder.abort()
            raise
    return StudioExportResult(
        path.resolve(strict=True),
        total,
        encoder.width,
        encoder.height,
        validated.settings.fps,
        first_digest,
        last_digest,
    )


def export_studio_project(
    project: StudioProject,
    artwork_path: str | Path,
    destination: str | Path,
    *,
    resource_base: str | Path | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    phase: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    extra_renderers: tuple[CapabilityRenderer, ...] = (),
) -> StudioExportResult:
    """Export a Studio project with its explicit reference/embedded audio policy."""

    validated = project.validate()
    output = Path(destination)
    expected_suffix = f".{validated.export.container}"
    if output.suffix.lower() != expected_suffix:
        raise ValueError(
            f"Le projet demande {expected_suffix}, pas {output.suffix or 'sans extension'}"
        )
    if validated.export.audio_mode == AudioExportMode.REFERENCE:
        if phase is not None:
            phase("video")
        result = export_studio_video(
            validated,
            artwork_path,
            output,
            resource_base=resource_base,
            output_width=output_width,
            output_height=output_height,
            progress=progress,
            should_cancel=should_cancel,
            extra_renderers=extra_renderers,
        )
        if phase is not None:
            phase("complete")
        return result

    token = uuid4().hex
    video_stage = output.with_name(f".{output.stem}.{token}.video{expected_suffix}")
    video_partial = video_stage.with_name(
        f"{video_stage.stem}.part{expected_suffix}"
    )
    audio_stage = output.with_name(f".{output.stem}.{token}.audio.wav")
    mux_stage = output.with_name(f".{output.stem}.{token}.mux{expected_suffix}")
    stages = (video_stage, video_partial, audio_stage, mux_stage)
    try:
        if phase is not None:
            phase("video")
        video_result = export_studio_video(
            validated,
            artwork_path,
            video_stage,
            resource_base=resource_base,
            output_width=output_width,
            output_height=output_height,
            progress=progress,
            should_cancel=should_cancel,
            extra_renderers=extra_renderers,
        )
        if should_cancel is not None and should_cancel():
            raise RenderCancelled("Export Studio annulé")
        if phase is not None:
            phase("audio")
        audio_mix = mix_studio_audio(
            validated,
            artwork_path,
            resource_base=resource_base,
            cancelled=should_cancel,
        )
        write_pcm_wav(audio_mix, audio_stage)
        if should_cancel is not None and should_cancel():
            raise RenderCancelled("Export Studio annulé")
        if phase is not None:
            phase("mux")
        mux_studio_audio(
            video_stage,
            audio_stage,
            mux_stage,
            duration_seconds=(
                validated.settings.duration_frames / validated.settings.fps
            ),
            cancelled=should_cancel,
        )
        if should_cancel is not None and should_cancel():
            raise RenderCancelled("Export Studio annulé")
        for stage in stages[:-1]:
            stage.unlink(missing_ok=True)
        mux_stage.replace(output)
        if phase is not None:
            phase("complete")
        return replace(
            video_result,
            path=output.resolve(strict=True),
            audio_mode=AudioExportMode.EMBEDDED,
            audio_sample_count=audio_mix.sample_count,
        )
    finally:
        for stage in stages:
            stage.unlink(missing_ok=True)

from __future__ import annotations

from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import numpy as np

from .renderer import ArtworkRenderer


SUPPORTED_OUTPUTS = {".mp4", ".mov", ".webm"}


class RenderCancelled(RuntimeError):
    """Raised when a caller requests a clean cancellation."""


def encode_video(
    renderer: ArtworkRenderer,
    output_path: str | Path,
    progress: Callable[[int, int], None] | None = None,
    frame_callback: Callable[[np.ndarray, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    destination = Path(output_path)
    suffix = destination.suffix.lower()
    if suffix not in SUPPORTED_OUTPUTS:
        supported = ", ".join(sorted(SUPPORTED_OUTPUTS))
        raise ValueError(f"Format de sortie non pris en charge ({suffix or 'sans extension'}). Utilisez {supported}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}.part{suffix}")
    if temporary.exists():
        temporary.unlink()

    codec = "libvpx-vp9" if suffix == ".webm" else "libx264"
    output_params = ["-crf", str(renderer.config.crf)]
    if suffix in {".mp4", ".mov"}:
        output_params += ["-preset", "medium", "-movflags", "+faststart"]
    else:
        output_params += ["-b:v", "0"]

    writer = imageio_ffmpeg.write_frames(
        str(temporary),
        (renderer.width, renderer.height),
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        fps=renderer.config.fps,
        codec=codec,
        macro_block_size=2,
        ffmpeg_log_level="warning",
        output_params=output_params,
    )
    total = renderer.frame_count
    try:
        writer.send(None)
        for index, frame in enumerate(renderer.frames(), start=1):
            if should_cancel and should_cancel():
                raise RenderCancelled("Rendu annulé")
            writer.send(frame)
            if frame_callback:
                frame_callback(frame, index, total)
            if progress:
                progress(index, total)
        writer.close()
        temporary.replace(destination)
    except Exception:
        try:
            writer.close()
        finally:
            if temporary.exists():
                temporary.unlink()
        raise
    return destination

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import imageio_ffmpeg
import numpy as np

from .frame_source import FrameSource


SUPPORTED_OUTPUTS = {".mp4", ".mov", ".webm"}


logger = logging.getLogger(__name__)


class RenderCancelled(RuntimeError):
    """Raised when a caller requests a clean cancellation."""


def _validate_destination(destination: Path) -> str:
    suffix = destination.suffix.lower()
    if suffix not in SUPPORTED_OUTPUTS:
        logger.error("Format vidéo non pris en charge : %s", suffix or "sans extension")
        supported = ", ".join(sorted(SUPPORTED_OUTPUTS))
        raise ValueError(
            f"Format de sortie non pris en charge ({suffix or 'sans extension'}). "
            f"Utilisez {supported}."
        )
    if not destination.parent.exists():
        raise FileNotFoundError(
            f"Dossier de destination introuvable : {destination.parent}"
        )
    if not destination.parent.is_dir():
        raise NotADirectoryError(
            f"La destination n’est pas un dossier : {destination.parent}"
        )
    return suffix


def _encoding_profile(suffix: str, crf: int, quality: str) -> tuple[str, list[str]]:
    codec = "libvpx-vp9" if suffix == ".webm" else "libx264"
    output_params = ["-crf", str(crf)]
    if suffix in {".mp4", ".mov"}:
        preset = "slow" if quality == "studio" else "medium"
        output_params += [
            "-preset",
            preset,
            "-tune",
            "animation",
            "-movflags",
            "+faststart",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
        ]
    else:
        output_params += ["-b:v", "0"]
    return codec, output_params


class VideoFrameEncoder:
    """Incremental, recoverable FFmpeg encoder for externally rendered frames."""

    def __init__(
        self,
        output_path: str | Path,
        width: int,
        height: int,
        fps: int,
        *,
        crf: int = 16,
        quality: str = "studio",
        total_frames: int | None = None,
    ):
        self.destination = Path(output_path)
        self.suffix = _validate_destination(self.destination)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.crf = int(crf)
        self.quality = quality
        self.total_frames = total_frames
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("Taille et fréquence vidéo doivent être positives")
        if self.width % 2 or self.height % 2:
            raise ValueError("Les dimensions vidéo doivent être paires")
        if not 0 <= self.crf <= 51:
            raise ValueError("Le CRF doit être compris entre 0 et 51")
        if quality not in {"fast", "studio"}:
            raise ValueError("Profil vidéo inconnu")
        self.temporary = self.destination.with_name(
            f"{self.destination.stem}.part{self.suffix}"
        )
        self._writer: Any | None = None
        self._written = 0

    @property
    def written_frames(self) -> int:
        return self._written

    def open(self) -> None:
        if self._writer is not None:
            return
        if self.temporary.exists():
            self.temporary.unlink()
        codec, output_params = _encoding_profile(
            self.suffix, self.crf, self.quality
        )
        logger.info(
            "Encodeur ouvert : fichier=%s, codec=%s, taille=%dx%d, fps=%d, images=%s",
            self.destination.resolve(),
            codec,
            self.width,
            self.height,
            self.fps,
            self.total_frames if self.total_frames is not None else "flux",
        )
        writer = imageio_ffmpeg.write_frames(
            str(self.temporary),
            (self.width, self.height),
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            fps=self.fps,
            codec=codec,
            macro_block_size=2,
            ffmpeg_log_level="warning",
            output_params=output_params,
        )
        writer.send(None)
        self._writer = writer

    def write(self, frame: np.ndarray) -> None:
        if self._writer is None:
            self.open()
        array = np.asarray(frame)
        expected = (self.height, self.width, 3)
        if array.shape != expected:
            raise ValueError(
                f"Image vidéo de forme {array.shape}, attendu {expected}"
            )
        if array.dtype != np.uint8:
            raise TypeError("Les images vidéo doivent être en uint8 RGB")
        assert self._writer is not None
        self._writer.send(np.ascontiguousarray(array))
        self._written += 1

    def finish(self) -> Path:
        if self._writer is None or self._written == 0:
            self.abort()
            raise ValueError("Impossible de finaliser une vidéo sans image")
        writer = self._writer
        self._writer = None
        try:
            writer.close()
            self.temporary.replace(self.destination)
        except Exception:
            self.temporary.unlink(missing_ok=True)
            raise
        logger.info(
            "Encodage terminé : %s (%d images, %d octets)",
            self.destination.resolve(),
            self._written,
            self.destination.stat().st_size,
        )
        return self.destination

    def abort(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is not None:
            try:
                writer.close()
            except Exception:
                logger.debug("Fermeture de l’encodeur partiel impossible", exc_info=True)
        self.temporary.unlink(missing_ok=True)
        logger.info("Encodage partiel nettoyé : %s", self.destination.resolve())


def encode_video(
    renderer: FrameSource,
    output_path: str | Path,
    progress: Callable[[int, int], None] | None = None,
    frame_callback: Callable[[np.ndarray, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    destination = Path(output_path)
    total = renderer.frame_count
    encoder = VideoFrameEncoder(
        destination,
        renderer.width,
        renderer.height,
        renderer.config.fps,
        crf=renderer.config.crf,
        quality=renderer.config.quality,
        total_frames=total,
    )
    logger.info(
        "Encodage démarré : fichier=%s, taille=%dx%d, images=%d, fps=%d",
        destination.resolve(),
        renderer.width,
        renderer.height,
        total,
        renderer.config.fps,
    )
    try:
        encoder.open()
        for index, frame in enumerate(renderer.frames(), start=1):
            if should_cancel and should_cancel():
                raise RenderCancelled("Rendu annulé")
            encoder.write(frame)
            if frame_callback:
                frame_callback(frame, index, total)
            if progress:
                progress(index, total)
        return encoder.finish()
    except RenderCancelled:
        logger.warning("Encodage annulé : %s", destination.resolve())
        encoder.abort()
        raise
    except Exception:
        logger.exception("Échec de l’encodage : %s", destination.resolve())
        encoder.abort()
        raise

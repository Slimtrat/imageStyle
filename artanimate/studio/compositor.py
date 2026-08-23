from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from PIL import Image

from .camera import render_camera_frame, resolve_camera_pose
from .model import Clip, FitMode, StudioProject, TrackKind
from .sources import TimedFrameSource, validate_frame_index, validate_timed_frame


class MissingClipSourceError(KeyError):
    """Raised when an active visual clip has no registered frame source."""


def _resize_rgb(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    if frame.shape[1] == width and frame.shape[0] == height:
        return np.ascontiguousarray(frame)
    image = Image.fromarray(frame, mode="RGB")
    return np.asarray(
        image.resize((width, height), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )


def fit_frame(
    frame: np.ndarray,
    output_width: int,
    output_height: int,
    mode: FitMode,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit an RGB frame and return canvas-sized RGB plus a normalized alpha mask."""

    source_height, source_width = frame.shape[:2]
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Une source Studio ne peut pas avoir de dimensions nulles")
    canvas = np.zeros((output_height, output_width, 3), dtype=np.uint8)
    alpha = np.zeros((output_height, output_width), dtype=np.float32)

    if mode == FitMode.STRETCH:
        canvas[:] = _resize_rgb(frame, output_width, output_height)
        alpha.fill(1.0)
        return canvas, alpha

    scale_x = output_width / source_width
    scale_y = output_height / source_height
    scale = min(scale_x, scale_y) if mode == FitMode.CONTAIN else max(scale_x, scale_y)
    scaled_width = max(1, int(round(source_width * scale)))
    scaled_height = max(1, int(round(source_height * scale)))
    resized = _resize_rgb(frame, scaled_width, scaled_height)

    if mode == FitMode.CONTAIN:
        left = (output_width - scaled_width) // 2
        top = (output_height - scaled_height) // 2
        right = left + scaled_width
        bottom = top + scaled_height
        canvas[top:bottom, left:right] = resized
        alpha[top:bottom, left:right] = 1.0
        return canvas, alpha

    left = max(0, (scaled_width - output_width) // 2)
    top = max(0, (scaled_height - output_height) // 2)
    cropped = resized[top : top + output_height, left : left + output_width]
    if cropped.shape[:2] != (output_height, output_width):
        raise ValueError("Le crop Studio n’a pas produit les dimensions du projet")
    canvas[:] = cropped
    alpha.fill(1.0)
    return canvas, alpha


def alpha_composite_rgb(
    background: np.ndarray,
    foreground: np.ndarray,
    alpha: np.ndarray,
    *,
    opacity: float = 1.0,
) -> np.ndarray:
    if background.shape != foreground.shape:
        raise ValueError("Les deux images composées doivent avoir les mêmes dimensions")
    if alpha.shape != background.shape[:2]:
        raise ValueError("Le masque alpha doit correspondre aux dimensions du canvas")
    effective = np.clip(alpha.astype(np.float32) * float(opacity), 0.0, 1.0)[..., None]
    mixed = foreground.astype(np.float32) * effective + background.astype(np.float32) * (
        1.0 - effective
    )
    return np.rint(np.clip(mixed, 0.0, 255.0)).astype(np.uint8)


class StudioCompositor:
    """Deterministic, UI-independent V3 Studio frame compositor."""

    def __init__(
        self,
        project: StudioProject,
        sources: Mapping[str, TimedFrameSource],
        *,
        output_width: int | None = None,
        output_height: int | None = None,
    ):
        self.project = project.validate()
        self.sources = dict(sources)
        self.fps = self.project.settings.fps
        self.frame_count = self.project.settings.duration_frames
        self.width = output_width or self.project.settings.width
        self.height = output_height or self.project.settings.height
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Les dimensions du compositeur Studio doivent être positives")
        if (
            self.width * self.project.settings.height
            != self.height * self.project.settings.width
        ):
            raise ValueError("Un proxy Studio doit conserver le ratio du projet")

    def _source_for(self, clip: Clip) -> TimedFrameSource:
        try:
            source = self.sources[clip.clip_id]
        except KeyError as exc:
            raise MissingClipSourceError(
                f"Aucune source de frame enregistrée pour le clip {clip.clip_id}"
            ) from exc
        if source.fps != self.fps:
            raise ValueError(
                f"La source {clip.clip_id} utilise {source.fps} FPS au lieu de {self.fps}"
            )
        return source

    def _clip_frame(self, clip: Clip, project_frame: int) -> tuple[np.ndarray, np.ndarray]:
        source = self._source_for(clip)
        local_frame = clip.source_in_frame + project_frame - clip.start_frame
        validate_frame_index(local_frame, source.frame_count)
        raw = validate_timed_frame(source, source.frame_at(local_frame))
        if clip.camera is not None:
            camera_frame = project_frame - clip.start_frame
            pose = resolve_camera_pose(clip.camera, camera_frame)
            rendered = render_camera_frame(
                raw,
                self.width,
                self.height,
                pose,
                background=self.project.settings.background,
            )
            return rendered, np.ones((self.height, self.width), dtype=np.float32)
        return fit_frame(raw, self.width, self.height, clip.fit)

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        background = np.empty((self.height, self.width, 3), dtype=np.uint8)
        background[:] = self.project.settings.background

        # Track order is bottom-to-top. Multiple active clips on a track are
        # composited in tuple order, which keeps overlap behavior deterministic.
        for track in self.project.tracks:
            if track.kind == TrackKind.AUDIO or track.hidden or track.muted:
                continue
            for clip in track.clips:
                if (
                    not clip.enabled
                    or frame_index < clip.start_frame
                    or frame_index >= clip.end_frame
                ):
                    continue
                foreground, alpha = self._clip_frame(clip, frame_index)
                background = alpha_composite_rgb(
                    background,
                    foreground,
                    alpha,
                    opacity=clip.opacity,
                )
        return background


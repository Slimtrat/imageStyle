from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from PIL import Image

from .camera import render_camera_frame, resolve_camera_pose
from .effect_2d import Effect2DClipSettings, settings_for_effect_clip
from .model import Clip, ClipKind, FitMode, StudioProject, TrackKind
from .manual_match import (
    ManualMatchSettings,
    incoming_manual_match,
    warp_matched_frame,
)
from .sources import TimedFrameSource, validate_frame_index, validate_timed_frame
from .transitions import (
    active_visual_transition,
    transition_progress,
    transition_clip_pair,
    validate_project_transitions,
)
from .transition_strategies import compose_transition_frames


class MissingClipSourceError(KeyError):
    """Raised when an active visual clip has no registered frame source."""


class MissingEffectTargetError(KeyError):
    """Raised when an artwork-relative effect has no active artwork target."""


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


def blend_rgb_frames(
    from_frame: np.ndarray,
    to_frame: np.ndarray,
    to_weight: float,
) -> np.ndarray:
    if (
        from_frame.shape != to_frame.shape
        or from_frame.dtype != np.uint8
        or to_frame.dtype != np.uint8
    ):
        raise ValueError("Les deux états du fondu doivent être des frames RGB uint8 identiques")
    weight = min(1.0, max(0.0, float(to_weight)))
    mixed = (
        from_frame.astype(np.float32) * (1.0 - weight)
        + to_frame.astype(np.float32) * weight
    )
    return np.rint(np.clip(mixed, 0.0, 255.0)).astype(np.uint8)


def composite_artwork_effect(
    background: np.ndarray,
    effected: np.ndarray,
    reference: np.ndarray,
    alpha: np.ndarray,
    *,
    intensity: float,
    opacity: float,
) -> np.ndarray:
    """Apply an artwork-relative RGB delta while preserving an exact off state."""

    if background.shape != effected.shape or effected.shape != reference.shape:
        raise ValueError("Le calque d’effet et sa référence doivent partager le canvas")
    if alpha.shape != background.shape[:2]:
        raise ValueError("Le masque du calque d’effet doit correspondre au canvas")
    strength = np.clip(
        alpha.astype(np.float32) * float(intensity) * float(opacity),
        0.0,
        1.0,
    )[..., None]
    delta = effected.astype(np.float32) - reference.astype(np.float32)
    composed = background.astype(np.float32) + delta * strength
    return np.rint(np.clip(composed, 0.0, 255.0)).astype(np.uint8)


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
        validate_project_transitions(self.project, validate_sources=True)
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
        self.effect_settings: dict[str, Effect2DClipSettings] = {
            clip.clip_id: settings_for_effect_clip(clip)
            for track in self.project.tracks
            for clip in track.clips
            if clip.kind == ClipKind.EFFECT_2D
        }
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

    def _transform_frame(
        self,
        raw: np.ndarray,
        clip: Clip,
        project_frame: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        match = incoming_manual_match(self.project, clip.clip_id)
        if match is not None:
            return warp_matched_frame(
                raw,
                self.width,
                self.height,
                ManualMatchSettings.from_transition(match),
            )
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

    def _clip_frame(
        self,
        clip: Clip,
        project_frame: int,
        *,
        virtual_handle: bool = False,
    ) -> tuple[np.ndarray, np.ndarray]:
        source = self._source_for(clip)
        local_frame = clip.source_in_frame + project_frame - clip.start_frame
        if virtual_handle and clip.kind in {ClipKind.STILL, ClipKind.ARTWORK_2D}:
            local_frame = min(source.frame_count - 1, max(0, local_frame))
        validate_frame_index(local_frame, source.frame_count)
        raw = validate_timed_frame(source, source.frame_at(local_frame))
        return self._transform_frame(raw, clip, project_frame)

    def _composite_clip(
        self,
        background: np.ndarray,
        clip: Clip,
        frame: int,
        *,
        virtual_handle: bool = False,
    ) -> np.ndarray:
        foreground, alpha = self._clip_frame(clip, frame, virtual_handle=virtual_handle)
        return alpha_composite_rgb(background, foreground, alpha, opacity=clip.opacity)

    def _effect_target(self, clip: Clip, project_frame: int) -> Clip:
        settings = self.effect_settings[clip.clip_id]
        target = next(
            (
                candidate
                for track in self.project.tracks
                for candidate in track.clips
                if candidate.clip_id == settings.target_clip_id
                and candidate.kind in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}
                and candidate.enabled
                and candidate.start_frame <= project_frame < candidate.end_frame
            ),
            None,
        )
        if target is None:
            raise MissingEffectTargetError(
                f"Le calque {clip.clip_id} ne trouve pas son plan d’œuvre actif "
                f"{settings.target_clip_id}"
            )
        return target

    def _effect_frame(
        self,
        clip: Clip,
        project_frame: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        source = self._source_for(clip)
        local_frame = clip.source_in_frame + project_frame - clip.start_frame
        validate_frame_index(local_frame, source.frame_count)
        effected = validate_timed_frame(source, source.frame_at(local_frame))
        reference = np.asarray(getattr(source, "reference_frame", None))
        if reference.shape != (source.height, source.width, 3) or reference.dtype != np.uint8:
            raise TypeError(
                f"La source du calque {clip.clip_id} doit exposer sa référence RGB uint8"
            )
        target = self._effect_target(clip, project_frame)
        effected_canvas, alpha = self._transform_frame(effected, target, project_frame)
        reference_canvas, reference_alpha = self._transform_frame(
            reference,
            target,
            project_frame,
        )
        if not np.array_equal(alpha, reference_alpha):
            raise ValueError("L’effet 2D et sa référence ne partagent pas le même masque")
        return (
            effected_canvas,
            reference_canvas,
            alpha,
            self.effect_settings[clip.clip_id].intensity,
        )

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        background = np.empty((self.height, self.width, 3), dtype=np.uint8)
        background[:] = self.project.settings.background

        # Track order is bottom-to-top. Multiple active clips on a track are
        # composited in tuple order, which keeps overlap behavior deterministic.
        for track in self.project.tracks:
            if track.kind == TrackKind.AUDIO or track.hidden or track.muted:
                continue
            transition = active_visual_transition(
                self.project,
                track.track_id,
                frame_index,
            )
            transitioned_clip_ids: set[str] = set()
            if transition is not None:
                pair = transition_clip_pair(self.project, transition)
                if pair.from_clip.enabled and pair.to_clip.enabled:
                    from_state = self._composite_clip(
                        background,
                        pair.from_clip,
                        frame_index,
                        virtual_handle=True,
                    )
                    to_state = self._composite_clip(
                        background,
                        pair.to_clip,
                        frame_index,
                        virtual_handle=True,
                    )
                    background = compose_transition_frames(
                        transition,
                        from_state,
                        to_state,
                        transition_progress(transition, frame_index),
                    )
                    transitioned_clip_ids = {
                        pair.from_clip.clip_id,
                        pair.to_clip.clip_id,
                    }
            for clip in track.clips:
                if clip.clip_id in transitioned_clip_ids:
                    continue
                if (
                    not clip.enabled
                    or frame_index < clip.start_frame
                    or frame_index >= clip.end_frame
                ):
                    continue
                if clip.kind == ClipKind.EFFECT_2D:
                    effected, reference, alpha, intensity = self._effect_frame(
                        clip,
                        frame_index,
                    )
                    background = composite_artwork_effect(
                        background,
                        effected,
                        reference,
                        alpha,
                        intensity=intensity,
                        opacity=clip.opacity,
                    )
                    continue
                background = self._composite_clip(background, clip, frame_index)
        return background

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from .image_io import load_normalized_rgb
from .model import AssetKind, Clip, ClipKind, FitMode, MediaAsset, StudioProject, Track, TrackKind
from .sources import validate_frame_index


@dataclass(frozen=True, slots=True)
class StillClipSettings:
    """Non-destructive source-space framing for one still-image clip."""

    crop_x: float = 0.0
    crop_y: float = 0.0
    crop_width: float = 1.0
    crop_height: float = 1.0
    rotation_degrees: float = 0.0

    def validate(self) -> StillClipSettings:
        values = {
            "crop_x": self.crop_x,
            "crop_y": self.crop_y,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "rotation_degrees": self.rotation_degrees,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"still.{name} doit être numérique")
            if not math.isfinite(float(value)):
                raise ValueError(f"still.{name} doit être fini")
        if self.crop_x < 0 or self.crop_y < 0:
            raise ValueError("Le recadrage ne peut pas commencer hors de l’image")
        if self.crop_width <= 0 or self.crop_height <= 0:
            raise ValueError("Le recadrage doit conserver une surface positive")
        epsilon = 1e-9
        if self.crop_x + self.crop_width > 1.0 + epsilon:
            raise ValueError("Le recadrage dépasse la largeur de l’image")
        if self.crop_y + self.crop_height > 1.0 + epsilon:
            raise ValueError("Le recadrage dépasse la hauteur de l’image")
        if abs(float(self.rotation_degrees)) > 3600.0:
            raise ValueError("La rotation doit rester comprise entre -3600° et 3600°")
        return self

    def to_dict(self) -> dict[str, float]:
        self.validate()
        return {
            "crop_x": float(self.crop_x),
            "crop_y": float(self.crop_y),
            "crop_width": float(self.crop_width),
            "crop_height": float(self.crop_height),
            "rotation_degrees": float(self.rotation_degrees),
        }

    @classmethod
    def from_mapping(cls, value: object) -> StillClipSettings:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise TypeError("Les réglages d’image fixe doivent être un objet JSON")
        nested = value.get("still", value)
        if not isinstance(nested, dict):
            raise TypeError("clip.parameters.still doit être un objet JSON")
        allowed = {"crop_x", "crop_y", "crop_width", "crop_height", "rotation_degrees"}
        unknown = set(nested) - allowed
        if unknown:
            raise ValueError("Réglage d’image fixe inconnu : " + ", ".join(sorted(unknown)))
        return cls(
            crop_x=float(nested.get("crop_x", 0.0)),
            crop_y=float(nested.get("crop_y", 0.0)),
            crop_width=float(nested.get("crop_width", 1.0)),
            crop_height=float(nested.get("crop_height", 1.0)),
            rotation_degrees=float(nested.get("rotation_degrees", 0.0)),
        ).validate()

    @classmethod
    def from_clip(cls, clip: Clip) -> StillClipSettings:
        if clip.kind != ClipKind.STILL:
            raise ValueError("Les réglages d’image fixe exigent un clip still")
        return cls.from_mapping(clip.parameters)


class StillImageSource:
    """Addressable immutable still source shared by preview and final export."""

    def __init__(
        self,
        asset_id: str,
        path: str | Path,
        fingerprint: str | None,
        frame: np.ndarray,
        fps: int,
        *,
        diagnostic: bool = False,
        diagnostic_message: str | None = None,
    ) -> None:
        rgb = np.ascontiguousarray(frame, dtype=np.uint8)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("Une source d’image fixe doit être RGB")
        rgb.setflags(write=False)
        self.asset_id = str(asset_id)
        self.path = Path(path)
        self.fingerprint = fingerprint
        self._frame = rgb
        self.width = int(rgb.shape[1])
        self.height = int(rgb.shape[0])
        self.fps = int(fps)
        self.frame_count = 2_147_483_647
        self.diagnostic = bool(diagnostic)
        self.diagnostic_message = diagnostic_message

    @classmethod
    def open(
        cls,
        asset: MediaAsset,
        path: str | Path,
        fps: int,
        settings: StillClipSettings | None = None,
    ) -> StillImageSource:
        frame, _inspection = load_normalized_rgb(path)
        transformed = transform_still_frame(frame, settings or StillClipSettings())
        return cls(asset.asset_id, path, asset.fingerprint, transformed, fps)

    @classmethod
    def missing(
        cls,
        asset: MediaAsset,
        path: str | Path,
        fps: int,
        width: int,
        height: int,
        message: str,
    ) -> StillImageSource:
        frame = diagnostic_media_frame(width, height)
        return cls(
            asset.asset_id,
            path,
            asset.fingerprint,
            frame,
            fps,
            diagnostic=True,
            diagnostic_message=message,
        )

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        return self._frame


def transform_still_frame(frame: np.ndarray, settings: StillClipSettings) -> np.ndarray:
    settings.validate()
    height, width = frame.shape[:2]
    left = min(width - 1, max(0, int(math.floor(settings.crop_x * width))))
    top = min(height - 1, max(0, int(math.floor(settings.crop_y * height))))
    right = min(width, max(left + 1, int(math.ceil((settings.crop_x + settings.crop_width) * width))))
    bottom = min(height, max(top + 1, int(math.ceil((settings.crop_y + settings.crop_height) * height))))
    cropped = np.ascontiguousarray(frame[top:bottom, left:right])
    rotation = float(settings.rotation_degrees) % 360.0
    if math.isclose(rotation, 0.0, abs_tol=1e-9):
        result = cropped
    else:
        image = Image.fromarray(cropped)
        result = np.asarray(
            image.rotate(
                -float(settings.rotation_degrees),
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(0, 0, 0),
            ),
            dtype=np.uint8,
        )
    output = np.ascontiguousarray(result, dtype=np.uint8)
    output.setflags(write=False)
    return output


def diagnostic_media_frame(width: int, height: int) -> np.ndarray:
    width = max(64, int(width))
    height = max(64, int(height))
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:] = (42, 18, 24)
    stripe = max(8, min(width, height) // 24)
    yy, xx = np.indices((height, width))
    frame[((xx + yy) // stripe) % 2 == 0] = (62, 24, 31)
    thickness = max(3, min(width, height) // 45)
    diagonal = np.abs(xx * height - yy * width) <= thickness * max(width, height)
    other = np.abs((width - 1 - xx) * height - yy * width) <= thickness * max(width, height)
    frame[diagonal | other] = (239, 91, 91)
    border = max(3, min(width, height) // 80)
    frame[:border] = frame[-border:] = frame[:, :border] = frame[:, -border:] = (255, 126, 126)
    return np.ascontiguousarray(frame)


def _image_asset(project: StudioProject, asset_id: str) -> MediaAsset:
    try:
        asset = next(item for item in project.assets if item.asset_id == asset_id)
    except StopIteration as exc:
        raise KeyError(f"Image locale introuvable : {asset_id}") from exc
    if asset.kind != AssetKind.IMAGE:
        raise ValueError("Un clip d’image fixe exige un asset image")
    return asset


def add_still_clip(
    project: StudioProject,
    asset_id: str,
    *,
    start_frame: int,
    duration_frames: int | None = None,
    track_id: str | None = None,
) -> tuple[StudioProject, Clip]:
    _image_asset(project, asset_id)
    if isinstance(start_frame, bool) or not isinstance(start_frame, int):
        raise TypeError("La frame de départ du plan réel doit être un entier")
    start = start_frame
    if not 0 <= start < project.settings.duration_frames:
        raise ValueError("Le plan réel doit commencer dans la durée du projet")
    remaining = project.settings.duration_frames - start
    if duration_frames is not None and (
        isinstance(duration_frames, bool) or not isinstance(duration_frames, int)
    ):
        raise TypeError("La durée du plan réel doit être un entier de frames")
    duration = (
        remaining
        if duration_frames is None
        else min(duration_frames, remaining)
    )
    if duration <= 0:
        raise ValueError("La durée du plan réel doit être positive")
    tracks = list(project.tracks)
    if track_id is None:
        track_index = next(
            (
                index
                for index, track in enumerate(tracks)
                if track.kind == TrackKind.VIDEO and not track.locked
            ),
            None,
        )
    else:
        track_index = next((index for index, track in enumerate(tracks) if track.track_id == track_id), None)
        if track_index is None:
            raise KeyError(f"Piste vidéo introuvable : {track_id}")
        if tracks[track_index].kind != TrackKind.VIDEO:
            raise ValueError("Une image fixe exige une piste vidéo")
        if tracks[track_index].locked:
            raise PermissionError("La piste vidéo ciblée est verrouillée")
    if track_index is None:
        tracks.append(Track(f"video-{uuid4().hex[:12]}", TrackKind.VIDEO, "Réel"))
        track_index = len(tracks) - 1
    clip = Clip(
        f"still-{uuid4().hex[:12]}",
        ClipKind.STILL,
        start,
        duration,
        asset_id=asset_id,
        fit=FitMode.COVER,
        parameters={"still": StillClipSettings().to_dict()},
    ).validate()
    track = tracks[track_index]
    tracks[track_index] = replace(
        track,
        clips=tuple(sorted((*track.clips, clip), key=lambda item: (item.start_frame, item.clip_id))),
    )
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        item for item_track in updated.tracks for item in item_track.clips if item.clip_id == clip.clip_id
    )
    return updated, effective


def update_still_clip(
    project: StudioProject,
    clip_id: str,
    *,
    duration_frames: int,
    fit: FitMode,
    opacity: float,
    enabled: bool,
    settings: StillClipSettings,
) -> tuple[StudioProject, Clip]:
    location = next(
        (
            (track_index, clip_index, track, clip)
            for track_index, track in enumerate(project.tracks)
            for clip_index, clip in enumerate(track.clips)
            if clip.clip_id == clip_id
        ),
        None,
    )
    if location is None:
        raise KeyError(f"Clip d’image fixe introuvable : {clip_id}")
    track_index, clip_index, track, clip = location
    if track.locked:
        raise PermissionError("La piste du plan réel est verrouillée")
    if clip.kind != ClipKind.STILL:
        raise ValueError("Les réglages exigent un clip d’image fixe")
    _image_asset(project, clip.asset_id or "")
    if isinstance(duration_frames, bool) or not isinstance(duration_frames, int):
        raise TypeError("La durée du plan réel doit être un entier de frames")
    duration = duration_frames
    if duration <= 0 or clip.start_frame + duration > project.settings.duration_frames:
        raise ValueError("La durée du plan réel dépasse le projet")
    if not isinstance(fit, FitMode):
        raise TypeError("Le cadrage doit être un FitMode")
    if isinstance(opacity, bool) or not isinstance(opacity, int | float):
        raise TypeError("L’opacité du plan réel doit être numérique")
    if not math.isfinite(float(opacity)) or not 0.0 <= float(opacity) <= 1.0:
        raise ValueError("L’opacité du plan réel doit être comprise entre 0 et 1")
    if not isinstance(enabled, bool):
        raise TypeError("La visibilité du plan réel doit être un booléen")
    if not isinstance(settings, StillClipSettings):
        raise TypeError("Les réglages du plan réel doivent être des StillClipSettings")
    settings.validate()
    updated_clip = replace(
        clip,
        duration_frames=duration,
        fit=fit,
        opacity=float(opacity),
        enabled=enabled,
        parameters={"still": settings.to_dict()},
    ).validate()
    clips = list(track.clips)
    clips[clip_index] = updated_clip
    tracks = list(project.tracks)
    tracks[track_index] = replace(track, clips=tuple(clips))
    updated = replace(project, tracks=tuple(tracks)).validate()
    effective = next(
        item for item_track in updated.tracks for item in item_track.clips if item.clip_id == clip_id
    )
    return updated, effective

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Iterable

import numpy as np
from PIL import Image

from .model import (
    ClipKind,
    Easing,
    StudioProject,
    Transition,
    TransitionKind,
)
from .video import video_source_frame_count


@dataclass(frozen=True, slots=True)
class MatchPoint:
    x: float = 0.0
    y: float = 0.0

    def validate(
        self,
        *,
        where: str,
        minimum: float = -2.0,
        maximum: float = 2.0,
    ) -> MatchPoint:
        for name, value in (("x", self.x), ("y", self.y)):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"{where}.{name} doit être numérique")
            if not math.isfinite(float(value)):
                raise ValueError(f"{where}.{name} doit être fini")
            if not minimum <= float(value) <= maximum:
                raise ValueError(
                    f"{where}.{name} doit être compris entre {minimum} et {maximum}"
                )
        return self

    def to_dict(self) -> dict[str, float]:
        self.validate(where="match.point")
        return {"x": float(self.x), "y": float(self.y)}

    @classmethod
    def from_dict(cls, values: Any, *, where: str) -> MatchPoint:
        if not isinstance(values, dict):
            raise TypeError(f"{where} doit être un objet JSON")
        unknown = sorted(set(values) - {"x", "y"})
        if unknown:
            raise ValueError(f"Clé(s) inconnue(s) dans {where} : {', '.join(unknown)}")
        return cls(float(values.get("x", 0.0)), float(values.get("y", 0.0)))


@dataclass(frozen=True, slots=True)
class MatchCrop:
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0

    def validate(self) -> MatchCrop:
        values = (self.x, self.y, self.width, self.height)
        if any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for value in values
        ):
            raise TypeError("Le crop du match doit être numérique")
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("Le crop du match doit être fini")
        if self.width <= 0.001 or self.height <= 0.001:
            raise ValueError("Le crop du match doit avoir une surface positive")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Le crop du match doit rester dans la frame réelle")
        return self

    def to_dict(self) -> dict[str, float]:
        self.validate()
        return {
            "x": float(self.x),
            "y": float(self.y),
            "width": float(self.width),
            "height": float(self.height),
        }

    @classmethod
    def from_dict(cls, values: Any) -> MatchCrop:
        if not isinstance(values, dict):
            raise TypeError("match.transform.source_crop doit être un objet JSON")
        unknown = sorted(set(values) - {"x", "y", "width", "height"})
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans match.transform.source_crop : "
                + ", ".join(unknown)
            )
        return cls(
            float(values.get("x", 0.0)),
            float(values.get("y", 0.0)),
            float(values.get("width", 1.0)),
            float(values.get("height", 1.0)),
        ).validate()


_ZERO_CORNERS = (
    MatchPoint(),
    MatchPoint(),
    MatchPoint(),
    MatchPoint(),
)


def _points_from_json(values: Any, *, where: str) -> tuple[MatchPoint, ...]:
    if not isinstance(values, list | tuple) or len(values) != 4:
        raise ValueError(f"{where} doit contenir quatre coins")
    return tuple(
        MatchPoint.from_dict(value, where=f"{where}[{index}]")
        for index, value in enumerate(values)
    )


def _is_convex_quad(points: Iterable[tuple[float, float]]) -> bool:
    values = tuple(points)
    if len(values) != 4:
        return False
    crosses = []
    for index in range(4):
        ax, ay = values[index]
        bx, by = values[(index + 1) % 4]
        cx, cy = values[(index + 2) % 4]
        crosses.append((bx - ax) * (cy - by) - (by - ay) * (cx - bx))
    non_zero = [value for value in crosses if abs(value) > 1e-8]
    return len(non_zero) == 4 and (
        all(value > 0 for value in non_zero)
        or all(value < 0 for value in non_zero)
    )


@dataclass(frozen=True, slots=True)
class ManualMatchTransform:
    source_crop: MatchCrop = MatchCrop()
    source_corner_offsets: tuple[MatchPoint, ...] = _ZERO_CORNERS
    position_x: float = 0.5
    position_y: float = 0.5
    scale: float = 1.0
    rotation_degrees: float = 0.0
    target_corner_offsets: tuple[MatchPoint, ...] = _ZERO_CORNERS

    def source_quad(self) -> tuple[MatchPoint, ...]:
        crop = self.source_crop
        bases = (
            (crop.x, crop.y),
            (crop.x + crop.width, crop.y),
            (crop.x + crop.width, crop.y + crop.height),
            (crop.x, crop.y + crop.height),
        )
        return tuple(
            MatchPoint(
                base_x + offset.x * crop.width,
                base_y + offset.y * crop.height,
            )
            for (base_x, base_y), offset in zip(
                bases,
                self.source_corner_offsets,
                strict=True,
            )
        )

    def target_quad(
        self,
        output_width: int,
        output_height: int,
    ) -> tuple[tuple[float, float], ...]:
        width = max(1, int(output_width)) - 1
        height = max(1, int(output_height)) - 1
        center_x = self.position_x * width
        center_y = self.position_y * height
        radians = math.radians(self.rotation_degrees)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        corners = (
            (-0.5 * width, -0.5 * height),
            (0.5 * width, -0.5 * height),
            (0.5 * width, 0.5 * height),
            (-0.5 * width, 0.5 * height),
        )
        result = []
        for (x, y), offset in zip(corners, self.target_corner_offsets, strict=True):
            scaled_x = x * self.scale
            scaled_y = y * self.scale
            result.append(
                (
                    center_x + scaled_x * cosine - scaled_y * sine + offset.x * width,
                    center_y + scaled_x * sine + scaled_y * cosine + offset.y * height,
                )
            )
        return tuple(result)

    def validate(self) -> ManualMatchTransform:
        self.source_crop.validate()
        if len(self.source_corner_offsets) != 4 or len(self.target_corner_offsets) != 4:
            raise ValueError("Un match manuel doit conserver quatre coins source et cible")
        for index, point in enumerate(self.source_corner_offsets):
            point.validate(
                where=f"match.transform.source_corner_offsets[{index}]",
                minimum=-1.0,
                maximum=1.0,
            )
        source_quad = self.source_quad()
        for index, point in enumerate(source_quad):
            point.validate(
                where=f"match.transform.source_quad[{index}]",
                minimum=0.0,
                maximum=1.0,
            )
        if not _is_convex_quad((point.x, point.y) for point in source_quad):
            raise ValueError("Les quatre coins source du match doivent rester convexes")
        for name, value, minimum, maximum in (
            ("position_x", self.position_x, -1.0, 2.0),
            ("position_y", self.position_y, -1.0, 2.0),
            ("scale", self.scale, 0.05, 20.0),
            ("rotation_degrees", self.rotation_degrees, -3600.0, 3600.0),
        ):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"match.transform.{name} doit être numérique")
            if not math.isfinite(float(value)) or not minimum <= float(value) <= maximum:
                raise ValueError(
                    f"match.transform.{name} doit être compris entre {minimum} et {maximum}"
                )
        for index, point in enumerate(self.target_corner_offsets):
            point.validate(where=f"match.transform.target_corner_offsets[{index}]")
        if not _is_convex_quad(self.target_quad(1000, 1000)):
            raise ValueError("Les quatre coins cible du match doivent rester convexes")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "source_crop": self.source_crop.to_dict(),
            "source_corner_offsets": [
                point.to_dict() for point in self.source_corner_offsets
            ],
            "position_x": float(self.position_x),
            "position_y": float(self.position_y),
            "scale": float(self.scale),
            "rotation_degrees": float(self.rotation_degrees),
            "target_corner_offsets": [
                point.to_dict() for point in self.target_corner_offsets
            ],
        }

    @classmethod
    def from_dict(cls, values: Any) -> ManualMatchTransform:
        if not isinstance(values, dict):
            raise TypeError("match.transform doit être un objet JSON")
        allowed = {
            "source_crop",
            "source_corner_offsets",
            "position_x",
            "position_y",
            "scale",
            "rotation_degrees",
            "target_corner_offsets",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans match.transform : " + ", ".join(unknown)
            )
        return cls(
            source_crop=MatchCrop.from_dict(values.get("source_crop", {})),
            source_corner_offsets=_points_from_json(
                values.get("source_corner_offsets", [point.to_dict() for point in _ZERO_CORNERS]),
                where="match.transform.source_corner_offsets",
            ),
            position_x=float(values.get("position_x", 0.5)),
            position_y=float(values.get("position_y", 0.5)),
            scale=float(values.get("scale", 1.0)),
            rotation_degrees=float(values.get("rotation_degrees", 0.0)),
            target_corner_offsets=_points_from_json(
                values.get("target_corner_offsets", [point.to_dict() for point in _ZERO_CORNERS]),
                where="match.transform.target_corner_offsets",
            ),
        ).validate()


@dataclass(frozen=True, slots=True)
class ManualMatchSettings:
    reference_source_frame: int = 0
    overlay_opacity: float = 0.5
    easing: Easing = Easing.EASE_IN_OUT
    transform: ManualMatchTransform = ManualMatchTransform()

    def validate(self) -> ManualMatchSettings:
        if (
            isinstance(self.reference_source_frame, bool)
            or not isinstance(self.reference_source_frame, int)
            or self.reference_source_frame < 0
        ):
            raise ValueError("La frame de référence réelle doit être un entier positif")
        if (
            isinstance(self.overlay_opacity, bool)
            or not isinstance(self.overlay_opacity, int | float)
            or not math.isfinite(float(self.overlay_opacity))
            or not 0.0 <= float(self.overlay_opacity) <= 1.0
        ):
            raise ValueError("L’opacité d’overlay doit être comprise entre 0 et 1")
        if not isinstance(self.easing, Easing):
            raise TypeError("L’interpolation du match doit être un Easing")
        self.transform.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "reference_source_frame": self.reference_source_frame,
            "overlay_opacity": float(self.overlay_opacity),
            "easing": self.easing.value,
            "transform": self.transform.to_dict(),
        }

    @classmethod
    def from_transition(cls, transition: Transition) -> ManualMatchSettings:
        if transition.kind != TransitionKind.MATCH:
            raise ValueError("Les réglages demandés ne concernent pas un match manuel")
        values = transition.parameters or {}
        if not isinstance(values, dict):
            raise TypeError("Les réglages du match doivent être un objet JSON")
        allowed = {"reference_source_frame", "overlay_opacity", "easing", "transform"}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans les réglages du match : "
                + ", ".join(unknown)
            )
        try:
            easing = Easing(values.get("easing", Easing.EASE_IN_OUT.value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Interpolation de match inconnue") from exc
        return cls(
            reference_source_frame=int(values.get("reference_source_frame", 0)),
            overlay_opacity=float(values.get("overlay_opacity", 0.5)),
            easing=easing,
            transform=ManualMatchTransform.from_dict(values.get("transform", {})),
        ).validate()


def validate_manual_match_transition(
    project: StudioProject,
    transition: Transition,
) -> ManualMatchSettings:
    from .transitions import transition_clip_pair

    settings = ManualMatchSettings.from_transition(transition)
    pair = transition_clip_pair(project, transition)
    if pair.from_clip.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
        raise ValueError("Le départ d’un match manuel doit être un plan d’œuvre")
    if pair.to_clip.kind not in {ClipKind.STILL, ClipKind.VIDEO}:
        raise ValueError("L’arrivée d’un match manuel doit être une photo ou une vidéo")
    if pair.to_clip.kind == ClipKind.STILL:
        if settings.reference_source_frame != 0:
            raise ValueError("Une photo réelle utilise la frame de référence 0")
    else:
        if pair.to_clip.asset_id is None:
            raise ValueError("Le plan vidéo réel ne référence aucun asset")
        video_source_frame_count(project, pair.to_clip.asset_id)
        minimum = pair.to_clip.source_in_frame
        maximum = minimum + pair.to_clip.duration_frames - 1
        if not minimum <= settings.reference_source_frame <= maximum:
            raise ValueError(
                "La frame de référence doit rester dans le plan vidéo réel"
            )
    return settings


def incoming_manual_match(
    project: StudioProject,
    clip_id: str,
) -> Transition | None:
    matches = [
        transition
        for transition in project.transitions
        if transition.kind == TransitionKind.MATCH
        and transition.to_clip_id == clip_id
    ]
    if len(matches) > 1:
        raise ValueError("Un plan réel ne peut recevoir qu’un match manuel")
    return matches[0] if matches else None


def _perspective_coefficients(
    output_quad: tuple[tuple[float, float], ...],
    source_quad: tuple[tuple[float, float], ...],
) -> tuple[float, ...]:
    matrix = []
    target = []
    for (x, y), (u, v) in zip(output_quad, source_quad, strict=True):
        matrix.append((x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y))
        matrix.append((0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y))
        target.extend((u, v))
    try:
        coefficients = np.linalg.solve(
            np.asarray(matrix, dtype=np.float64),
            np.asarray(target, dtype=np.float64),
        )
    except np.linalg.LinAlgError as exc:
        raise ValueError("La perspective du match est dégénérée") from exc
    return tuple(float(value) for value in coefficients)


def warp_matched_frame(
    frame: np.ndarray,
    output_width: int,
    output_height: int,
    settings: ManualMatchSettings,
) -> tuple[np.ndarray, np.ndarray]:
    settings.validate()
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise TypeError("Le match manuel attend une frame RGB uint8")
    source_height, source_width = frame.shape[:2]
    source_quad = tuple(
        (point.x * (source_width - 1), point.y * (source_height - 1))
        for point in settings.transform.source_quad()
    )
    target_quad = settings.transform.target_quad(output_width, output_height)
    coefficients = _perspective_coefficients(target_quad, source_quad)
    image = Image.fromarray(np.ascontiguousarray(frame), "RGB")
    alpha_source = Image.new("L", (source_width, source_height), 255)
    size = (int(output_width), int(output_height))
    warped = image.transform(
        size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0),
    )
    alpha = alpha_source.transform(
        size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BILINEAR,
        fillcolor=0,
    )
    return (
        np.asarray(warped, dtype=np.uint8),
        np.asarray(alpha, dtype=np.float32) / 255.0,
    )


def add_manual_match(
    project: StudioProject,
    first_clip_id: str,
    second_clip_id: str,
    *,
    duration_frames: int | None = None,
    easing: Easing = Easing.EASE_IN_OUT,
) -> tuple[StudioProject, Transition]:
    from .transitions import (
        DissolveSettings,
        add_dissolve,
        transition_clip_pair,
        validate_project_transitions,
    )

    selected = [
        clip
        for track in project.tracks
        for clip in track.clips
        if clip.clip_id in {first_clip_id, second_clip_id}
    ]
    if len(selected) != 2:
        raise KeyError("Les deux plans du match manuel sont introuvables")
    selected.sort(key=lambda clip: (clip.start_frame, clip.end_frame, clip.clip_id))
    from_clip, to_clip = selected
    if from_clip.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
        raise ValueError("Le premier plan du match doit venir de l’œuvre")
    if to_clip.kind not in {ClipKind.STILL, ClipKind.VIDEO}:
        raise ValueError("Le second plan du match doit être une photo ou une vidéo")
    existing = next(
        (
            transition
            for transition in project.transitions
            if transition.from_clip_id == from_clip.clip_id
            and transition.to_clip_id == to_clip.clip_id
        ),
        None,
    )
    if existing is not None and existing.kind == TransitionKind.MATCH:
        raise ValueError("Ces deux plans possèdent déjà un match manuel")
    if existing is not None and existing.kind != TransitionKind.DISSOLVE:
        raise ValueError("La relation existante ne peut pas devenir un match manuel")

    effective_easing = (
        DissolveSettings.from_transition(existing).easing
        if existing is not None
        else Easing(easing)
    )
    reference = to_clip.source_in_frame if to_clip.kind == ClipKind.VIDEO else 0
    settings = ManualMatchSettings(
        reference_source_frame=reference,
        easing=effective_easing,
    ).validate()
    if existing is None:
        dissolved_project, dissolve = add_dissolve(
            project,
            from_clip.clip_id,
            to_clip.clip_id,
            duration_frames=duration_frames,
            easing=effective_easing,
        )
        match = replace(
            dissolve,
            kind=TransitionKind.MATCH,
            parameters=settings.to_dict(),
        ).validate()
        transitions = tuple(
            match if item.transition_id == dissolve.transition_id else item
            for item in dissolved_project.transitions
        )
        candidate = replace(dissolved_project, transitions=transitions)
    else:
        match = replace(
            existing,
            kind=TransitionKind.MATCH,
            parameters=settings.to_dict(),
        ).validate()
        transitions = tuple(
            match if item.transition_id == existing.transition_id else item
            for item in project.transitions
        )
        candidate = replace(project, transitions=transitions)
    transition_clip_pair(candidate, match)
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate(), match


def update_manual_match(
    project: StudioProject,
    transition_id: str,
    *,
    duration_frames: int | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
    reference_source_frame: int | None = None,
    overlay_opacity: float | None = None,
    easing: Easing | None = None,
    transform: ManualMatchTransform | None = None,
) -> StudioProject:
    from .transitions import (
        _available_window,
        _fit_window_around_cut,
        transition_by_id,
        transition_clip_pair,
        transition_end_frame,
        validate_project_transitions,
    )

    current = transition_by_id(project, transition_id)
    if current.kind != TransitionKind.MATCH:
        raise ValueError("La transition sélectionnée n’est pas un match manuel")
    settings = ManualMatchSettings.from_transition(current)
    updated_settings = ManualMatchSettings(
        reference_source_frame=(
            settings.reference_source_frame
            if reference_source_frame is None
            else int(reference_source_frame)
        ),
        overlay_opacity=(
            settings.overlay_opacity
            if overlay_opacity is None
            else float(overlay_opacity)
        ),
        easing=settings.easing if easing is None else Easing(easing),
        transform=settings.transform if transform is None else transform,
    ).validate()
    start = current.start_frame if start_frame is None else int(start_frame)
    if end_frame is not None and duration_frames is not None:
        raise ValueError("Indiquez une fin ou une durée, pas les deux")
    if end_frame is not None:
        end = int(end_frame)
    elif duration_frames is not None:
        duration = int(duration_frames)
        if start_frame is not None:
            end = start + duration
        elif duration != current.duration_frames:
            pair = transition_clip_pair(project, current)
            minimum, maximum = _available_window(project, pair)
            start, end = _fit_window_around_cut(
                pair,
                minimum,
                maximum,
                duration,
            )
        else:
            end = transition_end_frame(current)
    else:
        end = (
            transition_end_frame(current)
            if start_frame is None
            else start + current.duration_frames
        )
    updated = replace(
        current,
        start_frame=start,
        duration_frames=end - start,
        parameters=updated_settings.to_dict(),
    ).validate()
    candidate = replace(
        project,
        transitions=tuple(
            updated if item.transition_id == transition_id else item
            for item in project.transitions
        ),
    )
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate()

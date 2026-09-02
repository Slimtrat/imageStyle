from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .manual_match import ManualMatchTransform, MatchPoint
from .model import ClipKind, Easing, StudioProject, Transition, TransitionKind
from .transition_matching import AkazeArtworkMatchSolver, SpatialMatchSolution


SPATIAL_REVIEW_STATES = {"automatic", "accepted", "adjusted"}


def spatial_transform_from_solution(
    solution: SpatialMatchSolution,
) -> ManualMatchTransform:
    """Expose one persisted homography through the common four-corner editor."""

    solution.validate()
    unit_quad = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    return ManualMatchTransform(
        target_corner_offsets=tuple(
            MatchPoint(float(x - base_x), float(y - base_y))
            for (x, y), (base_x, base_y) in zip(
                solution.target_quad,
                unit_quad,
                strict=True,
            )
        )
    ).validate()


def spatial_solution_from_transform(
    baseline: SpatialMatchSolution,
    transform: ManualMatchTransform,
) -> SpatialMatchSolution:
    """Rebuild the normalized homography while retaining AKAZE diagnostics."""

    baseline.validate()
    transform.validate()
    source = np.asarray(
        tuple((point.x, point.y) for point in transform.source_quad()),
        dtype=np.float32,
    )
    target_pixels = transform.target_quad(1001, 1001)
    target = np.asarray(
        tuple((x / 1000.0, y / 1000.0) for x, y in target_pixels),
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(source, target)
    if not np.isfinite(homography).all() or abs(float(homography[2, 2])) < 1.0e-12:
        raise ValueError("La correction manuelle produit une homographie dégénérée")
    homography /= homography[2, 2]
    return replace(
        baseline,
        target_quad=tuple((float(x), float(y)) for x, y in target),
        homography=tuple(
            tuple(float(value) for value in row)
            for row in homography
        ),
    ).validate()


@dataclass(frozen=True, slots=True)
class SpatialMatchSettings:
    solution: SpatialMatchSolution
    easing: Easing = Easing.EASE_IN_OUT
    automatic_solution: SpatialMatchSolution | None = None
    reference_source_frame: int = 0
    overlay_opacity: float = 0.5
    transform: ManualMatchTransform | None = None
    review_status: str = "automatic"
    comparison_overlay: bool = False

    @property
    def original_solution(self) -> SpatialMatchSolution:
        return self.automatic_solution or self.solution

    @property
    def editor_transform(self) -> ManualMatchTransform:
        return self.transform or spatial_transform_from_solution(self.solution)

    def validate(self) -> SpatialMatchSettings:
        self.solution.validate()
        self.original_solution.validate()
        self.editor_transform.validate()
        if not isinstance(self.easing, Easing):
            raise TypeError("L’interpolation du raccord spatial doit être un Easing")
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
        if self.review_status not in SPATIAL_REVIEW_STATES:
            raise ValueError("État éditorial de raccord spatial inconnu")
        if not isinstance(self.comparison_overlay, bool):
            raise TypeError("Le mode de comparaison du raccord doit être booléen")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload = {
            "easing": self.easing.value,
            "solution": self.solution.to_dict(),
            "automatic_solution": self.original_solution.to_dict(),
            "reference_source_frame": self.reference_source_frame,
            "overlay_opacity": float(self.overlay_opacity),
            "transform": self.editor_transform.to_dict(),
            "review_status": self.review_status,
        }
        if self.comparison_overlay:
            payload["comparison_overlay"] = True
        return payload

    @classmethod
    def from_transition(cls, transition: Transition) -> SpatialMatchSettings:
        if transition.kind != TransitionKind.SPATIAL_MATCH:
            raise ValueError("Les réglages demandés ne concernent pas un raccord spatial")
        values = transition.parameters or {}
        if not isinstance(values, dict):
            raise TypeError("Les réglages du raccord spatial doivent être un objet JSON")
        allowed = {
            "easing",
            "solution",
            "automatic_solution",
            "reference_source_frame",
            "overlay_opacity",
            "transform",
            "review_status",
            "comparison_overlay",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans les réglages du raccord spatial : "
                + ", ".join(unknown)
            )
        try:
            easing = Easing(values.get("easing", Easing.EASE_IN_OUT.value))
            solution = SpatialMatchSolution.from_dict(values.get("solution"))
            automatic_payload = values.get("automatic_solution")
            automatic = (
                SpatialMatchSolution.from_dict(automatic_payload)
                if automatic_payload is not None
                else solution
            )
            transform_payload = values.get("transform")
            transform = (
                ManualMatchTransform.from_dict(transform_payload)
                if transform_payload is not None
                else spatial_transform_from_solution(solution)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Réglages de raccord spatial invalides") from exc
        return cls(
            solution=solution,
            easing=easing,
            automatic_solution=automatic,
            reference_source_frame=int(values.get("reference_source_frame", 0)),
            overlay_opacity=float(values.get("overlay_opacity", 0.5)),
            transform=transform,
            review_status=str(values.get("review_status", "automatic")),
            comparison_overlay=values.get("comparison_overlay", False),
        ).validate()


def validate_spatial_match_transition(
    project: StudioProject,
    transition: Transition,
) -> SpatialMatchSettings:
    from .transitions import transition_clip_pair
    from .video import video_source_frame_count

    settings = SpatialMatchSettings.from_transition(transition)
    pair = transition_clip_pair(project, transition)
    if pair.from_clip.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
        raise ValueError("Le départ d’un raccord spatial doit être un plan d’œuvre")
    if pair.to_clip.kind not in {ClipKind.STILL, ClipKind.VIDEO}:
        raise ValueError("Le raccord spatial exige une photo ou une vidéo réelle")
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
            raise ValueError("La frame de référence doit rester dans le plan vidéo réel")
    return settings


def add_spatial_match(
    project: StudioProject,
    first_clip_id: str,
    second_clip_id: str,
    solution: SpatialMatchSolution,
    *,
    duration_frames: int | None = None,
    easing: Easing = Easing.EASE_IN_OUT,
    reference_source_frame: int | None = None,
) -> tuple[StudioProject, Transition]:
    from .transitions import add_dissolve, transition_clip_pair, validate_project_transitions

    solution.validate()
    dissolved, dissolve = add_dissolve(
        project,
        first_clip_id,
        second_clip_id,
        duration_frames=duration_frames,
        easing=easing,
    )
    pair = transition_clip_pair(dissolved, dissolve)
    reference = (
        pair.to_clip.source_in_frame
        if reference_source_frame is None and pair.to_clip.kind == ClipKind.VIDEO
        else int(reference_source_frame or 0)
    )
    settings = SpatialMatchSettings(
        solution=solution,
        easing=easing,
        automatic_solution=solution,
        reference_source_frame=reference,
        transform=spatial_transform_from_solution(solution),
    )
    spatial = replace(
        dissolve,
        kind=TransitionKind.SPATIAL_MATCH,
        parameters=settings.to_dict(),
    ).validate()
    candidate = replace(
        dissolved,
        transitions=tuple(
            spatial if item.transition_id == dissolve.transition_id else item
            for item in dissolved.transitions
        ),
    )
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate(), spatial


def _update_three_d_camera_match(
    project: StudioProject,
    transition: Transition,
    solution: SpatialMatchSolution,
) -> StudioProject:
    from ..desktop.studio3d_camera_match import solve_studio3d_camera_match
    from .transitions import transition_clip_pair

    pair = transition_clip_pair(project, transition)
    clip = pair.from_clip
    if clip.kind != ClipKind.ARTWORK_3D or not isinstance(clip.parameters, dict):
        return project
    parameters = deepcopy(clip.parameters)
    camera = parameters.get("camera")
    if not isinstance(camera, dict) or not isinstance(camera.get("match"), dict):
        return project
    previous = camera["match"]
    pose = solve_studio3d_camera_match(
        solution.target_quad,
        artwork_aspect=(project.artwork.width or 1) / (project.artwork.height or 1),
        output_width=project.settings.width,
        output_height=project.settings.height,
    )
    camera["match"] = pose.to_dict(
        start_frame=int(previous["start_frame"]),
        end_frame=int(previous["end_frame"]),
    )
    return replace(
        project,
        tracks=tuple(
            replace(
                track,
                clips=tuple(
                    replace(item, parameters=parameters)
                    if item.clip_id == clip.clip_id
                    else item
                    for item in track.clips
                ),
            )
            for track in project.tracks
        ),
    )


def update_spatial_match(
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
    solution: SpatialMatchSolution | None = None,
    automatic_solution: SpatialMatchSolution | None = None,
    review_status: str | None = None,
    comparison_overlay: bool | None = None,
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
    if current.kind != TransitionKind.SPATIAL_MATCH:
        raise ValueError("La transition sélectionnée n’est pas un raccord spatial")
    settings = SpatialMatchSettings.from_transition(current)
    solution_baseline = settings.solution if solution is None else solution
    geometry_changed = solution is not None or transform is not None
    if geometry_changed:
        effective_transform = (
            spatial_transform_from_solution(solution_baseline)
            if transform is None
            else transform
        )
        edited_solution = spatial_solution_from_transform(
            solution_baseline,
            effective_transform,
        )
    else:
        effective_transform = settings.editor_transform
        edited_solution = settings.solution
    updated_settings = SpatialMatchSettings(
        solution=edited_solution,
        easing=settings.easing if easing is None else Easing(easing),
        automatic_solution=(
            automatic_solution
            or (solution_baseline if solution is not None else settings.original_solution)
        ),
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
        transform=effective_transform,
        review_status=review_status or settings.review_status,
        comparison_overlay=(
            settings.comparison_overlay
            if comparison_overlay is None
            else bool(comparison_overlay)
        ),
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
            start, end = _fit_window_around_cut(pair, minimum, maximum, duration)
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
    if geometry_changed:
        candidate = _update_three_d_camera_match(candidate, updated, edited_solution)
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate()


def restore_automatic_spatial_match(
    project: StudioProject,
    transition_id: str,
) -> StudioProject:
    from .transitions import transition_by_id

    settings = SpatialMatchSettings.from_transition(
        transition_by_id(project, transition_id)
    )
    automatic = settings.original_solution
    return update_spatial_match(
        project,
        transition_id,
        transform=spatial_transform_from_solution(automatic),
        automatic_solution=automatic,
        review_status="automatic",
    )


def solve_spatial_match_reference(
    project: StudioProject,
    transition_id: str,
    *,
    project_path: str | Path,
    reference_source_frame: int,
) -> SpatialMatchSolution:
    """Solve a photo or selected video frame through the exact rendered framing path."""

    from .assets import resolve_asset_path
    from .camera import render_camera_frame, resolve_camera_pose
    from .compositor import fit_frame
    from .image_io import load_normalized_image
    from .media import StillClipSettings, transform_still_frame
    from .transitions import transition_by_id, transition_clip_pair
    from .video import VideoClipSettings, VideoFrameSource

    transition = transition_by_id(project, transition_id)
    pair = transition_clip_pair(project, transition)
    target_clip = pair.to_clip
    if target_clip.asset_id is None:
        raise ValueError("Le plan réel ne référence aucun média")
    try:
        asset = next(
            item for item in project.assets if item.asset_id == target_clip.asset_id
        )
    except StopIteration as exc:
        raise KeyError("Le média réel du raccord est introuvable") from exc
    artwork_path = resolve_asset_path(project.artwork.path, project_path)
    target_path = resolve_asset_path(asset.path, project_path)
    artwork, _inspection = load_normalized_image(artwork_path)
    if target_clip.kind == ClipKind.STILL:
        if reference_source_frame != 0:
            raise ValueError("Une photo réelle utilise la frame de référence 0")
        target_image, _target_inspection = load_normalized_image(target_path)
        target_rgb = transform_still_frame(
            np.asarray(target_image, dtype=np.uint8),
            StillClipSettings.from_clip(target_clip),
        )
    elif target_clip.kind == ClipKind.VIDEO:
        source = VideoFrameSource(
            asset,
            target_path,
            project.settings.fps,
            VideoClipSettings.from_clip(target_clip),
        )
        try:
            target_rgb = source.frame_at(int(reference_source_frame))
        finally:
            source.close()
    else:
        raise ValueError("Le raccord spatial exige une photo ou une vidéo réelle")
    local_frame = int(reference_source_frame) - target_clip.source_in_frame
    if target_clip.camera is not None:
        target_canvas = render_camera_frame(
            target_rgb,
            project.settings.width,
            project.settings.height,
            resolve_camera_pose(target_clip.camera, local_frame),
            background=project.settings.background,
        )
    else:
        target_canvas, _coverage = fit_frame(
            target_rgb,
            project.settings.width,
            project.settings.height,
            target_clip.fit,
        )
    return AkazeArtworkMatchSolver().solve(artwork, target_canvas)

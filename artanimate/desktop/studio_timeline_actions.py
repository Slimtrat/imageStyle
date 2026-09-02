from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from ..studio.manual_match import (
    add_manual_match as create_manual_match,
    update_manual_match,
)
from ..studio.model import TransitionKind
from ..studio.spatial_match import (
    SpatialMatchSettings,
    solve_spatial_match_reference,
    spatial_transform_from_solution,
    update_spatial_match,
)
from ..studio.audio import set_audio_clip_fades
from ..studio.timeline import (
    OVERLAP_POLICY,
    clip_location,
    delete_clips,
    duplicate_clip,
    move_clip,
    reorder_track,
    snap_frame,
    split_clip,
    timeline_snap_targets,
    track_by_id,
    trim_clip,
)
from ..studio.transitions import (
    add_dissolve as create_dissolve,
    delete_transition,
    transition_by_id,
    update_dissolve,
)


if TYPE_CHECKING:
    from .studio import StudioPanel


class StudioTimelineActions(QObject):
    """Binds frame-exact timeline edit commands to the artwork-first workspace."""

    def __init__(self, panel: StudioPanel):
        super().__init__(panel)
        self.panel = panel
        timeline = panel.timeline
        timeline.clipMoveRequested.connect(self.move_clips)
        timeline.clipTrimRequested.connect(self.trim_clip)
        timeline.audioFadeRequested.connect(self.set_audio_fades)
        timeline.splitRequested.connect(self.split_clips)
        timeline.duplicateRequested.connect(self.duplicate_clips)
        timeline.deleteRequested.connect(self.delete_clips)
        timeline.trackReorderRequested.connect(self.reorder_track)
        timeline.dissolveRequested.connect(self.add_dissolve)
        timeline.transitionResizeRequested.connect(self.resize_transition)
        timeline.transitionDeleteRequested.connect(self.delete_transition)
        timeline.matchRequested.connect(self.add_manual_match)

    @staticmethod
    def _ids(value: object) -> tuple[str, ...]:
        if not isinstance(value, (tuple, list)):
            return ()
        return tuple(str(item) for item in value)

    def _error(self, exc: Exception) -> None:
        self.panel.project_status.setText(f"Montage inchangé · {exc}")

    def _snap(
        self,
        frame: int,
        *,
        exclude_clip_ids: tuple[str, ...] = (),
    ) -> int:
        project = self.panel.project
        if project is None:
            return int(frame)
        threshold = max(
            1,
            int(round(8 / self.panel.timeline.scene.pixels_per_frame)),
        )
        targets = timeline_snap_targets(
            project,
            playhead=self.panel.transport.current_frame,
            exclude_clip_ids=exclude_clip_ids,
        )
        return snap_frame(
            frame,
            targets,
            threshold_frames=threshold,
            enabled=self.panel.timeline.snapping_enabled,
        )

    def move_clips(
        self,
        clip_ids: object,
        anchor_clip_id: str,
        target_frame: int,
        target_track_id: str,
    ) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None or not selected:
            return
        try:
            original = {
                clip_id: clip_location(project, clip_id)[3]
                for clip_id in selected
            }
            anchor = original[anchor_clip_id]
            snapped = self._snap(int(target_frame), exclude_clip_ids=selected)
            delta = snapped - anchor.start_frame
            updated = project
            for clip_id in selected:
                destination = target_track_id if len(selected) == 1 else None
                updated = move_clip(
                    updated,
                    clip_id,
                    original[clip_id].start_frame + delta,
                    target_track_id=destination,
                )
            self.panel._commit_timeline_project(
                updated,
                f"Déplacer {len(selected)} clip(s)",
            )
            self.panel.timeline.scene.set_selection(selected)
            self.panel.project_status.setText(
                f"{len(selected)} clip(s) déplacé(s) · collisions = {OVERLAP_POLICY}"
            )
        except (KeyError, ValueError, PermissionError) as exc:
            self._error(exc)

    def trim_clip(self, clip_id: str, start: int, end: int) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            snapped_start = self._snap(int(start), exclude_clip_ids=(clip_id,))
            snapped_end = self._snap(int(end), exclude_clip_ids=(clip_id,))
            updated = trim_clip(project, clip_id, snapped_start, snapped_end)
            self.panel._commit_timeline_project(
                updated,
                "Retailler un clip",
                merge_key=f"trim:{clip_id}",
            )
            self.panel.timeline.scene.set_selection((clip_id,))
        except (KeyError, ValueError, PermissionError) as exc:
            self._error(exc)

    def set_audio_fades(
        self,
        clip_id: str,
        fade_in_frames: int,
        fade_out_frames: int,
    ) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            updated = set_audio_clip_fades(
                project,
                clip_id,
                fade_in_frames,
                fade_out_frames,
            )
            self.panel._commit_timeline_project(
                updated,
                "Régler les fondus audio",
                merge_key=f"audio-fades:{clip_id}",
            )
            self.panel.timeline.scene.set_selection((clip_id,))
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def split_clips(self, clip_ids: object) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None:
            return
        frame = self.panel.transport.current_frame
        updated = project
        right_ids: list[str] = []
        try:
            for clip_id in selected:
                clip = clip_location(updated, clip_id)[3]
                if clip.start_frame < frame < clip.end_frame:
                    updated, right = split_clip(updated, clip_id, frame)
                    right_ids.append(right.clip_id)
            if not right_ids:
                raise ValueError("Le playhead doit être à l’intérieur d’un clip sélectionné")
            self.panel._commit_timeline_project(updated, "Scinder les clips")
            self.panel.timeline.scene.set_selection(tuple(right_ids))
        except (KeyError, ValueError, PermissionError) as exc:
            self._error(exc)

    def duplicate_clips(self, clip_ids: object) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None:
            return
        updated = project
        copies: list[str] = []
        try:
            for clip_id in selected:
                updated, duplicate = duplicate_clip(updated, clip_id)
                copies.append(duplicate.clip_id)
            if not copies:
                return
            self.panel._commit_timeline_project(updated, "Dupliquer les clips")
            self.panel.timeline.scene.set_selection(tuple(copies))
        except (KeyError, ValueError, PermissionError) as exc:
            self._error(exc)

    def delete_clips(self, clip_ids: object) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None or not selected:
            return
        try:
            updated = delete_clips(project, selected)
            self.panel._commit_timeline_project(updated, "Supprimer les clips")
            self.panel.timeline.scene.set_selection(())
        except (KeyError, ValueError, PermissionError) as exc:
            self._error(exc)

    def add_dissolve(self, clip_ids: object) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None:
            return
        if len(selected) != 2:
            self._error(ValueError("Sélectionnez exactement deux plans adjacents"))
            return
        try:
            updated, transition = create_dissolve(project, selected[0], selected[1])
            self.panel._commit_timeline_project(
                updated,
                "Ajouter un fondu enchaîné",
            )
            self.panel.timeline.scene.set_transition_selection(
                transition.transition_id
            )
            self.panel.project_status.setText(
                f"Fondu créé · {transition.duration_frames} frames · "
                "poignées de source validées"
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def add_manual_match(self, clip_ids: object) -> None:
        project = self.panel.project
        selected = self._ids(clip_ids)
        if project is None:
            return
        if len(selected) != 2:
            self._error(
                ValueError("Sélectionnez un plan d’œuvre puis un plan photo ou vidéo")
            )
            return
        try:
            updated, transition = create_manual_match(
                project,
                selected[0],
                selected[1],
            )
            self.panel._commit_timeline_project(
                updated,
                "Créer le match manuel virtuel → réel",
            )
            self.panel.timeline.scene.set_transition_selection(
                transition.transition_id
            )
            self.panel.project_status.setText(
                f"Match réel créé · {transition.duration_frames} frames · "
                "quatre coins éditables"
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def resize_transition(
        self,
        transition_id: str,
        start_frame: int,
        end_frame: int,
    ) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            transition = transition_by_id(project, transition_id)
            if transition.kind == TransitionKind.MATCH:
                updated = update_manual_match(
                    project,
                    transition_id,
                    start_frame=int(start_frame),
                    end_frame=int(end_frame),
                )
            elif transition.kind == TransitionKind.SPATIAL_MATCH:
                updated = update_spatial_match(
                    project,
                    transition_id,
                    start_frame=int(start_frame),
                    end_frame=int(end_frame),
                )
            else:
                updated = update_dissolve(
                    project,
                    transition_id,
                    start_frame=int(start_frame),
                    end_frame=int(end_frame),
                )
            self.panel._commit_timeline_project(
                updated,
                "Régler la fenêtre de transition",
                merge_key=f"transition-window:{transition_id}",
            )
            self.panel.timeline.scene.set_transition_selection(transition_id)
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def apply_transition_edit(self, edit: object) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            transition_id = str(getattr(edit, "transition_id"))
            updated = update_dissolve(
                project,
                transition_id,
                duration_frames=int(getattr(edit, "duration_frames")),
                easing=getattr(edit, "easing"),
            )
            self.panel._commit_timeline_project(
                updated,
                "Régler le fondu enchaîné",
                merge_key=f"transition-settings:{transition_id}",
            )
            self.panel.timeline.scene.set_transition_selection(transition_id)
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def apply_match_edit(self, edit: object) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            transition_id = str(getattr(edit, "transition_id"))
            transition = transition_by_id(project, transition_id)
            if transition.kind == TransitionKind.SPATIAL_MATCH:
                base = (
                    self.panel._match_proposal[1]
                    if self.panel._match_proposal is not None
                    and self.panel._match_proposal[0] == transition_id
                    else project
                )
                requested_reference = int(getattr(edit, "reference_source_frame"))
                settings = SpatialMatchSettings.from_transition(
                    transition_by_id(base, transition_id)
                )
                if requested_reference != settings.reference_source_frame:
                    solution = solve_spatial_match_reference(
                        project,
                        transition_id,
                        project_path=self.panel._match_context_path(),
                        reference_source_frame=requested_reference,
                    )
                    base = update_spatial_match(
                        project,
                        transition_id,
                        reference_source_frame=requested_reference,
                        solution=solution,
                        automatic_solution=solution,
                        transform=spatial_transform_from_solution(solution),
                    )
                    settings = SpatialMatchSettings.from_transition(
                        transition_by_id(base, transition_id)
                    )
                transform = getattr(edit, "transform")
                status = (
                    "accepted"
                    if transform.to_dict()
                    == spatial_transform_from_solution(
                        settings.original_solution
                    ).to_dict()
                    else "adjusted"
                )
                updated = update_spatial_match(
                    base,
                    transition_id,
                    duration_frames=int(getattr(edit, "duration_frames")),
                    reference_source_frame=requested_reference,
                    overlay_opacity=float(getattr(edit, "overlay_opacity")),
                    easing=getattr(edit, "easing"),
                    transform=transform,
                    review_status=status,
                    comparison_overlay=False,
                )
                self.panel._clear_spatial_match_proposal()
            else:
                updated = update_manual_match(
                    project,
                    transition_id,
                    duration_frames=int(getattr(edit, "duration_frames")),
                    reference_source_frame=int(
                        getattr(edit, "reference_source_frame")
                    ),
                    overlay_opacity=float(getattr(edit, "overlay_opacity")),
                    easing=getattr(edit, "easing"),
                    transform=getattr(edit, "transform"),
                )
            self.panel._commit_timeline_project(
                updated,
                "Accepter le raccord spatial"
                if transition.kind == TransitionKind.SPATIAL_MATCH
                else "Régler le match manuel",
                merge_key=f"match-settings:{transition_id}",
            )
            self.panel.timeline.scene.set_transition_selection(transition_id)
            self.panel.project_status.setText(
                "Match réel réglé · transformation sérialisée"
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def apply_match_transform(self, transition_id: str, transform: object) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            transition = transition_by_id(project, transition_id)
            if transition.kind == TransitionKind.SPATIAL_MATCH:
                self.panel._preview_spatial_match_transform(transition_id, transform)
                return
            updated = update_manual_match(project, transition_id, transform=transform)
            self.panel._commit_timeline_project(
                updated,
                "Manipuler le match dans le canvas",
                merge_key=f"match-canvas:{transition_id}",
            )
            self.panel.timeline.scene.set_transition_selection(transition_id)
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def delete_transition(self, transition_id: str) -> None:
        project = self.panel.project
        if project is None or not transition_id:
            return
        try:
            updated = delete_transition(project, transition_id)
            self.panel._commit_timeline_project(updated, "Retrouver le cut")
            self.panel.timeline.scene.set_transition_selection(None)
            self.panel.project_status.setText(
                "Transition retirée · cut frame-exact restauré"
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self._error(exc)

    def reorder_track(self, track_id: str, direction: int) -> None:
        project = self.panel.project
        if project is None:
            return
        try:
            source_index, _track = track_by_id(project, track_id)
            target = min(
                len(project.tracks) - 1,
                max(0, source_index + int(direction)),
            )
            if target == source_index:
                return
            self.panel._commit_timeline_project(
                reorder_track(project, track_id, target),
                "Réordonner une piste",
            )
        except (KeyError, IndexError, ValueError) as exc:
            self._error(exc)


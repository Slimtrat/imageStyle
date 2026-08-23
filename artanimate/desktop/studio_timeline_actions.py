from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

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
        timeline.splitRequested.connect(self.split_clips)
        timeline.duplicateRequested.connect(self.duplicate_clips)
        timeline.deleteRequested.connect(self.delete_clips)
        timeline.trackReorderRequested.connect(self.reorder_track)

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


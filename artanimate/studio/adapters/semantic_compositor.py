from __future__ import annotations

import numpy as np

from ..camera import render_camera_frame
from ..compositor import alpha_composite_rgb, composite_artwork_effect, fit_frame
from ..model import CameraPose, FitMode, StudioProject
from ..sources import validate_frame_index
from .classic_2d import PreparedRenderPlan, PreparedRenderPlanEntry
from .legacy_project import LegacySemanticProject


def _require_rgb(value: object, where: str) -> np.ndarray:
    frame = np.asarray(value)
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise TypeError(f"{where} doit produire une frame RGB uint8")
    return frame


class SemanticPlanCompositor:
    """Canonical 2D compositor driven only by prepared semantic invocations."""

    def __init__(
        self,
        project: StudioProject,
        semantic: LegacySemanticProject,
        prepared: PreparedRenderPlan,
    ) -> None:
        self.project = project.validate()
        self.semantic = semantic
        self.prepared = prepared
        self.width = prepared.plan.constraints.width
        self.height = prepared.plan.constraints.height
        self.fps = prepared.plan.constraints.fps
        self.frame_count = project.settings.duration_frames
        if self.fps != project.settings.fps:
            raise ValueError("Le plan sémantique doit partager le FPS du projet")
        self._entries = {
            item.plan_entry.request.invocation.invocation_id: item
            for item in prepared.entries
        }
        self._content_by_clip = {
            binding.clip_id: binding.invocation_id
            for binding in semantic.bindings
            if binding.role == "content"
        }

    @staticmethod
    def _active(entry: PreparedRenderPlanEntry, project_frame: int) -> bool:
        invocation = entry.plan_entry.request.invocation
        return invocation.start_frame <= project_frame < invocation.end_frame

    def _camera_entry(
        self,
        target_invocation_id: str,
        project_frame: int,
    ) -> PreparedRenderPlanEntry | None:
        matches = []
        for entry in self.prepared.entries:
            invocation = entry.plan_entry.request.invocation
            if invocation.capability_id != "camera.animate" or not self._active(entry, project_frame):
                continue
            if invocation.parameters["target_invocation_id"] == target_invocation_id:
                matches.append(entry)
        if len(matches) > 1:
            raise ValueError("Deux cameras sémantiques ciblent simultanément le même plan")
        return matches[0] if matches else None

    def _transform(
        self,
        image: np.ndarray,
        content_entry: PreparedRenderPlanEntry,
        project_frame: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        invocation = content_entry.plan_entry.request.invocation
        camera = self._camera_entry(invocation.invocation_id, project_frame)
        if camera is not None:
            local = project_frame - camera.plan_entry.request.invocation.start_frame
            camera_frame = camera.prepared.frame_at(local)
            pose = camera_frame.metadata.to_dict()["pose"]
            rendered = render_camera_frame(
                image,
                self.width,
                self.height,
                CameraPose(**pose),
                background=self.project.settings.background,
            )
            return rendered, np.ones((self.height, self.width), dtype=np.float32)
        fit = FitMode(invocation.parameters.to_dict().get("fit", FitMode.CONTAIN.value))
        return fit_frame(image, self.width, self.height, fit)

    def _target_for_effect(
        self,
        effect_entry: PreparedRenderPlanEntry,
        project_frame: int,
    ) -> PreparedRenderPlanEntry:
        target_clip_id = str(
            effect_entry.plan_entry.request.invocation.parameters["target_clip_id"]
        )
        try:
            target_invocation_id = self._content_by_clip[target_clip_id]
            target = self._entries[target_invocation_id]
        except KeyError as exc:
            raise ValueError(
                f"Le calque sémantique ne trouve pas son plan cible {target_clip_id}"
            ) from exc
        if not self._active(target, project_frame):
            raise ValueError("Le plan ciblé par l'effet n'est pas actif")
        return target

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        if self.prepared.closed:
            raise RuntimeError("Le plan de rendu sémantique a été fermé")
        background = np.empty((self.height, self.width, 3), dtype=np.uint8)
        background[:] = self.project.settings.background
        for entry in self.prepared.entries:
            invocation = entry.plan_entry.request.invocation
            if not self._active(entry, frame_index):
                continue
            if invocation.capability_id in {"camera.animate", "audio.play"}:
                continue
            local = frame_index - invocation.start_frame
            rendered = entry.prepared.frame_at(local)
            opacity = float(invocation.parameters.to_dict().get("opacity", 1.0))
            if rendered.blend_mode == "artwork.delta":
                effected = _require_rgb(rendered.image, invocation.invocation_id)
                reference = _require_rgb(rendered.reference, invocation.invocation_id + ".reference")
                target = self._target_for_effect(entry, frame_index)
                effected_canvas, alpha = self._transform(effected, target, frame_index)
                reference_canvas, reference_alpha = self._transform(reference, target, frame_index)
                if not np.array_equal(alpha, reference_alpha):
                    raise ValueError("L'effet et sa référence ne partagent pas le même masque")
                background = composite_artwork_effect(
                    background,
                    effected_canvas,
                    reference_canvas,
                    alpha,
                    intensity=float(invocation.parameters["intensity"]),
                    opacity=opacity,
                )
                continue
            foreground, alpha = self._transform(
                _require_rgb(rendered.image, invocation.invocation_id),
                entry,
                frame_index,
            )
            background = alpha_composite_rgb(
                background,
                foreground,
                alpha,
                opacity=opacity,
            )
        return background

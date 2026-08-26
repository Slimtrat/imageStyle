from __future__ import annotations

import numpy as np

from ..camera import render_camera_frame
from ..compositor import alpha_composite_rgb, composite_artwork_effect, fit_frame
from ..model import CameraPose, FitMode, StudioProject
from ..sources import validate_frame_index
from ..semantic_actions import SEMANTIC_ACTION_IDS
from .classic_2d import PreparedRenderPlan, PreparedRenderPlanEntry
from .legacy_project import LegacySemanticProject


def _require_rgb(value: object, where: str) -> np.ndarray:
    frame = np.asarray(value)
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise TypeError(f"{where} doit produire une frame RGB uint8")
    return frame


def _fit_scalar(
    value: np.ndarray,
    width: int,
    height: int,
    fit: FitMode,
) -> np.ndarray:
    scalar = np.asarray(value, dtype=np.float32)
    if scalar.ndim != 2:
        raise TypeError("Une ressource sémantique doit être un plan scalaire")
    encoded = np.repeat(
        np.rint(np.clip(scalar, 0.0, 1.0) * 255.0).astype(np.uint8)[..., None],
        3,
        axis=2,
    )
    canvas, coverage = fit_frame(encoded, width, height, fit)
    return np.ascontiguousarray(
        (canvas[..., 0].astype(np.float32) / 255.0) * coverage,
        dtype=np.float32,
    )


def _edge_fill(image: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Deterministic local disocclusion fallback without an external model."""

    mask = np.asarray(alpha) > 0.02
    if not np.any(mask):
        return image.copy()
    height, width = mask.shape
    ys, xs = np.nonzero(mask)
    margin = max(2, int(round(min(width, height) * 0.015)))
    x0, x1 = max(0, int(xs.min()) - margin), min(width, int(xs.max()) + margin + 1)
    y0, y1 = max(0, int(ys.min()) - margin), min(height, int(ys.max()) + margin + 1)
    local_mask = mask[y0:y1, x0:x1]
    ring = np.ones(local_mask.shape, dtype=bool)
    ring[local_mask] = False
    sample = image[y0:y1, x0:x1][ring]
    if not len(sample):
        sample = image[~mask]
    color = (
        np.median(sample, axis=0).astype(np.float32)
        if len(sample)
        else np.zeros(3, dtype=np.float32)
    )
    source = image[y0:y1, x0:x1].astype(np.float32)
    filled = source.copy()
    filled[local_mask] = color
    for _iteration in range(10):
        padded = np.pad(filled, ((1, 1), (1, 1), (0, 0)), mode="edge")
        neighbors = (
            padded[:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, :-2]
            + padded[1:-1, 2:]
        ) * 0.25
        filled[local_mask] = neighbors[local_mask]
    blend = np.clip(alpha[y0:y1, x0:x1], 0.0, 1.0)[..., None]
    result = image.copy()
    result[y0:y1, x0:x1] = np.rint(
        source * (1.0 - blend) + filled * blend
    ).astype(np.uint8)
    return result


def _shift_layer(
    image: np.ndarray,
    alpha: np.ndarray,
    dx: int,
    dy: int,
) -> tuple[np.ndarray, np.ndarray]:
    height, width = alpha.shape
    shifted_image = np.zeros_like(image)
    shifted_alpha = np.zeros_like(alpha, dtype=np.float32)
    source_x0 = max(0, -dx)
    source_y0 = max(0, -dy)
    target_x0 = max(0, dx)
    target_y0 = max(0, dy)
    span_x = min(width - source_x0, width - target_x0)
    span_y = min(height - source_y0, height - target_y0)
    if span_x <= 0 or span_y <= 0:
        return shifted_image, shifted_alpha
    source = np.s_[source_y0 : source_y0 + span_y, source_x0 : source_x0 + span_x]
    target = np.s_[target_y0 : target_y0 + span_y, target_x0 : target_x0 + span_x]
    shifted_image[target] = image[source]
    shifted_alpha[target] = alpha[source]
    return shifted_image, shifted_alpha


def _depth_warp(
    image: np.ndarray,
    depth: np.ndarray,
    travel: list[float],
    strength: float,
    progress: float,
) -> np.ndarray:
    height, width = depth.shape
    center = (np.clip(depth, 0.0, 1.0) - 0.5) * 2.0
    shift_x = float(travel[0]) * width * float(strength) * float(progress)
    shift_y = float(travel[1]) * height * float(strength) * float(progress)
    grid_y, grid_x = np.indices((height, width), dtype=np.float32)
    source_x = np.clip(np.rint(grid_x - shift_x * center), 0, width - 1).astype(np.intp)
    source_y = np.clip(np.rint(grid_y - shift_y * center), 0, height - 1).astype(np.intp)
    return np.ascontiguousarray(image[source_y, source_x], dtype=np.uint8)


def _parse_color(value: str) -> np.ndarray:
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    return np.array(
        [int(text[index : index + 2], 16) for index in (0, 2, 4)],
        dtype=np.float32,
    )


def _particles(
    image: np.ndarray,
    mask: np.ndarray,
    parameters: dict[str, object],
    progress: float,
    seed: int,
) -> np.ndarray:
    active = np.argwhere(mask > 0.05)
    if not len(active):
        return image
    count = min(int(parameters["count"]), 1_000)
    rng = np.random.default_rng(int(seed))
    selected = active[rng.choice(len(active), size=count, replace=len(active) < count)]
    phase = rng.uniform(0.0, np.pi * 2.0, size=count)
    drift = rng.uniform(0.55, 1.0, size=count)
    speed = float(parameters["speed"])
    size = float(parameters["size"])
    color = _parse_color(str(parameters["color"]))
    height, width = mask.shape
    result = image.astype(np.float32).copy()
    visibility = float(np.sin(np.pi * np.clip(progress, 0.0, 1.0)))
    radius = max(1, int(round(size)))
    for index, (base_y, base_x) in enumerate(selected):
        x = int(round(base_x + np.sin(phase[index] + progress * 5.0) * size * 2.0))
        y = int(round(base_y - progress * speed * height * 0.18 * drift[index]))
        x0, x1 = max(0, x - radius), min(width, x + radius + 1)
        y0, y1 = max(0, y - radius), min(height, y + radius + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.ogrid[y0:y1, x0:x1]
        distance = ((xx - x) ** 2 + (yy - y) ** 2) / max(1.0, radius * radius)
        particle_alpha = np.clip(1.0 - distance, 0.0, 1.0) * visibility * 0.72
        region = result[y0:y1, x0:x1]
        region[:] = region * (1.0 - particle_alpha[..., None]) + color * particle_alpha[..., None]
    return np.rint(np.clip(result, 0.0, 255.0)).astype(np.uint8)


    """Canonical 2D compositor driven only by prepared semantic invocations."""
class SemanticPlanCompositor:

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
        self._semantic_resource_cache: dict[tuple[str, str], np.ndarray] = {}

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

    def _fitted_semantic_resource(
        self,
        rendered,
        fit: FitMode,
    ) -> np.ndarray:
        metadata = rendered.metadata.to_dict()
        key = (str(metadata["invocation_id"]), fit.value)
        cached = self._semantic_resource_cache.get(key)
        if cached is not None:
            return cached
        fitted = _fit_scalar(rendered.alpha, self.width, self.height, fit)
        self._semantic_resource_cache[key] = fitted
        return fitted


    def _semantic_action(
        self,
        background: np.ndarray,
        rendered,
        fit: FitMode,
    ) -> np.ndarray:
        metadata = rendered.metadata.to_dict()
        parameters = metadata["parameters"]
        progress = float(metadata["progress"])
        blend_mode = rendered.blend_mode
        if blend_mode in {"semantic.object-move", "semantic.object-exit-frame"}:
            alpha = self._fitted_semantic_resource(rendered, fit)
            selected = np.argwhere(alpha > 0.02)
            if not len(selected):
                return background
            ys, xs = selected[:, 0], selected[:, 1]
            center_x = (float(xs.min()) + float(xs.max())) * 0.5
            center_y = (float(ys.min()) + float(ys.max())) * 0.5
            if blend_mode == "semantic.object-move":
                destination = parameters["destination"]
                dx = (float(destination[0]) * self.width - center_x) * progress
                dy = (float(destination[1]) * self.height - center_y) * progress
            else:
                margin = float(parameters["margin"])
                direction = str(parameters["direction"])
                if direction == "left":
                    final_dx, final_dy = -margin * self.width - float(xs.max()), 0.0
                elif direction == "right":
                    final_dx, final_dy = self.width * (1.0 + margin) - float(xs.min()), 0.0
                elif direction == "top":
                    final_dx, final_dy = 0.0, -margin * self.height - float(ys.max())
                else:
                    final_dx, final_dy = 0.0, self.height * (1.0 + margin) - float(ys.min())
                dx, dy = final_dx * progress, final_dy * progress
            object_pixels = background.copy()
            cleared = (
                _edge_fill(background, alpha)
                if parameters["fill_mode"] == "edge-fill"
                else background.copy()
            )
            shifted, shifted_alpha = _shift_layer(
                object_pixels,
                alpha,
                int(round(dx)),
                int(round(dy)),
            )
            return alpha_composite_rgb(cleared, shifted, shifted_alpha)
        if blend_mode == "semantic.scene-parallax":
            depth = self._fitted_semantic_resource(rendered, fit)
            return _depth_warp(
                background,
                depth,
                parameters["travel"],
                float(parameters["strength"]),
                progress,
            )
        if blend_mode == "semantic.environment-particles":
            mask = (
                np.ones((self.height, self.width), dtype=np.float32)
                if rendered.alpha is None
                else self._fitted_semantic_resource(rendered, fit)
            )
            return _particles(
                background,
                mask,
                parameters,
                progress,
                int(metadata["seed"]),
            )
        if blend_mode == "semantic.camera-inspect":
            bounds = metadata["target_bounds"]
            if bounds is None:
                raise ValueError("camera.inspect exige un cadrage cible")
            target_x = float(bounds["x"]) + float(bounds["width"]) * 0.5
            target_y = float(bounds["y"]) + float(bounds["height"]) * 0.5
            pose = CameraPose(
                x=0.5 + (target_x - 0.5) * progress,
                y=0.5 + (target_y - 0.5) * progress,
                zoom=1.0 + (float(parameters["zoom"]) - 1.0) * progress,
            )
            return render_camera_frame(
                background,
                self.width,
                self.height,
                pose,
                background=self.project.settings.background,
            )
        if blend_mode == "semantic.camera-zoom-out":
            start_zoom = float(parameters["start_zoom"])
            pose = CameraPose(zoom=start_zoom + (1.0 - start_zoom) * progress)
            return render_camera_frame(
                background,
                self.width,
                self.height,
                pose,
                background=self.project.settings.background,
            )
        raise ValueError(f"Mode de composition sémantique inconnu : {blend_mode}")

    def frame_at(self, frame_index: int) -> np.ndarray:
        validate_frame_index(frame_index, self.frame_count)
        if self.prepared.closed:
            raise RuntimeError("Le plan de rendu sémantique a été fermé")
        background = np.empty((self.height, self.width, 3), dtype=np.uint8)
        background[:] = self.project.settings.background
        semantic_actions = []
        artwork_fit = FitMode.CONTAIN
        for entry in self.prepared.entries:
            invocation = entry.plan_entry.request.invocation
            if not self._active(entry, frame_index):
                continue
            if invocation.capability_id in {"camera.animate", "audio.play"}:
                continue
            local = frame_index - invocation.start_frame
            rendered = entry.prepared.frame_at(local)
            if invocation.capability_id in SEMANTIC_ACTION_IDS:
                stage = {
                    "object.move": 20,
                    "object.exit_frame": 20,
                    "environment.particles": 30,
                    "scene.parallax": 40,
                    "camera.inspect": 50,
                    "camera.zoom_out": 50,
                }[invocation.capability_id]
                semantic_actions.append(
                    (stage, invocation.start_frame, invocation.invocation_id, rendered)
                )
                continue
            if invocation.capability_id in {
                "artwork.present",
                "scene.depth_present",
            }:
                artwork_fit = FitMode(
                    invocation.parameters.to_dict().get(
                        "fit",
                        FitMode.CONTAIN.value,
                    )
                )
            opacity = float(invocation.parameters.to_dict().get("opacity", 1.0))
            if rendered.blend_mode == "artwork.delta":
                effected = _require_rgb(rendered.image, invocation.invocation_id)
                reference = _require_rgb(
                    rendered.reference,
                    invocation.invocation_id + ".reference",
                )
                target = self._target_for_effect(entry, frame_index)
                effected_canvas, alpha = self._transform(effected, target, frame_index)
                reference_canvas, reference_alpha = self._transform(
                    reference,
                    target,
                    frame_index,
                )
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
        for _stage, _start, _invocation_id, rendered in sorted(
            semantic_actions,
            key=lambda item: (item[0], item[1], item[2]),
        ):
            background = self._semantic_action(background, rendered, artwork_fit)
        return background

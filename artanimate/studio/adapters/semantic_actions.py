from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ..model import StudioProject
from ..semantic import (
    FrozenJsonObject,
    RenderFrame,
    RenderRequest,
    RendererDescriptor,
    RendererEvaluation,
    ResourceRef,
)
from ..semantic_actions import SEMANTIC_ACTION_IDS, SEMANTIC_ACTION_RENDERER_ID
from ..sources import validate_frame_index


_BLEND_MODES = {
    "object.move": "semantic.object-move",
    "object.exit_frame": "semantic.object-exit-frame",
    "region.blink": "semantic.region-blink",
    "scene.parallax": "semantic.scene-parallax",
    "camera.inspect": "semantic.camera-inspect",
    "camera.zoom_out": "semantic.camera-zoom-out",
    "environment.particles": "semantic.environment-particles",
}


def _ease(value: float, easing: str) -> float:
    progress = float(np.clip(value, 0.0, 1.0))
    if easing == "linear":
        return progress
    if easing == "ease-in":
        return progress * progress
    if easing == "ease-out":
        return 1.0 - (1.0 - progress) * (1.0 - progress)
    if easing == "ease-in-out":
        return progress * progress * (3.0 - 2.0 * progress)
    raise ValueError(f"Accélération sémantique inconnue : {easing}")


def _resource_ref(request: RenderRequest, kind: str) -> ResourceRef | None:
    target = request.target
    if target is None:
        return None
    return next(
        (item for item in target.resource_refs if item.kind == kind),
        None,
    )


class SemanticActionPreparedRender:
    def __init__(
        self,
        request: RenderRequest,
        *,
        resource: np.ndarray | None,
        resource_kind: str | None,
        fallback: str | None = None,
    ) -> None:
        self.request = request
        self.width = request.constraints.width
        self.height = request.constraints.height
        self.fps = request.constraints.fps
        self.frame_count = request.invocation.duration_frames
        self.resource = resource
        self.resource_kind = resource_kind
        self.fallback = fallback
        self.closed = False

    def frame_at(self, frame_index: int) -> RenderFrame:
        if self.closed:
            raise RuntimeError("Ce rendu d’action sémantique est fermé")
        local = validate_frame_index(frame_index, self.frame_count)
        values = self.request.invocation.parameters.to_dict()
        raw = 1.0 if self.frame_count == 1 else local / (self.frame_count - 1)
        progress = _ease(raw, str(values.get("easing", "ease-in-out")))
        events: list[str] = []
        if local == 0:
            events.append("started")
        if (
            self.request.invocation.capability_id == "region.blink"
            and local == int(values["close_frames"]) - 1
        ):
            events.append("blink-closed")
        if local == self.frame_count - 1:
            if self.request.invocation.capability_id == "object.exit_frame":
                events.append("object-exited")
            events.append("completed")
        bounds = None
        if self.request.target is not None and self.request.target.bounds is not None:
            target_bounds = self.request.target.bounds
            bounds = {
                "x": target_bounds.x,
                "y": target_bounds.y,
                "width": target_bounds.width,
                "height": target_bounds.height,
            }
        metadata: dict[str, Any] = {
            "capability_id": self.request.invocation.capability_id,
            "invocation_id": self.request.invocation.invocation_id,
            "target_id": self.request.invocation.target_id,
            "progress": progress,
            "raw_progress": raw,
            "local_frame": local,
            "frame_count": self.frame_count,
            "events": events,
            "parameters": values,
            "seed": int(values.get("seed", 0)),
            "resource_kind": self.resource_kind,
            "target_bounds": bounds,
            "target_attributes": (
                self.request.target.attributes.to_dict()
                if self.request.target is not None
                else {}
            ),
        }
        if self.fallback is not None:
            metadata["fallback"] = self.fallback
        return RenderFrame(
            image=None,
            alpha=self.resource,
            blend_mode=_BLEND_MODES[self.request.invocation.capability_id],
            metadata=FrozenJsonObject(metadata, where="semantic_action.frame"),
        )

    def close(self) -> None:
        self.closed = True
        self.resource = None


class LocalSemanticActionRenderer:
    descriptor = RendererDescriptor(
        SEMANTIC_ACTION_RENDERER_ID,
        "Actions sémantiques locales",
        tuple(sorted(SEMANTIC_ACTION_IDS)),
        version="1",
        deterministic=True,
        offline=True,
        supports_alpha=True,
        priority=200,
    )

    def __init__(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        *,
        resource_base: str | Path | None = None,
    ) -> None:
        self.project = project.validate()
        self.artwork_path = Path(artwork_path).resolve(strict=False)
        self.resource_base = (
            Path(resource_base).resolve(strict=False)
            if resource_base is not None
            else self.artwork_path.parent
        )
        self._assets = {item.asset_id: item for item in project.assets}

    def _resource_path(self, request: RenderRequest, kind: str) -> Path | None:
        reference = _resource_ref(request, kind)
        if reference is None:
            return None
        if reference.asset_id == self.project.artwork.asset_id:
            return self.artwork_path
        asset = self._assets.get(reference.asset_id)
        if asset is None:
            return None
        path = Path(asset.path)
        return path.resolve(strict=False) if path.is_absolute() else (self.resource_base / path).resolve(strict=False)

    def _resource_problem(self, request: RenderRequest, kind: str) -> str | None:
        path = self._resource_path(request, kind)
        if path is None:
            return f"ressource {kind} non référencée"
        if not path.is_file():
            return f"ressource {kind} introuvable : {path}"
        return None

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        capability_id = request.invocation.capability_id
        if capability_id not in SEMANTIC_ACTION_IDS:
            return RendererEvaluation(False, reasons=("capability non prise en charge",))
        reasons: list[str] = []
        if capability_id in {"object.move", "object.exit_frame", "region.blink"}:
            problem = self._resource_problem(request, "mask")
            if problem:
                reasons.append(problem)
        elif capability_id == "scene.parallax":
            problem = self._resource_problem(request, "depth")
            if problem:
                reasons.append(problem)
        elif capability_id == "camera.inspect" and (
            request.target is None or request.target.bounds is None
        ):
            reasons.append("la cible ne possède aucun cadrage normalisé")
        values = request.invocation.parameters.to_dict()
        if capability_id == "object.move":
            destination = values.get("destination", [0.5, 0.5])
            if any(not -0.5 <= float(item) <= 1.5 for item in destination):
                reasons.append("la destination doit rester proche du cadre normalisé")
        if capability_id == "scene.parallax":
            travel = values.get("travel", [0.0, 0.0])
            if any(abs(float(item)) > 0.25 for item in travel):
                reasons.append("le déplacement parallax dépasse 25 % du cadre")
        if capability_id == "region.blink":
            duration = (
                int(values.get("close_frames", 0))
                + int(values.get("hold_frames", 0))
                + int(values.get("open_frames", 0))
            )
            if duration != request.invocation.duration_frames:
                reasons.append("la durée du blink doit être la somme fermeture + maintien + ouverture")
        if capability_id == "environment.particles":
            color = str(values.get("color", "#ffffff"))
            if len(color) not in {4, 7} or not color.startswith("#"):
                reasons.append("la couleur doit utiliser la notation #RGB ou #RRGGBB")
            else:
                try:
                    int(color[1:], 16)
                except ValueError:
                    reasons.append("la couleur contient des chiffres hexadécimaux invalides")
        if reasons:
            return RendererEvaluation(False, reasons=tuple(reasons))
        return RendererEvaluation(True, score=200)

    def _load_resource(self, request: RenderRequest, kind: str) -> np.ndarray:
        path = self._resource_path(request, kind)
        if path is None:
            raise ValueError(f"Ressource {kind} absente pour l’action")
        try:
            with Image.open(path) as image:
                gray = ImageOps.exif_transpose(image).convert("L")
                gray.load()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError(f"Ressource {kind} illisible : {path}") from exc
        reference = _resource_ref(request, kind)
        array = np.asarray(gray, dtype=np.float32) / 255.0
        if reference is not None and bool(reference.metadata.get("invert", False)):
            array = 1.0 - array
        return np.ascontiguousarray(array, dtype=np.float32)

    def prepare(self, request: RenderRequest) -> SemanticActionPreparedRender:
        evaluation = self.evaluate(request)
        if not evaluation.compatible:
            raise ValueError("Action sémantique impossible : " + "; ".join(evaluation.reasons))
        capability_id = request.invocation.capability_id
        if capability_id in {"object.move", "object.exit_frame", "region.blink"}:
            resource = self._load_resource(request, "mask")
            return SemanticActionPreparedRender(
                request,
                resource=resource,
                resource_kind="mask",
            )
        if capability_id == "scene.parallax":
            return SemanticActionPreparedRender(
                request,
                resource=self._load_resource(request, "depth"),
                resource_kind="depth",
            )
        if capability_id == "environment.particles":
            path = self._resource_path(request, "mask")
            resource = self._load_resource(request, "mask") if path is not None and path.is_file() else None
            return SemanticActionPreparedRender(
                request,
                resource=resource,
                resource_kind="mask" if resource is not None else None,
                fallback=None if resource is not None else "full-scene",
            )
        return SemanticActionPreparedRender(
            request,
            resource=None,
            resource_kind=None,
        )

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Event
from typing import Protocol
from uuid import uuid4

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .assets import fingerprint_file, import_media_asset
from .model import AssetKind, MediaAsset, StudioProject
from .semantic import (
    Affordance,
    AffordanceSet,
    AnalyzerRun,
    Bounds,
    FrozenJsonObject,
    ResourceRef,
    SceneObject,
    SceneRelation,
    SemanticScene,
)


LOCAL_ANALYZER_ID = "analyzer.local-composition"
LOCAL_ANALYZER_VERSION = "1"
ANALYSIS_MANIFEST_VERSION = 1


class AnalysisCancelled(RuntimeError):
    """Raised when an analysis is cancelled at a deterministic boundary."""


@dataclass(frozen=True, slots=True)
class SceneAnalysisRequest:
    artwork_path: Path
    artwork_asset_id: str
    cache_dir: Path
    cancelled: Event
    parameters: FrozenJsonObject = FrozenJsonObject()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artwork_path", Path(self.artwork_path))
        object.__setattr__(self, "cache_dir", Path(self.cache_dir))
        if not isinstance(self.parameters, FrozenJsonObject):
            object.__setattr__(
                self,
                "parameters",
                FrozenJsonObject(self.parameters, where="analysis.parameters"),
            )


@dataclass(frozen=True, slots=True)
class SceneAnalysisResult:
    analyzer_id: str
    analyzer_version: str
    source_fingerprint: str
    width: int
    height: int
    objects: tuple[SceneObject, ...]
    relations: tuple[SceneRelation, ...]
    assets: tuple[MediaAsset, ...]
    artwork_resources: tuple[ResourceRef, ...]
    artwork_affordances: tuple[Affordance, ...]
    background_resources: tuple[ResourceRef, ...] = ()
    background_affordances: tuple[Affordance, ...] = ()
    parameters: FrozenJsonObject = FrozenJsonObject()
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Une analyse doit conserver les dimensions de l’œuvre")
        if not self.source_fingerprint:
            raise ValueError("Une analyse doit conserver le fingerprint de sa source")
        asset_ids = {asset.asset_id for asset in self.assets}
        for asset in self.assets:
            asset.validate()
        for resource in (*self.artwork_resources, *self.background_resources):
            if resource.asset_id not in asset_ids:
                raise ValueError("Une ressource d’analyse référence un asset absent")
        for scene_object in self.objects:
            for resource in scene_object.resource_refs:
                if resource.asset_id not in asset_ids:
                    raise ValueError("Un objet analysé référence un asset absent")


class SceneAnalyzer(Protocol):
    analyzer_id: str
    version: str

    def analyze(self, request: SceneAnalysisRequest) -> SceneAnalysisResult: ...


def _check_cancelled(cancelled: Event) -> None:
    if cancelled.is_set():
        raise AnalysisCancelled("Analyse locale annulée")


def _cache_key(fingerprint: str) -> str:
    return sha256(fingerprint.encode("utf-8")).hexdigest()[:24]


def _atomic_png(image: Image.Image, destination: Path) -> None:
    temporary = destination.with_name(destination.stem + ".tmp.png")
    image.save(temporary, format="PNG", optimize=True)
    os.replace(temporary, destination)


def _atomic_json(payload: Mapping[str, object], destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def _derived_asset(
    asset_id: str,
    path: Path,
    *,
    width: int,
    height: int,
    resource_kind: str,
    analyzer_id: str,
    analyzer_version: str,
    source_fingerprint: str,
) -> MediaAsset:
    identity = fingerprint_file(path)
    return MediaAsset(
        asset_id,
        AssetKind.IMAGE,
        str(path.resolve(strict=False)),
        fingerprint=identity.fingerprint,
        width=width,
        height=height,
        metadata={
            "derived_by": analyzer_id,
            "analyzer_version": analyzer_version,
            "source_fingerprint": source_fingerprint,
            "resource_kind": resource_kind,
            "file_size": identity.size,
            "modified_ns": identity.modified_ns,
        },
    ).validate()


class LocalCompositionAnalyzer:
    """Deterministic, model-free foreground and depth enrichment."""

    analyzer_id = LOCAL_ANALYZER_ID
    version = LOCAL_ANALYZER_VERSION

    def analyze(self, request: SceneAnalysisRequest) -> SceneAnalysisResult:
        _check_cancelled(request.cancelled)
        source = request.artwork_path.resolve(strict=True)
        identity = fingerprint_file(source)
        key = _cache_key(identity.fingerprint)
        cache = request.cache_dir / self.analyzer_id / self.version / key
        cache.mkdir(parents=True, exist_ok=True)
        manifest_path = cache / "analysis.json"
        mask_path = cache / "foreground-mask.png"
        depth_path = cache / "depth-map.png"
        if manifest_path.is_file() and mask_path.is_file() and depth_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    manifest.get("manifest_version") == ANALYSIS_MANIFEST_VERSION
                    and manifest.get("source_fingerprint") == identity.fingerprint
                    and manifest.get("analyzer_version") == self.version
                ):
                    return self._result_from_manifest(
                        manifest,
                        mask_path,
                        depth_path,
                        cache_hit=True,
                    )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass

        _check_cancelled(request.cancelled)
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
        width, height = image.size
        analysis_width = min(width, 256)
        analysis_height = max(1, int(round(height * analysis_width / width)))
        if analysis_height > 256:
            analysis_height = 256
            analysis_width = max(1, int(round(width * analysis_height / height)))
        small = image.resize(
            (analysis_width, analysis_height),
            Image.Resampling.BILINEAR,
        )
        pixels = np.asarray(small, dtype=np.float32)
        _check_cancelled(request.cancelled)

        border_size = max(1, min(analysis_width, analysis_height) // 24)
        border = np.concatenate(
            (
                pixels[:border_size].reshape(-1, 3),
                pixels[-border_size:].reshape(-1, 3),
                pixels[:, :border_size].reshape(-1, 3),
                pixels[:, -border_size:].reshape(-1, 3),
            ),
            axis=0,
        )
        background = np.median(border, axis=0)
        distance = np.linalg.norm(pixels - background, axis=2) / np.sqrt(3 * 255**2)
        threshold = max(0.07, float(np.quantile(distance, 0.62)))
        candidate = distance > threshold
        coverage = float(candidate.mean())
        fallback = coverage < 0.035 or coverage > 0.86
        if fallback:
            yy, xx = np.mgrid[0:analysis_height, 0:analysis_width]
            nx = (xx + 0.5) / analysis_width
            ny = (yy + 0.5) / analysis_height
            candidate = ((nx - 0.5) / 0.38) ** 2 + ((ny - 0.5) / 0.42) ** 2 <= 1
        mask_small = Image.fromarray(
            np.where(candidate, 255, 0).astype(np.uint8),
        ).filter(ImageFilter.MedianFilter(5))
        mask_array = np.asarray(mask_small, dtype=np.uint8) >= 128
        ys, xs = np.nonzero(mask_array)
        if not len(xs):
            xs = np.array([0, analysis_width - 1])
            ys = np.array([0, analysis_height - 1])
            fallback = True
        margin_x = max(1, analysis_width // 50)
        margin_y = max(1, analysis_height // 50)
        left = max(0, int(xs.min()) - margin_x)
        top = max(0, int(ys.min()) - margin_y)
        right = min(analysis_width, int(xs.max()) + 1 + margin_x)
        bottom = min(analysis_height, int(ys.max()) + 1 + margin_y)
        bounds = Bounds(
            left / analysis_width,
            top / analysis_height,
            max(1, right - left) / analysis_width,
            max(1, bottom - top) / analysis_height,
        )
        separation = float(np.mean(distance[mask_array])) if mask_array.any() else 0.0
        confidence = round(
            min(0.92, max(0.28 if fallback else 0.48, 0.42 + separation)),
            6,
        )

        _check_cancelled(request.cancelled)
        mask = mask_small.resize((width, height), Image.Resampling.NEAREST)
        luminance = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
        yy, xx = np.mgrid[0:height, 0:width]
        nx = (xx + 0.5) / width
        ny = (yy + 0.5) / height
        center = np.clip(1.0 - np.sqrt(((nx - 0.5) / 0.72) ** 2 + ((ny - 0.5) / 0.8) ** 2), 0.0, 1.0)
        mask_full = np.asarray(mask, dtype=np.float32) / 255.0
        depth_array = np.clip(
            0.48 * center + 0.24 * luminance + 0.28 * mask_full,
            0.0,
            1.0,
        )
        depth = Image.fromarray(
            np.round(depth_array * 255).astype(np.uint8),
        ).filter(ImageFilter.GaussianBlur(max(1.0, min(width, height) / 180.0)))
        _atomic_png(mask, mask_path)
        _check_cancelled(request.cancelled)
        _atomic_png(depth, depth_path)

        manifest: dict[str, object] = {
            "manifest_version": ANALYSIS_MANIFEST_VERSION,
            "analyzer_id": self.analyzer_id,
            "analyzer_version": self.version,
            "source_fingerprint": identity.fingerprint,
            "width": width,
            "height": height,
            "bounds": bounds.to_dict(),
            "confidence": confidence,
            "fallback": fallback,
            "parameters": request.parameters.to_dict(),
        }
        _atomic_json(manifest, manifest_path)
        return self._result_from_manifest(
            manifest,
            mask_path,
            depth_path,
            cache_hit=False,
        )

    def _result_from_manifest(
        self,
        manifest: Mapping[str, object],
        mask_path: Path,
        depth_path: Path,
        *,
        cache_hit: bool,
    ) -> SceneAnalysisResult:
        fingerprint = str(manifest["source_fingerprint"])
        width = int(manifest["width"])
        height = int(manifest["height"])
        bounds = Bounds.from_dict(manifest["bounds"])
        confidence = float(manifest["confidence"])
        fallback = bool(manifest.get("fallback", False))
        mask_asset = _derived_asset(
            "analysis:foreground-mask",
            mask_path,
            width=width,
            height=height,
            resource_kind="mask",
            analyzer_id=self.analyzer_id,
            analyzer_version=self.version,
            source_fingerprint=fingerprint,
        )
        depth_asset = _derived_asset(
            "analysis:depth-map",
            depth_path,
            width=width,
            height=height,
            resource_kind="depth",
            analyzer_id=self.analyzer_id,
            analyzer_version=self.version,
            source_fingerprint=fingerprint,
        )
        source = self.analyzer_id
        foreground = SceneObject(
            "auto-foreground",
            "subject.foreground",
            "Zone principale" if fallback else "Sujet détecté",
            confidence=confidence,
            bounds=bounds,
            resource_refs=(
                ResourceRef(
                    "analysis:foreground-mask",
                    "mask",
                    mask_asset.asset_id,
                    metadata=FrozenJsonObject({"editable": True}),
                ),
            ),
            attributes=FrozenJsonObject(
                {
                    "analysis_owner": self.analyzer_id,
                    "fallback": fallback,
                    "editable": True,
                }
            ),
            affordances=(
                Affordance("camera-inspectable", confidence, source=source),
                Affordance("frame-exitable", confidence, source=source),
                Affordance("movable", confidence, source=source),
            ),
        )
        relation = SceneRelation(
            "analysis:foreground-on-artwork",
            "part-of",
            foreground.object_id,
            "artwork",
            confidence=confidence,
            attributes=FrozenJsonObject({"analysis_owner": self.analyzer_id}),
        )
        return SceneAnalysisResult(
            self.analyzer_id,
            self.version,
            fingerprint,
            width,
            height,
            (foreground,),
            (relation,),
            (mask_asset, depth_asset),
            (
                ResourceRef(
                    "analysis:depth-map",
                    "depth",
                    depth_asset.asset_id,
                    metadata=FrozenJsonObject({"editable": False}),
                ),
            ),
            (Affordance("depth-aware", confidence, source=source),),
            background_resources=(
                ResourceRef(
                    "analysis:background-mask",
                    "mask",
                    mask_asset.asset_id,
                    metadata=FrozenJsonObject(
                        {"editable": True, "invert": True}
                    ),
                ),
            ),
            background_affordances=(
                Affordance("depth-aware", confidence, source=source),
            ),
            parameters=FrozenJsonObject(manifest.get("parameters", {})),
            cache_hit=cache_hit,
        )


def apply_scene_analysis(
    project: StudioProject,
    result: SceneAnalysisResult,
) -> StudioProject:
    project.validate()
    assert project.scene is not None
    previous_asset_ids = {
        asset.asset_id
        for asset in project.assets
        if (asset.metadata or {}).get("derived_by") == result.analyzer_id
    }
    assets = tuple(
        asset for asset in project.assets if asset.asset_id not in previous_asset_ids
    ) + result.assets
    objects: list[SceneObject] = []
    for scene_object in project.scene.objects:
        if scene_object.attributes.get("analysis_owner") == result.analyzer_id:
            continue
        attributes = scene_object.attributes
        affordances = tuple(
            item for item in scene_object.affordances
            if item.source != result.analyzer_id
        )
        resources = tuple(
            item for item in scene_object.resource_refs
            if item.asset_id not in previous_asset_ids
        )
        if scene_object.semantic_type == "artwork":
            affordances = AffordanceSet.merge(
                affordances,
                result.artwork_affordances,
            ).values
            resources = (*resources, *result.artwork_resources)
            artwork_attributes = scene_object.attributes.to_dict()
            artwork_attributes.update(
                fingerprint=result.source_fingerprint,
                width=result.width,
                height=result.height,
            )
            attributes = FrozenJsonObject(artwork_attributes)
        elif scene_object.semantic_type == "scene.background":
            affordances = AffordanceSet.merge(
                affordances,
                result.background_affordances,
            ).values
            resources = (*resources, *result.background_resources)
        objects.append(
            replace(
                scene_object,
                affordances=affordances,
                resource_refs=resources,
                attributes=attributes,
            )
        )
    objects.extend(result.objects)
    relations = tuple(
        item for item in project.scene.relations
        if item.attributes.get("analysis_owner") != result.analyzer_id
    ) + result.relations
    provenance = tuple(
        item for item in project.scene.analyzer_provenance
        if item.analyzer_id != result.analyzer_id
    ) + (
        AnalyzerRun(
            result.analyzer_id,
            result.analyzer_version,
            result.source_fingerprint,
            result.parameters,
        ),
    )
    scene = replace(
        project.scene,
        objects=tuple(objects),
        relations=relations,
        analyzer_provenance=provenance,
    )
    artwork = replace(
        project.artwork,
        fingerprint=result.source_fingerprint,
        width=result.width,
        height=result.height,
    )
    return replace(project, artwork=artwork, assets=assets, scene=scene).validate()


def invalidate_stale_scene_analysis(project: StudioProject) -> StudioProject:
    """Remove analyzer-owned facts that target an older artwork fingerprint."""
    project.validate()
    assert project.scene is not None
    current_fingerprint = project.artwork.fingerprint
    stale_analyzers = {
        run.analyzer_id
        for run in project.scene.analyzer_provenance
        if current_fingerprint is None
        or run.source_fingerprint != current_fingerprint
    }
    stale_asset_ids = {
        asset.asset_id
        for asset in project.assets
        if (asset.metadata or {}).get("derived_by") in stale_analyzers
    }
    stale_object_ids = {
        scene_object.object_id
        for scene_object in project.scene.objects
        if scene_object.attributes.get("analysis_owner") in stale_analyzers
    }
    objects: list[SceneObject] = []
    for scene_object in project.scene.objects:
        if scene_object.object_id in stale_object_ids:
            continue
        resources = tuple(
            resource for resource in scene_object.resource_refs
            if resource.asset_id not in stale_asset_ids
        )
        affordances = tuple(
            item for item in scene_object.affordances
            if item.source not in stale_analyzers
        )
        attributes = scene_object.attributes
        if scene_object.semantic_type == "artwork":
            values = attributes.to_dict()
            if current_fingerprint is not None:
                values["fingerprint"] = current_fingerprint
            if project.artwork.width is not None:
                values["width"] = project.artwork.width
            if project.artwork.height is not None:
                values["height"] = project.artwork.height
            attributes = FrozenJsonObject(values)
        objects.append(
            replace(
                scene_object,
                resource_refs=resources,
                affordances=affordances,
                attributes=attributes,
            )
        )
    relations = tuple(
        relation for relation in project.scene.relations
        if relation.source_id not in stale_object_ids
        and relation.target_id not in stale_object_ids
        and relation.attributes.get("analysis_owner") not in stale_analyzers
    )
    removed_invocations = {
        invocation.invocation_id
        for invocation in project.invocations
        if invocation.target_id in stale_object_ids
    }
    invocations = tuple(
        invocation for invocation in project.invocations
        if invocation.invocation_id not in removed_invocations
    )
    triggers = tuple(
        trigger for trigger in project.triggers
        if trigger.source_invocation_id not in removed_invocations
        and trigger.action_invocation_id not in removed_invocations
    )
    scene = replace(
        project.scene,
        objects=tuple(objects),
        relations=relations,
        analyzer_provenance=tuple(
            run for run in project.scene.analyzer_provenance
            if run.analyzer_id not in stale_analyzers
        ),
    )
    assets = tuple(
        asset for asset in project.assets if asset.asset_id not in stale_asset_ids
    )
    return replace(
        project,
        assets=assets,
        scene=scene,
        invocations=invocations,
        triggers=triggers,
    ).validate()


def add_manual_selection(
    project: StudioProject,
    bounds: Bounds,
    *,
    label: str = "Zone manuelle",
) -> tuple[StudioProject, SceneObject]:
    project.validate()
    assert project.scene is not None
    scene_object = SceneObject(
        f"manual-{uuid4().hex}",
        "object.manual",
        label.strip() or "Zone manuelle",
        bounds=bounds,
        attributes=FrozenJsonObject({"editable": True, "manual": True}),
        affordances=(
            Affordance("camera-inspectable", source="manual.selection"),
            Affordance("frame-exitable", source="manual.selection"),
            Affordance("movable", source="manual.selection"),
        ),
    )
    scene = replace(project.scene, objects=(*project.scene.objects, scene_object))
    return replace(project, scene=scene).validate(), scene_object


def add_manual_mask(
    project: StudioProject,
    mask_path: str | Path,
    project_path: str | Path,
    bounds: Bounds,
    *,
    label: str = "Objet détouré",
) -> tuple[StudioProject, SceneObject]:
    project.validate()
    assert project.scene is not None
    asset_id = f"manual-mask-{uuid4().hex}"
    imported = import_media_asset(
        mask_path,
        AssetKind.IMAGE,
        project_path,
        asset_id=asset_id,
    )
    asset = replace(
        imported,
        metadata={
            **(imported.metadata or {}),
            "derived_by": "manual",
            "resource_kind": "mask",
        },
    ).validate()
    scene_object = SceneObject(
        f"manual-{uuid4().hex}",
        "object.manual-mask",
        label.strip() or "Objet détouré",
        bounds=bounds,
        resource_refs=(
            ResourceRef(
                f"resource:{asset_id}",
                "mask",
                asset.asset_id,
                metadata=FrozenJsonObject({"editable": True}),
            ),
        ),
        attributes=FrozenJsonObject({"editable": True, "manual": True}),
        affordances=(
            Affordance("camera-inspectable", source="manual.mask"),
            Affordance("frame-exitable", source="manual.mask"),
            Affordance("movable", source="manual.mask"),
        ),
    )
    scene = replace(project.scene, objects=(*project.scene.objects, scene_object))
    return (
        replace(project, assets=(*project.assets, asset), scene=scene).validate(),
        scene_object,
    )


def update_scene_object_bounds(
    project: StudioProject,
    object_id: str,
    bounds: Bounds,
    *,
    label: str | None = None,
) -> StudioProject:
    project.validate()
    assert project.scene is not None
    found = False
    objects: list[SceneObject] = []
    for scene_object in project.scene.objects:
        if scene_object.object_id != object_id:
            objects.append(scene_object)
            continue
        if scene_object.semantic_type in {"artwork", "scene.background", "scene.camera"}:
            raise ValueError("Cet élément structurel ne peut pas être redéfini")
        found = True
        objects.append(
            replace(
                scene_object,
                bounds=bounds,
                label=(label.strip() if label and label.strip() else scene_object.label),
                attributes=FrozenJsonObject(
                    {**scene_object.attributes.to_dict(), "corrected_manually": True}
                ),
            )
        )
    if not found:
        raise KeyError(f"Objet de scène introuvable : {object_id}")
    return replace(
        project,
        scene=replace(project.scene, objects=tuple(objects)),
    ).validate()


def remove_scene_object(project: StudioProject, object_id: str) -> StudioProject:
    project.validate()
    assert project.scene is not None
    target = project.scene.object_by_id(object_id)
    if target is None:
        raise KeyError(f"Objet de scène introuvable : {object_id}")
    if target.semantic_type in {"artwork", "scene.background", "scene.camera"}:
        raise ValueError("Cet élément structurel ne peut pas être ignoré")
    objects = tuple(
        item for item in project.scene.objects if item.object_id != object_id
    )
    relations = tuple(
        item for item in project.scene.relations
        if item.source_id != object_id and item.target_id != object_id
    )
    removed_invocation_ids = {
        item.invocation_id
        for item in project.invocations
        if item.target_id == object_id
    }
    invocations = tuple(
        item for item in project.invocations
        if item.invocation_id not in removed_invocation_ids
    )
    triggers = tuple(
        item for item in project.triggers
        if item.source_invocation_id not in removed_invocation_ids
        and item.action_invocation_id not in removed_invocation_ids
    )
    removed_clip_ids = {
        clip.clip_id
        for track in project.tracks
        for clip in track.clips
        if clip.invocation_id in removed_invocation_ids
    }
    tracks = tuple(
        replace(
            track,
            clips=tuple(
                clip for clip in track.clips if clip.clip_id not in removed_clip_ids
            ),
        )
        for track in project.tracks
    )
    transitions = tuple(
        item for item in project.transitions
        if item.from_clip_id not in removed_clip_ids and item.to_clip_id not in removed_clip_ids
    )
    referenced_assets = {
        resource.asset_id
        for item in objects
        for resource in item.resource_refs
    }
    assets = tuple(
        asset for asset in project.assets
        if asset.asset_id in referenced_assets
        or (asset.metadata or {}).get("resource_kind") not in {"mask", "depth"}
    )
    scene = replace(project.scene, objects=objects, relations=relations)
    return replace(
        project,
        tracks=tracks,
        transitions=transitions,
        assets=assets,
        scene=scene,
        invocations=invocations,
        triggers=triggers,
    ).validate()

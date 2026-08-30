from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFilter

from .assets import import_media_asset
from .model import AssetKind, MediaAsset, StudioProject
from .semantic import (
    Affordance,
    AnalyzerRun,
    Bounds,
    CapabilityInvocation,
    FrozenJsonObject,
    ResourceRef,
    SceneObject,
    SceneRelation,
    TimelineTrigger,
)
from .semantic_actions import add_semantic_action_clip, semantic_action_catalog


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{where} doit être un objet JSON")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{where} contient une clé non textuelle")
    return dict(value)


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*",
        value,
    ):
        raise ValueError(f"{where} doit être un identifiant portable")
    return value


def _positive_integer(value: Any, where: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{where} doit être un entier supérieur ou égal à {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class RecipeSemanticRegion:
    region_id: str
    region_type: str
    label: str
    bounds: tuple[float, float, float, float]
    mask_shape: str = "ellipse"
    mask_asset: str | None = None
    feather: float = 0.08

    @classmethod
    def from_dict(cls, payload: Any, index: int) -> RecipeSemanticRegion:
        where = f"recipe.semantic_regions[{index}]"
        values = _object(payload, where)
        unknown = sorted(
            set(values) - {"id", "type", "label", "bounds", "mask"}
        )
        if unknown:
            raise ValueError(f"Clé(s) inconnue(s) dans {where} : " + ", ".join(unknown))
        raw_bounds = values.get("bounds")
        if (
            not isinstance(raw_bounds, list)
            or len(raw_bounds) != 4
            or any(isinstance(item, bool) or not isinstance(item, int | float) for item in raw_bounds)
        ):
            raise ValueError(f"{where}.bounds doit être [x, y, largeur, hauteur]")
        bounds = tuple(float(item) for item in raw_bounds)
        Bounds(*bounds)
        mask = _object(values.get("mask", {}), f"{where}.mask")
        mask_unknown = sorted(set(mask) - {"shape", "asset", "feather"})
        if mask_unknown:
            raise ValueError(
                f"Clé(s) inconnue(s) dans {where}.mask : " + ", ".join(mask_unknown)
            )
        asset = mask.get("asset")
        if asset is not None:
            asset = _identifier(asset, f"{where}.mask.asset")
        result = cls(
            _identifier(values.get("id"), f"{where}.id"),
            str(values.get("type", "free")),
            str(values.get("label", values.get("id", "Région"))).strip(),
            bounds,
            str(mask.get("shape", "ellipse")),
            asset,
            float(mask.get("feather", 0.08)),
        )
        return result.validate()

    def validate(self) -> RecipeSemanticRegion:
        if self.region_type not in {"eye", "mouth", "object", "free"}:
            raise ValueError("Le type de région doit être eye, mouth, object ou free")
        if not self.label:
            raise ValueError("Une région sémantique doit posséder un label")
        Bounds(*self.bounds)
        if self.mask_shape not in {"ellipse", "rectangle"}:
            raise ValueError("Le masque manuel doit être ellipse ou rectangle")
        if not 0.0 <= self.feather <= 0.35:
            raise ValueError("Le feather du masque doit être compris entre 0 et 0,35")
        return self

    def to_dict(self) -> dict[str, Any]:
        mask: dict[str, Any] = {
            "shape": self.mask_shape,
            "feather": self.feather,
        }
        if self.mask_asset is not None:
            mask["asset"] = self.mask_asset
        return {
            "id": self.region_id,
            "type": self.region_type,
            "label": self.label,
            "bounds": list(self.bounds),
            "mask": mask,
        }


@dataclass(frozen=True, slots=True)
class RecipeSemanticAction:
    action_id: str
    capability_id: str
    target_region_id: str
    trigger_shot_id: str
    parameters: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: Any, index: int) -> RecipeSemanticAction:
        where = f"recipe.semantic_actions[{index}]"
        values = _object(payload, where)
        unknown = sorted(
            set(values) - {"id", "capability", "target", "trigger", "parameters"}
        )
        if unknown:
            raise ValueError(f"Clé(s) inconnue(s) dans {where} : " + ", ".join(unknown))
        trigger = _object(values.get("trigger"), f"{where}.trigger")
        trigger_unknown = sorted(set(trigger) - {"event", "shot"})
        if trigger_unknown:
            raise ValueError(
                f"Clé(s) inconnue(s) dans {where}.trigger : "
                + ", ".join(trigger_unknown)
            )
        if trigger.get("event", "shot_end") != "shot_end":
            raise ValueError("Cette slice prend en charge le trigger shot_end")
        result = cls(
            _identifier(values.get("id"), f"{where}.id"),
            _identifier(values.get("capability"), f"{where}.capability"),
            _identifier(values.get("target"), f"{where}.target"),
            _identifier(trigger.get("shot"), f"{where}.trigger.shot"),
            _object(values.get("parameters", {}), f"{where}.parameters"),
        )
        if result.capability_id != "region.blink":
            raise ValueError("Cette slice sémantique prend en charge region.blink")
        return result

    @property
    def duration_frames(self) -> int:
        return (
            _positive_integer(self.parameters.get("close_frames", 6), "close_frames", 2)
            + _positive_integer(self.parameters.get("hold_frames", 2), "hold_frames")
            + _positive_integer(self.parameters.get("open_frames", 8), "open_frames", 2)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.action_id,
            "capability": self.capability_id,
            "target": self.target_region_id,
            "trigger": {"event": "shot_end", "shot": self.trigger_shot_id},
            "parameters": dict(self.parameters),
        }


def validate_recipe_semantics(
    regions: tuple[RecipeSemanticRegion, ...],
    actions: tuple[RecipeSemanticAction, ...],
    *,
    media: Mapping[str, Any],
    shot_ids: set[str],
) -> None:
    region_ids = tuple(item.region_id for item in regions)
    if len(region_ids) != len(set(region_ids)):
        raise ValueError("La recette contient deux régions sémantiques portant le même id")
    action_ids = tuple(item.action_id for item in actions)
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("La recette contient deux actions sémantiques portant le même id")
    by_region = {item.region_id: item for item in regions}
    for region in regions:
        region.validate()
        if region.mask_asset is not None:
            asset = media.get(region.mask_asset)
            if asset is None or asset.kind != AssetKind.IMAGE:
                raise ValueError(
                    f"La région {region.region_id} référence un masque image absent"
                )
    for action in actions:
        region = by_region.get(action.target_region_id)
        if region is None:
            raise ValueError(f"L’action {action.action_id} cible une région absente")
        if action.capability_id == "region.blink" and region.region_type != "eye":
            raise ValueError("region.blink exige une région de type eye")
        if action.trigger_shot_id not in shot_ids:
            raise ValueError(f"Le trigger de {action.action_id} référence un plan absent")
        action.duration_frames


def _generated_mask(
    region: RecipeSemanticRegion,
    width: int,
    height: int,
    destination: Path,
) -> None:
    scale = 4
    canvas = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(canvas)
    x, y, region_width, region_height = region.bounds
    box = (
        round(x * width * scale),
        round(y * height * scale),
        round((x + region_width) * width * scale),
        round((y + region_height) * height * scale),
    )
    if region.mask_shape == "ellipse":
        draw.ellipse(box, fill=255)
    else:
        draw.rectangle(box, fill=255)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask = canvas.resize((width, height), Image.Resampling.LANCZOS)
    if region.feather > 0.0:
        radius = max(0.5, min(region_width * width, region_height * height) * region.feather)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=radius))
    mask.save(destination)


def compile_recipe_semantics(
    project: StudioProject,
    project_path: Path,
    regions: tuple[RecipeSemanticRegion, ...],
    actions: tuple[RecipeSemanticAction, ...],
    *,
    media_by_recipe_id: Mapping[str, MediaAsset],
) -> StudioProject:
    if not regions and not actions:
        return project
    if project.scene is None:
        raise ValueError("Le projet doit posséder une scène avant de compiler ses régions")
    assets = list(project.assets)
    objects = list(project.scene.objects)
    relations = list(project.scene.relations)
    region_object_ids: dict[str, str] = {}
    actions_by_region: dict[str, list[RecipeSemanticAction]] = {}
    for action in actions:
        actions_by_region.setdefault(action.target_region_id, []).append(action)
    for region in regions:
        object_id = f"region-{region.region_id}"
        region_object_ids[region.region_id] = object_id
        if region.mask_asset is not None:
            mask_asset = media_by_recipe_id[region.mask_asset]
        else:
            generated = (
                project_path.parent
                / "assets"
                / "semantic"
                / f"region-{region.region_id}-mask.png"
            )
            _generated_mask(
                region,
                project.artwork.width or 1,
                project.artwork.height or 1,
                generated,
            )
            mask_asset = import_media_asset(
                generated,
                AssetKind.IMAGE,
                project_path,
                asset_id=f"region-mask-{region.region_id}",
            )
            mask_asset = replace(
                mask_asset,
                metadata={
                    **{
                        key: value for key, value in (mask_asset.metadata or {}).items()
                        if key != "modified_ns"
                    },
                    "resource_kind": "mask",
                    "region_id": region.region_id,
                    "source": "manual.recipe",
                },
            )
            assets.append(mask_asset)
        region_actions = actions_by_region.get(region.region_id, [])
        projection_targets = {action.trigger_shot_id for action in region_actions}
        if len(projection_targets) > 1:
            raise ValueError(
                f"La région {region.region_id} ne peut pas être projetée vers plusieurs plans dans cette slice"
            )
        projection_target = next(iter(projection_targets), None)
        projection_transition = (
            next(
                (
                    transition
                    for transition in project.transitions
                    if transition.to_clip_id == f"shot-{projection_target}"
                    and transition.kind.value == "spatial_match"
                ),
                None,
            )
            if projection_target is not None
            else None
        )
        if region_actions and projection_transition is None:
            raise ValueError(
                f"La région animée {region.region_id} exige un raccord spatial vers le plan {projection_target}"
            )
        attributes: dict[str, Any] = {
            "region_type": region.region_type,
            "provenance": {
                "analyzer_id": "manual.recipe-regions",
                "version": "1",
                "editable": True,
            },
        }
        if projection_transition is not None:
            reference_camera_frame = (
                projection_transition.duration_frames
                - projection_transition.duration_frames // 2
                - 1
            )
            attributes["projection"] = {
                "transition_id": projection_transition.transition_id,
                "target_clip_id": projection_transition.to_clip_id,
                "reference_camera_frame": reference_camera_frame,
            }
        affordances = [Affordance("region-editable", source="manual.recipe-regions")]
        if region.region_type == "eye":
            affordances.append(Affordance("blinkable", source="manual.recipe-regions"))
        objects.append(
            SceneObject(
                object_id,
                f"artwork.region.{region.region_type}",
                region.label,
                bounds=Bounds(*region.bounds),
                resource_refs=(
                    ResourceRef(
                        f"mask-{region.region_id}",
                        "mask",
                        mask_asset.asset_id,
                        metadata=FrozenJsonObject(
                            {
                                "canonical_space": "artwork",
                                "feather": region.feather,
                            }
                        ),
                    ),
                ),
                attributes=FrozenJsonObject(attributes),
                affordances=tuple(affordances),
            )
        )
        relations.append(
            SceneRelation(
                f"contains-{region.region_id}",
                "contains",
                "artwork",
                object_id,
            )
        )
    provenance = AnalyzerRun(
        "manual.recipe-regions",
        "1",
        project.artwork.fingerprint or project.project_id,
        FrozenJsonObject({"region_ids": list(region_object_ids)}),
    )
    scene = replace(
        project.scene,
        objects=tuple(objects),
        relations=tuple(relations),
        analyzer_provenance=(*project.scene.analyzer_provenance, provenance),
    )
    project = replace(project, assets=tuple(assets), scene=scene).validate()

    descriptors = {item.capability_id: item for item in semantic_action_catalog()}
    for action in actions:
        target_object_id = region_object_ids[action.target_region_id]
        source_clip = next(
            clip
            for track in project.tracks
            for clip in track.clips
            if clip.clip_id == f"shot-{action.trigger_shot_id}"
        )
        if source_clip.invocation_id is None:
            raise ValueError("Le plan déclencheur ne possède aucune invocation")
        descriptor = descriptors[action.capability_id]
        parameters = descriptor.normalize_parameters(action.parameters)
        duration = action.duration_frames
        start = source_clip.end_frame - duration
        invocation = CapabilityInvocation(
            f"action-{action.action_id}",
            action.capability_id,
            start,
            duration,
            target_id=target_object_id,
            parameters=parameters,
        )
        project, action_clip = add_semantic_action_clip(project, invocation)
        stable_clip_id = f"semantic-action-{action.action_id}"
        project = replace(
            project,
            tracks=tuple(
                replace(
                    track,
                    clips=tuple(
                        replace(clip, clip_id=stable_clip_id)
                        if clip.clip_id == action_clip.clip_id
                        else clip
                        for clip in track.clips
                    ),
                )
                for track in project.tracks
            ),
        ).validate()
        project = replace(
            project,
            triggers=(
                *project.triggers,
                TimelineTrigger(
                    f"trigger-{action.action_id}",
                    source_clip.invocation_id,
                    "completed",
                    invocation.invocation_id,
                    -duration,
                ),
            ),
        ).validate()
    return project.validate()

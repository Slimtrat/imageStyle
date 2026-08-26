from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .affordances import Affordance, AffordanceSet
from .common import FrozenJsonObject, confidence, finite_number, identifier


@dataclass(frozen=True, slots=True)
class Bounds:
    """Normalized artwork-local rectangle."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        x = finite_number(self.x, "bounds.x")
        y = finite_number(self.y, "bounds.y")
        width = finite_number(self.width, "bounds.width")
        height = finite_number(self.height, "bounds.height")
        if width <= 0.0 or height <= 0.0:
            raise ValueError("Les dimensions d'une bounds doivent être positives")
        tolerance = 1e-9
        if x < -tolerance or y < -tolerance or x + width > 1.0 + tolerance or y + height > 1.0 + tolerance:
            raise ValueError("Une bounds doit rester dans le repère normalisé de l'œuvre")

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "Bounds":
        if not isinstance(values, Mapping):
            raise TypeError("bounds doit être un objet JSON")
        unknown = set(values) - {"x", "y", "width", "height"}
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans bounds : " + ", ".join(sorted(unknown)))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ResourceRef:
    resource_id: str
    kind: str
    asset_id: str
    metadata: FrozenJsonObject = field(default_factory=FrozenJsonObject)

    def __post_init__(self) -> None:
        identifier(self.resource_id, "resource.resource_id")
        identifier(self.kind, "resource.kind")
        identifier(self.asset_id, "resource.asset_id")
        if not isinstance(self.metadata, FrozenJsonObject):
            object.__setattr__(
                self,
                "metadata",
                FrozenJsonObject(self.metadata, where="resource.metadata"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "kind": self.kind,
            "asset_id": self.asset_id,
            "metadata": self.metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ResourceRef":
        if not isinstance(values, Mapping):
            raise TypeError("Une ressource de scène doit être un objet JSON")
        unknown = set(values) - {"resource_id", "kind", "asset_id", "metadata"}
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans ResourceRef : " + ", ".join(sorted(unknown)))
        return cls(
            resource_id=values["resource_id"],
            kind=values["kind"],
            asset_id=values["asset_id"],
            metadata=FrozenJsonObject(values.get("metadata", {}), where="resource.metadata"),
        )


@dataclass(frozen=True, slots=True)
class SceneObject:
    object_id: str
    semantic_type: str
    label: str
    confidence: float = 1.0
    bounds: Bounds | None = None
    resource_refs: tuple[ResourceRef, ...] = ()
    attributes: FrozenJsonObject = field(default_factory=FrozenJsonObject)
    affordances: tuple[Affordance, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.object_id, "scene_object.object_id")
        identifier(self.semantic_type, "scene_object.semantic_type")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Un objet de scène doit avoir un label")
        confidence(self.confidence, "scene_object.confidence")
        resource_ids = tuple(item.resource_id for item in self.resource_refs)
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("Un objet de scène contient des ressources dupliquées")
        normalized = AffordanceSet(self.affordances)
        object.__setattr__(self, "affordances", normalized.values)
        if not isinstance(self.attributes, FrozenJsonObject):
            object.__setattr__(
                self,
                "attributes",
                FrozenJsonObject(self.attributes, where="scene_object.attributes"),
            )

    @property
    def affordance_ids(self) -> frozenset[str]:
        return frozenset(item.affordance_id for item in self.affordances)

    @property
    def resource_kinds(self) -> frozenset[str]:
        return frozenset(item.kind for item in self.resource_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "semantic_type": self.semantic_type,
            "label": self.label,
            "confidence": self.confidence,
            "bounds": self.bounds.to_dict() if self.bounds is not None else None,
            "resource_refs": [item.to_dict() for item in self.resource_refs],
            "attributes": self.attributes.to_dict(),
            "affordances": [item.to_dict() for item in self.affordances],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SceneObject":
        if not isinstance(values, Mapping):
            raise TypeError("Un objet de scène doit être un objet JSON")
        allowed = {
            "object_id",
            "semantic_type",
            "label",
            "confidence",
            "bounds",
            "resource_refs",
            "attributes",
            "affordances",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans SceneObject : " + ", ".join(sorted(unknown)))
        return cls(
            object_id=values["object_id"],
            semantic_type=values["semantic_type"],
            label=values["label"],
            confidence=values.get("confidence", 1.0),
            bounds=Bounds.from_dict(values["bounds"]) if values.get("bounds") is not None else None,
            resource_refs=tuple(ResourceRef.from_dict(item) for item in values.get("resource_refs", [])),
            attributes=FrozenJsonObject(values.get("attributes", {}), where="scene_object.attributes"),
            affordances=tuple(Affordance.from_dict(item) for item in values.get("affordances", [])),
        )


@dataclass(frozen=True, slots=True)
class SceneRelation:
    relation_id: str
    relation_type: str
    source_id: str
    target_id: str
    confidence: float = 1.0
    attributes: FrozenJsonObject = field(default_factory=FrozenJsonObject)

    def __post_init__(self) -> None:
        identifier(self.relation_id, "relation.relation_id")
        identifier(self.relation_type, "relation.relation_type")
        identifier(self.source_id, "relation.source_id")
        identifier(self.target_id, "relation.target_id")
        if self.source_id == self.target_id:
            raise ValueError("Une relation de scène doit relier deux objets différents")
        confidence(self.confidence, "relation.confidence")
        if not isinstance(self.attributes, FrozenJsonObject):
            object.__setattr__(
                self,
                "attributes",
                FrozenJsonObject(self.attributes, where="relation.attributes"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "confidence": self.confidence,
            "attributes": self.attributes.to_dict(),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SceneRelation":
        if not isinstance(values, Mapping):
            raise TypeError("Une relation de scène doit être un objet JSON")
        allowed = {"relation_id", "relation_type", "source_id", "target_id", "confidence", "attributes"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans SceneRelation : " + ", ".join(sorted(unknown)))
        return cls(
            relation_id=values["relation_id"],
            relation_type=values["relation_type"],
            source_id=values["source_id"],
            target_id=values["target_id"],
            confidence=values.get("confidence", 1.0),
            attributes=FrozenJsonObject(values.get("attributes", {}), where="relation.attributes"),
        )


@dataclass(frozen=True, slots=True)
class AnalyzerRun:
    analyzer_id: str
    version: str
    source_fingerprint: str
    parameters: FrozenJsonObject = field(default_factory=FrozenJsonObject)

    def __post_init__(self) -> None:
        identifier(self.analyzer_id, "analyzer.analyzer_id")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("La version d'un analyzer doit être renseignée")
        if not isinstance(self.source_fingerprint, str) or not self.source_fingerprint.strip():
            raise ValueError("Le fingerprint analysé doit être renseigné")
        if not isinstance(self.parameters, FrozenJsonObject):
            object.__setattr__(
                self,
                "parameters",
                FrozenJsonObject(self.parameters, where="analyzer.parameters"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_id": self.analyzer_id,
            "version": self.version,
            "source_fingerprint": self.source_fingerprint,
            "parameters": self.parameters.to_dict(),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "AnalyzerRun":
        if not isinstance(values, Mapping):
            raise TypeError("Une provenance d'analyse doit être un objet JSON")
        allowed = {"analyzer_id", "version", "source_fingerprint", "parameters"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans AnalyzerRun : " + ", ".join(sorted(unknown)))
        return cls(
            analyzer_id=values["analyzer_id"],
            version=values["version"],
            source_fingerprint=values["source_fingerprint"],
            parameters=FrozenJsonObject(values.get("parameters", {}), where="analyzer.parameters"),
        )


@dataclass(frozen=True, slots=True)
class SemanticScene:
    scene_id: str
    artwork_asset_id: str
    objects: tuple[SceneObject, ...]
    relations: tuple[SceneRelation, ...] = ()
    analyzer_provenance: tuple[AnalyzerRun, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.scene_id, "scene.scene_id")
        identifier(self.artwork_asset_id, "scene.artwork_asset_id")
        if not self.objects:
            raise ValueError("Une scène doit contenir au moins l'œuvre")
        object_ids = tuple(item.object_id for item in self.objects)
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("La scène contient des identifiants d'objets dupliqués")
        known = set(object_ids)
        relation_ids: set[str] = set()
        for relation in self.relations:
            if relation.relation_id in relation_ids:
                raise ValueError("La scène contient des relations dupliquées")
            relation_ids.add(relation.relation_id)
            if relation.source_id not in known or relation.target_id not in known:
                raise ValueError(
                    f"La relation {relation.relation_id} référence un objet absent"
                )
        if not any(item.semantic_type == "artwork" for item in self.objects):
            raise ValueError("La scène doit contenir un objet sémantique 'artwork'")

    @classmethod
    def minimal(
        cls,
        artwork_asset_id: str,
        *,
        scene_id: str | None = None,
    ) -> "SemanticScene":
        """Create the no-model fallback available for every imported artwork."""
        return cls(
            scene_id=scene_id or f"scene-{uuid4().hex}",
            artwork_asset_id=artwork_asset_id,
            objects=(
                SceneObject(
                    "artwork",
                    "artwork",
                    "Œuvre",
                    bounds=Bounds(0.0, 0.0, 1.0, 1.0),
                    affordances=(
                        Affordance("presentable", source="builtin.minimal"),
                        Affordance("camera-inspectable", source="builtin.minimal"),
                        Affordance("effect-applicable", source="builtin.minimal"),
                    ),
                ),
                SceneObject(
                    "background",
                    "scene.background",
                    "Arrière-plan",
                    bounds=Bounds(0.0, 0.0, 1.0, 1.0),
                    affordances=(Affordance("presentable", source="builtin.minimal"),),
                ),
                SceneObject(
                    "camera",
                    "scene.camera",
                    "Caméra",
                    affordances=(Affordance("animatable", source="builtin.minimal"),),
                ),
            ),
        )

    def object_by_id(self, object_id: str) -> SceneObject | None:
        return next((item for item in self.objects if item.object_id == object_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "artwork_asset_id": self.artwork_asset_id,
            "objects": [item.to_dict() for item in self.objects],
            "relations": [item.to_dict() for item in self.relations],
            "analyzer_provenance": [item.to_dict() for item in self.analyzer_provenance],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SemanticScene":
        if not isinstance(values, Mapping):
            raise TypeError("Une scène doit être un objet JSON")
        allowed = {"scene_id", "artwork_asset_id", "objects", "relations", "analyzer_provenance"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans SemanticScene : " + ", ".join(sorted(unknown)))
        return cls(
            scene_id=values["scene_id"],
            artwork_asset_id=values["artwork_asset_id"],
            objects=tuple(SceneObject.from_dict(item) for item in values.get("objects", [])),
            relations=tuple(SceneRelation.from_dict(item) for item in values.get("relations", [])),
            analyzer_provenance=tuple(AnalyzerRun.from_dict(item) for item in values.get("analyzer_provenance", [])),
        )

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .common import FrozenJsonObject, JsonValue, confidence, finite_number, identifier, thaw_json


_VALUE_TYPES = frozenset(
    {"any", "boolean", "integer", "number", "string", "choice", "color", "direction", "resource", "point"}
)


def _freeze_value(value: Any, where: str) -> JsonValue:
    return FrozenJsonObject({"value": value}, where=where)["value"]


@dataclass(frozen=True, slots=True)
class CapabilityParameter:
    parameter_id: str
    label: str
    value_type: str
    required: bool = False
    default: JsonValue = None
    has_default: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[JsonValue, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        identifier(self.parameter_id, "capability_parameter.parameter_id")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Un paramètre de capability doit avoir un label")
        identifier(self.value_type, "capability_parameter.value_type")
        if self.value_type not in _VALUE_TYPES:
            raise ValueError(
                f"Type de paramètre inconnu {self.value_type!r}; types disponibles : "
                + ", ".join(sorted(_VALUE_TYPES))
            )
        if not isinstance(self.required, bool) or not isinstance(self.has_default, bool):
            raise TypeError("required et has_default doivent être booléens")
        if self.required and self.has_default:
            raise ValueError("Un paramètre obligatoire ne doit pas définir de valeur par défaut")
        object.__setattr__(self, "default", _freeze_value(self.default, f"parameter {self.parameter_id}.default"))
        object.__setattr__(self, "choices", tuple(_freeze_value(item, f"parameter {self.parameter_id}.choices") for item in self.choices))
        if self.minimum is not None:
            finite_number(self.minimum, f"parameter {self.parameter_id}.minimum")
        if self.maximum is not None:
            finite_number(self.maximum, f"parameter {self.parameter_id}.maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("La borne minimum d'un paramètre dépasse son maximum")
        if self.choices and self.value_type not in {"choice", "string", "direction"}:
            raise ValueError("Des choices ne sont permis que pour choice, string ou direction")
        if self.has_default:
            self.validate_value(self.default)

    def validate_value(self, value: Any) -> JsonValue:
        frozen = _freeze_value(value, f"parameter {self.parameter_id}")
        plain = thaw_json(frozen)
        if self.value_type == "boolean" and not isinstance(plain, bool):
            raise TypeError(f"{self.parameter_id} doit être booléen")
        if self.value_type == "integer" and (isinstance(plain, bool) or not isinstance(plain, int)):
            raise TypeError(f"{self.parameter_id} doit être un entier")
        if self.value_type == "number" and (isinstance(plain, bool) or not isinstance(plain, int | float)):
            raise TypeError(f"{self.parameter_id} doit être numérique")
        if self.value_type in {"string", "choice", "color", "direction", "resource"} and not isinstance(plain, str):
            raise TypeError(f"{self.parameter_id} doit être textuel")
        if self.value_type == "point" and (
            not isinstance(plain, list)
            or len(plain) != 2
            or any(isinstance(item, bool) or not isinstance(item, int | float) for item in plain)
        ):
            raise TypeError(f"{self.parameter_id} doit être un point [x, y]")
        if isinstance(plain, int | float) and not isinstance(plain, bool):
            number = finite_number(plain, self.parameter_id)
            if self.minimum is not None and number < self.minimum:
                raise ValueError(f"{self.parameter_id} est inférieur à {self.minimum}")
            if self.maximum is not None and number > self.maximum:
                raise ValueError(f"{self.parameter_id} est supérieur à {self.maximum}")
        if self.choices and frozen not in self.choices:
            raise ValueError(f"Valeur non autorisée pour {self.parameter_id}")
        return frozen

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "label": self.label,
            "value_type": self.value_type,
            "required": self.required,
            "default": thaw_json(self.default),
            "has_default": self.has_default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": [thaw_json(item) for item in self.choices],
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapabilityParameter":
        if not isinstance(values, Mapping):
            raise TypeError("Un paramètre de capability doit être un objet JSON")
        allowed = {"parameter_id", "label", "value_type", "required", "default", "has_default", "minimum", "maximum", "choices", "description"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans CapabilityParameter : " + ", ".join(sorted(unknown)))
        return cls(
            parameter_id=values["parameter_id"], label=values["label"], value_type=values["value_type"],
            required=values.get("required", False), default=values.get("default"), has_default=values.get("has_default", False),
            minimum=values.get("minimum"), maximum=values.get("maximum"), choices=tuple(values.get("choices", ())),
            description=values.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    requirement_id: str
    description: str
    target_required: bool = True
    semantic_types: tuple[str, ...] = ()
    affordance_ids: tuple[str, ...] = ()
    resource_kinds: tuple[str, ...] = ()
    minimum_confidence: float = 0.0

    def __post_init__(self) -> None:
        identifier(self.requirement_id, "capability_requirement.requirement_id")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Une exigence de capability doit être expliquée")
        if not isinstance(self.target_required, bool):
            raise TypeError("target_required doit être booléen")
        for where, values in (("semantic_types", self.semantic_types), ("affordance_ids", self.affordance_ids), ("resource_kinds", self.resource_kinds)):
            if len(values) != len(set(values)):
                raise ValueError(f"{where} contient un identifiant dupliqué")
            for value in values:
                identifier(value, f"capability_requirement.{where}")
        confidence(self.minimum_confidence, "capability_requirement.minimum_confidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id, "description": self.description, "target_required": self.target_required,
            "semantic_types": list(self.semantic_types), "affordance_ids": list(self.affordance_ids),
            "resource_kinds": list(self.resource_kinds), "minimum_confidence": self.minimum_confidence,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapabilityRequirement":
        if not isinstance(values, Mapping):
            raise TypeError("Une exigence de capability doit être un objet JSON")
        allowed = {"requirement_id", "description", "target_required", "semantic_types", "affordance_ids", "resource_kinds", "minimum_confidence"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans CapabilityRequirement : " + ", ".join(sorted(unknown)))
        return cls(
            requirement_id=values["requirement_id"], description=values["description"], target_required=values.get("target_required", True),
            semantic_types=tuple(values.get("semantic_types", ())), affordance_ids=tuple(values.get("affordance_ids", ())),
            resource_kinds=tuple(values.get("resource_kinds", ())), minimum_confidence=values.get("minimum_confidence", 0.0),
        )


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    label: str
    category: str
    requirements: tuple[CapabilityRequirement, ...] = ()
    parameters: tuple[CapabilityParameter, ...] = ()
    renderer_candidates: tuple[str, ...] = ()
    emitted_events: tuple[str, ...] = ("completed",)
    version: str = "1"
    description: str = ""

    def __post_init__(self) -> None:
        identifier(self.capability_id, "capability.capability_id")
        identifier(self.category, "capability.category")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Une capability doit avoir un label")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Une capability doit avoir une version")
        for where, values in (
            ("requirements", tuple(item.requirement_id for item in self.requirements)),
            ("parameters", tuple(item.parameter_id for item in self.parameters)),
            ("renderer_candidates", self.renderer_candidates), ("emitted_events", self.emitted_events),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"capability.{where} contient un identifiant dupliqué")
        for renderer_id in self.renderer_candidates:
            identifier(renderer_id, "capability.renderer_candidates")
        for event_id in self.emitted_events:
            identifier(event_id, "capability.emitted_events")

    def normalize_parameters(self, values: Mapping[str, Any]) -> FrozenJsonObject:
        if not isinstance(values, Mapping):
            raise TypeError("Les paramètres d'une invocation doivent être un objet JSON")
        specs = {item.parameter_id: item for item in self.parameters}
        unknown = sorted(set(values) - set(specs))
        if unknown:
            raise ValueError(f"Paramètre(s) inconnu(s) pour {self.capability_id} : " + ", ".join(unknown))
        normalized: dict[str, Any] = {}
        for parameter_id, spec in specs.items():
            if parameter_id in values:
                normalized[parameter_id] = thaw_json(spec.validate_value(values[parameter_id]))
            elif spec.required:
                raise ValueError(f"Paramètre obligatoire manquant pour {self.capability_id} : {parameter_id}")
            elif spec.has_default:
                normalized[parameter_id] = thaw_json(spec.default)
        return FrozenJsonObject(normalized, where=f"capability {self.capability_id}.parameters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id, "label": self.label, "category": self.category,
            "requirements": [item.to_dict() for item in self.requirements], "parameters": [item.to_dict() for item in self.parameters],
            "renderer_candidates": list(self.renderer_candidates), "emitted_events": list(self.emitted_events),
            "version": self.version, "description": self.description,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapabilityDescriptor":
        if not isinstance(values, Mapping):
            raise TypeError("Une capability doit être un objet JSON")
        allowed = {"capability_id", "label", "category", "requirements", "parameters", "renderer_candidates", "emitted_events", "version", "description"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans CapabilityDescriptor : " + ", ".join(sorted(unknown)))
        return cls(
            capability_id=values["capability_id"], label=values["label"], category=values["category"],
            requirements=tuple(CapabilityRequirement.from_dict(item) for item in values.get("requirements", ())),
            parameters=tuple(CapabilityParameter.from_dict(item) for item in values.get("parameters", ())),
            renderer_candidates=tuple(values.get("renderer_candidates", ())), emitted_events=tuple(values.get("emitted_events", ("completed",))),
            version=values.get("version", "1"), description=values.get("description", ""),
        )

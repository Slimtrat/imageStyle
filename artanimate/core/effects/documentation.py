from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


DOCUMENTATION_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "docs" / "effects.fr.json"
)


@dataclass(frozen=True, slots=True)
class ChoiceDocumentation:
    """One localized option for a choice parameter."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ParameterDocumentation:
    """Localized help and UI schema for one effect-specific parameter."""

    key: str
    label: str
    control: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    default: float | None = None
    step: float | None = None
    decimals: int = 0
    suffix: str = ""
    choices: tuple[ChoiceDocumentation, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectDocumentation:
    """Localized effect copy loaded from the packaged JSON asset."""

    key: str
    selector_label: str
    description: str
    parameters: tuple[ParameterDocumentation, ...]


def _number(value: Any, field: str, key: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"Documentation {key!r} : {field} doit être numérique")
    return float(value)


def _parse_parameter(raw: Any, effect_key: str) -> ParameterDocumentation:
    if not isinstance(raw, dict):
        raise ValueError(f"Documentation {effect_key!r} : paramètre invalide")
    key = str(raw.get("key", "")).strip()
    label = str(raw.get("label", "")).strip()
    control = str(raw.get("control", "")).strip()
    description = str(raw.get("description", "")).strip()
    if not key or not label or not description or control not in {"slider", "choice"}:
        raise ValueError(f"Documentation {effect_key!r}/{key!r} incomplète")
    if control == "choice":
        raw_choices = raw.get("choices")
        if not isinstance(raw_choices, list) or not raw_choices:
            raise ValueError(f"Documentation {effect_key!r}/{key!r} : choix manquants")
        choices = tuple(
            ChoiceDocumentation(str(choice["value"]), str(choice["label"]))
            for choice in raw_choices
        )
        return ParameterDocumentation(
            key=key,
            label=label,
            control=control,
            description=description,
            choices=choices,
        )

    minimum = _number(raw.get("minimum"), "minimum", key)
    maximum = _number(raw.get("maximum"), "maximum", key)
    default = _number(raw.get("default"), "default", key)
    step = _number(raw.get("step"), "step", key)
    decimals = int(raw.get("decimals", 0))
    if maximum <= minimum or step <= 0 or not minimum <= default <= maximum:
        raise ValueError(f"Documentation {effect_key!r}/{key!r} : bornes invalides")
    return ParameterDocumentation(
        key=key,
        label=label,
        control=control,
        description=description,
        minimum=minimum,
        maximum=maximum,
        default=default,
        step=step,
        decimals=decimals,
        suffix=str(raw.get("suffix", "")),
    )


@lru_cache(maxsize=1)
def load_effect_documentation() -> dict[str, EffectDocumentation]:
    """Load and validate the packaged French effect documentation once."""
    try:
        payload = json.loads(DOCUMENTATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Documentation des effets illisible : {exc}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("effects"), dict):
        raise ValueError("Schéma de documentation des effets non pris en charge")

    result: dict[str, EffectDocumentation] = {}
    for key, raw in payload["effects"].items():
        if not isinstance(raw, dict):
            raise ValueError(f"Documentation d’effet invalide : {key!r}")
        parameters = tuple(
            _parse_parameter(parameter, str(key)) for parameter in raw.get("parameters", [])
        )
        documentation = EffectDocumentation(
            key=str(key),
            selector_label=str(raw.get("selector_label", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            parameters=parameters,
        )
        if not documentation.selector_label or not documentation.description:
            raise ValueError(f"Documentation d’effet incomplète : {key!r}")
        if len({parameter.key for parameter in parameters}) != len(parameters):
            raise ValueError(f"Paramètres dupliqués dans la documentation : {key!r}")
        result[documentation.key] = documentation
    return result


def documentation_for(key: str) -> EffectDocumentation:
    """Return localized documentation for one registered effect."""
    try:
        return load_effect_documentation()[key]
    except KeyError as exc:
        raise ValueError(f"Documentation manquante pour l’effet {key!r}") from exc

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
from typing import Any


EFFECTS = ("sand", "wave")
ORDERS = ("chromatic", "reverse", "area", "luminance")
NEUTRAL_POSITIONS = ("first", "last")
OUTLINE_MODES = ("first", "last", "together")
DIRECTIONS = ("left", "right", "top", "bottom", "diagonal", "radial")


@dataclass(slots=True)
class RenderConfig:
    effect: str = "sand"
    order: str = "chromatic"
    outline: str = "last"
    direction: str = "left"
    duration: float = 12.0
    fps: int = 30
    width: int = 1280
    colors: int = 24
    hold_start: float = 0.6
    hold_end: float = 1.2
    overlap: float = 0.16
    start_hue: float = 0.0
    neutral_position: str = "last"
    shape_completion: int = 2
    background_tolerance: float = 11.0
    outline_luma: float = 36.0
    outline_chroma: float = 34.0
    wave_amplitude: float = 0.055
    wave_frequency: float = 2.7
    turbulence: float = 0.10
    soft_edge: float = 0.012
    grain_density: float = 0.0025
    grain_size: float = 1.35
    seed: int = 7
    crf: int = 18

    def validate(self) -> "RenderConfig":
        if self.effect not in EFFECTS:
            raise ValueError(f"effect doit être l'un de : {', '.join(EFFECTS)}")
        if self.order not in ORDERS:
            raise ValueError(f"order doit être l'un de : {', '.join(ORDERS)}")
        if self.neutral_position not in NEUTRAL_POSITIONS:
            raise ValueError(
                f"neutral_position doit être l’une de : {', '.join(NEUTRAL_POSITIONS)}"
            )
        if self.outline not in OUTLINE_MODES:
            raise ValueError(f"outline doit être l'un de : {', '.join(OUTLINE_MODES)}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction doit être l'une de : {', '.join(DIRECTIONS)}")
        if self.duration <= 0 or self.fps <= 0:
            raise ValueError("duration et fps doivent être strictement positifs")
        if self.width < 64:
            raise ValueError("width doit être supérieur ou égal à 64")
        if not 2 <= self.colors <= 64:
            raise ValueError("colors doit être compris entre 2 et 64")
        if self.hold_start < 0 or self.hold_end < 0:
            raise ValueError("les pauses ne peuvent pas être négatives")
        if self.hold_start + self.hold_end >= self.duration:
            raise ValueError("la somme des pauses doit être inférieure à la durée")
        if not 0 <= self.overlap < 0.9:
            raise ValueError("overlap doit être compris entre 0 et 0.9")
        if not isinstance(self.shape_completion, int) or not 0 <= self.shape_completion <= 4:
            raise ValueError("shape_completion doit être un entier compris entre 0 et 4")
        if self.background_tolerance < 0:
            raise ValueError("background_tolerance ne peut pas être négatif")
        if not 0 <= self.outline_luma <= 100:
            raise ValueError("outline_luma doit être compris entre 0 et 100")
        if self.grain_density < 0 or self.grain_size < 0:
            raise ValueError("les paramètres de grain ne peuvent pas être négatifs")
        if not 0 <= self.crf <= 51:
            raise ValueError("crf doit être compris entre 0 et 51")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "RenderConfig":
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"Clé(s) de configuration inconnue(s) : {', '.join(unknown)}")
        return cls(**values).validate()

    @classmethod
    def from_json(cls, path: str | Path) -> "RenderConfig":
        source = Path(path)
        try:
            values = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON invalide dans {source}: {exc}") from exc
        if not isinstance(values, dict):
            raise ValueError("Le fichier de configuration doit contenir un objet JSON")
        return cls.from_dict(values)

    def with_overrides(self, values: dict[str, Any]) -> "RenderConfig":
        merged = self.to_dict()
        merged.update({key: value for key, value in values.items() if value is not None})
        return RenderConfig.from_dict(merged)

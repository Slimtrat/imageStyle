from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
from typing import Any

from .effects import EffectCapability, create_effect, effect_keys


EFFECTS = effect_keys()
ORDERS = ("chromatic", "reverse", "area", "luminance")
NEUTRAL_POSITIONS = ("first", "last")
OUTLINE_MODES = ("first", "last", "together")
QUALITY_PROFILES = ("fast", "studio")
RGB_MODES = ("channels", "together")
DIRECTIONS = ("left", "right", "top", "bottom", "diagonal", "radial")


@dataclass(slots=True)
class RenderConfig:
    effect: str = "sand"
    order: str = "chromatic"
    outline: str = "together"
    direction: str = "left"
    rgb_mode: str = "channels"
    duration: float = 18.0
    fps: int = 30
    width: int = 1280
    colors: int = 24
    hold_start: float = 0.6
    hold_end: float = 1.2
    overlap: float = 0.28
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
    grain_density: float = 0.004
    grain_size: float = 1.35
    halo_width: float = 0.075
    halo_intensity: float = 0.9
    screenprint_width: float = 0.12
    laser_width: float = 0.018
    laser_intensity: float = 1.35
    seed: int = 7
    crf: int = 16
    quality: str = "studio"

    def validate(self) -> "RenderConfig":
        if self.effect not in EFFECTS:
            raise ValueError(f"effect doit être l'un de : {', '.join(EFFECTS)}")
        if self.order not in ORDERS:
            raise ValueError(f"order doit être l'un de : {', '.join(ORDERS)}")
        effect = create_effect(self.effect)
        if (
            self.order in {"chromatic", "reverse"}
            and not effect.supports(EffectCapability.CHROMATIC_SEQUENCE)
            and not effect.supports(EffectCapability.FRAME_COMPOSITOR)
        ):
            raise ValueError(f"L’effet {self.effect!r} ne prend pas en charge la roue chromatique")
        if self.neutral_position not in NEUTRAL_POSITIONS:
            raise ValueError(
                f"neutral_position doit être l’une de : {', '.join(NEUTRAL_POSITIONS)}"
            )
        if self.outline not in OUTLINE_MODES:
            raise ValueError(f"outline doit être l'un de : {', '.join(OUTLINE_MODES)}")
        if self.quality not in QUALITY_PROFILES:
            raise ValueError(f"quality doit être l'un de : {', '.join(QUALITY_PROFILES)}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction doit être l'une de : {', '.join(DIRECTIONS)}")
        if self.rgb_mode not in RGB_MODES:
            raise ValueError(f"rgb_mode doit être l'un de : {', '.join(RGB_MODES)}")
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
        if not 0.005 <= self.halo_width <= 0.30:
            raise ValueError("halo_width doit être compris entre 0.005 et 0.30")
        if not 0.0 <= self.halo_intensity <= 3.0:
            raise ValueError("halo_intensity doit être compris entre 0 et 3")
        if not 0.02 <= self.screenprint_width <= 0.40:
            raise ValueError("screenprint_width doit être compris entre 0.02 et 0.40")
        if not 0.002 <= self.laser_width <= 0.10:
            raise ValueError("laser_width doit être compris entre 0.002 et 0.10")
        if not 0.0 <= self.laser_intensity <= 4.0:
            raise ValueError("laser_intensity doit être compris entre 0 et 4")
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

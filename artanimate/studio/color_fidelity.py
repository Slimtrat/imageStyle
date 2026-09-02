from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Mapping

import numpy as np


COLOR_POLICY_SCHEMA_VERSION = 1
FAITHFUL_MEDIAN_DELTA_E00 = 2.0
FAITHFUL_P95_DELTA_E00 = 6.0


class ArtworkColorMode(str, Enum):
    """How the authored artwork reacts to the decorative 3D lighting."""

    FAITHFUL = "faithful"
    SCENE_INTEGRATED = "scene_integrated"


@dataclass(frozen=True, slots=True)
class ArtworkColorPolicy:
    """Versioned color contract shared by preview, headless render and export.

    Qt decodes the QImage-backed texture from sRGB and shades in linear light.  The
    faithful policy disables lighting only for the artwork material, keeps unity
    exposure, and uses linear scene tone mapping.  Geometry, depth, occlusion and
    shadow casting remain handled by the 3D scene.
    """

    mode: ArtworkColorMode = ArtworkColorMode.FAITHFUL
    texture_color_space: str = "srgb"
    exposure: float = 1.0
    tone_mapping: str = "linear"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ArtworkColorMode):
            raise TypeError("color_policy.mode doit être un ArtworkColorMode")
        if self.texture_color_space != "srgb":
            raise ValueError("Seul l’espace texture sRGB est actuellement pris en charge")
        if not math.isclose(float(self.exposure), 1.0, abs_tol=1e-9):
            raise ValueError("L’exposition fidèle doit rester fixée à 1.0")
        if self.tone_mapping != "linear":
            raise ValueError("Seul le tone mapping linéaire est actuellement pris en charge")

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any] | str | None,
    ) -> "ArtworkColorPolicy":
        if values is None:
            return cls()
        if isinstance(values, str):
            return cls(mode=ArtworkColorMode(values))
        if not isinstance(values, Mapping):
            raise TypeError("color_policy doit être un objet ou un nom de mode")
        unknown = sorted(
            set(values)
            - {"schema_version", "mode", "texture_color_space", "exposure", "tone_mapping"}
        )
        if unknown:
            raise ValueError(
                "Réglages colorimétriques inconnus : " + ", ".join(unknown)
            )
        version = int(values.get("schema_version", COLOR_POLICY_SCHEMA_VERSION))
        if version != COLOR_POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"Version de politique colorimétrique non prise en charge : {version}"
            )
        try:
            mode = ArtworkColorMode(str(values.get("mode", ArtworkColorMode.FAITHFUL.value)))
        except ValueError as exc:
            accepted = ", ".join(item.value for item in ArtworkColorMode)
            raise ValueError(
                f"Mode colorimétrique inconnu ; valeurs acceptées : {accepted}"
            ) from exc
        return cls(
            mode=mode,
            texture_color_space=str(values.get("texture_color_space", "srgb")),
            exposure=float(values.get("exposure", 1.0)),
            tone_mapping=str(values.get("tone_mapping", "linear")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COLOR_POLICY_SCHEMA_VERSION,
            "mode": self.mode.value,
            "texture_color_space": self.texture_color_space,
            "exposure": self.exposure,
            "tone_mapping": self.tone_mapping,
        }

    def qml_properties(self) -> dict[str, object]:
        return {
            "artworkColorMode": self.mode.value,
            "artworkTextureColorSpace": self.texture_color_space,
            "artworkExposure": self.exposure,
            "artworkToneMapping": self.tone_mapping,
        }


@dataclass(frozen=True, slots=True)
class ColorFidelityReport:
    median_delta_e00: float
    percentile_95_delta_e00: float
    sample_count: int
    median_limit: float = FAITHFUL_MEDIAN_DELTA_E00
    percentile_95_limit: float = FAITHFUL_P95_DELTA_E00

    @property
    def passes(self) -> bool:
        return (
            self.median_delta_e00 <= self.median_limit
            and self.percentile_95_delta_e00 <= self.percentile_95_limit
        )

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "median_delta_e00": self.median_delta_e00,
            "percentile_95_delta_e00": self.percentile_95_delta_e00,
            "sample_count": self.sample_count,
            "median_limit": self.median_limit,
            "percentile_95_limit": self.percentile_95_limit,
            "passes": self.passes,
        }


def _srgb_to_lab(image: np.ndarray) -> np.ndarray:
    rgb = np.asarray(image, dtype=np.float64)
    if rgb.ndim < 2 or rgb.shape[-1] != 3:
        raise ValueError("Une image RGB est requise pour mesurer la fidélité")
    if rgb.size == 0:
        raise ValueError("L’image de mesure ne peut pas être vide")
    if np.issubdtype(np.asarray(image).dtype, np.integer):
        rgb /= 255.0
    elif float(np.nanmax(rgb)) > 1.0 or float(np.nanmin(rgb)) < 0.0:
        raise ValueError("Les images flottantes RGB doivent être comprises entre 0 et 1")
    linear = np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )
    matrix = np.array(
        (
            (0.4124564, 0.3575761, 0.1804375),
            (0.2126729, 0.7151522, 0.0721750),
            (0.0193339, 0.1191920, 0.9503041),
        ),
        dtype=np.float64,
    )
    xyz = linear @ matrix.T
    xyz /= np.array((0.95047, 1.0, 1.08883), dtype=np.float64)
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    return np.stack(
        (116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])),
        axis=-1,
    )


def delta_e_ciede2000(reference_lab: np.ndarray, rendered_lab: np.ndarray) -> np.ndarray:
    """Vectorized CIEDE2000 implementation using the standard 1/1/1 weights."""

    first = np.asarray(reference_lab, dtype=np.float64)
    second = np.asarray(rendered_lab, dtype=np.float64)
    if first.shape != second.shape or first.shape[-1:] != (3,):
        raise ValueError("Les tableaux Lab comparés doivent avoir la même forme (..., 3)")
    l1, a1, b1 = np.moveaxis(first, -1, 0)
    l2, a2, b2 = np.moveaxis(second, -1, 0)
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_bar**7 / (c_bar**7 + 25.0**7)))
    ap1 = (1.0 + g) * a1
    ap2 = (1.0 + g) * a2
    cp1 = np.hypot(ap1, b1)
    cp2 = np.hypot(ap2, b2)
    hp1 = np.mod(np.degrees(np.arctan2(b1, ap1)), 360.0)
    hp2 = np.mod(np.degrees(np.arctan2(b2, ap2)), 360.0)

    delta_l = l2 - l1
    delta_c = cp2 - cp1
    hue_delta = hp2 - hp1
    zero_chroma = cp1 * cp2 == 0.0
    hue_delta = np.where(zero_chroma, 0.0, hue_delta)
    hue_delta = np.where(hue_delta > 180.0, hue_delta - 360.0, hue_delta)
    hue_delta = np.where(hue_delta < -180.0, hue_delta + 360.0, hue_delta)
    delta_h = 2.0 * np.sqrt(cp1 * cp2) * np.sin(np.radians(hue_delta) / 2.0)

    l_bar = (l1 + l2) / 2.0
    cp_bar = (cp1 + cp2) / 2.0
    hue_sum = hp1 + hp2
    hue_distance = np.abs(hp1 - hp2)
    hp_bar = np.where(zero_chroma, hue_sum, hue_sum / 2.0)
    hp_bar = np.where(
        (~zero_chroma) & (hue_distance > 180.0) & (hue_sum < 360.0),
        (hue_sum + 360.0) / 2.0,
        hp_bar,
    )
    hp_bar = np.where(
        (~zero_chroma) & (hue_distance > 180.0) & (hue_sum >= 360.0),
        (hue_sum - 360.0) / 2.0,
        hp_bar,
    )
    t = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )
    delta_theta = 30.0 * np.exp(-((hp_bar - 275.0) / 25.0) ** 2)
    rc = 2.0 * np.sqrt(cp_bar**7 / (cp_bar**7 + 25.0**7))
    sl = 1.0 + 0.015 * (l_bar - 50.0) ** 2 / np.sqrt(20.0 + (l_bar - 50.0) ** 2)
    sc = 1.0 + 0.045 * cp_bar
    sh = 1.0 + 0.015 * cp_bar * t
    rt = -np.sin(np.radians(2.0 * delta_theta)) * rc
    dl = delta_l / sl
    dc = delta_c / sc
    dh = delta_h / sh
    return np.sqrt(np.maximum(0.0, dl * dl + dc * dc + dh * dh + rt * dc * dh))


def measure_color_fidelity(
    reference_rgb: np.ndarray,
    rendered_rgb: np.ndarray,
    *,
    mask: np.ndarray | None = None,
    edge_filter: int = 0,
) -> ColorFidelityReport:
    reference = np.asarray(reference_rgb)
    rendered = np.asarray(rendered_rgb)
    if reference.shape != rendered.shape or reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError("Les images RGB comparées doivent avoir la même forme (H, W, 3)")
    selected = np.ones(reference.shape[:2], dtype=bool)
    if mask is not None:
        candidate = np.asarray(mask, dtype=bool)
        if candidate.shape != selected.shape:
            raise ValueError("Le masque colorimétrique doit avoir la taille de l’image")
        selected &= candidate
    border = int(edge_filter)
    if border < 0:
        raise ValueError("edge_filter ne peut pas être négatif")
    if border:
        if border * 2 >= min(selected.shape):
            raise ValueError("edge_filter retire toute la zone de mesure")
        interior = np.zeros_like(selected)
        interior[border:-border, border:-border] = True
        selected &= interior
    if not np.any(selected):
        raise ValueError("Aucun pixel disponible pour la mesure colorimétrique")
    differences = delta_e_ciede2000(
        _srgb_to_lab(reference)[selected],
        _srgb_to_lab(rendered)[selected],
    )
    return ColorFidelityReport(
        median_delta_e00=float(np.median(differences)),
        percentile_95_delta_e00=float(np.percentile(differences, 95)),
        sample_count=int(differences.size),
    )

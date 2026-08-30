from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .model import Easing, StudioProject, Transition, TransitionKind


PROLOGUE_RENDERER_ID = "local.prologue"
PROLOGUE_CAPABILITY_ID = "scene.prologue"


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where} doit être numérique")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{where} doit être fini")
    return result


def _color(value: Any, where: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not value.startswith("#"):
        raise ValueError(f"{where} doit utiliser #RRGGBB")
    text = value[1:]
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"{where} doit utiliser #RRGGBB")
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as exc:
        raise ValueError(f"{where} contient une couleur invalide") from exc


def _hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in color)


@dataclass(frozen=True, slots=True)
class PrologueSettings:
    title: str
    subtitle: str = ""
    placement: str = "center"
    font_family: str = "builtin-sans"
    title_size: float = 0.074
    subtitle_size: float = 0.027
    tracking: float = 0.075
    title_color: tuple[int, int, int] = (246, 239, 227)
    subtitle_color: tuple[int, int, int] = (188, 177, 169)
    background_top: tuple[int, int, int] = (13, 15, 21)
    background_bottom: tuple[int, int, int] = (25, 18, 29)
    accent_color: tuple[int, int, int] = (225, 177, 106)
    motion: str = "breathe"
    motion_strength: float = 0.018

    def validate(self) -> PrologueSettings:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Le prologue doit posséder un titre")
        if not isinstance(self.subtitle, str):
            raise TypeError("Le sous-titre du prologue doit être textuel")
        if self.placement not in {"center", "lower-third"}:
            raise ValueError("Le placement du prologue doit être center ou lower-third")
        if self.font_family != "builtin-sans":
            raise ValueError("Cette version portable fournit la famille builtin-sans")
        if not 0.035 <= self.title_size <= 0.18:
            raise ValueError("La taille du titre doit être comprise entre 0,035 et 0,18")
        if not 0.012 <= self.subtitle_size <= 0.09:
            raise ValueError("La taille du sous-titre doit être comprise entre 0,012 et 0,09")
        if not 0.0 <= self.tracking <= 0.25:
            raise ValueError("Le tracking doit être compris entre 0 et 0,25")
        if self.motion not in {"none", "breathe", "rise"}:
            raise ValueError("Le mouvement du prologue doit être none, breathe ou rise")
        if not 0.0 <= self.motion_strength <= 0.08:
            raise ValueError("Le mouvement du prologue doit rester inférieur à 8 %")
        for where, color in (
            ("title_color", self.title_color),
            ("subtitle_color", self.subtitle_color),
            ("background_top", self.background_top),
            ("background_bottom", self.background_bottom),
            ("accent_color", self.accent_color),
        ):
            if len(color) != 3 or any(
                isinstance(channel, bool)
                or not isinstance(channel, int)
                or not 0 <= channel <= 255
                for channel in color
            ):
                raise ValueError(f"prologue.{where} doit contenir trois canaux RGB")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "placement": self.placement,
            "typography": {
                "family": self.font_family,
                "title_size": self.title_size,
                "subtitle_size": self.subtitle_size,
                "tracking": self.tracking,
            },
            "colors": {
                "title": _hex(self.title_color),
                "subtitle": _hex(self.subtitle_color),
                "background_top": _hex(self.background_top),
                "background_bottom": _hex(self.background_bottom),
                "accent": _hex(self.accent_color),
            },
            "motion": {
                "kind": self.motion,
                "strength": self.motion_strength,
            },
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> PrologueSettings:
        values = dict(payload or {})
        unknown = sorted(
            set(values)
            - {"title", "subtitle", "placement", "typography", "colors", "motion"}
        )
        if unknown:
            raise ValueError("Réglage(s) de prologue inconnu(s) : " + ", ".join(unknown))
        typography = values.get("typography", {})
        colors = values.get("colors", {})
        motion = values.get("motion", {})
        if not all(isinstance(item, Mapping) for item in (typography, colors, motion)):
            raise TypeError("typography, colors et motion doivent être des objets")
        typography = dict(typography)
        colors = dict(colors)
        motion = dict(motion)
        typography_unknown = sorted(
            set(typography) - {"family", "title_size", "subtitle_size", "tracking"}
        )
        colors_unknown = sorted(
            set(colors)
            - {"title", "subtitle", "background_top", "background_bottom", "accent"}
        )
        motion_unknown = sorted(set(motion) - {"kind", "strength"})
        if typography_unknown or colors_unknown or motion_unknown:
            unknown = typography_unknown + colors_unknown + motion_unknown
            raise ValueError("Sous-réglage(s) de prologue inconnu(s) : " + ", ".join(unknown))
        result = cls(
            title=str(values.get("title", "SANS TITRE")).strip(),
            subtitle=str(values.get("subtitle", "")).strip(),
            placement=str(values.get("placement", "center")),
            font_family=str(typography.get("family", "builtin-sans")),
            title_size=_number(typography.get("title_size", 0.074), "prologue.title_size"),
            subtitle_size=_number(
                typography.get("subtitle_size", 0.027),
                "prologue.subtitle_size",
            ),
            tracking=_number(typography.get("tracking", 0.075), "prologue.tracking"),
            title_color=_color(colors.get("title", "#f6efe3"), "prologue.colors.title"),
            subtitle_color=_color(
                colors.get("subtitle", "#bcb1a9"),
                "prologue.colors.subtitle",
            ),
            background_top=_color(
                colors.get("background_top", "#0d0f15"),
                "prologue.colors.background_top",
            ),
            background_bottom=_color(
                colors.get("background_bottom", "#19121d"),
                "prologue.colors.background_bottom",
            ),
            accent_color=_color(
                colors.get("accent", "#e1b16a"),
                "prologue.colors.accent",
            ),
            motion=str(motion.get("kind", "breathe")),
            motion_strength=_number(
                motion.get("strength", 0.018),
                "prologue.motion.strength",
            ),
        )
        return result.validate()


@dataclass(frozen=True, slots=True)
class DiscoverySettings:
    easing: Easing = Easing.EASE_IN_OUT
    direction: str = "center-out"
    softness: float = 0.035

    def validate(self) -> DiscoverySettings:
        if not isinstance(self.easing, Easing):
            raise TypeError("L’interpolation de découverte doit être un Easing")
        if self.direction not in {"center-out", "bottom-up", "top-down"}:
            raise ValueError("La découverte doit être center-out, bottom-up ou top-down")
        if not 0.002 <= self.softness <= 0.15:
            raise ValueError("La douceur de découverte doit être comprise entre 0,002 et 0,15")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "easing": self.easing.value,
            "direction": self.direction,
            "softness": self.softness,
        }

    @classmethod
    def from_transition(cls, transition: Transition) -> DiscoverySettings:
        if transition.kind != TransitionKind.DISCOVER:
            raise ValueError("Les réglages demandés ne concernent pas une découverte")
        values = transition.parameters or {}
        if not isinstance(values, Mapping):
            raise TypeError("Les réglages de découverte doivent être un objet")
        unknown = sorted(set(values) - {"easing", "direction", "softness"})
        if unknown:
            raise ValueError("Réglage(s) de découverte inconnu(s) : " + ", ".join(unknown))
        try:
            easing = Easing(values.get("easing", Easing.EASE_IN_OUT.value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Interpolation de découverte inconnue") from exc
        return cls(
            easing,
            str(values.get("direction", "center-out")),
            _number(values.get("softness", 0.035), "discovery.softness"),
        ).validate()


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: int) -> int:
    if not text:
        return 0
    widths = [draw.textlength(character, font=font) for character in text]
    return int(round(sum(widths) + max(0, len(text) - 1) * tracking))


def _portable_glyphs(text: str) -> str:
    return (
        text.replace("Œ", "OE")
        .replace("œ", "oe")
        .replace("Æ", "AE")
        .replace("æ", "ae")
        .replace("\u202f", " ")
    )


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    tracking: int,
) -> None:
    x, y = xy
    for character in text:
        draw.text((round(x), round(y)), character, fill=fill, font=font)
        x += draw.textlength(character, font=font) + tracking


def render_prologue_frame(
    settings: PrologueSettings,
    width: int,
    height: int,
    frame_index: int,
    frame_count: int,
) -> np.ndarray:
    settings.validate()
    if width <= 0 or height <= 0 or frame_count <= 0:
        raise ValueError("Le rendu du prologue exige des dimensions et une durée positives")
    if not 0 <= frame_index < frame_count:
        raise IndexError("Frame de prologue hors limites")
    progress = 0.0 if frame_count == 1 else frame_index / (frame_count - 1)
    vertical = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    top = np.asarray(settings.background_top, dtype=np.float32)[None, None, :]
    bottom = np.asarray(settings.background_bottom, dtype=np.float32)[None, None, :]
    rgb = np.rint(top * (1.0 - vertical) + bottom * vertical).astype(np.uint8)
    rgb = np.repeat(rgb, width, axis=1)
    image = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(image)

    wave = math.sin(progress * math.pi)
    if settings.motion == "breathe":
        motion_y = -height * settings.motion_strength * wave
    elif settings.motion == "rise":
        motion_y = height * settings.motion_strength * (1.0 - progress)
    else:
        motion_y = 0.0
    center_y = height * (0.50 if settings.placement == "center" else 0.69) + motion_y
    title_px = max(12, round(height * settings.title_size))
    subtitle_px = max(8, round(height * settings.subtitle_size))
    title_font = ImageFont.load_default(size=title_px)
    subtitle_font = ImageFont.load_default(size=subtitle_px)
    title_tracking = max(0, round(title_px * settings.tracking))
    subtitle_tracking = max(0, round(subtitle_px * settings.tracking * 0.72))
    title = _portable_glyphs(settings.title.upper())
    subtitle = _portable_glyphs(settings.subtitle.upper())
    title_width = _tracked_width(draw, title, title_font, title_tracking)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    title_y = center_y - title_height * 0.55
    _draw_tracked_text(
        draw,
        ((width - title_width) * 0.5, title_y),
        title,
        title_font,
        settings.title_color,
        title_tracking,
    )
    accent_width = max(28, round(width * (0.08 + 0.07 * wave)))
    accent_y = round(title_y + title_height + height * 0.022)
    draw.rounded_rectangle(
        (
            (width - accent_width) // 2,
            accent_y,
            (width + accent_width) // 2,
            accent_y + max(2, round(height * 0.0025)),
        ),
        radius=2,
        fill=settings.accent_color,
    )
    if subtitle:
        subtitle_width = _tracked_width(draw, subtitle, subtitle_font, subtitle_tracking)
        _draw_tracked_text(
            draw,
            (
                (width - subtitle_width) * 0.5,
                accent_y + height * 0.032,
            ),
            subtitle,
            subtitle_font,
            settings.subtitle_color,
            subtitle_tracking,
        )
    return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))


def validate_discovery_transition(
    project: StudioProject,
    transition: Transition,
) -> DiscoverySettings:
    from .transitions import transition_clip_pair
    from .model import ClipKind

    settings = DiscoverySettings.from_transition(transition)
    pair = transition_clip_pair(project, transition)
    if pair.from_clip.kind != ClipKind.PROLOGUE:
        raise ValueError("Une découverte doit partir d’un prologue")
    if pair.to_clip.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
        raise ValueError("Une découverte doit arriver sur un plan d’œuvre")
    return settings


def add_discovery(
    project: StudioProject,
    first_clip_id: str,
    second_clip_id: str,
    *,
    duration_frames: int,
    easing: Easing = Easing.EASE_IN_OUT,
    direction: str = "center-out",
    softness: float = 0.035,
) -> tuple[StudioProject, Transition]:
    from dataclasses import replace
    from uuid import uuid4

    from .transitions import transition_clip_pair, validate_project_transitions

    if isinstance(duration_frames, bool) or not isinstance(duration_frames, int) or duration_frames < 2:
        raise ValueError("La découverte doit durer au moins deux frames")
    provisional = Transition(
        f"discover-{uuid4().hex[:12]}",
        TransitionKind.DISCOVER,
        first_clip_id,
        second_clip_id,
        0,
        duration_frames,
        DiscoverySettings(easing, direction, softness).to_dict(),
    )
    pair = transition_clip_pair(project, provisional)
    if pair.from_clip.end_frame != pair.to_clip.start_frame:
        raise ValueError("La découverte exige deux plans adjacents")
    transition = replace(provisional, start_frame=pair.to_clip.start_frame).validate()
    candidate = replace(project, transitions=(*project.transitions, transition))
    validate_project_transitions(candidate, validate_sources=True)
    return candidate.validate(), transition

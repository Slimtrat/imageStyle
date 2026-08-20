from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .colors import (
    FAMILY_LABELS,
    closest_centers,
    family_for_color,
    hex_color,
    hue_and_saturation,
    kmeans_lab,
    rgb_to_lab,
)
from .config import RenderConfig
from .masks import complete_family_labels


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ColorLayer:
    key: str
    label: str
    color: tuple[int, int, int]
    mask: np.ndarray
    hue: float
    luma: float
    pixel_count: int
    is_outline: bool = False

    def manifest(self, total_pixels: int) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "color": hex_color(self.color),
            "hue": round(self.hue, 2),
            "luma": round(self.luma, 2),
            "pixels": self.pixel_count,
            "coverage": round(self.pixel_count / total_pixels, 6),
            "outline": self.is_outline,
        }


@dataclass(slots=True)
class ArtworkAnalysis:
    source: np.ndarray
    background_color: tuple[int, int, int]
    background_mask: np.ndarray
    layers: list[ColorLayer]
    outline: ColorLayer | None
    source_path: str

    @property
    def size(self) -> tuple[int, int]:
        height, width = self.source.shape[:2]
        return width, height

    def ordered_layers(
        self,
        order: str,
        start_hue: float = 0.0,
        neutral_position: str = "last",
    ) -> list[ColorLayer]:
        layers = list(self.layers)
        if order == "area":
            return sorted(layers, key=lambda layer: layer.pixel_count, reverse=True)
        if order == "luminance":
            return sorted(layers, key=lambda layer: layer.luma, reverse=True)

        family_hues = {
            "red": 0.0,
            "orange": 30.0,
            "yellow": 56.0,
            "chartreuse": 85.0,
            "green": 125.0,
            "turquoise": 168.0,
            "cyan": 198.0,
            "blue": 232.0,
            "violet": 270.0,
            "magenta": 305.0,
            "rose": 337.0,
        }

        def is_neutral(layer: ColorLayer) -> bool:
            return layer.key == "neutral" or layer.key.startswith("neutral_")

        chromatic = sorted(
            (layer for layer in layers if not is_neutral(layer)),
            key=lambda layer: (family_hues[layer.key] - start_hue) % 360.0,
        )
        neutrals = sorted(
            (layer for layer in layers if is_neutral(layer)),
            key=lambda layer: layer.luma,
        )
        if order == "reverse":
            chromatic.reverse()
        if neutral_position == "first":
            return [*neutrals, *chromatic]
        return [*chromatic, *neutrals]

    def manifest(self, config: RenderConfig) -> dict[str, Any]:
        ordered = self.ordered_layers(config.order, config.start_hue, config.neutral_position)
        entries = [layer.manifest(self.source.shape[0] * self.source.shape[1]) for layer in ordered]
        if self.outline:
            outline_entry = self.outline.manifest(self.source.shape[0] * self.source.shape[1])
        else:
            outline_entry = None
        return {
            "source": self.source_path,
            "width": self.size[0],
            "height": self.size[1],
            "background": hex_color(self.background_color),
            "order": config.order,
            "outline_mode": config.outline,
            "layers": entries,
            "outline": outline_entry,
            "config": config.to_dict(),
        }

    def save_manifest(self, path: str | Path, config: RenderConfig) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.manifest(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Manifeste enregistré : %s", destination.resolve())

    def save_preview(self, path: str | Path, config: RenderConfig) -> None:
        ordered = self.ordered_layers(config.order, config.start_hue, config.neutral_position)
        items = ordered + ([self.outline] if self.outline else [])
        width, height = self.size
        palette_height = max(96, min(180, height // 5))
        preview = Image.new("RGB", (width, height + palette_height), self.background_color)
        preview.paste(Image.fromarray(self.source, "RGB"), (0, 0))
        draw = ImageDraw.Draw(preview)
        font = ImageFont.load_default()
        item_count = max(1, len(items))
        swatch_width = max(1, width // item_count)
        for index, layer in enumerate(items):
            x0 = index * swatch_width
            x1 = width if index == item_count - 1 else (index + 1) * swatch_width
            draw.rectangle((x0, height, x1, height + palette_height), fill=layer.color)
            text_color = (255, 255, 255) if layer.luma < 52 else (20, 20, 20)
            label = f"{index + 1} {layer.label}"
            draw.text((x0 + 5, height + 6), label, fill=text_color, font=font)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        preview.save(destination)
        logger.info("Planche d’analyse enregistrée : %s", destination.resolve())


def _load_rgb(path: str | Path, target_width: int) -> np.ndarray:
    source_path = Path(path)
    if not source_path.is_file():
        logger.error("Image source introuvable : %s", source_path)
        raise FileNotFoundError(f"Image introuvable : {source_path}")
    try:
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    except Exception as exc:
        logger.exception("Lecture impossible de l’image : %s", source_path)
        raise ValueError(f"Impossible de lire l'image {source_path}: {exc}") from exc

    target_height = max(2, int(round(image.height * target_width / image.width)))
    target_height += target_height % 2
    image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    white = Image.new("RGBA", image.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white, image).convert("RGB")
    return np.asarray(composited, dtype=np.uint8).copy()


def _border_color(source: np.ndarray) -> tuple[int, int, int]:
    height, width = source.shape[:2]
    band = max(1, min(height, width) // 50)
    border = np.concatenate(
        (
            source[:band].reshape(-1, 3),
            source[-band:].reshape(-1, 3),
            source[:, :band].reshape(-1, 3),
            source[:, -band:].reshape(-1, 3),
        ),
        axis=0,
    )
    median = np.median(border, axis=0)
    distances = np.sum((border.astype(np.float32) - median) ** 2, axis=1)
    core = border[distances <= np.percentile(distances, 55)]
    representative = np.median(core if len(core) else border, axis=0)
    return tuple(int(round(channel)) for channel in representative)


def analyze_artwork(path: str | Path, config: RenderConfig) -> ArtworkAnalysis:
    config.validate()
    logger.info(
        "Analyse démarrée : source=%s, largeur=%d, centres=%d",
        Path(path).resolve(),
        config.width,
        config.colors,
    )
    source = _load_rgb(path, config.width)
    height, width = source.shape[:2]
    logger.info("Image chargée : %dx%d pixels", width, height)
    flat_rgb = source.reshape(-1, 3)
    flat_lab = rgb_to_lab(flat_rgb)

    background_color = _border_color(source)
    background_lab = rgb_to_lab(np.asarray(background_color, dtype=np.uint8))[0:3]
    background_distance = np.linalg.norm(flat_lab - background_lab, axis=1)
    background_mask_flat = background_distance <= config.background_tolerance
    background_coverage = float(np.mean(background_mask_flat))
    logger.info(
        "Fond détecté : rgb=%s, couverture=%.1f %%",
        background_color,
        background_coverage * 100.0,
    )
    if background_coverage < 0.02:
        logger.warning("Le fond détecté couvre moins de 2 %% de l’image")
    elif background_coverage > 0.95:
        logger.warning("Le fond détecté couvre plus de 95 %% de l’image")

    chroma = np.linalg.norm(flat_lab[:, 1:3], axis=1)
    outline_mask_flat = (
        (~background_mask_flat)
        & (flat_lab[:, 0] <= config.outline_luma)
        & (chroma <= config.outline_chroma)
    )
    color_indices = np.flatnonzero(~background_mask_flat & ~outline_mask_flat)
    if len(color_indices) == 0:
        logger.error("Aucune zone colorée détectée avec les seuils courants")
        raise ValueError(
            "Aucune zone colorée détectée. Réduisez background_tolerance ou outline_luma."
        )

    rng = np.random.default_rng(config.seed)
    sample_count = min(90_000, len(color_indices))
    if sample_count < len(color_indices):
        sample_indices = rng.choice(color_indices, sample_count, replace=False)
    else:
        sample_indices = color_indices
    centers = kmeans_lab(flat_lab[sample_indices], config.colors, config.seed)
    assignments = closest_centers(flat_lab[color_indices], centers)

    family_masks: dict[str, np.ndarray] = {}
    family_colors: dict[str, list[tuple[np.ndarray, int, float]]] = {}
    for cluster_index in range(len(centers)):
        members_local = np.flatnonzero(assignments == cluster_index)
        if len(members_local) == 0:
            continue
        members = color_indices[members_local]
        representative = np.mean(flat_rgb[members].astype(np.float32), axis=0)
        center_chroma = float(np.linalg.norm(centers[cluster_index, 1:3]))
        family, hue = family_for_color(representative, center_chroma)
        if family == "neutral":
            family = "neutral_light" if centers[cluster_index, 0] >= 62.0 else "neutral_dark"
        if family not in family_masks:
            family_masks[family] = np.zeros(height * width, dtype=bool)
            family_colors[family] = []
        family_masks[family][members] = True
        family_colors[family].append((representative, len(members), hue))

    family_order = tuple(family_masks)
    family_ids = {family: index for index, family in enumerate(family_order)}
    raw_labels = np.full(height * width, -1, dtype=np.int16)
    for family, mask_flat in family_masks.items():
        raw_labels[mask_flat] = family_ids[family]
    completed_labels = complete_family_labels(
        raw_labels.reshape(height, width),
        config.shape_completion,
    ).reshape(-1)
    changed = int(np.count_nonzero(completed_labels != raw_labels))
    active_count = max(1, int(np.count_nonzero(raw_labels >= 0)))
    if changed:
        logger.info(
            "Complétion des formes : niveau=%d, %.2f %% des pixels colorés réattribués",
            config.shape_completion,
            changed * 100.0 / active_count,
        )
    for family, family_id in family_ids.items():
        family_masks[family] = completed_labels == family_id

    layers: list[ColorLayer] = []
    for family, mask_flat in family_masks.items():
        if not np.any(mask_flat):
            logger.info("Famille supprimée par la complétion : %s", family)
            continue
        weighted = family_colors[family]
        total = sum(count for _, count, _ in weighted)
        rgb = sum(color * count for color, count, _ in weighted) / total
        color = tuple(int(round(channel)) for channel in rgb)
        hue, _, _ = hue_and_saturation(color)
        layer_luma = float(rgb_to_lab(np.asarray(color, dtype=np.uint8))[0])
        layers.append(
            ColorLayer(
                key=family,
                label=FAMILY_LABELS[family],
                color=color,
                mask=mask_flat.reshape(height, width),
                hue=hue,
                luma=layer_luma,
                pixel_count=int(mask_flat.sum()),
            )
        )

    outline: ColorLayer | None = None
    outline_count = int(outline_mask_flat.sum())
    if not outline_count:
        logger.warning("Aucun contour sombre distinct n’a été détecté")
    if outline_count:
        outline_rgb = np.mean(flat_rgb[outline_mask_flat].astype(np.float32), axis=0)
        outline_color = tuple(int(round(channel)) for channel in outline_rgb)
        outline = ColorLayer(
            key="outline",
            label=FAMILY_LABELS["outline"],
            color=outline_color,
            mask=outline_mask_flat.reshape(height, width),
            hue=0.0,
            luma=float(np.mean(flat_lab[outline_mask_flat, 0])),
            pixel_count=outline_count,
            is_outline=True,
        )

    logger.info(
        "Analyse terminée : familles=%s, contours=%d pixels",
        ", ".join(sorted(layer.label for layer in layers)),
        outline_count,
    )
    return ArtworkAnalysis(
        source=source,
        background_color=background_color,
        background_mask=background_mask_flat.reshape(height, width),
        layers=layers,
        outline=outline,
        source_path=str(Path(path).resolve()),
    )

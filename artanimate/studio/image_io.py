from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError


EXIF_ORIENTATION_TAG = 274


@dataclass(frozen=True, slots=True)
class ImageInspection:
    width: int
    height: int
    format: str
    original_mode: str
    exif_orientation: int
    orientation_applied: bool
    color_profile: str
    color_profile_embedded: bool
    has_alpha: bool

    def metadata(self) -> dict[str, object]:
        scale = min(1.0, 160.0 / self.width, 160.0 / self.height)
        return {
            "format": self.format,
            "original_mode": self.original_mode,
            "exif_orientation": self.exif_orientation,
            "orientation_applied": self.orientation_applied,
            "color_profile": self.color_profile,
            "color_profile_embedded": self.color_profile_embedded,
            "has_alpha": self.has_alpha,
            "thumbnail_width": max(1, round(self.width * scale)),
            "thumbnail_height": max(1, round(self.height * scale)),
        }


def _profile_name(profile: ImageCms.ImageCmsProfile) -> str:
    try:
        return ImageCms.getProfileName(profile).strip() or "ICC embarqué"
    except (AttributeError, OSError, TypeError, ValueError):
        return "ICC embarqué"


def _to_srgb(image: Image.Image, icc_profile: bytes | None) -> tuple[Image.Image, str]:
    if not icc_profile:
        return image.convert("RGB"), "sRGB présumé"
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(icc_profile))
        destination_profile = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(
            image,
            source_profile,
            destination_profile,
            outputMode="RGB",
        )
        return converted, _profile_name(source_profile)
    except (OSError, TypeError, ValueError):
        # A malformed optional profile must not make otherwise valid pixels unusable.
        return image.convert("RGB"), "ICC invalide · sRGB présumé"


def load_normalized_image(path: str | Path) -> tuple[Image.Image, ImageInspection]:
    """Decode a still once, normalize EXIF orientation and convert it to sRGB."""

    source = Path(path)
    try:
        with Image.open(source) as opened:
            opened.load()
            original_mode = opened.mode
            image_format = opened.format or source.suffix.removeprefix(".").upper() or "IMAGE"
            try:
                orientation = int(opened.getexif().get(EXIF_ORIENTATION_TAG, 1))
            except (AttributeError, TypeError, ValueError):
                orientation = 1
            icc_profile = opened.info.get("icc_profile")
            if not isinstance(icc_profile, bytes):
                icc_profile = None
            has_alpha = "A" in opened.getbands() or "transparency" in opened.info
            oriented = ImageOps.exif_transpose(opened)
            normalized, profile_name = _to_srgb(oriented, icc_profile)
            normalized.load()
            normalized = normalized.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Image locale illisible : {source}") from exc

    inspection = ImageInspection(
        width=normalized.width,
        height=normalized.height,
        format=image_format,
        original_mode=original_mode,
        exif_orientation=orientation,
        orientation_applied=orientation not in {0, 1},
        color_profile=profile_name,
        color_profile_embedded=icc_profile is not None,
        has_alpha=has_alpha,
    )
    return normalized, inspection


def load_normalized_rgb(path: str | Path) -> tuple[np.ndarray, ImageInspection]:
    image, inspection = load_normalized_image(path)
    frame = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))
    frame.setflags(write=False)
    return frame, inspection

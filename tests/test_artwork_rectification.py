from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from artanimate.studio.artwork_rectification import (
    detect_artwork_quad,
    rectify_artwork,
    rectify_image,
)


def _perspective_artwork() -> tuple[Image.Image, tuple[tuple[int, int], ...]]:
    image = Image.new("RGB", (420, 320), (218, 197, 176))
    corners = ((64, 54), (350, 42), (368, 260), (48, 274))
    draw = ImageDraw.Draw(image)
    draw.polygon(corners, fill=(36, 145, 186))
    draw.polygon(((112, 92), (245, 70), (305, 222), (92, 240)), fill=(244, 194, 38))
    draw.ellipse((150, 105, 280, 230), fill=(216, 54, 104))
    draw.line((*corners, corners[0]), fill=(30, 28, 42), width=4, joint="curve")
    return image, corners


def test_detect_and_rectify_a_perspective_artwork() -> None:
    image, expected = _perspective_artwork()

    record = detect_artwork_quad(image, inset_ratio=0.0)
    flattened = rectify_image(image, record)

    assert record.confidence >= 0.8
    assert flattened.size == (record.output_width, record.output_height)
    assert record.output_width > record.output_height
    for actual, wanted in zip(record.corners, expected, strict=True):
        assert actual == pytest.approx(wanted, abs=10.0)


def test_uniform_wall_is_rejected() -> None:
    image = Image.new("RGB", (420, 320), (218, 197, 176))

    with pytest.raises(ValueError, match="contour"):
        detect_artwork_quad(image)


def test_rectification_writes_image_manifest_and_preview(tmp_path: Path) -> None:
    image, _corners = _perspective_artwork()
    source = tmp_path / "source.png"
    destination = tmp_path / "rectified.png"
    manifest = tmp_path / "rectification.json"
    preview = tmp_path / "detection.png"
    image.save(source)

    record = rectify_artwork(
        source,
        destination,
        manifest_path=manifest,
        preview_path=preview,
    )

    assert record.confidence >= 0.8
    assert destination.is_file()
    assert manifest.is_file()
    assert preview.is_file()
    with Image.open(destination) as flattened:
        assert flattened.size == (record.output_width, record.output_height)

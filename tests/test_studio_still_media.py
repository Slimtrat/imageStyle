from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.studio.assets import import_media_asset, register_media_asset
from artanimate.studio.media import (
    StillClipSettings,
    StillImageSource,
    add_still_clip,
    transform_still_frame,
    update_still_clip,
)
from artanimate.studio.model import AssetKind, ClipKind, FitMode, StudioProject
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.source_registry import ArtworkSourceRegistry
from artanimate.studio.timeline import duplicate_clip, trim_clip


def make_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    Image.new("RGB", size, color).save(path)


def project_with_still(
    tmp_path: Path,
    *,
    media_size: tuple[int, int] = (80, 120),
    start_frame: int = 0,
) -> tuple[StudioProject, Path, Path, str]:
    artwork = tmp_path / "artwork.png"
    media = tmp_path / "real.png"
    make_image(artwork, (90, 160), (15, 25, 35))
    make_image(media, media_size, (210, 45, 35))
    project = StudioProject.new(artwork)
    project, asset, _created = register_media_asset(
        project,
        media,
        tmp_path / "reel.artanimate",
    )
    project, clip = add_still_clip(
        project,
        asset.asset_id,
        start_frame=start_frame,
        duration_frames=60,
    )
    return project, artwork, media, clip.clip_id


def test_image_import_normalizes_exif_orientation_and_records_metadata(tmp_path: Path) -> None:
    source = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (40, 20), (80, 120, 180))
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)

    asset = import_media_asset(
        source,
        AssetKind.IMAGE,
        tmp_path / "reel.artanimate",
        asset_id="oriented",
    )

    assert (asset.width, asset.height) == (20, 40)
    assert asset.metadata["exif_orientation"] == 6
    assert asset.metadata["orientation_applied"] is True
    assert asset.metadata["color_profile"] == "sRGB présumé"
    assert asset.metadata["thumbnail_width"] == 20
    assert asset.metadata["thumbnail_height"] == 40


def test_still_settings_crop_then_rotate_without_mutating_source() -> None:
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    frame[:, :40] = (230, 30, 20)
    frame[:, 40:] = (20, 40, 230)
    settings = StillClipSettings(
        crop_x=0.5,
        crop_y=0.0,
        crop_width=0.5,
        crop_height=1.0,
        rotation_degrees=90.0,
    )

    transformed = transform_still_frame(frame, settings)

    assert transformed.shape == (40, 40, 3)
    assert transformed[..., 2].mean() > 200
    assert np.all(frame[:, :40, 0] == 230)
    with pytest.raises(ValueError, match="dépasse"):
        StillClipSettings(crop_x=0.8, crop_width=0.4).validate()


@pytest.mark.parametrize("media_size", [(60, 140), (160, 70)])
def test_portrait_and_landscape_stills_fill_vertical_reel(
    tmp_path: Path,
    media_size: tuple[int, int],
) -> None:
    project, artwork, _media, _clip_id = project_with_still(
        tmp_path,
        media_size=media_size,
    )

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
        resource_base=tmp_path,
    ) as session:
        frame = session.frame_at(10)
        execution_mode = session.execution_mode

    assert execution_mode == "semantic"
    assert frame.shape == (160, 90, 3)
    assert np.all(frame[0, 0] == (210, 45, 35))
    assert np.all(frame[-1, -1] == (210, 45, 35))


def test_missing_still_renders_diagnostic_frame_without_crashing(tmp_path: Path) -> None:
    project, artwork, media, _clip_id = project_with_still(tmp_path)
    media.unlink()

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
        resource_base=tmp_path,
    ) as session:
        frame = session.frame_at(12)

    assert frame.shape == (160, 90, 3)
    assert np.any(frame[..., 0] > 220)
    assert not np.all(frame == (15, 25, 35))


def test_still_clip_is_editable_trimmable_and_duplicable(tmp_path: Path) -> None:
    project, _artwork, _media, clip_id = project_with_still(tmp_path)
    project, edited = update_still_clip(
        project,
        clip_id,
        duration_frames=50,
        fit=FitMode.CONTAIN,
        opacity=0.65,
        enabled=True,
        settings=StillClipSettings(crop_x=0.1, crop_width=0.8),
    )
    project = trim_clip(project, clip_id, 5, 45)
    project, duplicate = duplicate_clip(project, clip_id, target_frame=70)

    assert edited.kind == ClipKind.STILL
    trimmed = next(
        clip for track in project.tracks for clip in track.clips if clip.clip_id == clip_id
    )
    assert (trimmed.start_frame, trimmed.duration_frames, trimmed.source_in_frame) == (5, 40, 5)
    assert StillClipSettings.from_clip(trimmed).crop_x == pytest.approx(0.1)
    assert duplicate.asset_id == trimmed.asset_id
    assert duplicate.parameters == trimmed.parameters


def test_still_source_registry_is_bounded_and_preserves_project_fps(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    make_image(first, (30, 40), (10, 20, 30))
    make_image(second, (30, 40), (30, 20, 10))
    project_path = tmp_path / "reel.artanimate"
    assets = (
        import_media_asset(first, AssetKind.IMAGE, project_path, asset_id="first"),
        import_media_asset(second, AssetKind.IMAGE, project_path, asset_id="second"),
    )
    registry = ArtworkSourceRegistry(max_media_sources=1)

    source = registry.still_image(assets[0], first, StillClipSettings(), 60)
    same = registry.still_image(assets[0], first, StillClipSettings(), 60)
    registry.still_image(assets[1], second, StillClipSettings(), 60)

    assert isinstance(source, StillImageSource)
    assert source is same
    assert source.fps == 60
    assert registry.media_decode_count == 2
    assert registry.media_source_count == 1

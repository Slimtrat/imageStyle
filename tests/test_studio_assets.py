from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest

from artanimate.studio.assets import (
    AssetAvailability,
    check_media_asset,
    find_relink_candidates,
    import_artwork_asset,
    import_media_asset,
    relink_media_asset,
    resolve_asset_path,
)
from artanimate.studio.model import AssetKind, Clip, ClipKind, StudioProject, Track, TrackKind


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 120), color).save(path)


def test_imported_asset_is_relative_inside_project_and_fingerprinted(tmp_path: Path) -> None:
    project_path = tmp_path / "projects" / "reel.artanimate"
    project_path.parent.mkdir()
    image_path = project_path.parent / "media" / "real.jpg"
    make_image(image_path, (180, 60, 40))

    asset = import_media_asset(image_path, AssetKind.IMAGE, project_path, asset_id="real")

    assert asset.path == "media/real.jpg"
    assert asset.fingerprint.startswith("sha256-sampled:")
    assert (asset.width, asset.height) == (80, 120)
    assert resolve_asset_path(asset.path, project_path) == image_path.resolve()
    assert check_media_asset(asset, project_path).state == AssetAvailability.AVAILABLE


def test_asset_status_distinguishes_missing_replaced_and_invalid(tmp_path: Path) -> None:
    project_path = tmp_path / "reel.artanimate"
    image_path = tmp_path / "real.png"
    make_image(image_path, (20, 80, 160))
    asset = import_media_asset(image_path, AssetKind.IMAGE, project_path, asset_id="real")

    make_image(image_path, (200, 180, 20))
    assert check_media_asset(asset, project_path).state == AssetAvailability.REPLACED

    image_path.unlink()
    assert check_media_asset(asset, project_path).state == AssetAvailability.MISSING

    image_path.mkdir()
    assert check_media_asset(asset, project_path).state == AssetAvailability.INVALID


def test_relink_keeps_asset_id_so_all_clips_follow_new_file(tmp_path: Path) -> None:
    project_path = tmp_path / "reel.artanimate"
    artwork_path = tmp_path / "artwork.png"
    first = tmp_path / "first.jpg"
    moved = tmp_path / "moved" / "first.jpg"
    make_image(artwork_path, (240, 240, 240))
    make_image(first, (60, 120, 180))
    make_image(moved, (60, 120, 180))

    project = StudioProject.new(artwork_path)
    artwork = import_artwork_asset(artwork_path, project_path)
    asset = import_media_asset(first, AssetKind.IMAGE, project_path, asset_id="real")
    video = Track(
        "video-main",
        TrackKind.VIDEO,
        "Réel",
        (
            Clip("real-a", ClipKind.STILL, 0, 120, asset_id="real"),
            Clip("real-b", ClipKind.STILL, 120, 120, asset_id="real"),
        ),
    )
    project = replace(project, artwork=artwork, assets=(asset,), tracks=(video,)).validate()

    relinked = relink_media_asset(project, "real", moved, project_path)

    assert relinked.assets[0].asset_id == "real"
    assert resolve_asset_path(relinked.assets[0].path, project_path) == moved.resolve()
    assert {clip.asset_id for clip in relinked.tracks[0].clips} == {"real"}


def test_folder_search_only_returns_same_content_candidates(tmp_path: Path) -> None:
    project_path = tmp_path / "reel.artanimate"
    original = tmp_path / "original" / "real.jpg"
    correct = tmp_path / "search" / "nested" / "real.jpg"
    wrong = tmp_path / "search" / "wrong" / "real.jpg"
    make_image(original, (20, 30, 40))
    make_image(correct, (20, 30, 40))
    make_image(wrong, (200, 30, 40))
    asset = import_media_asset(original, AssetKind.IMAGE, project_path, asset_id="real")

    assert find_relink_candidates(asset, (tmp_path / "search",)) == (correct.resolve(),)


def test_import_rejects_kind_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "not-a-video.jpg"
    make_image(source, (10, 20, 30))

    with pytest.raises(ValueError, match="incompatible"):
        import_media_asset(source, AssetKind.VIDEO, tmp_path / "reel.artanimate")


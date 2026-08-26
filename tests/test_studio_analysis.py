from __future__ import annotations

from pathlib import Path
from threading import Event

from PIL import Image, ImageDraw
import pytest

from artanimate.studio.analysis import (
    AnalysisCancelled,
    LocalCompositionAnalyzer,
    SceneAnalysisRequest,
    add_manual_mask,
    add_manual_selection,
    apply_scene_analysis,
    remove_scene_object,
    update_scene_object_bounds,
)
from artanimate.studio.model import StudioProject
from artanimate.studio.assets import relink_artwork_asset
from artanimate.studio.semantic import Bounds


def _photographic_fixture(path: Path) -> None:
    image = Image.new("RGB", (180, 120), (235, 228, 210))
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 18, 130, 108), fill=(35, 78, 155))
    draw.rectangle((75, 45, 112, 102), fill=(210, 52, 55))
    image.save(path)


def test_local_analysis_is_deterministic_cached_and_resource_backed(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "portrait.png"
    _photographic_fixture(artwork)
    analyzer = LocalCompositionAnalyzer()
    request = SceneAnalysisRequest(
        artwork,
        "artwork",
        tmp_path / "cache",
        Event(),
    )

    first = analyzer.analyze(request)
    second = analyzer.analyze(request)
    assert not first.cache_hit
    assert second.cache_hit
    assert first.source_fingerprint == second.source_fingerprint
    assert first.objects[0].to_dict() == second.objects[0].to_dict()
    assert first.relations[0].to_dict() == second.relations[0].to_dict()
    assert {resource.kind for resource in first.artwork_resources} == {"depth"}
    assert {resource.kind for resource in first.objects[0].resource_refs} == {"mask"}
    assert all(Path(asset.path).is_file() for asset in first.assets)

    project = apply_scene_analysis(StudioProject.new(artwork), first)
    assert project.artwork.fingerprint == first.source_fingerprint
    assert project.scene.object_by_id("auto-foreground") is not None
    foreground = project.scene.object_by_id("auto-foreground")
    assert foreground.affordance_ids >= {"movable", "frame-exitable"}
    assert all(item.source == analyzer.analyzer_id for item in foreground.affordances)
    assert project.scene.object_by_id("artwork").affordance_ids >= {"depth-aware"}
    background = project.scene.object_by_id("background")
    assert background.affordance_ids >= {"depth-aware"}
    background_mask = next(item for item in background.resource_refs if item.kind == "mask")
    assert background_mask.metadata["invert"] is True
    assert background_mask.asset_id == foreground.resource_refs[0].asset_id
    payload = project.to_dict()
    resources = payload["scene"]["objects"][0]["resource_refs"]
    assert all("asset_id" in resource for resource in resources)
    assert "base64" not in str(payload).lower()
    reopened = StudioProject.from_dict(payload)
    assert reopened.to_dict() == payload
    assert reopened.scene.analyzer_provenance[0].source_fingerprint == first.source_fingerprint
    assert "pixels" not in str(payload).lower()


def test_changed_fingerprint_invalidates_cache_and_abstract_art_has_fallback(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "abstract.png"
    Image.new("RGB", (96, 96), (120, 60, 180)).save(artwork)
    analyzer = LocalCompositionAnalyzer()
    request = SceneAnalysisRequest(artwork, "artwork", tmp_path / "cache", Event())
    first = analyzer.analyze(request)
    assert first.objects[0].attributes["fallback"] is True
    assert first.objects[0].confidence >= 0.28

    Image.new("RGB", (96, 96), (10, 190, 80)).save(artwork)
    changed = analyzer.analyze(
        SceneAnalysisRequest(artwork, "artwork", tmp_path / "cache", Event())
    )
    assert changed.source_fingerprint != first.source_fingerprint
    assert {asset.path for asset in changed.assets} != {asset.path for asset in first.assets}


def test_relink_invalidates_stale_analysis_but_preserves_manual_objects(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original.png"
    replacement = tmp_path / "replacement.png"
    _photographic_fixture(original)
    Image.new("RGB", (120, 180), (20, 180, 90)).save(replacement)
    analyzer = LocalCompositionAnalyzer()
    result = analyzer.analyze(
        SceneAnalysisRequest(original, "artwork", tmp_path / "cache", Event())
    )
    enriched = apply_scene_analysis(StudioProject.new(original), result)
    enriched, manual = add_manual_selection(
        enriched,
        Bounds(0.1, 0.1, 0.25, 0.3),
        label="Conserver",
    )

    relinked = relink_artwork_asset(
        enriched,
        replacement,
        tmp_path / "project.artanimate",
    )
    assert relinked.scene.object_by_id("auto-foreground") is None
    assert relinked.scene.object_by_id(manual.object_id) is not None
    assert relinked.scene.analyzer_provenance == ()
    assert all(
        (asset.metadata or {}).get("derived_by") != analyzer.analyzer_id
        for asset in relinked.assets
    )
    artwork_object = relinked.scene.object_by_id("artwork")
    assert "depth-aware" not in artwork_object.affordance_ids
    assert all(resource.kind != "depth" for resource in artwork_object.resource_refs)


def test_analysis_honors_pre_cancelled_request(tmp_path: Path) -> None:
    artwork = tmp_path / "cancel.png"
    Image.new("RGB", (64, 64), "black").save(artwork)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(AnalysisCancelled, match="annulée"):
        LocalCompositionAnalyzer().analyze(
            SceneAnalysisRequest(artwork, "artwork", tmp_path / "cache", cancelled)
        )


def test_manual_selection_mask_correction_and_ignore_are_pure_project_edits(
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    mask = tmp_path / "mask.png"
    Image.new("RGB", (100, 80), "white").save(artwork)
    Image.new("L", (100, 80), 255).save(mask)
    project = StudioProject.new(artwork)

    selected, manual = add_manual_selection(
        project,
        Bounds(0.1, 0.2, 0.4, 0.5),
        label="Visage",
    )
    assert selected.scene.object_by_id(manual.object_id).label == "Visage"
    corrected = update_scene_object_bounds(
        selected,
        manual.object_id,
        Bounds(0.2, 0.15, 0.3, 0.55),
        label="Portrait",
    )
    assert corrected.scene.object_by_id(manual.object_id).label == "Portrait"
    assert corrected.scene.object_by_id(manual.object_id).attributes["corrected_manually"]

    masked, masked_object = add_manual_mask(
        corrected,
        mask,
        tmp_path / "project.artanimate",
        Bounds(0.2, 0.15, 0.3, 0.55),
    )
    resource = masked_object.resource_refs[0]
    assert resource.kind == "mask"
    assert any(asset.asset_id == resource.asset_id for asset in masked.assets)
    assert "base64" not in str(masked.to_dict()).lower()

    ignored = remove_scene_object(masked, masked_object.object_id)
    assert ignored.scene.object_by_id(masked_object.object_id) is None
    assert all(asset.asset_id != resource.asset_id for asset in ignored.assets)

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from artanimate.core.config import RenderConfig
from artanimate.studio.adapters import legacy_capability_catalog, project_as_semantic
from artanimate.studio.effect_2d import add_effect_clip
from artanimate.studio.model import (
    AssetKind,
    Clip,
    ClipKind,
    MediaAsset,
    StudioProject,
    Track,
    TrackKind,
)


def test_v1_project_projection_is_deterministic_and_non_mutating(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "artwork.png", duration_seconds=4)
    before = project.to_dict()

    first = project_as_semantic(project)
    second = project_as_semantic(project)

    assert first == second
    assert project.to_dict() == before
    assert first.scene.scene_id == f"scene:{project.project_id}"
    assert tuple(item.capability_id for item in first.invocations) == (
        "artwork.present",
        "camera.animate",
    )
    assert first.binding_for(first.invocations[0].invocation_id).clip_id == "artwork-main"


def test_effect_snapshot_becomes_capability_parameters_without_reinterpretation(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "artwork.png", duration_seconds=4)
    config = RenderConfig(
        effect="rgb_fade",
        direction="bottom",
        duration=6.0,
        fps=30,
        colors=17,
        seed=93,
    )
    project, clip = add_effect_clip(
        project,
        config,
        start_frame=15,
        duration_seconds=1.5,
        intensity=0.72,
        opacity=0.64,
    )

    semantic = project_as_semantic(project)
    invocation = next(item for item in semantic.invocations if item.capability_id == "reveal.chromatic")
    parameters = invocation.parameters.to_dict()

    assert invocation.start_frame == clip.start_frame
    assert invocation.duration_frames == clip.duration_frames
    assert parameters["render_config"] == clip.parameters["render_config"]
    assert parameters["render_config"]["colors"] == 17
    assert parameters["render_config"]["seed"] == 93
    assert parameters["intensity"] == 0.72
    assert parameters["opacity"] == 0.64
    assert invocation.renderer_policy.renderer_ids == ("classic.effect.rgb_fade",)


def test_real_media_and_audio_map_to_renderer_independent_intents(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "artwork.png", duration_seconds=4)
    assets = (
        MediaAsset("photo-real", AssetKind.IMAGE, str(tmp_path / "photo.jpg")),
        MediaAsset("music", AssetKind.AUDIO, str(tmp_path / "music.wav")),
    )
    real_track = Track(
        "real",
        TrackKind.VIDEO,
        "Réel",
        (Clip("real-shot", ClipKind.STILL, 60, 30, asset_id="photo-real"),),
    )
    audio_track = Track(
        "audio-main",
        TrackKind.AUDIO,
        "Musique",
        (Clip("music-clip", ClipKind.AUDIO, 0, 120, asset_id="music"),),
    )
    project = replace(
        project,
        assets=assets,
        tracks=(project.tracks[0], real_track, project.tracks[1], audio_track),
    ).validate()

    semantic = project_as_semantic(project)
    by_capability = {item.capability_id: item for item in semantic.invocations}

    assert by_capability["media.present"].parameters["asset_id"] == "photo-real"
    assert by_capability["audio.play"].parameters["asset_id"] == "music"
    assert by_capability["media.present"].target_id is None


def test_native_catalog_covers_every_mapped_legacy_capability(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "artwork.png")
    projected = project_as_semantic(project)
    catalog = {item.capability_id: item for item in legacy_capability_catalog()}

    assert {item.capability_id for item in projected.invocations} <= set(catalog)
    assert "scene.depth_present" in catalog
    assert "media.present" in catalog
    assert "audio.play" in catalog

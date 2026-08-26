from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from artanimate.studio.adapters import build_studio_capability_registry
from artanimate.core.config import RenderConfig
from artanimate.studio.analysis import remove_scene_object
from artanimate.studio.effect_2d import add_effect_clip
from artanimate.studio.model import AssetKind, MediaAsset, StudioProject
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.semantic import (
    Affordance,
    Bounds,
    CapabilityInvocation,
    ResourceRef,
    SceneObject,
    AvailabilityStatus,
)
from artanimate.studio.semantic_actions import (
    add_semantic_action_clip,
    is_semantic_action_clip,
)
from artanimate.studio.timeline import (
    duplicate_clip,
    move_clip,
    split_clip,
    trim_clip,
)


def _write_scene(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = np.zeros((64, 64, 3), dtype=np.uint8)
    source[:] = (24, 38, 54)
    source[:, :, 1] += np.arange(64, dtype=np.uint8)[None, :]
    source[20:40, 8:20] = (224, 42, 32)
    artwork = tmp_path / "artwork.png"
    Image.fromarray(source).save(artwork)

    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:40, 8:20] = 255
    mask_path = tmp_path / "mask.png"
    Image.fromarray(mask).save(mask_path)

    depth = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
    depth_path = tmp_path / "depth.png"
    Image.fromarray(depth).save(depth_path)
    return artwork, mask_path, depth_path


def _project_with_resources(tmp_path: Path) -> tuple[StudioProject, Path]:
    artwork_path, mask_path, depth_path = _write_scene(tmp_path)
    project = StudioProject.new(artwork_path, fps=30, duration_seconds=4)
    assert project.scene is not None
    mask_asset = MediaAsset(
        "mask-asset",
        AssetKind.IMAGE,
        str(mask_path),
        width=64,
        height=64,
        metadata={"resource_kind": "mask"},
    )
    depth_asset = MediaAsset(
        "depth-asset",
        AssetKind.IMAGE,
        str(depth_path),
        width=64,
        height=64,
        metadata={"resource_kind": "depth"},
    )
    objects = []
    for scene_object in project.scene.objects:
        if scene_object.object_id == "artwork":
            scene_object = replace(
                scene_object,
                resource_refs=(
                    *scene_object.resource_refs,
                    ResourceRef("artwork-depth", "depth", "depth-asset"),
                ),
                affordances=(
                    *scene_object.affordances,
                    Affordance("depth-aware", source="test"),
                ),
            )
        objects.append(scene_object)
    objects.append(
        SceneObject(
            "subject",
            "artwork.element",
            "Sujet",
            bounds=Bounds(8 / 64, 20 / 64, 12 / 64, 20 / 64),
            resource_refs=(ResourceRef("subject-mask", "mask", "mask-asset"),),
            affordances=(
                Affordance("movable", source="test"),
                Affordance("frame-exitable", source="test"),
                Affordance("camera-inspectable", source="test"),
            ),
        )
    )
    scene = replace(project.scene, objects=tuple(objects))
    return replace(
        project,
        assets=(mask_asset, depth_asset),
        scene=scene,
    ).validate(), artwork_path


def _add_action(
    project: StudioProject,
    capability_id: str,
    target_id: str | None,
    parameters: dict[str, object] | None = None,
    *,
    start: int = 0,
    duration: int = 5,
):
    descriptor = build_studio_capability_registry().get(capability_id)
    invocation = CapabilityInvocation.create(
        capability_id,
        start_frame=start,
        duration_frames=duration,
        target_id=target_id,
        parameters=descriptor.normalize_parameters(parameters or {}),
    )
    updated, clip = add_semantic_action_clip(project, invocation)
    return updated, invocation, clip


def test_object_move_extracts_only_the_mask_and_is_seek_deterministic(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    project, _invocation, _clip = _add_action(
        project,
        "object.move",
        "subject",
        {"destination": [0.75, 0.5], "seed": 17},
    )

    with StudioRenderSession(project, artwork_path, output_width=64, output_height=64) as session:
        start = session.frame_at(0)
        final = session.frame_at(4)
        repeated = session.frame_at(4)

    assert tuple(start[30, 14]) == (224, 42, 32)
    assert tuple(final[30, 14]) != (224, 42, 32)
    assert final[30, 48, 0] > 180
    assert np.array_equal(final, repeated)


def test_exit_frame_crosses_the_requested_edge_and_emits_known_events(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    project, invocation, _clip = _add_action(
        project,
        "object.exit_frame",
        "subject",
        {"direction": "right", "margin": 0.05},
    )

    with StudioRenderSession(project, artwork_path, output_width=64, output_height=64) as session:
        final = session.frame_at(4)
        assert session.prepared_plan is not None
        prepared = session.prepared_plan.by_invocation_id(invocation.invocation_id)
        first_events = prepared.prepared.frame_at(0).metadata.to_dict()["events"]
        final_events = prepared.prepared.frame_at(4).metadata.to_dict()["events"]

    assert not np.any(np.all(final == (224, 42, 32), axis=2))
    assert first_events == ["started"]
    assert final_events == ["object-exited", "completed"]


def test_parallax_preserves_filled_borders_and_particles_repeat(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    baseline = project
    project, _parallax, _clip = _add_action(
        project,
        "scene.parallax",
        "artwork",
        {"travel": [0.08, 0.03], "strength": 1.4},
        duration=7,
    )
    project, _particles_action, _particles_clip = _add_action(
        project,
        "environment.particles",
        "subject",
        {"count": 40, "color": "#f4d06f", "seed": 23, "speed": 0.2},
        duration=7,
    )

    with StudioRenderSession(baseline, artwork_path, output_width=64, output_height=64) as session:
        unchanged = session.frame_at(3)
    with StudioRenderSession(project, artwork_path, output_width=64, output_height=64) as session:
        first = session.frame_at(3)
    with StudioRenderSession(project, artwork_path, output_width=64, output_height=64) as session:
        second = session.frame_at(3)

    assert not np.array_equal(first, unchanged)
    assert np.array_equal(first, second)
    assert np.all(first[[0, -1], [0, -1]] != 0)



def test_camera_inspect_finishes_on_the_selected_scene_object(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    project, _invocation, _clip = _add_action(
        project,
        "camera.inspect",
        "subject",
        {"zoom": 2.0},
    )

    with StudioRenderSession(
        project,
        artwork_path,
        output_width=64,
        output_height=64,
    ) as session:
        final = session.frame_at(4)
    assert final[32, 32, 0] > 180
    assert final[32, 32, 1] < 100



def test_object_action_composes_after_an_existing_reveal(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    config = RenderConfig(
        effect="wave",
        width=64,
        fps=30,
        duration=1.0,
        hold_start=0.1,
        hold_end=0.1,
        quality="fast",
    ).validate()
    project, _effect_clip = add_effect_clip(
        project,
        config,
        start_frame=0,
        duration_seconds=1.0,
        target_clip_id="artwork-main",
    )
    project, _invocation, _clip = _add_action(
        project,
        "object.move",
        "subject",
        {"destination": [0.7, 0.5], "seed": 41},
    )

    with StudioRenderSession(
        project,
        artwork_path,
        output_width=64,
        output_height=64,
    ) as session:
        first = session.frame_at(3)
        second = session.frame_at(3)
        assert session.execution_mode == "semantic"

    assert np.array_equal(first, second)

def test_camera_zoom_out_finishes_on_the_faithful_artwork_frame(
    tmp_path: Path,
) -> None:
    project, artwork_path = _project_with_resources(tmp_path)
    baseline = project
    project, _invocation, _clip = _add_action(
        project,
        "camera.zoom_out",
        "camera",
        {"start_zoom": 2.0},
    )

    with StudioRenderSession(baseline, artwork_path, output_width=64, output_height=64) as session:
        expected = session.frame_at(4)
    with StudioRenderSession(project, artwork_path, output_width=64, output_height=64) as session:
        start = session.frame_at(0)
        final = session.frame_at(4)

    assert not np.array_equal(start, expected)
    assert np.array_equal(final, expected)


def test_action_clip_trim_move_duplicate_and_split_keep_intents_in_sync(
    tmp_path: Path,
) -> None:
    project, _artwork_path = _project_with_resources(tmp_path)
    project, invocation, clip = _add_action(
        project,
        "object.move",
        "subject",
        {"destination": [0.7, 0.4], "seed": 31},
        start=2,
        duration=10,
    )

    trimmed = trim_clip(project, clip.clip_id, 4, 11)
    trimmed_invocation = next(
        item for item in trimmed.invocations if item.invocation_id == invocation.invocation_id
    )
    assert (trimmed_invocation.start_frame, trimmed_invocation.duration_frames) == (4, 7)

    moved = move_clip(trimmed, clip.clip_id, 12)
    moved_invocation = next(
        item for item in moved.invocations if item.invocation_id == invocation.invocation_id
    )
    assert (moved_invocation.start_frame, moved_invocation.duration_frames) == (12, 7)

    duplicated, duplicate = duplicate_clip(moved, clip.clip_id, target_frame=20)
    assert duplicate.invocation_id != clip.invocation_id
    duplicate_invocation = next(
        item for item in duplicated.invocations if item.invocation_id == duplicate.invocation_id
    )
    assert duplicate_invocation.parameters == moved_invocation.parameters
    assert duplicate_invocation.start_frame == 20

    split, right = split_clip(duplicated, duplicate.clip_id, 23)
    assert right.invocation_id != duplicate.invocation_id
    left_invocation = next(
        item for item in split.invocations if item.invocation_id == duplicate.invocation_id
    )
    right_invocation = next(
        item for item in split.invocations if item.invocation_id == right.invocation_id
    )
    assert (left_invocation.start_frame, left_invocation.duration_frames) == (20, 3)
    assert (right_invocation.start_frame, right_invocation.duration_frames) == (23, 4)


def test_missing_depth_is_explained_before_the_renderer_is_prepared(
    tmp_path: Path,
) -> None:
    artwork, _mask, _depth = _write_scene(tmp_path)
    project = StudioProject.new(artwork)
    assert project.scene is not None

    decision = build_studio_capability_registry().evaluate(
        "scene.parallax",
        project.scene,
        "artwork",
    )

    assert decision.status == AvailabilityStatus.ANALYSIS_REQUIRED
    assert "depth-aware" in decision.reasons[0]
    assert "depth" in decision.reasons[0]


def test_ignoring_a_target_removes_its_action_clip_and_invocation(
    tmp_path: Path,
) -> None:
    project, _artwork_path = _project_with_resources(tmp_path)
    project, invocation, clip = _add_action(
        project,
        "object.exit_frame",
        "subject",
        {"direction": "left"},
    )

    updated = remove_scene_object(project, "subject")

    assert updated.scene is not None
    assert updated.scene.object_by_id("subject") is None
    assert all(
        item.invocation_id != invocation.invocation_id
        for item in updated.invocations
    )
    assert all(
        not is_semantic_action_clip(item) or item.clip_id != clip.clip_id
        for track in updated.tracks
        for item in track.clips
    )


def test_session_resolves_relative_masks_from_the_project_directory(
    tmp_path: Path,
) -> None:
    project_directory = tmp_path / "project-assets"
    project_directory.mkdir()
    project, artwork_path = _project_with_resources(project_directory)
    source_directory = tmp_path / "external-artwork"
    source_directory.mkdir()
    external_artwork = source_directory / artwork_path.name
    with Image.open(artwork_path) as image:
        image.save(external_artwork)
    relative_assets = tuple(
        replace(asset, path=Path(asset.path).name)
        for asset in project.assets
    )
    project = replace(project, assets=relative_assets).validate()
    project, _invocation, _clip = _add_action(
        project,
        "object.move",
        "subject",
        {"destination": [0.7, 0.5]},
    )

    with StudioRenderSession(
        project,
        external_artwork,
        output_width=64,
        output_height=64,
        resource_base=project_directory,
    ) as session:
        rendered = session.frame_at(4)

    assert rendered[30, 45, 0] > 180

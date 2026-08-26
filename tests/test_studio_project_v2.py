from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from artanimate.studio.adapters.classic_2d import (
    build_classic_2d_renderer_registry,
    build_legacy_capability_registry,
)
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.model import (
    STUDIO_SCHEMA_VERSION,
    StudioProject,
    migrate_project_payload,
)
from artanimate.studio.persistence import load_project, save_project
from artanimate.studio.semantic import RenderConstraints, RenderPlanner


FIXTURES = Path(__file__).with_name("fixtures")
V1_FIXTURE = FIXTURES / "studio_project_v1.artanimate"
V2_FIXTURE = FIXTURES / "studio_project_v2.artanimate"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_signature(project: StudioProject) -> tuple:
    semantic = project_as_semantic(project)
    renderers = build_classic_2d_renderer_registry(
        project,
        project.artwork.path,
    )
    plan = RenderPlanner(
        build_legacy_capability_registry(),
        renderers,
    ).plan(
        project.project_id,
        semantic.scene,
        tuple(
            item
            for item in semantic.invocations
            if item.capability_id != "audio.play"
        ),
        RenderConstraints(
            project.settings.width,
            project.settings.height,
            project.settings.fps,
            quality=project.export.quality,
        ),
    )
    return tuple(
        (
            entry.request.invocation.to_dict(),
            entry.renderer_id,
            entry.renderer_version,
            entry.request.seed,
        )
        for entry in plan.entries
    )


def test_v1_fixture_migrates_offline_without_rewriting_render_snapshots() -> None:
    raw = _json(V1_FIXTURE)
    before = deepcopy(raw)
    original_snapshot = raw["tracks"][1]["clips"][0]["parameters"][
        "render_config"
    ]

    project = StudioProject.from_dict(raw)
    migrated = project.to_dict()
    reveal = next(
        item
        for item in project.invocations
        if item.capability_id == "reveal.chromatic"
    )

    assert raw == before
    assert project.schema_version == STUDIO_SCHEMA_VERSION == 2
    assert project.scene is not None
    assert project.scene.scene_id == "scene:fixture-project-v1"
    assert project.tracks[0].clips[0].legacy_kind == "artwork_2d"
    assert project.tracks[0].clips[0].invocation_id is not None
    assert reveal.parameters["render_config"] == original_snapshot
    assert migrated["vendor_metadata"] == raw["vendor_metadata"]


def test_v2_fixture_round_trips_unknown_semantic_types_and_missing_renderer() -> None:
    raw = _json(V2_FIXTURE)
    project = StudioProject.from_dict(raw)
    custom_object = project.scene.object_by_id("curatorial-zone")
    custom_invocation = next(
        item for item in project.invocations if item.invocation_id == "vendor:aura:01"
    )

    assert custom_object is not None
    assert custom_object.semantic_type == "museum.custom.zone"
    assert "vendor.aura-reactive" in custom_object.affordance_ids
    assert custom_invocation.capability_id == "vendor.animate-aura"
    assert custom_invocation.renderer_policy.renderer_ids == (
        "vendor.renderer.not-installed",
    )

    encoded = project.to_dict()
    restored = StudioProject.from_dict(encoded)
    assert restored == project
    assert encoded["vendor_document"] == raw["vendor_document"]
    assert encoded["renderer_preferences"] == raw["renderer_preferences"]
    assert restored.triggers[0].event_id == "completed"


def test_legacy_binding_preserves_missing_renderer_and_extension_parameters() -> None:
    raw = _json(V2_FIXTURE)
    content = raw["invocations"][0]
    content["renderer_policy"] = {
        "mode": "pinned",
        "renderer_ids": ["vendor.renderer.not-installed"],
    }
    content["parameters"]["future_hint"] = {
        "strategy": "keep-intent",
    }

    project = StudioProject.from_dict(raw)
    restored = next(
        item
        for item in project.invocations
        if item.invocation_id == content["invocation_id"]
    )

    assert restored.renderer_policy.renderer_ids == (
        "vendor.renderer.not-installed",
    )
    assert restored.parameters["future_hint"] == {"strategy": "keep-intent"}
    assert restored.parameters["source_in_frame"] == 0


def test_saving_and_reopening_keeps_the_same_render_plan(tmp_path: Path) -> None:
    project = load_project(V1_FIXTURE)
    before = _plan_signature(project)

    destination = save_project(project, tmp_path / "migrated-v2")
    reopened = load_project(destination)

    assert _plan_signature(reopened) == before
    assert reopened == project


def test_migration_is_pure_successive_and_idempotent() -> None:
    raw = _json(V1_FIXTURE)
    before = deepcopy(raw)

    migrated = migrate_project_payload(raw)
    repeated = migrate_project_payload(migrated)

    assert raw == before
    assert migrated["schema_version"] == 2
    assert repeated == migrated
    assert all(
        clip["invocation_id"]
        for track in migrated["tracks"]
        for clip in track["clips"]
    )

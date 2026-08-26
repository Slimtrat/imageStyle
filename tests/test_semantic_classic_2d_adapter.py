from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core.effects import effect_keys
from artanimate.studio.adapters.classic_2d import (
    ClosedPreparedRenderError,
    build_classic_2d_renderer_registry,
    build_legacy_capability_registry,
    prepare_render_plan,
)
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.adapters.semantic_compositor import SemanticPlanCompositor
from artanimate.studio.compositor import StudioCompositor
from artanimate.studio.effect_2d import add_effect_clip
from artanimate.studio.model import StudioProject
from artanimate.studio.semantic import RenderConstraints, RenderPlanner
from artanimate.studio.source_registry import ArtworkSourceRegistry


def _project_with_effect(tmp_path: Path) -> tuple[StudioProject, Path]:
    artwork = tmp_path / "artwork.png"
    pixels = np.zeros((72, 108, 3), dtype=np.uint8)
    pixels[:] = (22, 28, 38)
    pixels[8:64, 12:96] = (214, 52, 92)
    pixels[24:48, 36:72] = (42, 170, 218)
    Image.fromarray(pixels).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=4)
    project, _clip = add_effect_clip(
        project,
        RenderConfig(
            effect="rgb_fade",
            duration=1.0,
            fps=30,
            width=96,
            quality="fast",
            hold_start=0.0,
            hold_end=0.0,
            seed=17,
        ),
        start_frame=30,
        duration_seconds=1.0,
        intensity=0.78,
        opacity=0.66,
    )
    return project, artwork


def test_classic_adapters_register_every_existing_2d_effect(tmp_path: Path) -> None:
    project, artwork = _project_with_effect(tmp_path)
    renderers = build_classic_2d_renderer_registry(project, artwork)

    for effect_key in effect_keys():
        renderer = renderers.get(f"classic.effect.{effect_key}")
        assert renderer.descriptor.capability_ids
    assert renderers.get("classic.artwork.static")
    assert renderers.get("classic.camera-2d")


def test_semantic_render_plan_matches_legacy_compositor_golden_frames(tmp_path: Path) -> None:
    project, artwork = _project_with_effect(tmp_path)
    sources = ArtworkSourceRegistry()
    semantic = project_as_semantic(project)
    capabilities = build_legacy_capability_registry()
    renderers = build_classic_2d_renderer_registry(
        project,
        artwork,
        sources=sources,
    )
    constraints = RenderConstraints(180, 320, project.settings.fps, quality="studio")
    plan = RenderPlanner(capabilities, renderers).plan(
        project.project_id,
        semantic.scene,
        semantic.invocations,
        constraints,
    )
    legacy = StudioCompositor(
        project,
        sources.sources_for(project, artwork),
        output_width=180,
        output_height=320,
    )

    with prepare_render_plan(plan, renderers) as prepared:
        migrated = SemanticPlanCompositor(project, semantic, prepared)
        for frame_index in (0, 29, 30, 38, 45, 59, 60, 119):
            assert np.array_equal(
                migrated.frame_at(frame_index),
                legacy.frame_at(frame_index),
            ), frame_index


def test_prepared_plan_closes_all_native_sources_and_rejects_late_frames(tmp_path: Path) -> None:
    project, artwork = _project_with_effect(tmp_path)
    semantic = project_as_semantic(project)
    capabilities = build_legacy_capability_registry()
    renderers = build_classic_2d_renderer_registry(project, artwork)
    plan = RenderPlanner(capabilities, renderers).plan(
        project.project_id,
        semantic.scene,
        semantic.invocations,
        RenderConstraints(180, 320, 30),
    )
    prepared = prepare_render_plan(plan, renderers)
    first = prepared.entries[0].prepared

    prepared.close()
    prepared.close()

    assert prepared.closed
    assert all(item.prepared.closed for item in prepared.entries)
    with pytest.raises(ClosedPreparedRenderError, match="fermé"):
        first.frame_at(0)


def test_effect_seek_backward_is_independent_from_render_order(tmp_path: Path) -> None:
    project, artwork = _project_with_effect(tmp_path)
    semantic = project_as_semantic(project)
    capabilities = build_legacy_capability_registry()
    renderers = build_classic_2d_renderer_registry(project, artwork)
    plan = RenderPlanner(capabilities, renderers).plan(
        project.project_id,
        semantic.scene,
        semantic.invocations,
        RenderConstraints(180, 320, 30),
    )
    with prepare_render_plan(plan, renderers) as prepared:
        compositor = SemanticPlanCompositor(project, semantic, prepared)
        early = compositor.frame_at(34).copy()
        compositor.frame_at(58)
        restored = compositor.frame_at(34)

    assert np.array_equal(restored, early)

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core.effects import effect_keys
from artanimate.studio.adapters.classic_2d import (
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


@pytest.mark.parametrize("effect_key", effect_keys())
def test_every_native_effect_matches_its_semantic_adapter_golden_frames(
    tmp_path: Path,
    effect_key: str,
) -> None:
    artwork = tmp_path / f"{effect_key}.png"
    y, x = np.mgrid[0:48, 0:64]
    pixels = np.empty((48, 64, 3), dtype=np.uint8)
    pixels[..., 0] = (x * 4 + y * 2) % 256
    pixels[..., 1] = (x * 2 + 40) % 256
    pixels[..., 2] = (y * 5 + 70) % 256
    pixels[10:38, 14:50] = (224, 54, 96)
    Image.fromarray(pixels).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=2)
    project, clip = add_effect_clip(
        project,
        RenderConfig(
            effect=effect_key,
            duration=1.0,
            fps=30,
            width=64,
            quality="fast",
            hold_start=0.0,
            hold_end=0.0,
            seed=31,
        ),
        start_frame=15,
        duration_seconds=1.0,
        intensity=0.73,
        opacity=0.81,
    )
    source_registry = ArtworkSourceRegistry(max_effect_sources=len(effect_keys()))
    semantic = project_as_semantic(project)
    renderers = build_classic_2d_renderer_registry(
        project,
        artwork,
        sources=source_registry,
    )
    plan = RenderPlanner(
        build_legacy_capability_registry(),
        renderers,
    ).plan(
        project.project_id,
        semantic.scene,
        semantic.invocations,
        RenderConstraints(90, 160, 30),
    )
    legacy = StudioCompositor(
        project,
        source_registry.sources_for(project, artwork),
        output_width=90,
        output_height=160,
    )

    with prepare_render_plan(plan, renderers) as prepared:
        migrated = SemanticPlanCompositor(project, semantic, prepared)
        for frame_index in (
            clip.start_frame,
            clip.start_frame + clip.duration_frames // 2,
            clip.end_frame - 1,
        ):
            assert np.array_equal(
                migrated.frame_at(frame_index),
                legacy.frame_at(frame_index),
            ), (effect_key, frame_index)

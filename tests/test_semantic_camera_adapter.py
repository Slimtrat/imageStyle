from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from artanimate.studio.adapters.classic_2d import (
    build_classic_2d_renderer_registry,
    build_legacy_capability_registry,
    prepare_render_plan,
)
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.adapters.semantic_compositor import SemanticPlanCompositor
from artanimate.studio.compositor import StudioCompositor
from artanimate.studio.model import (
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Easing,
    StudioProject,
)
from artanimate.studio.semantic import RenderConstraints, RenderPlanner
from artanimate.studio.source_registry import ArtworkSourceRegistry


def test_camera_capability_preserves_authored_keyframes_and_easing(tmp_path: Path) -> None:
    artwork = tmp_path / "camera-artwork.png"
    pixels = np.zeros((80, 120, 3), dtype=np.uint8)
    pixels[:, :40] = (220, 50, 80)
    pixels[:, 40:80] = (40, 180, 120)
    pixels[:, 80:] = (42, 92, 224)
    Image.fromarray(pixels).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=2)
    artwork_track = project.tracks[0]
    artwork_clip = replace(
        artwork_track.clips[0],
        camera=CameraAnimation(
            (
                CameraKeyframe(
                    0,
                    CameraPose(x=0.22, y=0.42, zoom=1.8, rotation_degrees=-4),
                    Easing.EASE_OUT,
                ),
                CameraKeyframe(
                    59,
                    CameraPose(x=0.72, y=0.58, zoom=1.15, rotation_degrees=3),
                    Easing.EASE_IN_OUT,
                ),
            )
        ),
    )
    project = replace(
        project,
        tracks=(replace(artwork_track, clips=(artwork_clip,)), *project.tracks[1:]),
    ).validate()
    source_registry = ArtworkSourceRegistry()
    semantic = project_as_semantic(project)
    camera_invocation = next(
        item for item in semantic.invocations if item.capability_id == "camera.animate"
    )
    assert camera_invocation.parameters.to_dict()["keyframes"][0]["easing"] == "ease_out"
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
        RenderConstraints(180, 320, 30),
    )
    legacy = StudioCompositor(
        project,
        source_registry.sources_for(project, artwork),
        output_width=180,
        output_height=320,
    )

    with prepare_render_plan(plan, renderers) as prepared:
        migrated = SemanticPlanCompositor(project, semantic, prepared)
        for frame_index in (0, 12, 29, 46, 59):
            assert np.array_equal(
                migrated.frame_at(frame_index),
                legacy.frame_at(frame_index),
            ), frame_index

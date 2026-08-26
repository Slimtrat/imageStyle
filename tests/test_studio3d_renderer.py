from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
from PIL import Image
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d_capture import StandaloneStudio3DCapture
from artanimate.desktop.studio3d_renderer import ClassicStudio3DRenderer
from artanimate.studio.adapters.classic_2d import build_legacy_capability_registry
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.semantic import RendererRegistry, RenderConstraints, RenderPlanner

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])



def _semantic_3d_project(tmp_path):
    artwork = tmp_path / "artwork.png"
    pixels = np.zeros((64, 96, 3), dtype=np.uint8)
    pixels[:, :32] = (220, 50, 30)
    pixels[:, 32:64] = (30, 180, 80)
    pixels[:, 64:] = (35, 70, 220)
    Image.fromarray(pixels).save(artwork)
    config = RenderConfig(
        effect="sand",
        duration=1.0,
        fps=30,
        width=96,
        hold_start=0.1,
        hold_end=0.1,
        quality="fast",
    )
    project = StudioProject.new(artwork, fps=30, duration_seconds=1)
    video = project.tracks[0]
    clip = replace(
        video.clips[0],
        kind=ClipKind.ARTWORK_3D,
        parameters={
            "schema_version": 1,
            "render_config": config.to_dict(),
            "camera": {
                "yaw": 3.0,
                "pitch": -76.0,
                "distance": 600.0,
                "motion": "top_drift",
                "motion_strength": 0.7,
            },
            "lamp_brightness": 2.8,
            "lamp_motion": 0.4,
        },
    )
    project = replace(
        project,
        tracks=(replace(video, clips=(clip,)), *project.tracks[1:]),
    ).validate()
    return artwork, project


def _prepared_3d(tmp_path):
    artwork, project = _semantic_3d_project(tmp_path)
    semantic = project_as_semantic(project)
    invocation = next(
        item
        for item in semantic.invocations
        if item.capability_id == "scene.depth_present"
    )
    renderer = ClassicStudio3DRenderer(artwork)
    renderers = RendererRegistry()
    renderers.register(renderer)
    renderers.freeze()
    plan = RenderPlanner(
        build_legacy_capability_registry(),
        renderers,
    ).plan(
        project.project_id,
        semantic.scene,
        (invocation,),
        RenderConstraints(90, 160, 30, quality="fast", proxy=True),
    )
    return renderer.prepare(plan.entries[0].request)


def test_classic_studio3d_renderer_is_selected_by_the_semantic_plan(tmp_path) -> None:
    prepared = _prepared_3d(tmp_path)
    try:
        assert prepared.request.invocation.capability_id == "scene.depth_present"
        assert prepared.request.invocation.renderer_policy.renderer_ids == (
            "classic.studio-3d",
        )
        assert (prepared.width, prepared.height, prepared.fps, prepared.frame_count) == (
            90,
            160,
            30,
            30,
        )
        assert prepared.scene_data.stage_count >= 1
    finally:
        prepared.close()


def test_studio3d_prepared_render_is_random_access_and_complete(tmp_path) -> None:
    prepared = _prepared_3d(tmp_path)
    try:
        first = prepared.frame_at(4)
        prepared.frame_at(1)
        restored = prepared.frame_at(4)

        assert np.array_equal(restored.image, first.image)
        assert restored.metadata == first.metadata
        assert restored.blend_mode == "scene.3d.packet"
        metadata = restored.metadata.to_dict()
        assert metadata["frame_index"] == 4
        assert metadata["qml_properties"]["outputAspect"] == pytest.approx(9 / 16)
        assert metadata["qml_properties"]["cameraMotion"] == "top_drift"
        assert metadata["camera_pose"]["distance"] > 0
    finally:
        prepared.close()

    with pytest.raises(RuntimeError, match="fermé"):
        prepared.frame_at(0)


def test_real_offscreen_surface_captures_without_the_visible_workspace(
    app,
    tmp_path,
) -> None:
    prepared = _prepared_3d(tmp_path)
    try:
        with StandaloneStudio3DCapture(90, 160) as capture:
            image = capture.capture_at(prepared, 0)

        assert not image.isNull()
        assert image.size().toTuple() == (90, 160)
        assert capture.panel.testAttribute(
            Qt.WidgetAttribute.WA_DontShowOnScreen
        )
    finally:
        prepared.close()

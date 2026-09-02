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
from artanimate.desktop.studio3d_export import qimage_to_rgb
from artanimate.desktop.studio3d_renderer import (
    CapturedStudio3DRender,
    ClassicStudio3DRenderer,
)
from artanimate.studio.adapters.classic_2d import build_legacy_capability_registry
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.color_fidelity import measure_color_fidelity
from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.semantic import RendererRegistry, RenderConstraints, RenderPlanner


class _FakeCapturePort:
    def __init__(self) -> None:
        self.calls = []
        self.released = []

    def capture(self, prepared, frame_index, *, cancelled=None):
        self.calls.append((prepared, frame_index, cancelled))
        image = np.empty((prepared.height, prepared.width, 3), dtype=np.uint8)
        image[:] = (12, 34, 56)
        return image

    def release(self, prepared) -> None:
        self.released.append(prepared)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _semantic_3d_project(
    tmp_path,
    color_mode: str | None = None,
    *,
    camera_overrides: dict | None = None,
    lamp_brightness: float = 2.8,
    lamp_motion: float = 0.4,
):
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
    camera = {
        "yaw": 3.0,
        "pitch": -76.0,
        "distance": 600.0,
        "motion": "top_drift",
        "motion_strength": 0.7,
    }
    camera.update(camera_overrides or {})
    settings = {
        "schema_version": 1,
        "render_config": config.to_dict(),
        "camera": camera,
        "lamp_brightness": lamp_brightness,
        "lamp_motion": lamp_motion,
    }
    if color_mode is not None:
        settings["color_policy"] = {"mode": color_mode}
    clip = replace(
        video.clips[0],
        kind=ClipKind.ARTWORK_3D,
        parameters=settings,
    )
    project = replace(
        project,
        tracks=(replace(video, clips=(clip,)), *project.tracks[1:]),
    ).validate()
    return artwork, project


def _prepared_3d(tmp_path, color_mode: str | None = None, **scene_settings):
    artwork, project = _semantic_3d_project(
        tmp_path,
        color_mode,
        **scene_settings,
    )
    semantic = project_as_semantic(project)
    invocation = next(
        item
        for item in semantic.invocations
        if item.capability_id == "scene.depth_present"
    )
    renderer = ClassicStudio3DRenderer(artwork, capture_port=object())
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
    return renderer.prepare_state(plan.entries[0].request)


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
        assert metadata["qml_properties"]["artworkColorMode"] == "faithful"
        assert metadata["camera_pose"]["distance"] > 0
        start = prepared.frame_at(0)
        end = prepared.frame_at(prepared.frame_count - 1)
        assert np.array_equal(prepared.frame_at(0).image, start.image)
        assert np.array_equal(
            prepared.frame_at(prepared.frame_count - 1).image, end.image
        )
    finally:
        prepared.close()

    with pytest.raises(RuntimeError, match="fermé"):
        prepared.frame_at(0)


def test_captured_studio3d_render_returns_final_rgb_and_releases_resources(
    tmp_path,
) -> None:
    prepared = _prepared_3d(tmp_path)
    capture = _FakeCapturePort()
    rendered = CapturedStudio3DRender(prepared, capture, None)

    frame = rendered.frame_at(3)

    assert frame.blend_mode == "normal"
    assert frame.image.shape == (160, 90, 3)
    assert tuple(frame.image[0, 0]) == (12, 34, 56)
    assert frame.metadata["frame_index"] == 3
    assert capture.calls == [(prepared, 3, None)]

    rendered.close()
    rendered.close()
    assert capture.released == [prepared]
    with pytest.raises(RuntimeError, match="fermée"):
        rendered.frame_at(0)


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


@pytest.mark.skipif(
    os.environ.get("ARTANIMATE_RUN_GPU_COLOR_TEST") != "1",
    reason="qualification GPU Windows explicite",
)
def test_windows_gpu_faithful_material_meets_delta_e_budget(app, tmp_path) -> None:
    faithful = _prepared_3d(tmp_path, "faithful")
    faithful_angled = _prepared_3d(
        tmp_path,
        "faithful",
        camera_overrides={
            "yaw": -11.0,
            "pitch": -70.0,
            "distance": 650.0,
            "motion": "fixed",
            "motion_strength": 0.0,
        },
        lamp_brightness=0.75,
        lamp_motion=0.0,
    )
    integrated = _prepared_3d(tmp_path, "scene_integrated")
    source_colors = np.array(
        ((220, 50, 30), (30, 180, 80), (35, 70, 220)),
        dtype=np.uint8,
    )
    try:
        with StandaloneStudio3DCapture(360, 640) as capture:
            frame_index = faithful.frame_count - 1
            faithful_rgb = qimage_to_rgb(capture.capture_at(faithful, frame_index))
            faithful_angled_rgb = qimage_to_rgb(
                capture.capture_at(faithful_angled, frame_index)
            )
            integrated_rgb = qimage_to_rgb(capture.capture_at(integrated, frame_index))

        def reference_for(rendered):
            pixels = rendered.reshape(-1, 3)
            distances = np.linalg.norm(
                pixels[:, None, :].astype(np.float64)
                - source_colors[None, :, :].astype(np.float64),
                axis=2,
            )
            labels = distances.argmin(axis=1)
            interior = (distances.min(axis=1) < 12.0).reshape(rendered.shape[:2])
            reference = source_colors[labels].reshape(rendered.shape)
            return reference, interior

        reference, interior = reference_for(faithful_rgb)
        faithful_reports = [
            measure_color_fidelity(reference, faithful_rgb, mask=interior)
        ]
        angled_reference, angled_interior = reference_for(faithful_angled_rgb)
        faithful_reports.append(
            measure_color_fidelity(
                angled_reference,
                faithful_angled_rgb,
                mask=angled_interior,
            )
        )
        integrated_report = measure_color_fidelity(
            reference,
            integrated_rgb,
            mask=interior,
        )

        assert all(report.sample_count > 10_000 for report in faithful_reports)
        assert all(report.passes for report in faithful_reports)
        assert integrated_report.passes is False
        assert all(
            report.median_delta_e00 < integrated_report.median_delta_e00
            for report in faithful_reports
        )
    finally:
        faithful.close()
        faithful_angled.close()
        integrated.close()

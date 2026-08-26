from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio_preview import StudioPreviewController
from artanimate.studio.adapters.legacy_project import project_as_semantic
from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.timeline import move_clip, trim_clip


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _three_d_project(artwork: Path) -> StudioProject:
    config = RenderConfig(
        effect="wave",
        duration=1.0,
        fps=30,
        width=96,
        hold_start=0.08,
        hold_end=0.08,
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
                "motion": "flyover",
                "motion_strength": 0.75,
                "distance": 620.0,
            },
        },
    )
    return replace(
        project,
        tracks=(replace(video, clips=(clip,)), *project.tracks[1:]),
    ).validate()


def _wait_for_frame(controller, project, artwork, frame):
    received = []
    failures = []
    loop = QEventLoop()

    def ready(index, image, cached):
        received.append((index, image, cached))
        loop.quit()

    controller.frameReady.connect(ready)
    controller.failed.connect(lambda message: (failures.append(message), loop.quit()))
    controller.request(project, artwork, frame)
    QTimer.singleShot(8000, loop.quit)
    loop.exec()
    controller.frameReady.disconnect(ready)
    assert failures == []
    assert received, "Le proxy 3D n’a livré aucune frame"
    return received[-1]


def test_trimmed_and_moved_3d_clip_renders_through_the_timeline_bridge(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "painting.png"
    Image.new("RGB", (96, 64), (180, 70, 35)).save(artwork)
    project = _three_d_project(artwork)
    project = trim_clip(project, "artwork-main", 5, 25)
    project = move_clip(project, "artwork-main", 8)
    before_render = project.to_dict()
    semantic = project_as_semantic(project)

    depth = next(
        item
        for item in semantic.invocations
        if item.capability_id == "scene.depth_present"
    )
    assert (depth.start_frame, depth.duration_frames) == (8, 20)
    assert depth.parameters["source_in_frame"] == 5
    assert all(item.capability_id != "camera.animate" for item in semantic.invocations)

    controller = StudioPreviewController()
    controller.set_proxy_width(90)
    try:
        index, image, cached = _wait_for_frame(
            controller,
            project,
            artwork,
            10,
        )

        assert index == 10
        assert not cached
        assert image.size().toTuple() == (90, 160)
        assert (90, 160) in controller.three_d_capture._surfaces
        assert project.to_dict() == before_render
    finally:
        controller.shutdown()
    assert controller.active_job_count == 0
    assert controller.three_d_capture._surfaces == {}

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio3d_bridge import Studio3DCaptureBridge
from artanimate.studio.persistence import load_project, project_digest, save_project
from artanimate.v3_qualification import (
    CONTROL_FRAMES,
    _render_controls,
    build_v3_qualification_project,
    qualification_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_qualification_scenario_covers_the_complete_v3_reel(tmp_path: Path) -> None:
    project, project_path, media = build_v3_qualification_project(tmp_path)

    assert qualification_scenario(project) == {
        "resolution": [1080, 1920],
        "fps": 30,
        "duration_frames": 360,
        "duration_seconds": 12.0,
        "camera_shots": 3,
        "camera_keyframes": 4,
        "effect_2d_clips": 1,
        "artwork_3d_clips": 1,
        "real_image_clips": 1,
        "manual_matches": 1,
        "audio_clips": 1,
        "audio_trimmed": True,
    }
    assert all(path.is_file() for path in media.values())
    save_project(project, project_path)
    reopened = load_project(project_path)
    assert reopened == project
    assert project_digest(reopened) == project_digest(project)


def test_qualification_controls_render_through_the_real_semantic_pipeline(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication(["ArtAnimate V3 test"])
    project, project_path, media = build_v3_qualification_project(
        tmp_path,
        width=90,
        height=160,
    )
    bridge = Studio3DCaptureBridge(max_surfaces=1)
    try:
        frames, mode = _render_controls(
            project,
            media["artwork"],
            project_path,
            bridge,
        )
    finally:
        bridge.close()
        application.processEvents()

    assert mode == "semantic"
    assert tuple(frames) == CONTROL_FRAMES
    assert all(frame.shape == (160, 90, 3) for frame in frames.values())
    assert all(frame.dtype == np.uint8 for frame in frames.values())
    assert len({frame.tobytes() for frame in frames.values()}) >= 5


def test_windows_launcher_exposes_the_repeatable_v3_qualification() -> None:
    launcher = (PROJECT_ROOT / "packaging" / "windows" / "launcher.py").read_text(
        encoding="utf-8"
    )

    assert "--qualify-v3" in launcher
    assert "write_v3_qualification_report" in launcher

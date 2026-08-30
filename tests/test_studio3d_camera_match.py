from __future__ import annotations

import pytest

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d_camera_match import solve_studio3d_camera_match
from artanimate.desktop.studio3d_state import (
    Studio3DSceneSettings,
    Studio3DSceneStateResolver,
)


def test_camera_match_recovers_the_real_artwork_viewpoint() -> None:
    target_quad = (
        (0.18147177, 0.37604979),
        (0.90668362, 0.29581106),
        (0.91830659, 0.69737118),
        (0.18893912, 0.62891197),
    )

    pose = solve_studio3d_camera_match(
        target_quad,
        artwork_aspect=1880 / 1306,
        output_width=540,
        output_height=960,
    )

    assert pose.reprojection_error < 1.0
    assert 18.0 <= pose.field_of_view <= 118.0
    assert pose.distance > 0.0


def test_scene_camera_converges_then_holds_the_solved_pose() -> None:
    config = RenderConfig(duration=3.0, fps=30)
    match = {
        "start_frame": 30,
        "end_frame": 60,
        "x": 25.0,
        "y": -32.0,
        "z": 18.0,
        "pitch": -82.0,
        "yaw": -14.0,
        "roll": 5.0,
        "distance": 700.0,
        "field_of_view": 72.0,
    }
    settings = Studio3DSceneSettings.from_config(
        config,
        camera={
            "yaw": 4.0,
            "pitch": -73.0,
            "distance": 610.0,
            "motion": "fixed",
            "motion_strength": 0.0,
            "match": match,
        },
        output_aspect=9 / 16,
    )
    resolver = Studio3DSceneStateResolver(
        config,
        frame_count=90,
        artwork_aspect=1.44,
        settings=settings,
    )

    start = resolver.state_at(30)
    middle = resolver.state_at(45)
    end = resolver.state_at(60)
    held = resolver.state_at(89)

    assert start.camera_pose.match_weight == 0.0
    assert 0.0 < middle.camera_pose.match_weight < 1.0
    assert end.camera_pose.match_weight == 1.0
    assert held.camera_pose == end.camera_pose
    assert end.camera_pose.x == match["x"]
    assert end.camera_pose.roll == pytest.approx(match["roll"])
    assert end.camera_pose.field_of_view == match["field_of_view"]
    assert end.qml_properties()["cameraMatchWeight"] == 1.0

from __future__ import annotations

import pytest

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d_particles import (
    StudioLaserPathRecord,
    StudioSceneData,
)
from artanimate.desktop.studio3d_state import (
    Studio3DSceneSettings,
    Studio3DCameraSettings,
    Studio3DSceneStateResolver,
    effect_progress_at,
)


def _settings(config: RenderConfig, *, aspect: float = 9 / 16) -> Studio3DSceneSettings:
    return Studio3DSceneSettings.from_config(
        config,
        camera={
            "yaw": 4.0,
            "pitch": -76.0,
            "distance": 610.0,
            "pivot_y": -6.0,
            "orbit_turns": 0.12,
            "motion": "top_drift",
            "motion_strength": 0.7,
            "lamp": 2.8,
            "lamp_motion": 0.4,
        },
        output_aspect=aspect,
    )


def test_same_frame_restores_the_exact_same_complete_scene_state() -> None:
    config = RenderConfig(
        effect="screenprint_laser",
        duration=4.0,
        fps=20,
        hold_start=0.5,
        hold_end=0.5,
    )
    scene_data = StudioSceneData(
        particles=(),
        stage_count=4,
        outline_stage=2,
        laser_path=(
            StudioLaserPathRecord(0.1, 0.2, True),
            StudioLaserPathRecord(0.8, 0.7, True),
        ),
    )
    resolver = Studio3DSceneStateResolver(
        config,
        frame_count=80,
        artwork_aspect=1.5,
        settings=_settings(config),
        scene_data=scene_data,
    )

    first = resolver.state_at(47)
    resolver.state_at(72)
    restored = resolver.state_at(47)

    assert restored == first
    assert restored.qml_properties() == first.qml_properties()
    assert restored.timecode == "00:00:02:07"
    assert restored.tool.stage in range(scene_data.stage_count)


def test_backward_seek_is_direct_and_does_not_depend_on_prior_sequence() -> None:
    config = RenderConfig(effect="wave", duration=3.0, fps=12)
    resolver = Studio3DSceneStateResolver(
        config,
        frame_count=36,
        artwork_aspect=0.75,
        settings=_settings(config),
    )
    fresh = Studio3DSceneStateResolver(
        config,
        frame_count=36,
        artwork_aspect=0.75,
        settings=_settings(config),
    )

    resolver.state_at(30)

    assert resolver.state_at(5) == fresh.state_at(5)
    assert resolver.state_at(5).effect_progress < resolver.state_at(30).effect_progress


def test_effect_and_camera_progress_share_the_exact_studio_clock() -> None:
    config = RenderConfig(
        effect="rgb_fade",
        duration=10.0,
        fps=10,
        hold_start=2.0,
        hold_end=2.0,
    )
    resolver = Studio3DSceneStateResolver(
        config,
        frame_count=101,
        artwork_aspect=1.6,
        settings=_settings(config),
    )

    middle = resolver.state_at(50)

    assert middle.time == resolver.clock.frame_to_fraction(50)
    assert middle.effect_progress == pytest.approx(0.5)
    assert middle.camera_timing.drift_envelope == pytest.approx(0.7)
    assert effect_progress_at(config, 20, 101, clock=resolver.clock) == 0.0
    assert effect_progress_at(config, 80, 101, clock=resolver.clock) == 1.0


def test_camera_pose_accounts_for_vertical_output_framing() -> None:
    config = RenderConfig(duration=2.0, fps=20)
    vertical = Studio3DSceneStateResolver(
        config,
        frame_count=40,
        artwork_aspect=1.6,
        settings=_settings(config, aspect=9 / 16),
    ).state_at(39)
    horizontal = Studio3DSceneStateResolver(
        config,
        frame_count=40,
        artwork_aspect=1.6,
        settings=_settings(config, aspect=16 / 9),
    ).state_at(39)

    assert vertical.camera_pose.distance > horizontal.camera_pose.distance
    assert vertical.qml_properties()["outputAspect"] == pytest.approx(9 / 16)
    assert vertical.qml_properties()["artworkColorMode"] == "faithful"
    assert vertical.qml_properties()["artworkExposure"] == pytest.approx(1.0)


def test_scene_state_rejects_frames_outside_the_shot() -> None:
    config = RenderConfig(duration=2.0, fps=20)
    resolver = Studio3DSceneStateResolver(
        config,
        frame_count=40,
        artwork_aspect=1.0,
        settings=_settings(config),
    )

    with pytest.raises(IndexError, match="hors plage"):
        resolver.state_at(40)


def test_scene_settings_reject_invalid_camera_contracts() -> None:
    with pytest.raises(ValueError, match="distance"):
        Studio3DCameraSettings(distance=0.0)
    with pytest.raises(ValueError, match="Mouvement"):
        Studio3DCameraSettings(motion="free_orbit")
    with pytest.raises(ValueError, match="motion_strength"):
        Studio3DCameraSettings(motion_strength=1.3)

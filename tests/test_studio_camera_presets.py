from artanimate.studio.camera_presets import (
    CameraPreset,
    PresetApplyMode,
    apply_camera_preset,
    generate_camera_preset,
    golden_camera_path,
)
from artanimate.studio.model import CameraAnimation, CameraKeyframe, CameraPose


def test_all_presets_generate_editable_bounded_keyframes() -> None:
    for preset in CameraPreset:
        keyframes = generate_camera_preset(
            preset,
            start_frame=10,
            duration_frames=90,
            artwork_ratio=16 / 9,
            project_ratio=9 / 16,
            intensity=0.5,
            seed="project-42",
        )
        animation = CameraAnimation(keyframes).validate(clip_duration_frames=120)
        assert animation.keyframes[0].frame == 10
        assert animation.keyframes[-1].frame == 99
        assert all(0.25 <= keyframe.pose.zoom <= 20 for keyframe in keyframes)


def test_reveal_finishes_on_stable_whole_artwork() -> None:
    keyframes = generate_camera_preset(
        CameraPreset.REVEAL,
        start_frame=0,
        duration_frames=100,
        artwork_ratio=1.4,
        project_ratio=9 / 16,
    )
    penultimate, final = keyframes[-2:]
    assert penultimate.pose == CameraPose()
    assert final.pose == CameraPose()
    assert final.frame - penultimate.frame >= 10


def test_handheld_is_deterministic_and_subtle_by_default() -> None:
    first = generate_camera_preset(
        CameraPreset.HANDHELD,
        start_frame=0,
        duration_frames=120,
        artwork_ratio=1.0,
        project_ratio=9 / 16,
        intensity=0.25,
        seed="same-project",
    )
    second = generate_camera_preset(
        CameraPreset.HANDHELD,
        start_frame=0,
        duration_frames=120,
        artwork_ratio=1.0,
        project_ratio=9 / 16,
        intensity=0.25,
        seed="same-project",
    )
    assert golden_camera_path(first) == golden_camera_path(second)
    assert max(abs(keyframe.pose.x - 0.5) for keyframe in first) < 0.02
    assert max(abs(keyframe.pose.y - 0.5) for keyframe in first) < 0.02
    assert max(abs(keyframe.pose.rotation_degrees) for keyframe in first) < 0.3


def test_replace_and_insert_modes_are_explicit() -> None:
    animation = CameraAnimation(
        (
            CameraKeyframe(0, CameraPose()),
            CameraKeyframe(30, CameraPose(zoom=1.2)),
            CameraKeyframe(100, CameraPose(zoom=1.5)),
        )
    )
    replaced = apply_camera_preset(
        animation,
        CameraPreset.DRIFT,
        start_frame=20,
        duration_frames=60,
        clip_duration_frames=120,
        artwork_ratio=1.0,
        project_ratio=9 / 16,
        mode=PresetApplyMode.REPLACE,
    )
    inserted = apply_camera_preset(
        animation,
        CameraPreset.DRIFT,
        start_frame=20,
        duration_frames=60,
        clip_duration_frames=120,
        artwork_ratio=1.0,
        project_ratio=9 / 16,
        mode=PresetApplyMode.INSERT,
    )
    assert 30 not in {keyframe.frame for keyframe in replaced.keyframes}
    assert 30 in {keyframe.frame for keyframe in inserted.keyframes}
    assert 100 in {keyframe.frame for keyframe in replaced.keyframes}


def test_macro_golden_path_documents_trajectory() -> None:
    path = golden_camera_path(
        generate_camera_preset(
            CameraPreset.MACRO,
            start_frame=0,
            duration_frames=61,
            artwork_ratio=1.0,
            project_ratio=1.0,
            intensity=0.5,
            seed="golden",
        )
    )
    assert path == (
        (0.0, 0.38, 0.42, 3.3, 0.0),
        (33.0, 0.53, 0.48, 3.036, 0.0),
        (60.0, 0.62, 0.56, 2.772, 0.0),
    )


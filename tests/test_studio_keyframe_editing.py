import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from artanimate.studio.camera import (
    copy_camera_keyframe,
    move_camera_keyframe,
    set_camera_keyframe_easing,
)
from artanimate.studio.model import (
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Easing,
)


def animation() -> CameraAnimation:
    return CameraAnimation(
        (
            CameraKeyframe(0, CameraPose(zoom=4.0), Easing.EASE_OUT),
            CameraKeyframe(30, CameraPose(zoom=2.0), Easing.LINEAR),
            CameraKeyframe(60, CameraPose(zoom=1.0), Easing.EASE_IN_OUT),
        )
    )


def test_keyframes_can_move_copy_and_change_easing() -> None:
    moved = move_camera_keyframe(animation(), 30, 40)
    assert [keyframe.frame for keyframe in moved.keyframes] == [0, 40, 60]
    assert moved.keyframes[1].pose.zoom == 2.0

    copied = copy_camera_keyframe(moved, 40, 50)
    assert [keyframe.frame for keyframe in copied.keyframes] == [0, 40, 50, 60]
    assert copied.keyframes[2].pose == copied.keyframes[1].pose

    changed = set_camera_keyframe_easing(copied, 50, Easing.EASE_IN)
    assert changed.keyframes[2].easing == Easing.EASE_IN


def test_keyframe_editing_refuses_missing_or_occupied_targets() -> None:
    with pytest.raises(KeyError, match="introuvable"):
        move_camera_keyframe(animation(), 10, 20)
    with pytest.raises(ValueError, match="existe déjà"):
        move_camera_keyframe(animation(), 30, 60)
    with pytest.raises(ValueError, match="durée"):
        copy_camera_keyframe(animation(), 30, 120, clip_duration_frames=100)


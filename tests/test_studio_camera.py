import numpy as np

from artanimate.studio.camera import (
    interpolate_camera_pose,
    remove_camera_keyframe,
    render_camera_frame,
    resolve_camera_pose,
    upsert_camera_keyframe,
)
from artanimate.studio.model import (
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Easing,
)


def test_camera_resolves_keyframes_and_shortest_rotation() -> None:
    animation = CameraAnimation(
        (
            CameraKeyframe(
                0,
                CameraPose(x=0.75, y=0.25, zoom=4.0, rotation_degrees=170),
                Easing.LINEAR,
            ),
            CameraKeyframe(
                10,
                CameraPose(x=0.5, y=0.5, zoom=1.0, rotation_degrees=-170),
            ),
        )
    )

    middle = resolve_camera_pose(animation, 5)

    assert middle.x == 0.625
    assert middle.y == 0.375
    assert middle.zoom == 2.5
    assert middle.rotation_degrees == 180.0
    assert resolve_camera_pose(animation, 50) == animation.keyframes[-1].pose


def test_camera_easing_and_keyframe_upsert_are_deterministic() -> None:
    start = CameraPose(zoom=1.0)
    end = CameraPose(zoom=5.0)
    assert interpolate_camera_pose(start, end, 0.5, Easing.EASE_IN).zoom == 1.5

    animation = upsert_camera_keyframe(None, 20, end)
    animation = upsert_camera_keyframe(animation, 0, start, easing=Easing.LINEAR)
    animation = upsert_camera_keyframe(animation, 20, CameraPose(zoom=4.0))
    assert [keyframe.frame for keyframe in animation.keyframes] == [0, 20]
    assert animation.keyframes[-1].pose.zoom == 4.0
    assert remove_camera_keyframe(animation, 20).keyframes == (animation.keyframes[0],)


def test_camera_full_pose_preserves_artwork_and_macro_centers_target() -> None:
    artwork = np.zeros((100, 100, 3), dtype=np.uint8)
    artwork[:50, :50] = (255, 0, 0)
    artwork[:50, 50:] = (0, 255, 0)
    artwork[50:, :50] = (0, 0, 255)
    artwork[50:, 50:] = (255, 255, 0)

    full = render_camera_frame(artwork, 100, 100, CameraPose())
    macro = render_camera_frame(
        artwork,
        100,
        100,
        CameraPose(x=0.75, y=0.25, zoom=2.0),
    )

    assert np.array_equal(full, artwork)
    assert tuple(macro[50, 50]) == (0, 255, 0)
    assert np.array_equal(
        macro,
        render_camera_frame(
            artwork,
            100,
            100,
            CameraPose(x=0.75, y=0.25, zoom=2.0),
        ),
    )


def test_camera_contain_at_zoom_one_keeps_horizontal_artwork_complete() -> None:
    artwork = np.full((50, 100, 3), (220, 80, 40), dtype=np.uint8)

    frame = render_camera_frame(
        artwork,
        100,
        200,
        CameraPose(),
        background=(10, 20, 30),
    )

    assert tuple(frame[0, 0]) == (10, 20, 30)
    assert tuple(frame[100, 50]) == (220, 80, 40)
    assert np.all(frame[75:125] == (220, 80, 40))


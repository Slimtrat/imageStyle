from dataclasses import replace

import pytest

from artanimate.studio.model import (
    AssetKind,
    AudioExportMode,
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Clip,
    ClipKind,
    Easing,
    ExportSettings,
    MediaAsset,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
    Transition,
    TransitionKind,
)


def complete_project() -> StudioProject:
    base = StudioProject.new("C:/art/painting.png", fps=30, duration_seconds=10)
    real = MediaAsset("real-photo", AssetKind.IMAGE, "C:/art/real.jpg", width=1200, height=1800)
    music = MediaAsset("music", AssetKind.AUDIO, "C:/audio/reference.wav")
    camera = CameraAnimation(
        (
            CameraKeyframe(0, CameraPose(x=0.72, y=0.41, zoom=4.2), Easing.EASE_OUT),
            CameraKeyframe(149, CameraPose(x=0.5, y=0.5, zoom=1.0)),
        )
    )
    video = Track(
        "video-main",
        TrackKind.VIDEO,
        "Œuvre et réel",
        (
            Clip("artwork-shot", ClipKind.ARTWORK_2D, 0, 150, camera=camera),
            Clip("real-shot", ClipKind.STILL, 150, 150, asset_id="real-photo"),
        ),
    )
    effects = Track(
        "effects-main",
        TrackKind.EFFECT,
        "Effets",
        (
            Clip(
                "pigment-accent",
                ClipKind.EFFECT_2D,
                90,
                30,
                parameters={"effect": "pigment_sweep", "intensity": 0.25},
            ),
        ),
    )
    audio = Track(
        "audio-main",
        TrackKind.AUDIO,
        "Musique",
        (Clip("music-clip", ClipKind.AUDIO, 0, 300, asset_id="music"),),
    )
    return replace(
        base,
        assets=(real, music),
        tracks=(video, effects, audio),
        transitions=(
            Transition(
                "to-real",
                TransitionKind.DISSOLVE,
                "artwork-shot",
                "real-shot",
                start_frame=145,
                duration_frames=10,
            ),
        ),
        export=ExportSettings(audio_mode=AudioExportMode.REFERENCE),
    ).validate()


def test_new_project_is_artwork_first_and_reel_native() -> None:
    project = StudioProject.new("painting.png")

    assert project.artwork.path == "painting.png"
    assert project.settings == ProjectSettings()
    assert [track.kind for track in project.tracks] == [
        TrackKind.VIDEO,
        TrackKind.EFFECT,
        TrackKind.AUDIO,
    ]
    assert project.tracks[0].clips[0].kind == ClipKind.ARTWORK_2D
    assert project.tracks[0].clips[0].camera.keyframes[0].pose == CameraPose()
    assert project.export.audio_mode == AudioExportMode.REFERENCE


def test_complete_project_round_trips_without_losing_timeline_state() -> None:
    project = complete_project()

    restored = StudioProject.from_dict(project.to_dict())

    assert restored == project
    assert restored.tracks[0].clips[0].camera.keyframes[-1].pose.zoom == 1.0
    assert restored.transitions[0].kind == TransitionKind.DISSOLVE


def test_project_preserves_unknown_keys_and_rejects_future_schemas() -> None:
    payload = complete_project().to_dict()
    payload["cloud_url"] = "https://invalid.example"
    restored = StudioProject.from_dict(payload)
    assert restored.to_dict()["cloud_url"] == "https://invalid.example"

    payload = complete_project().to_dict()
    payload["schema_version"] = 99
    with pytest.raises(ValueError, match="version plus récente"):
        StudioProject.from_dict(payload)


def test_project_rejects_wrong_asset_type_and_external_artwork_source() -> None:
    project = complete_project()
    wrong_real = replace(project.assets[0], kind=AssetKind.AUDIO, width=None, height=None)
    with pytest.raises(ValueError, match="Type d’asset incompatible"):
        replace(project, assets=(wrong_real, project.assets[1])).validate()

    artwork_clip = replace(project.tracks[0].clips[0], asset_id="real-photo")
    broken_track = replace(
        project.tracks[0],
        clips=(artwork_clip, project.tracks[0].clips[1]),
    )
    with pytest.raises(ValueError, match="œuvre centrale"):
        replace(project, tracks=(broken_track, *project.tracks[1:])).validate()


def test_project_rejects_duplicate_ids_and_out_of_range_keyframes() -> None:
    project = complete_project()
    with pytest.raises(ValueError, match="clip dupliqué"):
        duplicate = replace(
            project.tracks[1].clips[0],
            clip_id=project.tracks[0].clips[0].clip_id,
        )
        effects = replace(project.tracks[1], clips=(duplicate,))
        replace(project, tracks=(project.tracks[0], effects, project.tracks[2])).validate()

    invalid_camera = CameraAnimation(
        (CameraKeyframe(150, CameraPose(), Easing.LINEAR),)
    )
    invalid_clip = replace(project.tracks[0].clips[0], camera=invalid_camera)
    video = replace(
        project.tracks[0],
        clips=(invalid_clip, project.tracks[0].clips[1]),
    )
    with pytest.raises(ValueError, match="dépasse la durée locale"):
        replace(project, tracks=(video, *project.tracks[1:])).validate()


from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from artanimate.studio.camera import move_camera_keyframe, resolve_camera_pose
from artanimate.studio.explore import (
    ExplorePlanRole,
    SMART_MAX_ROTATION_DEGREES,
    SMART_MAX_ZOOM,
    create_explore_project,
    explore_clip,
    explore_clip_role,
    is_explore_project,
    mark_explore_music_attached,
    recommend_explore_zones,
    replace_explore_real_placeholder,
)
from artanimate.studio.model import (
    AssetKind,
    Clip,
    ClipKind,
    Easing,
    MediaAsset,
    StudioProject,
    TrackKind,
    TransitionKind,
)
from artanimate.studio.semantic import Affordance, Bounds, SceneObject
from artanimate.studio.timeline import delete_clips, move_clip, trim_clip


from artanimate.studio.transitions import delete_transition, update_dissolve
def _project(tmp_path: Path, *, fps: int = 30) -> StudioProject:
    tmp_path.mkdir(parents=True, exist_ok=True)
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (120, 80), (160, 90, 40)).save(artwork)
    base = StudioProject.new(artwork, fps=fps)
    scene = replace(
        base.scene,
        objects=(
            *base.scene.objects,
            SceneObject(
                "zone-left",
                "artwork.region",
                "Détail gauche",
                bounds=Bounds(0.08, 0.15, 0.28, 0.35),
            ),
            SceneObject(
                "zone-right",
                "artwork.region",
                "Détail droit",
                bounds=Bounds(0.62, 0.42, 0.25, 0.3),
            ),
        ),
    )
    return replace(
        base,
        artwork=replace(base.artwork, width=120, height=80),
        scene=scene,
    ).validate()


def _explore(tmp_path: Path, *, fps: int = 30) -> StudioProject:
    return create_explore_project(
        _project(tmp_path, fps=fps),
        macro_zone_id="zone-left",
        inspection_zone_id="zone-right",
    ).project


def _project_with_proposals(tmp_path: Path) -> StudioProject:
    base = _project(tmp_path)
    assert base.scene is not None
    proposals = (
        SceneObject(
            "auto-interest-01",
            "artwork.region.face",
            "Visage",
            confidence=0.8,
            bounds=Bounds(0.08, 0.12, 0.16, 0.2),
            attributes={
                "proposal_status": "proposed",
                "rank": 1,
                "scores": {"global": 0.8},
            },
            affordances=(Affordance("camera-inspectable"),),
        ),
        SceneObject(
            "auto-interest-02",
            "artwork.region.lines",
            "Motif droit",
            confidence=0.72,
            bounds=Bounds(0.72, 0.62, 0.18, 0.2),
            attributes={
                "proposal_status": "proposed",
                "rank": 2,
                "scores": {"global": 0.72},
            },
            affordances=(Affordance("camera-inspectable"),),
        ),
    )
    return replace(
        base,
        scene=replace(base.scene, objects=(*base.scene.objects, *proposals)),
    ).validate()


def test_explore_is_a_standard_editable_twelve_second_project(
    tmp_path: Path,
) -> None:
    project = _explore(tmp_path)
    video_track = next(
        track for track in project.tracks if track.kind == TrackKind.VIDEO
    )

    assert project.settings.duration_frames == 360
    assert [clip.start_frame for clip in video_track.clips] == [0, 75, 165, 270]
    assert [clip.duration_frames for clip in video_track.clips] == [75, 90, 105, 90]
    assert [explore_clip_role(clip) for clip in video_track.clips] == [
        ExplorePlanRole.MACRO,
        ExplorePlanRole.INSPECTION,
        ExplorePlanRole.REVEAL,
        ExplorePlanRole.REAL_PLACEHOLDER,
    ]
    assert {
        invocation.capability_id for invocation in project.invocations
    } <= {"artwork.present", "camera.animate"}

    assert all(clip.kind == ClipKind.ARTWORK_2D for clip in video_track.clips)
    longer = StudioProject.new(tmp_path / "long.png", duration_seconds=20)
    Image.new("RGB", (64, 64), (10, 20, 30)).save(tmp_path / "long.png")
    longer_explore = create_explore_project(longer).project
    assert longer_explore.settings.duration_frames == 360
    assert max(
        clip.end_frame
        for track in longer_explore.tracks
        for clip in track.clips
    ) == 360
    sixty_fps = _explore(tmp_path / "sixty-fps", fps=60)
    assert sixty_fps.settings.duration_frames == 720
    assert sixty_fps.tracks[0].clips[-1].end_frame == 720

    assert all(transition.kind == TransitionKind.DISSOLVE for transition in project.transitions)
    assert len(project.transitions) == 3
    assert not next(
        track for track in project.tracks if track.kind == TrackKind.EFFECT
    ).clips
    assert next(
        track for track in project.tracks if track.kind == TrackKind.AUDIO
    ).name == "Musique · à choisir"
    assert is_explore_project(project)
    assert StudioProject.from_dict(project.to_dict()) == project


def test_explore_targets_selected_zones_and_reveal_finishes_on_whole_artwork(
    tmp_path: Path,
) -> None:
    project = _explore(tmp_path)
    macro = explore_clip(project, ExplorePlanRole.MACRO)
    inspection = explore_clip(project, ExplorePlanRole.INSPECTION)
    reveal = explore_clip(project, ExplorePlanRole.REVEAL)

    assert macro is not None and macro.camera is not None
    assert inspection is not None and inspection.camera is not None
    assert reveal is not None and reveal.camera is not None
    assert macro.camera.keyframes[0].pose.x < 0.4
    assert inspection.camera.keyframes[0].pose.x > 0.6
    final = resolve_camera_pose(reveal.camera, reveal.duration_frames - 1)
    assert final == final.__class__(x=0.5, y=0.5, zoom=1.0)


def test_explore_recommends_diverse_regions_and_bounds_smart_camera(
    tmp_path: Path,
) -> None:
    source = _project_with_proposals(tmp_path)

    recommendation = recommend_explore_zones(source)
    result = create_explore_project(source)
    macro = explore_clip(result.project, ExplorePlanRole.MACRO)
    inspection = explore_clip(result.project, ExplorePlanRole.INSPECTION)

    assert recommendation.macro_zone_id == "auto-interest-01"
    assert recommendation.inspection_zone_id == "auto-interest-02"
    assert len(recommendation.rationale) == 2
    assert macro is not None and macro.camera is not None
    assert inspection is not None and inspection.camera is not None
    assert len(macro.camera.keyframes) >= 5
    for clip in (macro, inspection):
        assert clip.camera is not None
        assert max(item.pose.zoom for item in clip.camera.keyframes) <= SMART_MAX_ZOOM
        assert max(
            abs(item.pose.rotation_degrees)
            for item in clip.camera.keyframes
        ) <= SMART_MAX_ROTATION_DEGREES
        assert all(
            0.02 <= item.pose.x <= 0.98
            and 0.02 <= item.pose.y <= 0.98
            for item in clip.camera.keyframes
        )


def test_explore_keyframes_and_transitions_use_existing_edit_commands(
    tmp_path: Path,
) -> None:
    project = _explore(tmp_path)
    macro = explore_clip(project, ExplorePlanRole.MACRO)
    assert macro is not None and macro.camera is not None
    source_frame = macro.camera.keyframes[1].frame
    moved = move_camera_keyframe(
        macro.camera,
        source_frame,
        source_frame + 1,
        clip_duration_frames=macro.duration_frames,
    )
    assert any(
        keyframe.frame == source_frame + 1 for keyframe in moved.keyframes
    )

    transition = project.transitions[0]
    edited = update_dissolve(
        project,
        transition.transition_id,
        duration_frames=10,
        easing=Easing.LINEAR,
    )
    effective = next(
        item
        for item in edited.transitions
        if item.transition_id == transition.transition_id
    )
    assert effective.duration_frames == 10
    without = delete_transition(edited, transition.transition_id)
    assert all(
        item.transition_id != transition.transition_id
        for item in without.transitions
    )




def test_every_explore_plan_uses_existing_move_trim_and_delete_commands(
    tmp_path: Path,
) -> None:
    roles = tuple(ExplorePlanRole)
    for role in roles:
        project = _explore(tmp_path / role.value)
        clip = explore_clip(project, role)
        assert clip is not None
        if clip.start_frame > 0:
            moved = move_clip(project, clip.clip_id, clip.start_frame - 1)
            assert next(
                item
                for track in moved.tracks
                for item in track.clips
                if item.clip_id == clip.clip_id
            ).start_frame == clip.start_frame - 1
        else:
            trimmed = trim_clip(project, clip.clip_id, 1, clip.end_frame)
            assert next(
                item
                for track in trimmed.tracks
                for item in track.clips
                if item.clip_id == clip.clip_id
            ).start_frame == 1
        deleted = delete_clips(project, (clip.clip_id,))
        assert all(
            item.clip_id != clip.clip_id
            for track in deleted.tracks
            for item in track.clips
        )


def test_real_placeholder_becomes_a_photo_or_video_without_hidden_state(
    tmp_path: Path,
) -> None:
    project = _explore(tmp_path)
    placeholder = explore_clip(project, ExplorePlanRole.REAL_PLACEHOLDER)
    assert placeholder is not None
    photo = MediaAsset(
        "photo",
        AssetKind.IMAGE,
        str(tmp_path / "photo.png"),
        width=64,
        height=64,
    )
    photo_project = replace(project, assets=(photo,)).validate()
    photo_project, photo_clip = replace_explore_real_placeholder(
        photo_project,
        placeholder.clip_id,
        photo.asset_id,
    )

    assert photo_clip.kind == ClipKind.STILL
    assert photo_clip.clip_id == placeholder.clip_id
    assert photo_clip.asset_id == photo.asset_id
    assert explore_clip(photo_project, ExplorePlanRole.REAL_PLACEHOLDER) is None
    assert is_explore_project(photo_project)

    video = MediaAsset(
        "video",
        AssetKind.VIDEO,
        str(tmp_path / "video.mp4"),
        width=64,
        height=64,
        metadata={"native_frame_count": 180, "native_fps": 30.0},
    )
    video_project = replace(project, assets=(video,)).validate()
    video_project, video_clip = replace_explore_real_placeholder(
        video_project,
        placeholder.clip_id,
        video.asset_id,
    )

    assert video_clip.kind == ClipKind.VIDEO
    assert video_clip.source_in_frame == 6
    assert video_clip.clip_id == placeholder.clip_id
    assert all(
        transition.to_clip_id == video_clip.clip_id
        or transition.from_clip_id != "explore-reveal"
        for transition in video_project.transitions
    )


def test_music_placeholder_is_only_a_normal_empty_audio_track(tmp_path: Path) -> None:
    project = _explore(tmp_path)
    audio_track = next(
        track for track in project.tracks if track.kind == TrackKind.AUDIO
    )
    audio_clip = Clip("music", ClipKind.AUDIO, 0, 30, asset_id="audio")
    asset = MediaAsset(
        "audio",
        AssetKind.AUDIO,
        str(tmp_path / "music.wav"),
        metadata={
            "sample_rate": 48_000,
            "channels": 2,
            "sample_count": 48_000,
            "duration_seconds": 1.0,
        },
    )
    tracks = tuple(
        replace(track, clips=(audio_clip,))
        if track.track_id == audio_track.track_id
        else track
        for track in project.tracks
    )
    with_music = mark_explore_music_attached(
        replace(project, assets=(asset,), tracks=tracks)
    )

    effective = next(
        track for track in with_music.tracks if track.kind == TrackKind.AUDIO
    )
    assert effective.name == "Musique"
    assert effective.clips[0].invocation_id is not None

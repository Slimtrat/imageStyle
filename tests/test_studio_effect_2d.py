from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core.effects import create_effect, effect_keys
from artanimate.studio.compositor import StudioCompositor
from artanimate.studio.effect_2d import (
    Effect2DClipSettings,
    add_effect_clip,
    settings_for_effect_clip,
)
from artanimate.studio.model import ProjectSettings, StudioProject
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.preview import ArtworkSourceRegistry, render_studio_preview_frame
from artanimate.studio.timeline import (
    duplicate_clip,
    move_clip,
    split_clip,
    trim_clip,
)


def small_project(path: Path, *, duration_frames: int = 90) -> StudioProject:
    project = StudioProject.new(path)
    artwork_track = project.tracks[0]
    artwork_clip = replace(
        artwork_track.clips[0],
        duration_frames=duration_frames,
        camera=None,
    )
    return replace(
        project,
        settings=ProjectSettings(
            width=108,
            height=192,
            fps=30,
            duration_frames=duration_frames,
            background=(3, 4, 5),
        ),
        tracks=(replace(artwork_track, clips=(artwork_clip,)), *project.tracks[1:]),
    ).validate()


class SolidSource:
    def __init__(self, color: tuple[int, int, int], frame_count: int = 90):
        self.width = 108
        self.height = 192
        self.fps = 30
        self.frame_count = frame_count
        self.frame = np.full((192, 108, 3), color, dtype=np.uint8)

    def frame_at(self, frame_index: int) -> np.ndarray:
        if not 0 <= frame_index < self.frame_count:
            raise IndexError(frame_index)
        return self.frame


class IndexedEffectSource:
    def __init__(
        self,
        reference: tuple[int, int, int],
        effect: tuple[int, int, int],
        frame_count: int = 30,
    ):
        self.width = 108
        self.height = 192
        self.fps = 30
        self.frame_count = frame_count
        self.reference_frame = np.full((192, 108, 3), reference, dtype=np.uint8)
        self.effect = np.asarray(effect, dtype=np.uint8)

    def frame_at(self, frame_index: int) -> np.ndarray:
        if not 0 <= frame_index < self.frame_count:
            raise IndexError(frame_index)
        value = np.clip(self.effect.astype(np.int16) + frame_index, 0, 255).astype(np.uint8)
        return np.broadcast_to(value, self.reference_frame.shape).copy()


def test_effect_settings_are_a_complete_snapshot_and_use_registered_factories() -> None:
    source = RenderConfig(effect="sand", duration=4.0, hold_start=0.2, hold_end=0.4)
    settings = Effect2DClipSettings.from_config(
        source,
        duration_seconds=1.0,
        fps=30,
        intensity=0.65,
    )
    parameters = settings.to_parameters()

    source.effect = "wave"
    source.grain_density = 0.0

    restored = Effect2DClipSettings.from_parameters(parameters)
    assert restored.effect == "sand"
    assert restored.config.grain_density == RenderConfig().grain_density
    assert restored.config.duration == 1.0
    assert restored.config.fps == 30
    assert restored.intensity == 0.65
    assert create_effect(restored.effect).key == "sand"

    for key in effect_keys():
        candidate = Effect2DClipSettings.from_config(
            RenderConfig(effect=key),
            duration_seconds=0.5,
            fps=30,
        )
        assert create_effect(candidate.effect).key == key


def test_effect_clips_from_half_to_two_seconds_are_positioned_on_artwork(tmp_path: Path) -> None:
    project = small_project(tmp_path / "art.png")
    half_project, half = add_effect_clip(
        project,
        RenderConfig(effect="sand"),
        start_frame=10,
        duration_seconds=0.5,
    )
    full_project, full = add_effect_clip(
        half_project,
        RenderConfig(effect="wave"),
        start_frame=30,
        duration_seconds=2.0,
        intensity=0.75,
        opacity=0.8,
    )

    assert half.start_frame == 10
    assert half.duration_frames == 15
    assert full.start_frame == 30
    assert full.duration_frames == 60
    assert full.opacity == 0.8
    assert settings_for_effect_clip(full).intensity == 0.75
    assert len(full_project.tracks[1].clips) == 2



def test_effect_duration_and_position_are_strict(tmp_path: Path) -> None:
    project = small_project(tmp_path / "art.png")
    selected = RenderConfig(effect="sand")

    with pytest.raises(ValueError, match="0,5 et 2"):
        add_effect_clip(project, selected, start_frame=0, duration_seconds=0.49)
    with pytest.raises(ValueError, match="0,5 et 2"):
        add_effect_clip(project, selected, start_frame=0, duration_seconds=2.01)
    with pytest.raises(TypeError, match="frame entière"):
        add_effect_clip(project, selected, start_frame=1.5, duration_seconds=1.0)


def test_effect_timeline_edits_stay_inside_source_and_target(tmp_path: Path) -> None:
    project = small_project(tmp_path / "art.png")
    artwork_track = project.tracks[0]
    target = replace(artwork_track.clips[0], duration_frames=60)
    project = replace(
        project,
        tracks=(replace(artwork_track, clips=(target,)), *project.tracks[1:]),
    ).validate()
    project, clip = add_effect_clip(
        project,
        RenderConfig(effect="sand"),
        start_frame=45,
        duration_seconds=0.5,
    )

    with pytest.raises(ValueError, match="plan de l’œuvre"):
        move_clip(project, clip.clip_id, 46)
    with pytest.raises(ValueError, match="plan de l’œuvre"):
        duplicate_clip(project, clip.clip_id)
    with pytest.raises(ValueError, match="au moins 0,5"):
        trim_clip(project, clip.clip_id, 46, 60)
    with pytest.raises(ValueError, match="au moins 0,5"):
        split_clip(project, clip.clip_id, 52)


def test_effect_source_registry_reuses_sources_and_stays_bounded(tmp_path: Path) -> None:
    path = tmp_path / "art.png"
    Image.new("RGB", (64, 64), (210, 40, 25)).save(path)
    registry = ArtworkSourceRegistry(max_effect_sources=1)
    first = Effect2DClipSettings.from_config(
        RenderConfig(effect="sand", width=64, colors=4, quality="fast"),
        duration_seconds=0.5,
        fps=30,
    )
    second = Effect2DClipSettings.from_config(
        RenderConfig(effect="wave", width=64, colors=4, quality="fast"),
        duration_seconds=0.5,
        fps=30,
    )

    registry.effect_source(path, None, first)
    cached = registry.effect_source(path, None, second)
    assert registry.effect_source(path, None, second) is cached
    assert registry.effect_source_count == 1

def test_disabling_effect_layer_recovers_exact_underlying_frame(tmp_path: Path) -> None:
    project = small_project(tmp_path / "art.png")
    project, effect_clip = add_effect_clip(
        project,
        RenderConfig(effect="sand"),
        start_frame=10,
        duration_seconds=1.0,
    )
    artwork_source = SolidSource((200, 20, 10))
    effect_source = IndexedEffectSource((200, 20, 10), (20, 100, 220))
    sources = {
        "artwork-main": artwork_source,
        effect_clip.clip_id: effect_source,
    }
    enabled = StudioCompositor(project, sources).frame_at(10)

    effect_track = project.tracks[1]
    disabled_clip = replace(effect_clip, enabled=False)
    disabled_project = replace(
        project,
        tracks=(project.tracks[0], replace(effect_track, clips=(disabled_clip,)), project.tracks[2]),
    ).validate()
    disabled = StudioCompositor(disabled_project, sources).frame_at(10)
    underlying = StudioCompositor(
        replace(
            project,
            tracks=(project.tracks[0], replace(effect_track, clips=()), project.tracks[2]),
        ).validate(),
        {"artwork-main": artwork_source},
    ).frame_at(10)

    assert not np.array_equal(enabled, underlying)
    assert np.array_equal(disabled, underlying)


def test_trim_changes_only_effect_local_time(tmp_path: Path) -> None:
    project = small_project(tmp_path / "art.png")
    project, effect_clip = add_effect_clip(
        project,
        RenderConfig(effect="sand"),
        start_frame=10,
        duration_seconds=1.0,
    )
    trimmed = trim_clip(project, effect_clip.clip_id, 15, 30)
    clip = trimmed.tracks[1].clips[0]
    source = IndexedEffectSource((100, 100, 100), (20, 30, 40))
    rendered = StudioCompositor(
        trimmed,
        {
            "artwork-main": SolidSource((100, 100, 100)),
            clip.clip_id: source,
        },
    ).frame_at(15)

    assert clip.source_in_frame == 5
    assert np.all(rendered == (25, 35, 45))


def test_preview_uses_the_same_effect_sources_and_compositor(tmp_path: Path) -> None:
    path = tmp_path / "art.png"
    Image.new("RGB", (64, 64), (210, 40, 25)).save(path)
    project = small_project(path)
    config = RenderConfig(
        effect="contour_laser",
        width=64,
        colors=4,
        duration=2.0,
        hold_start=0.1,
        hold_end=0.1,
        quality="fast",
    ).validate()
    project, _clip = add_effect_clip(
        project,
        config,
        start_frame=0,
        duration_seconds=0.5,
    )
    registry = ArtworkSourceRegistry()

    preview, cached = render_studio_preview_frame(
        project,
        path,
        5,
        requested_width=108,
        source_registry=registry,
    )
    expected = StudioRenderSession(
        project,
        path,
        output_width=108,
        output_height=192,
        source_registry=registry,
    ).frame_at(5)

    assert cached is False
    assert preview is not None
    assert np.array_equal(preview, expected)

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer
from artanimate.studio.artwork_source import (
    ArtworkTimedFrameSource,
    ArtworkTimedSourceFactory,
)
from artanimate.studio.compositor import StudioCompositor, fit_frame
from artanimate.studio.model import FitMode, ProjectSettings, StudioProject
from artanimate.studio.timeline import move_clip, trim_clip


def make_artwork(path: Path) -> None:
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 45, 55), fill=(230, 35, 45), outline="black", width=2)
    draw.rectangle((50, 8, 88, 55), fill=(35, 95, 225), outline="black", width=2)
    image.save(path)


def config(**values) -> RenderConfig:
    defaults = {
        "effect": "sand",
        "width": 96,
        "colors": 6,
        "duration": 2.0,
        "fps": 10,
        "hold_start": 0.2,
        "hold_end": 0.4,
        "grain_density": 0.001,
    }
    defaults.update(values)
    return RenderConfig(**defaults).validate()


def test_random_access_matches_every_sequential_renderer_frame(tmp_path: Path) -> None:
    path = tmp_path / "art.png"
    make_artwork(path)
    selected = config()
    analysis = analyze_artwork(path, selected)
    renderer = ArtworkRenderer(analysis, selected)
    source = ArtworkTimedFrameSource(renderer)

    sequential = list(renderer.frames())
    random_order = tuple(reversed(range(source.frame_count)))
    indexed = {index: source.frame_at(index) for index in random_order}

    assert all(np.array_equal(indexed[index], sequential[index]) for index in random_order)
    assert source.fps == selected.fps
    assert source.frame_count == renderer.frame_count
    assert np.array_equal(source.frame_at(source.frame_count - 1), analysis.source)


def test_holds_and_presentation_are_local_and_explicit(tmp_path: Path) -> None:
    path = tmp_path / "art.png"
    make_artwork(path)
    selected = config(effect="contour_laser")
    analysis = analyze_artwork(path, selected)
    renderer = ArtworkRenderer(analysis, selected)
    source_2d = ArtworkTimedFrameSource(renderer, presentation="2d")
    source_texture = ArtworkTimedFrameSource(renderer, presentation="texture")

    assert np.array_equal(source_2d.frame_at(0), renderer.frame_at(0, "2d"))
    assert np.array_equal(
        source_texture.frame_at(0),
        renderer.frame_at(0, "texture"),
    )
    assert np.array_equal(source_2d.frame_at(source_2d.frame_count - 1), analysis.source)
    assert np.array_equal(source_2d.frame_at(source_2d.frame_count - 2), analysis.source)
    with pytest.raises(ValueError, match="présentation"):
        ArtworkTimedFrameSource(renderer, presentation="unknown")


def test_trim_and_move_keep_the_same_source_time(tmp_path: Path) -> None:
    path = tmp_path / "art.png"
    make_artwork(path)
    selected = config(fps=30, duration=1.0, hold_start=0.1, hold_end=0.2)
    source = ArtworkTimedSourceFactory().source(path, selected)
    project = StudioProject.new(path)
    project = replace(
        project,
        settings=ProjectSettings(
            width=540,
            height=960,
            fps=selected.fps,
            duration_frames=source.frame_count,
            background=(0, 0, 0),
        ),
    )
    artwork_track = project.tracks[0]
    artwork_clip = replace(
        artwork_track.clips[0],
        duration_frames=source.frame_count,
        camera=None,
        fit=FitMode.CONTAIN,
    )
    project = replace(
        project,
        tracks=(replace(artwork_track, clips=(artwork_clip,)), *project.tracks[1:]),
    ).validate()
    trimmed = trim_clip(project, artwork_clip.clip_id, 4, source.frame_count - 2)
    moved = move_clip(trimmed, artwork_clip.clip_id, 6)
    clip = moved.tracks[0].clips[0]
    compositor = StudioCompositor(
        moved,
        {clip.clip_id: source},
        output_width=540,
        output_height=960,
    )

    expected, _alpha = fit_frame(source.frame_at(4), 540, 960, FitMode.CONTAIN)
    assert clip.source_in_frame == 4
    assert np.array_equal(compositor.frame_at(6), expected)


def test_analysis_and_frame_caches_are_bounded(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    make_artwork(first)
    make_artwork(second)
    factory = ArtworkTimedSourceFactory(max_analysis_entries=1)

    source = factory.source(first, config(effect="sand"), max_cache_bytes=96 * 64 * 3)
    factory.source(first, config(effect="wave"))
    assert factory.analysis_count == 1
    source.frame_at(0)
    source.frame_at(1)
    assert source.cache_entry_count == 1
    assert source.cache_bytes <= source.max_cache_bytes

    factory.source(second, config())
    assert factory.analysis_entry_count == 1
    assert factory.analysis_count == 2

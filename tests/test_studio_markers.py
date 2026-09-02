from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import wave

import numpy as np
from PIL import Image

from artanimate.studio.assets import import_media_asset
from artanimate.studio.audio import add_audio_clip
from artanimate.studio.markers import (
    MarkerKind,
    MarkerOrigin,
    TimelineMarkerState,
    add_custom_marker,
    adjacent_marker,
    delete_timeline_marker,
    import_music_analysis_markers,
    marker_by_id,
    set_marker_visibility,
    update_timeline_marker,
)
from artanimate.studio.model import AssetKind, StudioProject
from artanimate.studio.music_analysis import (
    MusicAnalysis,
    MusicAnalysisSettings,
    MusicEvent,
    MusicEventKind,
)
from artanimate.studio.timeline import delete_clips, timeline_snap_targets


def _project_with_audio(
    tmp_path: Path,
    *,
    fps: int = 30,
) -> tuple[StudioProject, str]:
    artwork = tmp_path / f"art-{fps}.png"
    audio = tmp_path / f"music-{fps}.wav"
    project_path = tmp_path / f"project-{fps}.artanimate"
    Image.new("RGB", (80, 60), "navy").save(artwork)
    samples = np.zeros(12 * 8_000, dtype="<i2")
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(samples.tobytes())
    asset = import_media_asset(
        audio,
        AssetKind.AUDIO,
        project_path,
        asset_id="music",
    )
    project = replace(
        StudioProject.new(
            artwork,
            fps=fps,
            duration_seconds=10,
        ),
        assets=(asset,),
    ).validate()
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=2 * fps,
        source_in_frame=1 * fps,
        duration_frames=6 * fps,
    )
    return project, clip.clip_id


def _analysis(fps: int) -> MusicAnalysis:
    sample_rate = 8_000
    source_seconds = (0.5, 1.0, 2.0, 3.0, 7.5, 8.0)
    kinds = (
        MusicEventKind.BEAT,
        MusicEventKind.DOWNBEAT,
        MusicEventKind.BEAT,
        MusicEventKind.DROP,
        MusicEventKind.BEAT,
        MusicEventKind.BEAT,
    )
    events = tuple(
        MusicEvent(
            kind,
            int(round(seconds * fps)),
            int(round(seconds * sample_rate)),
            0.55 if index == 2 else 0.88,
            index == 2,
        )
        for index, (kind, seconds) in enumerate(zip(kinds, source_seconds))
    )
    return MusicAnalysis(
        "audio-fingerprint",
        MusicAnalysisSettings(),
        fps,
        sample_rate,
        12 * sample_rate,
        120.0,
        0.9,
        events,
    ).validate()


def test_detected_markers_project_through_audio_trim_and_are_idempotent(
    tmp_path: Path,
) -> None:
    project, _clip_id = _project_with_audio(tmp_path)
    updated, added = import_music_analysis_markers(
        project,
        "music",
        _analysis(30),
    )

    assert [(item.kind, item.frame) for item in added] == [
        (MarkerKind.DOWNBEAT, 60),
        (MarkerKind.BEAT, 90),
        (MarkerKind.DROP, 120),
    ]
    assert added[1].uncertain
    assert added[1].origin == MarkerOrigin.DETECTED
    assert added[1].source_sample == 16_000
    again, duplicates = import_music_analysis_markers(
        updated,
        "music",
        _analysis(30),
    )
    assert duplicates == ()
    assert again == updated


def test_markers_round_trip_and_survive_audio_removal(tmp_path: Path) -> None:
    project, clip_id = _project_with_audio(tmp_path)
    project, added = import_music_analysis_markers(
        project,
        "music",
        _analysis(30),
    )
    payload = project.to_dict()
    reopened = StudioProject.from_dict(payload)
    assert TimelineMarkerState.from_project(reopened) == (
        TimelineMarkerState.from_project(project)
    )

    without_clip = delete_clips(reopened, (clip_id,))
    without_asset = replace(without_clip, assets=()).validate()
    assert marker_by_id(without_asset, added[0].marker_id) == added[0]


def test_custom_edit_delete_filter_navigation_and_snapping(
    tmp_path: Path,
) -> None:
    project, _clip_id = _project_with_audio(tmp_path)
    project, first = add_custom_marker(project, 44, label="Entrée")
    project, second = add_custom_marker(project, 88, label="Sortie")
    assert adjacent_marker(project, 44, 1) == second
    assert adjacent_marker(project, 44, -1) == second
    assert adjacent_marker(project, 100, 1) == first
    assert 44 in timeline_snap_targets(project)

    project = update_timeline_marker(
        project,
        first.marker_id,
        frame=46,
        kind=MarkerKind.DROP,
        label="Impact",
    )
    edited = marker_by_id(project, first.marker_id)
    assert (edited.frame, edited.kind, edited.label, edited.adjusted) == (
        46,
        MarkerKind.DROP,
        "Impact",
        True,
    )
    project = set_marker_visibility(project, MarkerKind.DROP)
    assert TimelineMarkerState.from_project(project).visible_markers() == (
        edited,
    )
    targets = timeline_snap_targets(project)
    assert 46 in targets and 88 not in targets

    project = delete_timeline_marker(project, second.marker_id)
    assert [item.marker_id for item in TimelineMarkerState.from_project(project).markers] == [
        first.marker_id
    ]


def test_audio_source_time_is_preserved_at_30_and_60_fps(
    tmp_path: Path,
) -> None:
    positions: list[tuple[float, tuple[int, ...]]] = []
    for fps in (30, 60):
        project, _clip_id = _project_with_audio(tmp_path, fps=fps)
        project, added = import_music_analysis_markers(
            project,
            "music",
            _analysis(fps),
        )
        positions.append(
            (
                added[0].frame / fps,
                tuple(item.source_sample for item in added),
            )
        )
    assert positions[0] == positions[1]

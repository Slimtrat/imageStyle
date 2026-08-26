from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from fractions import Fraction

from PIL import Image
import pytest

from artanimate.studio.adapters import build_studio_capability_registry
from artanimate.studio.clock import StudioClock
from artanimate.studio.events import compile_timeline_triggers, event_local_frame
from artanimate.studio.model import StudioProject
from artanimate.studio.render_session import StudioRenderSession
from artanimate.studio.semantic import CapabilityInvocation, TimelineTrigger
from artanimate.studio.semantic_actions import add_semantic_action_clip
from artanimate.studio.timeline import delete_clips


def _artwork(tmp_path: Path, name: str = "artwork.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (96, 64), (60, 110, 180)).save(path)
    return path


def _graph_project(tmp_path: Path) -> StudioProject:
    project = StudioProject.new(_artwork(tmp_path), fps=30, duration_seconds=10)
    invocations = (
        CapabilityInvocation("source", "test.source", 10, 20),
        CapabilityInvocation("action-a", "test.action", 80, 5),
        CapabilityInvocation("action-b", "test.action", 90, 7),
    )
    return replace(project, invocations=project.invocations + invocations).validate()


def test_one_completed_event_starts_several_actions_deterministically(
    tmp_path: Path,
) -> None:
    project = _graph_project(tmp_path)
    project = replace(
        project,
        triggers=(
            TimelineTrigger("trigger-b", "source", "completed", "action-b", 4),
            TimelineTrigger("trigger-a", "source", "completed", "action-a", -2),
        ),
    ).validate()

    first = compile_timeline_triggers(project)
    second = compile_timeline_triggers(project)

    assert first == second
    assert first.invocation("action-a").start_frame == 28
    assert first.invocation("action-b").start_frame == 34
    assert tuple(item.trigger_id for item in first.triggers) == (
        "trigger-a",
        "trigger-b",
    )


def test_chained_offsets_and_semantic_events_resolve_on_project_frames(
    tmp_path: Path,
) -> None:
    project = _graph_project(tmp_path)
    source = replace(
        next(item for item in project.invocations if item.invocation_id == "source"),
        capability_id="object.exit_frame",
    )
    project = replace(
        project,
        invocations=tuple(
            source if item.invocation_id == "source" else item
            for item in project.invocations
        ),
        triggers=(
            TimelineTrigger(
                "exit-to-a", "source", "object-exited", "action-a", 2
            ),
            TimelineTrigger("a-to-b", "action-a", "completed", "action-b", 3),
        ),
    ).validate()

    compiled = compile_timeline_triggers(project)

    assert event_local_frame(source, "object-exited") == 19
    assert compiled.invocation("action-a").start_frame == 31
    assert compiled.invocation("action-b").start_frame == 39


def test_audio_markers_and_beats_use_the_studio_clock_frame_domain(
    tmp_path: Path,
) -> None:
    project = _graph_project(tmp_path)
    clock = StudioClock(project.settings.fps)
    audio = CapabilityInvocation(
        "audio-source",
        "audio.play",
        20,
        90,
        parameters={
            "markers": [
                {"id": "refrain", "frame": clock.seconds_to_frame(Fraction(1, 2))}
            ],
            "beats": [0, {"frame": clock.seconds_to_frame(1)}],
        },
    )
    project = replace(
        project,
        invocations=project.invocations + (audio,),
        triggers=(
            TimelineTrigger(
                "marker-to-a", "audio-source", "marker:refrain", "action-a", 1
            ),
            TimelineTrigger(
                "beat-to-b", "audio-source", "beat:1", "action-b", -1
            ),
        ),
    ).validate()

    compiled = compile_timeline_triggers(
        project,
        build_studio_capability_registry(),
    )

    assert compiled.invocation("action-a").start_frame == 36
    assert compiled.invocation("action-b").start_frame == 49


def test_cycles_and_multiple_incoming_links_are_refused_with_diagnostics(
    tmp_path: Path,
) -> None:
    project = _graph_project(tmp_path)
    with pytest.raises(ValueError, match="action-a -> source -> action-a"):
        replace(
            project,
            triggers=(
                TimelineTrigger("one", "source", "completed", "action-a"),
                TimelineTrigger("two", "action-a", "completed", "source"),
            ),
        ).validate()

    project = replace(
        project,
        triggers=(
            TimelineTrigger("one", "source", "completed", "action-b"),
            TimelineTrigger("two", "action-a", "completed", "action-b"),
        ),
    ).validate()
    with pytest.raises(ValueError, match="qu’un déclencheur entrant"):
        compile_timeline_triggers(project)


def test_deleting_a_source_clip_removes_its_links_without_orphans(
    tmp_path: Path,
) -> None:
    project = StudioProject.new(_artwork(tmp_path, "delete.png"), duration_seconds=5)
    source = CapabilityInvocation(
        "source-action", "camera.zoom_out", 0, 5, target_id="camera"
    )
    action = CapabilityInvocation(
        "next-action", "camera.zoom_out", 20, 5, target_id="camera"
    )
    project, source_clip = add_semantic_action_clip(project, source)
    project, _action_clip = add_semantic_action_clip(project, action)
    project = replace(
        project,
        triggers=(
            TimelineTrigger(
                "source-next", "source-action", "completed", "next-action"
            ),
        ),
    ).validate()

    updated = delete_clips(project, (source_clip.clip_id,))

    assert updated.triggers == ()
    assert "source-action" not in {
        item.invocation_id for item in updated.invocations
    }
    assert "next-action" in {item.invocation_id for item in updated.invocations}


def test_render_session_consumes_the_same_trigger_compilation_as_export(
    tmp_path: Path,
) -> None:
    artwork = _artwork(tmp_path, "render.png")
    project = StudioProject.new(artwork, duration_seconds=4)
    source = CapabilityInvocation(
        "source-action", "camera.zoom_out", 2, 3, target_id="camera"
    )
    action = CapabilityInvocation(
        "next-action", "camera.zoom_out", 90, 3, target_id="camera"
    )
    project, _source_clip = add_semantic_action_clip(project, source)
    project, _action_clip = add_semantic_action_clip(project, action)
    project = replace(
        project,
        triggers=(
            TimelineTrigger(
                "source-next", "source-action", "completed", "next-action"
            ),
        ),
    ).validate()

    expected = compile_timeline_triggers(
        project,
        build_studio_capability_registry(),
    )
    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
    ) as session:
        assert session.trigger_compilation == expected
        assert session.trigger_compilation.invocation(
            "next-action"
        ).start_frame == 5
        assert session.prepared_plan is not None
        assert session.prepared_plan.by_invocation_id(
            "next-action"
        ).plan_entry.request.invocation.start_frame == 5

import json
import os
from pathlib import Path

import pytest

from artanimate.studio.model import ProjectSettings, StudioProject
from artanimate.studio.persistence import (
    ProjectSession,
    autosave_path,
    discard_recovery,
    find_recovery,
    load_project,
    normalize_project_path,
    save_autosave,
    save_project,
)


def test_project_save_is_atomic_utf8_and_round_trips(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "œuvre.png")
    destination = save_project(project, tmp_path / "mon-reel")

    assert destination == tmp_path / "mon-reel.artanimate"
    assert load_project(destination) == project
    raw = destination.read_text(encoding="utf-8")
    assert "œuvre.png" in raw
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_validation_preserves_last_valid_project(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "painting.png")
    destination = save_project(project, tmp_path / "reel.artanimate")
    original = destination.read_bytes()
    invalid = StudioProject(
        project_id=project.project_id,
        artwork=project.artwork,
        settings=ProjectSettings(duration_frames=0),
    )

    with pytest.raises(ValueError, match="au moins une frame"):
        save_project(invalid, destination)

    assert destination.read_bytes() == original
    assert load_project(destination) == project


def test_autosave_never_overwrites_the_main_project(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "painting.png")
    destination = save_project(project, tmp_path / "reel.artanimate")
    edited = StudioProject(
        project_id=project.project_id,
        artwork=project.artwork,
        settings=ProjectSettings(duration_frames=450),
        tracks=project.tracks,
    ).validate()

    recovery_path = save_autosave(edited, destination)

    assert recovery_path == autosave_path(destination)
    assert load_project(destination) == project
    assert load_project(recovery_path) == edited


def test_recovery_is_offered_only_when_autosave_is_newer(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "painting.png")
    destination = save_project(project, tmp_path / "reel.artanimate")
    recovery_path = save_autosave(project, destination)
    project_stat = destination.stat()
    os.utime(
        recovery_path,
        ns=(project_stat.st_atime_ns, project_stat.st_mtime_ns + 1_000_000),
    )

    candidate = find_recovery(destination)
    assert candidate is not None
    assert candidate.project == project

    discard_recovery(destination)
    assert find_recovery(destination) is None


def test_project_session_tracks_saved_identity_without_mutating_media(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "painting.png")
    session = ProjectSession.new(project)
    assert session.dirty

    session.mark_saved(tmp_path / "reel")
    assert session.path == normalize_project_path(tmp_path / "reel")
    assert not session.dirty

    edited = StudioProject(
        project_id=project.project_id,
        artwork=project.artwork,
        settings=ProjectSettings(duration_frames=450),
        tracks=project.tracks,
    ).validate()
    session.update(edited)
    assert session.dirty
    session.update(project)
    assert not session.dirty


def test_load_reports_invalid_json(tmp_path: Path) -> None:
    source = tmp_path / "broken.artanimate"
    source.write_text(json.dumps({"schema_version": 1})[:-1], encoding="utf-8")

    with pytest.raises(ValueError, match="JSON invalide"):
        load_project(source)


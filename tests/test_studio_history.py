from dataclasses import replace
from pathlib import Path

from artanimate.studio.history import StudioHistory
from artanimate.studio.model import ProjectSettings, StudioProject


def changed_duration(project: StudioProject, frames: int) -> StudioProject:
    return replace(
        project,
        settings=replace(project.settings, duration_frames=frames),
    ).validate()


def test_history_undo_redo_and_new_branch(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "art.png")
    history = StudioHistory()
    history.reset(project)
    first = changed_duration(project, 420)
    second = changed_duration(first, 480)

    assert history.commit(first, "Allonger le Reel")
    assert history.commit(second, "Allonger encore le Reel")
    assert history.undo() == first
    assert history.undo_label == "Allonger le Reel"
    assert history.redo_label == "Allonger encore le Reel"
    assert history.redo() == second

    assert history.undo() == first
    branch = changed_duration(first, 390)
    assert history.commit(branch, "Raccourcir le Reel")
    assert not history.can_redo


def test_continuous_commands_merge_and_history_is_bounded(tmp_path: Path) -> None:
    project = StudioProject.new(tmp_path / "art.png")
    history = StudioHistory(max_entries=2)
    history.reset(project)
    first = changed_duration(project, 361)
    second = changed_duration(first, 362)

    history.commit(first, "Ajuster", merge_key="duration")
    history.commit(second, "Ajuster", merge_key="duration")
    assert history.undo_count == 1
    assert history.undo() == project

    history.reset(project)
    current = project
    for frames in (361, 362, 363):
        current = changed_duration(current, frames)
        history.commit(current, f"Durée {frames}")
    assert history.undo_count == 2


def test_history_never_modifies_source_media(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    artwork.write_bytes(b"immutable-source")
    project = StudioProject.new(artwork)
    history = StudioHistory()
    history.reset(project)
    changed = replace(project, settings=ProjectSettings(duration_frames=600)).validate()

    history.commit(changed, "Changer la durée")
    history.undo()
    history.redo()

    assert artwork.read_bytes() == b"immutable-source"

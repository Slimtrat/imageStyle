from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QToolButton

from artanimate.desktop.app import MainWindow
from artanimate.desktop.history import GenerationHistory
from artanimate.desktop.history_widgets import GenerationCard
from artanimate.studio.export import export_studio_project
from artanimate.studio.model import ExportSettings, ProjectSettings, StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> tuple[StudioProject, Path]:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (64, 64), (45, 135, 95)).save(artwork)
    base = StudioProject.new(artwork, fps=30, duration_seconds=1)
    clip = replace(base.tracks[0].clips[0], duration_frames=5)
    project = replace(
        base,
        artwork=replace(base.artwork, width=64, height=64),
        settings=ProjectSettings(64, 64, 30, 5),
        tracks=(replace(base.tracks[0], clips=(clip,)), *base.tracks[1:]),
        export=ExportSettings(container="mp4", crf=18, quality="fast"),
    ).validate()
    return project, artwork


def test_successful_studio_export_is_deduplicated_with_thumbnail_and_safe_delete(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, artwork = _project(tmp_path)
    project_path = tmp_path / "project.artanimate"
    output = tmp_path / "reel.mp4"
    window = MainWindow(history_root=tmp_path / "history")
    window.studio_v3.canvas.set_artwork(artwork)
    window.studio_v3.set_project(project, reset_history=True)
    assert window.studio_document.save(project_path)
    saved_project = window.studio_v3.project
    window.studio_v3._export_failed("échec attendu")
    window.studio_v3._export_cancelled()
    assert window.history_store.load() == ()
    assert saved_project is not None
    result = export_studio_project(saved_project, artwork, output)

    window._studio_v3_export_succeeded(result)
    first = window.history_store.load()[0]
    first_thumbnail = first.thumbnail_path
    window._studio_v3_export_succeeded(result)
    records = window.history_store.load()

    assert len(records) == 1
    record = records[0]
    assert record.is_studio_project
    assert record.project_path == project_path.resolve()
    assert record.project_id == saved_project.project_id
    assert record.available
    assert record.thumbnail_path is not None and record.thumbnail_path.is_file()
    assert first_thumbnail is not None and not first_thumbnail.exists()
    assert record.config["frame_count"] == 5
    assert record.config["audio_mode"] == "reference"

    monkeypatch.setattr(
        "artanimate.desktop.app.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBoxYes,
    )
    window._delete_history_video(str(output))

    assert not output.exists()
    assert project_path.is_file()
    assert artwork.is_file()
    assert window.history_store.load() == ()

    window.history_store.add_studio(
        project_path,
        artwork,
        project_id=saved_project.project_id,
        export_config={"protected_paths": [str(artwork)]},
        project_path=project_path,
    )
    window._refresh_history()
    window._delete_history_video(str(project_path))

    assert project_path.is_file()
    assert artwork.is_file()
    assert window.history_store.load() == ()
    window.close()


def test_history_card_exposes_project_link_and_moved_paths(app, tmp_path: Path) -> None:
    output = tmp_path / "reel.mp4"
    source = tmp_path / "art.png"
    project = tmp_path / "reel.artanimate"
    output.write_bytes(b"video")
    source.write_bytes(b"image")
    project.write_text("{}", encoding="utf-8")
    record = GenerationHistory(tmp_path / "history").add_studio(
        output,
        source,
        project_id="project",
        export_config={"fps": 30},
        project_path=project,
    )
    card = GenerationCard(record)
    opened: list[str] = []
    card.project_requested.connect(opened.append)
    menu = card.findChild(QToolButton).menu()
    project_action = next(
        action for action in menu.actions() if action.text() == "Ouvrir le projet Studio"
    )

    assert project_action.isEnabled()
    project_action.trigger()
    assert opened == [str(project.resolve())]
    assert any("Studio" in label.text() for label in card.findChildren(QLabel))

    project.unlink()
    output.unlink()
    moved = GenerationCard(record)
    moved_menu = moved.findChild(QToolButton).menu()
    moved_project_action = next(
        action
        for action in moved_menu.actions()
        if action.text() == "Ouvrir le projet Studio"
    )
    play = next(
        button for button in moved.findChildren(QPushButton) if button.text() == "Lire"
    )

    assert not moved_project_action.isEnabled()
    assert "déplacé" in moved_project_action.toolTip()
    assert not play.isEnabled()
QMessageBoxYes = QMessageBox.StandardButton.Yes

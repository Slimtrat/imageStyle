from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

from PIL import Image
import pytest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.model import (
    AudioExportMode,
    ExportSettings,
    ProjectSettings,
    StudioProject,
)
from artanimate.studio.video import inspect_video


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path, *, frames: int = 5) -> tuple[StudioProject, Path]:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (64, 64), (35, 90, 175)).save(artwork)
    base = StudioProject.new(artwork, duration_seconds=1)
    clip = replace(base.tracks[0].clips[0], duration_frames=frames)
    project = replace(
        base,
        artwork=replace(base.artwork, width=64, height=64),
        settings=ProjectSettings(
            width=64,
            height=64,
            fps=30,
            duration_frames=frames,
        ),
        tracks=(replace(base.tracks[0], clips=(clip,)), *base.tracks[1:]),
        export=ExportSettings(container="mp4", crf=18, quality="fast"),
    ).validate()
    return project, artwork


def _wait_for_export(app: QApplication, panel: StudioPanel) -> None:
    deadline = monotonic() + 15
    while panel.export_controller.running and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    app.processEvents()
    assert not panel.export_controller.running


def test_export_panel_persists_settings_and_opens_from_header(app, tmp_path: Path) -> None:
    project, artwork = _project(tmp_path)
    panel = StudioPanel()
    panel.canvas.set_artwork(artwork)
    panel.set_project(project, reset_history=True)

    panel.export_button.click()
    panel.export_panel.container.setCurrentIndex(
        panel.export_panel.container.findData("mov")
    )
    panel.export_panel.quality.setCurrentIndex(
        panel.export_panel.quality.findData("studio")
    )
    panel.export_panel.crf.setValue(14)
    panel.export_panel.audio_mode.setCurrentIndex(
        panel.export_panel.audio_mode.findData(AudioExportMode.EMBEDDED.value)
    )

    assert panel.inspector_tabs.currentWidget() is panel.export_panel
    assert panel.project is not None
    assert panel.project.export.container == "mov"
    assert panel.project.export.quality == "studio"
    assert panel.project.export.crf == 14
    assert panel.project.export.audio_mode == AudioExportMode.EMBEDDED
    assert "5 images" in panel.export_panel.format_label.text()
    panel.close()


def test_desktop_export_reports_progress_and_creates_playable_video(
    app,
    tmp_path: Path,
) -> None:
    project, artwork = _project(tmp_path, frames=7)
    panel = StudioPanel()
    panel.canvas.set_artwork(artwork)
    panel.set_project(project, reset_history=True)
    destination = tmp_path / "final.mp4"

    assert panel.export_video(destination)
    assert panel.inspector_tabs.currentWidget() is panel.export_panel
    assert panel.export_controller.running
    assert not panel.export_panel.export_button.isEnabled()
    _wait_for_export(app, panel)

    inspection = inspect_video(destination)
    assert inspection.native_frame_count == 7
    assert panel.export_panel.progress.value() == 7
    assert "Export terminé" in panel.export_panel.progress.format()
    assert "Reel exporté" in panel.project_status.text()
    assert panel.export_panel.destination_label.text() == str(destination.resolve())
    panel.close()


def test_desktop_cancel_preserves_existing_destination(app, tmp_path: Path) -> None:
    project, artwork = _project(tmp_path, frames=120)
    destination = tmp_path / "existing.mp4"
    destination.write_bytes(b"previous-valid-export")
    panel = StudioPanel()
    panel.canvas.set_artwork(artwork)
    panel.set_project(project, reset_history=True)

    assert panel.export_video(destination)
    panel.export_controller.cancel()
    _wait_for_export(app, panel)

    assert destination.read_bytes() == b"previous-valid-export"
    assert not (tmp_path / "existing.part.mp4").exists()
    assert "fichier existant est resté intact" in panel.export_panel.status.text()
    panel.close()

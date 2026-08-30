from __future__ import annotations

import os
from pathlib import Path
import wave

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController
from artanimate.desktop.studio_timeline import semantic_clip_label
from artanimate.studio.explore import (
    ExplorePlanRole,
    explore_clip,
    is_explore_project,
)
from artanimate.studio.model import ClipKind, StudioProject, TrackKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (80, 120), (140, 80, 35)).save(artwork)
    return StudioProject.new(artwork)


def test_explore_panel_builds_one_undoable_standard_timeline(
    app,
    tmp_path: Path,
) -> None:
    original = _project(tmp_path)
    panel = StudioPanel()
    panel.set_project(original, reset_history=True)

    panel.explore_button.click()
    assert panel.inspector_tabs.currentWidget() is panel.explore_panel
    assert panel.explore_panel.macro_zone.currentData() == "artwork"
    assert panel.explore_panel.inspection_zone.currentData() == "artwork"

    panel.explore_panel.create_button.click()

    assert is_explore_project(panel.project)
    assert panel.timeline.selected_clip_ids == ("explore-macro",)
    assert panel.inspector_tabs.currentWidget() is panel.explore_panel
    assert "tout reste éditable" in panel.project_status.text()
    placeholder = explore_clip(
        panel.project,
        ExplorePlanRole.REAL_PLACEHOLDER,
    )
    assert placeholder is not None
    assert semantic_clip_label(panel.project, placeholder) == "Réel · média à choisir"

    panel.undo()
    assert not is_explore_project(panel.project)
    assert len(panel.project.tracks[0].clips) == 1
    panel.redo()
    assert is_explore_project(panel.project)
    panel.close()


def test_explore_completion_buttons_select_explicit_placeholders(
    app,
    tmp_path: Path,
) -> None:
    panel = StudioPanel()
    panel.set_project(_project(tmp_path), reset_history=True)
    panel.explore_panel.create_button.click()
    import_requests: list[bool] = []
    panel.asset_panel.importRequested.connect(lambda: import_requests.append(True))

    panel.explore_panel.real_button.click()

    placeholder = explore_clip(
        panel.project,
        ExplorePlanRole.REAL_PLACEHOLDER,
    )
    assert placeholder is not None
    assert panel.timeline.selected_clip_ids == (placeholder.clip_id,)
    assert panel.transport.current_frame == placeholder.start_frame
    assert panel.editor_tabs.currentWidget() is panel.asset_panel
    assert import_requests == [True]

    panel.explore_panel.music_button.click()
    assert panel.timeline.selected_clip_ids == ()
    assert panel.transport.current_frame == 0
    assert import_requests == [True, True]
    panel.close()


def test_document_import_replaces_selected_real_placeholder(
    app,
    tmp_path: Path,
) -> None:
    music = tmp_path / "music.wav"
    with wave.open(str(music), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48_000)
        stream.writeframes(bytes(9_600))

    photo = tmp_path / "capture.png"
    Image.new("RGB", (64, 64), (20, 80, 170)).save(photo)
    panel = StudioPanel()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    controller = StudioDocumentController(panel, settings, panel)
    panel.set_project(_project(tmp_path), reset_history=True)
    panel.explore_panel.create_button.click()
    placeholder = explore_clip(
        panel.project,
        ExplorePlanRole.REAL_PLACEHOLDER,
    )
    assert placeholder is not None
    panel.timeline.scene.set_selection((placeholder.clip_id,))

    assert controller.import_media(photo)

    replacement = next(
        clip
        for track in panel.project.tracks
        for clip in track.clips
        if clip.clip_id == placeholder.clip_id
    )
    assert replacement.kind == ClipKind.STILL
    assert replacement.asset_id is not None
    assert explore_clip(
        panel.project,
        ExplorePlanRole.REAL_PLACEHOLDER,
    ) is None
    assert len(panel.project.transitions) == 3
    assert panel.explore_panel.real_button.text() == "Média réel lié"

    panel.timeline.scene.set_selection(())
    panel.transport.seek(0)
    assert controller.import_media(music)
    audio_track = next(
        track for track in panel.project.tracks if track.kind == TrackKind.AUDIO
    )
    assert audio_track.name == "Musique"
    assert len(audio_track.clips) == 1
    assert panel.explore_panel.music_button.text() == "Musique liée"
    controller.shutdown()
    panel.close()

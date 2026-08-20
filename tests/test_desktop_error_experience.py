import os
from pathlib import Path

import pytest
from PIL import Image


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from artanimate.core.config import RenderConfig
from artanimate.desktop.app import MainWindow
from artanimate.desktop.preview import PreviewWorker
from artanimate.desktop.problems import UserProblem
from artanimate.desktop.widgets import PathDropZone
from artanimate.desktop.worker import RenderWorker


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("error-experience-settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )
    return QApplication.instance() or QApplication([])


def test_drop_zone_rejects_missing_path_visibly(app, tmp_path: Path) -> None:
    zone = PathDropZone("Œuvre", "Déposez", "image")
    rejected: list[UserProblem] = []
    zone.path_rejected.connect(rejected.append)

    assert not zone.set_path(tmp_path / "missing.png")
    assert zone.path is None
    assert zone.property("invalid") is True
    assert rejected[0].code == "source_not_found"
    assert "n’existe plus" in zone.path_label.text()


def test_problem_dialog_separates_action_from_technical_details(
    app,
    tmp_path: Path,
) -> None:
    window = MainWindow(history_root=tmp_path / "history")
    captured: dict[str, str] = {}

    def inspect_dialog() -> None:
        boxes = [
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QMessageBox)
        ]
        assert boxes
        box = boxes[-1]
        captured["title"] = box.windowTitle()
        captured["message"] = box.text()
        captured["action"] = box.informativeText()
        captured["details"] = box.detailedText()
        box.accept()

    try:
        QTimer.singleShot(0, inspect_dialog)
        window._show_problem(
            UserProblem(
                "source_not_found",
                "Œuvre introuvable",
                "Le fichier n’existe plus.",
                "Sélectionnez à nouveau l’image.",
                "FileNotFoundError: C:/missing.png",
            )
        )

        assert captured == {
            "title": "Œuvre introuvable",
            "message": "Le fichier n’existe plus.",
            "action": "Que faire : Sélectionnez à nouveau l’image.",
            "details": "FileNotFoundError: C:/missing.png",
        }
    finally:
        window.close()
        app.processEvents()


def test_start_render_reports_missing_source_without_starting_worker(
    app,
    tmp_path: Path,
) -> None:
    window = MainWindow(history_root=tmp_path / "history")
    shown: list[UserProblem] = []
    window._show_problem = (  # type: ignore[method-assign]
        lambda problem, **_kwargs: shown.append(problem)
    )
    try:
        window._start_render()

        assert shown[0].code == "source_missing"
        assert window._worker is None
        assert "Glissez une image" in shown[0].action
    finally:
        window.close()
        app.processEvents()


def test_start_render_reports_destination_deleted_after_selection(
    app,
    tmp_path: Path,
) -> None:
    source = tmp_path / "artwork.png"
    Image.new("RGB", (80, 60), (220, 30, 50)).save(source)
    destination = tmp_path / "exports"
    destination.mkdir()
    window = MainWindow(history_root=tmp_path / "history")
    shown: list[UserProblem] = []
    window._show_problem = (  # type: ignore[method-assign]
        lambda problem, **_kwargs: shown.append(problem)
    )
    try:
        window.source_zone.set_path(source)
        window._source_selected(str(source))
        window._preview_debounce.stop()
        window.destination_zone.set_path(destination)
        destination.rmdir()

        window._start_render()

        assert shown[-1].code == "destination_not_found"
        assert window.destination_zone.property("invalid") is True
        assert window._worker is None
    finally:
        window.close()
        app.processEvents()


def test_workers_emit_structured_problem_when_source_disappears(tmp_path: Path) -> None:
    source = tmp_path / "missing.png"
    destination = tmp_path / "exports"
    destination.mkdir()
    preview_failures: list[UserProblem] = []
    render_failures: list[UserProblem] = []
    preview = PreviewWorker(source, RenderConfig(width=320), revision=3)
    render = RenderWorker(source, destination / "video.mp4", RenderConfig(width=320))
    preview.failed.connect(lambda _revision, problem: preview_failures.append(problem))
    render.failed.connect(render_failures.append)

    preview.run()
    render.run()

    assert preview_failures[0].code == "source_not_found"
    assert render_failures[0].code == "source_not_found"

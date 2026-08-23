import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QToolButton

from artanimate.core.config import RenderConfig
from artanimate.desktop.app import MainWindow
from artanimate.desktop.history_widgets import GenerationCard


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("workspace-navigation-settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )
    return QApplication.instance() or QApplication([])


def test_workspace_has_actionable_menus_history_and_interactive_3d_studio(
    app,
    tmp_path: Path,
) -> None:
    window = MainWindow(history_root=tmp_path / "history")
    try:
        menu_names = [action.text().replace("&", "") for action in window.menuBar().actions()]
        assert menu_names == ["Fichier", "Édition", "Génération", "Réglages", "Affichage", "Historique"]
        assert window.workspace_tabs.count() == 3
        assert set(window._settings_cards) == {"effect", "colors", "analysis", "video"}
        assert window.history_panel.scroll.height() == 86
        window._open_settings("colors")
        assert window._settings_dialogs["colors"].isVisible()
        assert window.chromatic_wheel.minimumWidth() >= 400
        window._settings_dialogs["colors"].close()
        assert window.workspace_tabs.tabText(0) == "Atelier 2D"
        assert window.workspace_tabs.tabText(1) == "Studio 3D"
        assert window.workspace_tabs.tabText(2) == "Studio"
        window.workspace_tabs.setCurrentIndex(1)
        app.processEvents()
        assert not window.studio_3d.scene_errors
        assert "TEMPS RÉEL" in window.findChild(QLabel, "studioLiveBadge").text()
        studio_effect = window.studio_3d.effect_combo
        wow_index = studio_effect.findData("screenprint_laser")
        assert wow_index >= 0
        studio_effect.setCurrentIndex(wow_index)
        assert window.effect_combo.currentData() == "screenprint_laser"
        assert "contours noirs" in window.studio_3d.effect_description.text()
        window.studio_3d.effect_settings_button.click()
        assert window._settings_dialogs["effect"].isVisible()
        assert window.workspace_tabs.currentIndex() == 1
        window._settings_dialogs["effect"].close()

        destination = tmp_path / "exports"
        destination.mkdir()
        window.destination_zone.set_path(destination)
        window._destination_selected(str(destination))
        assert window.history_panel.directory_label.toolTip() == str(destination.resolve())
    finally:
        window.close()
        app.processEvents()


def test_history_card_menu_can_delete_a_generated_video(
    app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    history_root = tmp_path / "history"
    destination = tmp_path / "exports"
    destination.mkdir()
    output = destination / "old-wave.mp4"
    output.write_bytes(b"old video")
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    window = MainWindow(history_root=history_root)
    try:
        window.destination_zone.set_path(destination)
        window.history_store.add(output, source, RenderConfig(effect="wave"), "Vague")
        window._refresh_history()
        cards = window.history_panel.findChildren(GenerationCard)
        assert len(cards) == 1
        menu_button = cards[0].findChild(QToolButton, "historyMenuButton")
        assert menu_button is not None
        action_labels = [action.text() for action in menu_button.menu().actions()]
        assert "Afficher dans l’Explorateur Windows" in action_labels
        assert "Supprimer définitivement la vidéo…" in action_labels
        assert cards[0].record.output_path == output.resolve()

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        window._delete_history_video(str(output))

        assert not output.exists()
        assert window.history_store.load() == ()
    finally:
        window.close()
        app.processEvents()

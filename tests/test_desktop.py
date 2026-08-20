import logging
import os
from pathlib import Path

import pytest
from PIL import Image


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from artanimate.desktop.app import MainWindow


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_root))
    return QApplication.instance() or QApplication([])


def test_mode_switch_changes_visible_parameters_and_config(app) -> None:
    window = MainWindow()
    assert window.effect_combo.currentData() == "sand"
    assert window.mode_stack.currentIndex() == 0
    window.effect_combo.setCurrentIndex(1)
    assert window.effect_combo.currentData() == "wave"
    assert window.mode_stack.currentIndex() == 1
    config = window.build_config()
    assert config.effect == "wave"
    assert config.direction == "left"
    window.close()


def test_log_window_filters_by_level_source_and_text(app) -> None:
    window = MainWindow()
    source = logging.getLogger("artanimate.desktop.filter_test")
    source.info("palette ready")
    source.warning("background uncertain")
    source.error("encoding failed")
    app.processEvents()
    logs = window.log_window
    assert len(logs._records) >= 5  # includes mode selection and window-ready messages
    logs.level_filter.setCurrentIndex(3)
    assert "encoding failed" in logs.output.toPlainText()
    assert "palette ready" not in logs.output.toPlainText()
    logs.level_filter.setCurrentIndex(0)
    logs.search.setText("background")
    assert "background uncertain" in logs.output.toPlainText()
    assert "encoding failed" not in logs.output.toPlainText()
    logs.search.clear()
    source_index = logs.source_filter.findData("desktop.filter_test")
    assert source_index >= 0
    logs.source_filter.setCurrentIndex(source_index)
    assert "palette ready" in logs.output.toPlainText()
    assert "Interface desktop prête" not in logs.output.toPlainText()
    assert window.log_button.text() == "Logs (2)"
    window._show_logs()
    assert window.log_button.text() == "Logs"
    logs.hide()
    window.close()


def test_source_selection_populates_preview_destination_and_name(app, tmp_path: Path) -> None:
    source = tmp_path / "my-artwork.png"
    Image.new("RGB", (80, 60), (220, 30, 50)).save(source)
    window = MainWindow()
    window.destination_zone._path = None
    window.source_zone.set_path(source)
    window._source_selected(str(source))
    assert window.destination_zone.path == tmp_path.resolve()
    assert window.output_name.text() == "my-artwork-sand.mp4"
    assert window.source_preview.image._source is not None
    window.close()

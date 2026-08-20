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

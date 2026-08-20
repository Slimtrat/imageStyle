import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from artanimate.core.effects import effect_descriptors
from artanimate.desktop.app import MainWindow


def test_effect_and_parameter_documentation_is_exposed_as_tooltips() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        descriptors = effect_descriptors()
        assert window.effect_combo.count() == len(descriptors)
        for index, descriptor in enumerate(descriptors):
            assert window.effect_combo.itemData(index) == descriptor.key
            assert (
                window.effect_combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
                == descriptor.description
            )
            controls = window._effect_controls[descriptor.key]
            assert set(controls) == {parameter.key for parameter in descriptor.parameters}
            for parameter in descriptor.parameters:
                assert controls[parameter.key].toolTip() == parameter.description
    finally:
        window.close()
        app.processEvents()

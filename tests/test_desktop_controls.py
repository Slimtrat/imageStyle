import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.controls import ChromaticSequenceWheel, ParameterSlider


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_parameter_slider_exposes_value_and_bounds(app) -> None:
    slider = ParameterSlider(0.0, 1.0, 0.25, 0.05, 2, "×")
    assert slider.value() == 0.25
    assert slider.minimum_label.text() == "0.00×"
    assert slider.maximum_label.text() == "1.00×"
    slider.setValue(0.8)
    assert slider.value() == 0.8
    assert slider.value_label.text() == "0.80×"


def test_chromatic_wheel_tracks_rotation_direction_and_neutrals(app) -> None:
    wheel = ChromaticSequenceWheel()
    emitted: list[float] = []
    wheel.hueChanged.connect(emitted.append)
    wheel.setStartHue(120.0)
    wheel.setReverse(True)
    wheel.setNeutralPosition("first")
    wheel.setOutlineMode("together")
    wheel.resize(320, 340)
    pixmap = wheel.grab()
    assert wheel.startHue() == 120.0
    assert emitted == [120.0]
    assert not pixmap.isNull()

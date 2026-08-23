import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_transport import StudioTransport


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_transport_seek_step_and_timecode_share_one_frame(app) -> None:
    now = [0]
    transport = StudioTransport(time_source=lambda: now[0])
    frames = []
    transport.frameChanged.connect(frames.append)
    transport.set_project(30, 360)

    transport.seek(91)
    assert transport.current_frame == 91
    assert transport.slider.value() == 91
    assert transport.timecode.text() == "00:00:03:01"

    transport.step(-1)
    assert transport.current_frame == 90
    assert transport.timecode.text() == "00:00:03:00"
    assert frames[-1] == 90


def test_transport_uses_elapsed_time_instead_of_timer_tick_count(app) -> None:
    now = [10_000_000_000]
    transport = StudioTransport(time_source=lambda: now[0])
    transport.set_project(60, 720)
    transport.play()

    now[0] += 1_500_000_000
    transport._tick()

    assert transport.current_frame == 90
    # Calling tick repeatedly at the same timestamp must not advance the project.
    transport._tick()
    transport._tick()
    assert transport.current_frame == 90


def test_transport_stops_exactly_on_last_frame(app) -> None:
    now = [0]
    transport = StudioTransport(time_source=lambda: now[0])
    states = []
    transport.playbackChanged.connect(states.append)
    transport.set_project(30, 10)
    transport.play()
    now[0] = 10_000_000_000
    transport._tick()

    assert transport.current_frame == 9
    assert not transport.is_playing
    assert states == [True, False]


def test_stop_returns_to_start_and_loop_wraps_in_work_area(app) -> None:
    now = [0]
    transport = StudioTransport(time_source=lambda: now[0])
    transport.set_project(30, 100)
    transport.set_loop_range(30, 60)
    transport.set_loop_enabled(True)
    transport.seek(50)
    transport.play()

    now[0] = 1_000_000_000
    transport._tick()
    assert transport.current_frame == 50
    assert transport.is_playing

    transport.stop()
    assert transport.current_frame == 30
    assert not transport.is_playing

    transport.set_loop_enabled(False)
    transport.stop()
    assert transport.current_frame == 0


def test_timecode_edit_is_validated_and_clamped(app) -> None:
    transport = StudioTransport()
    transport.set_project(30, 100)
    transport.timecode.setText("00:00:10:00")
    transport._timecode_edited()
    assert transport.current_frame == 99

    transport.timecode.setText("00:00:00:30")
    transport._timecode_edited()
    assert transport.timecode.text() == "00:00:03:09"


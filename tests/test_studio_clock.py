from decimal import Decimal
from fractions import Fraction

import pytest

from artanimate.studio.clock import StudioClock


def test_studio_clock_keeps_reel_durations_frame_exact() -> None:
    clock_30 = StudioClock(30)
    clock_60 = StudioClock(60)

    assert clock_30.seconds_to_frame(12) == 360
    assert clock_60.seconds_to_frame(12) == 720
    assert clock_30.frame_to_fraction(1) == Fraction(1, 30)
    assert clock_30.seconds_to_frame(Decimal("0.1")) == 3


def test_studio_clock_defines_rounding_at_frame_boundaries() -> None:
    clock = StudioClock(30)
    time = Fraction(1, 100)

    assert clock.seconds_to_frame(time, rounding="floor") == 0
    assert clock.seconds_to_frame(time, rounding="nearest") == 0
    assert clock.seconds_to_frame(time, rounding="ceil") == 1
    assert clock.seconds_to_frame(Fraction(1, 60), rounding="nearest") == 1


def test_timecode_round_trips_without_float_conversion() -> None:
    clock = StudioClock(60)
    frame = ((2 * 60 + 3) * 60 + 4) * 60 + 17

    assert clock.format_timecode(frame) == "02:03:04:17"
    assert clock.parse_timecode("02:03:04:17") == frame


@pytest.mark.parametrize("fps", [0, -1, 241, 29.97, True])
def test_studio_clock_rejects_invalid_frame_rates(fps) -> None:
    with pytest.raises((TypeError, ValueError)):
        StudioClock(fps)


def test_studio_clock_rejects_negative_and_invalid_timecodes() -> None:
    clock = StudioClock(30)

    with pytest.raises(ValueError, match="négatif"):
        clock.seconds_to_frame(-0.1)
    with pytest.raises(ValueError, match="format attendu"):
        clock.parse_timecode("12:00")
    with pytest.raises(ValueError, match="hors limites"):
        clock.parse_timecode("00:00:00:30")


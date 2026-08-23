from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import re
from typing import Literal


RoundingMode = Literal["floor", "nearest", "ceil"]
TimeValue = int | float | Decimal | Fraction
_TIMECODE_RE = re.compile(
    r"^(?P<hours>\d{2,}):(?P<minutes>\d{2}):(?P<seconds>\d{2}):(?P<frames>\d{2})$"
)


def _as_fraction(value: TimeValue) -> Fraction:
    if isinstance(value, bool):
        raise TypeError("Une durée ne peut pas être un booléen")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        # Reading the decimal representation avoids importing the binary float noise
        # into the project timebase.
        return Fraction(str(value))
    raise TypeError(f"Type de durée non pris en charge : {type(value).__name__}")


def _round_positive(value: Fraction, mode: RoundingMode) -> int:
    numerator = value.numerator
    denominator = value.denominator
    if mode == "floor":
        return numerator // denominator
    if mode == "ceil":
        return (numerator + denominator - 1) // denominator
    if mode == "nearest":
        # Editorial time uses round-half-up rather than Python's banker rounding.
        return (2 * numerator + denominator) // (2 * denominator)
    raise ValueError("Arrondi inconnu : utilisez floor, nearest ou ceil")


@dataclass(frozen=True, slots=True)
class StudioClock:
    """Exact, frame-based timebase shared by every V3 Studio subsystem."""

    fps: int = 30

    def __post_init__(self) -> None:
        if isinstance(self.fps, bool) or not isinstance(self.fps, int):
            raise TypeError("Le FPS du projet doit être un entier")
        if not 1 <= self.fps <= 240:
            raise ValueError("Le FPS du projet doit être compris entre 1 et 240")

    def seconds_to_frame(
        self,
        seconds: TimeValue,
        *,
        rounding: RoundingMode = "nearest",
    ) -> int:
        duration = _as_fraction(seconds)
        if duration < 0:
            raise ValueError("Le temps du projet ne peut pas être négatif")
        return _round_positive(duration * self.fps, rounding)

    def frame_to_fraction(self, frame: int) -> Fraction:
        self.validate_frame(frame)
        return Fraction(frame, self.fps)

    def frame_to_seconds(self, frame: int) -> float:
        return float(self.frame_to_fraction(frame))

    def validate_frame(self, frame: int) -> int:
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise TypeError("Une position Studio doit être un numéro de frame entier")
        if frame < 0:
            raise ValueError("Une position Studio ne peut pas être négative")
        return frame

    def clamp_frame(self, frame: int, *, total_frames: int) -> int:
        self.validate_frame(frame)
        if total_frames <= 0:
            raise ValueError("Un projet doit contenir au moins une frame")
        return min(frame, total_frames - 1)

    def format_timecode(self, frame: int) -> str:
        frame = self.validate_frame(frame)
        total_seconds, local_frame = divmod(frame, self.fps)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{local_frame:02d}"

    def parse_timecode(self, value: str) -> int:
        match = _TIMECODE_RE.fullmatch(value.strip())
        if match is None:
            raise ValueError("Timecode invalide, format attendu HH:MM:SS:FF")
        hours = int(match.group("hours"))
        minutes = int(match.group("minutes"))
        seconds = int(match.group("seconds"))
        frames = int(match.group("frames"))
        if minutes >= 60 or seconds >= 60 or frames >= self.fps:
            raise ValueError("Timecode hors limites pour le FPS du projet")
        return ((hours * 60 + minutes) * 60 + seconds) * self.fps + frames


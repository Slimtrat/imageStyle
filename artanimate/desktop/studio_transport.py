from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QWidget,
)

from ..studio.clock import StudioClock


class StudioTransport(QWidget):
    """Frame-exact Studio transport anchored to elapsed monotonic time."""

    frameChanged = Signal(int)
    playbackChanged = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        time_source: Callable[[], int] = time.monotonic_ns,
    ):
        super().__init__(parent)
        self.setObjectName("studioTransport")
        self._time_source = time_source
        self._clock = StudioClock(30)
        self._frame_count = 1
        self._current_frame = 0
        self._playing = False
        self._anchor_frame = 0
        self._anchor_ns = 0
        self._loop_enabled = False
        self._loop_start = 0
        self._loop_end = 1

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        label = QLabel("TRANSPORT")
        label.setObjectName("studioTransportLabel")
        layout.addWidget(label)

        self.start_button = QPushButton("|◀")
        self.start_button.setObjectName("studioGoToStart")
        self.start_button.setToolTip("Revenir au début (Home)")
        self.previous_button = QPushButton("◀")
        self.previous_button.setObjectName("studioPreviousFrame")
        self.previous_button.setToolTip("Frame précédente (Flèche gauche)")
        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("studioPlayPause")
        self.play_button.setToolTip("Lecture / pause (Espace)")
        self.stop_button = QPushButton("■")
        self.stop_button.setObjectName("studioStop")
        self.stop_button.setToolTip("Arrêter et revenir au début")
        self.next_button = QPushButton("▶")
        self.next_button.setObjectName("studioNextFrame")
        self.next_button.setToolTip("Frame suivante (Flèche droite)")
        self.loop_button = QPushButton("↻")
        self.loop_button.setObjectName("studioLoop")
        self.loop_button.setToolTip("Lire la zone de travail en boucle")
        self.loop_button.setCheckable(True)
        for button in (
            self.start_button,
            self.previous_button,
            self.play_button,
            self.stop_button,
            self.next_button,
            self.loop_button,
        ):
            button.setFixedWidth(42)
            layout.addWidget(button)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("studioPlayheadSlider")
        self.slider.setRange(0, 0)
        self.slider.setTracking(True)
        layout.addWidget(self.slider, 1)

        self.timecode = QLineEdit("00:00:00:00")
        self.timecode.setObjectName("studioTimecode")
        self.timecode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timecode.setFixedWidth(112)
        self.timecode.setInputMask("00:00:00:00")
        layout.addWidget(self.timecode)

        self.frame_label = QLabel("1 / 1")
        self.frame_label.setObjectName("studioFrameCounter")
        self.frame_label.setMinimumWidth(80)
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.frame_label)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._tick)
        self.start_button.clicked.connect(lambda: self.seek(0))
        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button.clicked.connect(self.stop)
        self.next_button.clicked.connect(lambda: self.step(1))
        self.loop_button.toggled.connect(self.set_loop_enabled)
        self.slider.valueChanged.connect(self.seek)
        self.timecode.editingFinished.connect(self._timecode_edited)

        self._shortcuts = (
            QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_playback),
            QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.step(-1)),
            QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.step(1)),
            QShortcut(QKeySequence(Qt.Key.Key_Home), self, activated=lambda: self.seek(0)),
        )

    @property
    def current_frame(self) -> int:
        return self._current_frame

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> int:
        return self._clock.fps

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def loop_enabled(self) -> bool:
        return self._loop_enabled

    @property
    def loop_range(self) -> tuple[int, int]:
        return self._loop_start, self._loop_end

    def set_project(self, fps: int, frame_count: int) -> None:
        if frame_count <= 0:
            raise ValueError("Le transport Studio requiert au moins une frame")
        self.pause()
        self._clock = StudioClock(fps)
        self._frame_count = int(frame_count)
        self._loop_start = 0
        self._loop_end = self._frame_count
        self.slider.setRange(0, self._frame_count - 1)
        self.seek(0, force_signal=True)

    def set_loop_range(self, start_frame: int, end_frame: int) -> None:
        if not 0 <= start_frame < end_frame <= self._frame_count:
            raise ValueError("La zone de boucle doit rester dans la durée du projet")
        self._loop_start = int(start_frame)
        self._loop_end = int(end_frame)
        if self._playing and not self._loop_start <= self._current_frame < self._loop_end:
            self.seek(self._loop_start)

    def set_loop_enabled(self, enabled: bool) -> None:
        self._loop_enabled = bool(enabled)
        blocker = QSignalBlocker(self.loop_button)
        self.loop_button.setChecked(self._loop_enabled)
        del blocker

    def seek(
        self,
        frame: int,
        *,
        force_signal: bool = False,
        reanchor: bool = True,
    ) -> None:
        if isinstance(frame, bool) or not isinstance(frame, int):
            frame = int(frame)
        clamped = min(max(0, frame), self._frame_count - 1)
        changed = clamped != self._current_frame
        self._current_frame = clamped
        if self._playing and reanchor:
            self._anchor_frame = clamped
            self._anchor_ns = self._time_source()
        blocker = QSignalBlocker(self.slider)
        self.slider.setValue(clamped)
        del blocker
        self.timecode.setText(self._clock.format_timecode(clamped))
        self.frame_label.setText(f"{clamped + 1} / {self._frame_count}")
        if changed or force_signal:
            self.frameChanged.emit(clamped)

    def step(self, delta: int) -> None:
        self.pause()
        self.seek(self._current_frame + int(delta))

    def play(self) -> None:
        if self._playing:
            return
        if self._loop_enabled and not self._loop_start <= self._current_frame < self._loop_end:
            self.seek(self._loop_start)
        elif self._loop_enabled and self._current_frame == self._loop_end - 1:
            self.seek(self._loop_start)
        if self._current_frame >= self._frame_count - 1:
            self.seek(0)
        self._playing = True
        self._anchor_frame = self._current_frame
        self._anchor_ns = self._time_source()
        self.play_button.setText("❚❚")
        self._timer.start()
        self.playbackChanged.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._tick()
        self._playing = False
        self._timer.stop()
        self.play_button.setText("▶")
        self.playbackChanged.emit(False)

    def stop(self) -> None:
        self.pause()
        self.seek(self._loop_start if self._loop_enabled else 0)

    def toggle_playback(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def _tick(self) -> None:
        if not self._playing:
            return
        elapsed_ns = max(0, self._time_source() - self._anchor_ns)
        elapsed_frames = elapsed_ns * self._clock.fps // 1_000_000_000
        target = self._anchor_frame + int(elapsed_frames)
        if self._loop_enabled and target >= self._loop_end:
            span = self._loop_end - self._loop_start
            target = self._loop_start + (target - self._loop_start) % span
            self.seek(target, reanchor=False)
            return
        if target >= self._frame_count - 1:
            self.seek(self._frame_count - 1, reanchor=False)
            self._playing = False
            self._timer.stop()
            self.play_button.setText("▶")
            self.playbackChanged.emit(False)
            return
        self.seek(target, reanchor=False)

    def _timecode_edited(self) -> None:
        try:
            frame = self._clock.parse_timecode(self.timecode.text())
        except ValueError:
            self.timecode.setText(self._clock.format_timecode(self._current_frame))
            return
        self.seek(frame)


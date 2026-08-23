from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..studio.clock import StudioClock
from ..studio.model import Clip, ClipKind, StudioProject, Track, TrackKind


HEADER_WIDTH = 190
RULER_HEIGHT = 30
BASE_TRACK_HEIGHT = 56
CLIP_HEIGHT = 21


@dataclass(frozen=True, slots=True)
class TimelineClipLayout:
    track_id: str
    clip: Clip
    lane: int
    rect: QRectF


@dataclass(frozen=True, slots=True)
class TimelineTrackLayout:
    track: Track
    rect: QRectF
    lanes: int


def _clip_lanes(clips: tuple[Clip, ...]) -> dict[str, int]:
    """Assign deterministic sub-lanes so overlaps never paint ambiguously."""

    lane_ends: list[int] = []
    result: dict[str, int] = {}
    for clip in sorted(clips, key=lambda item: (item.start_frame, item.end_frame, item.clip_id)):
        lane = next(
            (index for index, end in enumerate(lane_ends) if end <= clip.start_frame),
            None,
        )
        if lane is None:
            lane = len(lane_ends)
            lane_ends.append(clip.end_frame)
        else:
            lane_ends[lane] = clip.end_frame
        result[clip.clip_id] = lane
    return result


class StudioTimelineScene(QWidget):
    seekRequested = Signal(int)
    selectionChanged = Signal(object)
    trackStateRequested = Signal(str, str, bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioTimelineScene")
        self.setAccessibleName("Timeline multi-pistes du Studio")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._project: StudioProject | None = None
        self._pixels_per_frame = 3.0
        self._playhead = 0
        self._selected: tuple[str, ...] = ()
        self._track_layouts: tuple[TimelineTrackLayout, ...] = ()
        self._clip_layouts: tuple[TimelineClipLayout, ...] = ()

    @property
    def pixels_per_frame(self) -> float:
        return self._pixels_per_frame

    @property
    def selected_clip_ids(self) -> tuple[str, ...]:
        return self._selected

    @property
    def visible_track_ids(self) -> tuple[str, ...]:
        return tuple(layout.track.track_id for layout in self._track_layouts)

    @property
    def clip_layouts(self) -> tuple[TimelineClipLayout, ...]:
        return self._clip_layouts

    def set_project(self, project: StudioProject | None) -> None:
        self._project = project
        valid_clip_ids = {
            clip.clip_id
            for track in project.tracks
            for clip in track.clips
        } if project is not None else set()
        self._selected = tuple(
            clip_id for clip_id in self._selected if clip_id in valid_clip_ids
        )
        self._rebuild_geometry()

    def set_pixels_per_frame(self, value: float) -> None:
        self._pixels_per_frame = min(18.0, max(0.75, float(value)))
        self._rebuild_geometry()

    def set_playhead(self, frame: int) -> None:
        self._playhead = max(0, int(frame))
        self.update()

    def set_selection(self, clip_ids: tuple[str, ...]) -> None:
        known = {layout.clip.clip_id for layout in self._clip_layouts}
        selection = tuple(dict.fromkeys(item for item in clip_ids if item in known))
        if selection == self._selected:
            return
        self._selected = selection
        self.selectionChanged.emit(self._selected)
        self.update()

    def frame_x(self, frame: int) -> float:
        return HEADER_WIDTH + frame * self._pixels_per_frame

    def frame_at_x(self, x: float) -> int:
        if self._project is None:
            return 0
        frame = int(round((x - HEADER_WIDTH) / self._pixels_per_frame))
        return min(self._project.settings.duration_frames - 1, max(0, frame))

    def _rebuild_geometry(self) -> None:
        project = self._project
        if project is None:
            self._track_layouts = ()
            self._clip_layouts = ()
            self.setFixedSize(QSize(HEADER_WIDTH + 400, RULER_HEIGHT + BASE_TRACK_HEIGHT))
            self.update()
            return

        width = int(
            HEADER_WIDTH
            + project.settings.duration_frames * self._pixels_per_frame
            + 36
        )
        y = float(RULER_HEIGHT)
        tracks: list[TimelineTrackLayout] = []
        clips: list[TimelineClipLayout] = []
        # The compositor consumes project order bottom-to-top. The timeline
        # displays the highest compositing layer first, like a physical stack.
        for track in reversed(project.tracks):
            lanes_by_clip = _clip_lanes(track.clips)
            lane_count = max(lanes_by_clip.values(), default=0) + 1
            height = max(BASE_TRACK_HEIGHT, 31 + lane_count * (CLIP_HEIGHT + 3))
            track_rect = QRectF(0, y, width, height)
            tracks.append(TimelineTrackLayout(track, track_rect, lane_count))
            for clip in track.clips:
                lane = lanes_by_clip[clip.clip_id]
                clip_rect = QRectF(
                    self.frame_x(clip.start_frame),
                    y + 28 + lane * (CLIP_HEIGHT + 3),
                    max(2.0, clip.duration_frames * self._pixels_per_frame),
                    CLIP_HEIGHT,
                )
                clips.append(TimelineClipLayout(track.track_id, clip, lane, clip_rect))
            y += height
        self._track_layouts = tuple(tracks)
        self._clip_layouts = tuple(clips)
        self.setFixedSize(QSize(width, max(RULER_HEIGHT + BASE_TRACK_HEIGHT, int(y))))
        self.update()

    def _state_rects(self, row: TimelineTrackLayout) -> dict[str, QRectF]:
        y = row.rect.top() + 5
        return {
            "muted": QRectF(112, y, 20, 20),
            "locked": QRectF(137, y, 20, 20),
            "hidden": QRectF(162, y, 20, 20),
        }

    def _track_at(self, point: QPointF) -> TimelineTrackLayout | None:
        return next(
            (layout for layout in self._track_layouts if layout.rect.contains(point)),
            None,
        )

    def _clip_at(self, point: QPointF) -> TimelineClipLayout | None:
        return next(
            (
                layout
                for layout in reversed(self._clip_layouts)
                if layout.rect.contains(point)
            ),
            None,
        )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#11151d"))
        painter.fillRect(0, 0, self.width(), RULER_HEIGHT, QColor("#202633"))
        painter.fillRect(0, 0, HEADER_WIDTH, self.height(), QColor("#181d27"))

        if self._project is None:
            painter.setPen(QColor("#8f9bb1"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucun projet Studio")
            return

        self._paint_ruler(painter)
        kind_label = {
            TrackKind.VIDEO: "IMAGE",
            TrackKind.EFFECT: "EFFET",
            TrackKind.AUDIO: "AUDIO",
        }
        for index, row in enumerate(self._track_layouts):
            painter.fillRect(
                row.rect,
                QColor("#171c26") if index % 2 == 0 else QColor("#141923"),
            )
            painter.fillRect(
                QRectF(0, row.rect.top(), HEADER_WIDTH, row.rect.height()),
                QColor("#222936") if index % 2 == 0 else QColor("#1e2531"),
            )
            painter.setPen(QPen(QColor("#30394a"), 1))
            painter.drawLine(
                QPointF(0, row.rect.bottom()),
                QPointF(self.width(), row.rect.bottom()),
            )
            painter.setPen(QColor("#e9edf5"))
            font = QFont(self.font())
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(8, row.rect.top() + 4, 98, 18), row.track.name)
            font.setBold(False)
            font.setPointSize(max(7, font.pointSize() - 1))
            painter.setFont(font)
            painter.setPen(QColor("#8f9bb1"))
            z_index = len(self._project.tracks) - index - 1
            painter.drawText(
                QRectF(8, row.rect.top() + 23, 98, 16),
                f"{kind_label[row.track.kind]} · Z{z_index}",
            )
            for field, rect in self._state_rects(row).items():
                enabled = bool(getattr(row.track, field))
                painter.fillRect(rect, QColor("#c86b50") if enabled else QColor("#343d4e"))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    {"muted": "M", "locked": "L", "hidden": "V"}[field],
                )

        colors = {
            ClipKind.ARTWORK_2D: QColor("#4f86c6"),
            ClipKind.ARTWORK_3D: QColor("#8a63d2"),
            ClipKind.STILL: QColor("#4ea39a"),
            ClipKind.VIDEO: QColor("#3f9b6d"),
            ClipKind.EFFECT_2D: QColor("#c8774f"),
            ClipKind.AUDIO: QColor("#b07ac4"),
        }
        for layout in self._clip_layouts:
            selected = layout.clip.clip_id in self._selected
            painter.setPen(
                QPen(QColor("#ffd166") if selected else QColor("#0c1017"), 2 if selected else 1)
            )
            painter.setBrush(colors[layout.clip.kind])
            painter.drawRoundedRect(layout.rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                layout.rect.adjusted(6, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                layout.clip.clip_id,
            )

        playhead_x = self.frame_x(self._playhead)
        painter.setPen(QPen(QColor("#f0b44d"), 2))
        painter.drawLine(QPointF(playhead_x, 0), QPointF(playhead_x, self.height()))
        painter.setBrush(QColor("#f0b44d"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            [
                QPointF(playhead_x - 5, 0),
                QPointF(playhead_x + 5, 0),
                QPointF(playhead_x, 8),
            ]
        )

    def _paint_ruler(self, painter: QPainter) -> None:
        project = self._project
        if project is None:
            return
        clock = StudioClock(project.settings.fps)
        minor = max(1, project.settings.fps // 2)
        painter.setFont(self.font())
        for frame in range(0, project.settings.duration_frames, minor):
            x = self.frame_x(frame)
            major = frame % project.settings.fps == 0
            painter.setPen(QColor("#8893a7") if major else QColor("#4d586c"))
            painter.drawLine(
                QPointF(x, RULER_HEIGHT - (14 if major else 7)),
                QPointF(x, RULER_HEIGHT),
            )
            if major:
                painter.drawText(
                    QRectF(x + 3, 2, 100, 16),
                    clock.format_timecode(frame),
                )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._project is None:
            super().mousePressEvent(event)
            return
        point = event.position()
        row = self._track_at(point)
        if point.x() < HEADER_WIDTH and row is not None:
            for field, rect in self._state_rects(row).items():
                if rect.contains(point):
                    self.trackStateRequested.emit(
                        row.track.track_id,
                        field,
                        not bool(getattr(row.track, field)),
                    )
                    event.accept()
                    return
        if point.x() >= HEADER_WIDTH:
            clip = self._clip_at(point)
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if clip is None:
                if not ctrl:
                    self.set_selection(())
            elif ctrl:
                selected = list(self._selected)
                if clip.clip.clip_id in selected:
                    selected.remove(clip.clip.clip_id)
                else:
                    selected.append(clip.clip.clip_id)
                self.set_selection(tuple(selected))
            else:
                self.set_selection((clip.clip.clip_id,))
            self.seekRequested.emit(self.frame_at_x(point.x()))
            event.accept()
            return
        super().mousePressEvent(event)


class StudioTimeline(QWidget):
    addTrackRequested = Signal(object)
    trackStateRequested = Signal(str, str, bool)
    selectionChanged = Signal(object)
    seekRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioTimeline")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        toolbar = QHBoxLayout()
        title = QLabel("TIMELINE · L’ŒUVRE EST LA SOURCE, LES PISTES SONT SA MISE EN SCÈNE")
        title.setObjectName("studioTimelineTitle")
        toolbar.addWidget(title)
        toolbar.addStretch(1)
        self.add_video = QPushButton("+ Plan")
        self.add_effect = QPushButton("+ Effet")
        self.add_audio = QPushButton("+ Audio")
        for button, kind in (
            (self.add_video, TrackKind.VIDEO),
            (self.add_effect, TrackKind.EFFECT),
            (self.add_audio, TrackKind.AUDIO),
        ):
            button.clicked.connect(
                lambda _checked=False, selected=kind: self.addTrackRequested.emit(selected)
            )
            toolbar.addWidget(button)
        toolbar.addWidget(QLabel("Zoom"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setObjectName("studioTimelineZoom")
        self.zoom.setRange(75, 1800)
        self.zoom.setValue(300)
        self.zoom.setFixedWidth(130)
        toolbar.addWidget(self.zoom)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("studioTimelineScroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scene = StudioTimelineScene()
        self.scroll.setWidget(self.scene)
        self.scroll.setMinimumHeight(190)
        layout.addWidget(self.scroll, 1)

        self.zoom.valueChanged.connect(
            lambda value: self.scene.set_pixels_per_frame(value / 100.0)
        )
        self.scene.seekRequested.connect(self.seekRequested)
        self.scene.selectionChanged.connect(self.selectionChanged)
        self.scene.trackStateRequested.connect(self.trackStateRequested)

    @property
    def selected_clip_ids(self) -> tuple[str, ...]:
        return self.scene.selected_clip_ids

    def set_project(self, project: StudioProject | None) -> None:
        self.scene.set_project(project)

    def set_playhead(self, frame: int) -> None:
        self.scene.set_playhead(frame)
        x = int(self.scene.frame_x(frame))
        bar = self.scroll.horizontalScrollBar()
        viewport_left = bar.value()
        viewport_right = viewport_left + self.scroll.viewport().width()
        if x < viewport_left + HEADER_WIDTH:
            bar.setValue(max(0, x - HEADER_WIDTH))
        elif x > viewport_right - 24:
            bar.setValue(x - self.scroll.viewport().width() + 24)


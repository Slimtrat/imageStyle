from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
)
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

from ..studio.audio import AudioClipSettings, AudioMixSettings, audio_envelope_gain
from ..studio.clock import StudioClock
from ..studio.model import Clip, ClipKind, StudioProject, Track, TrackKind
from ..studio.waveform import WaveformEnvelope, waveform_peaks_for_clip


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


def semantic_clip_label(project: StudioProject, clip: Clip) -> str:
    """Expose event graph participation without turning the timeline into a graph editor."""

    invocation_id = clip.invocation_id
    if invocation_id is None:
        return clip.clip_id
    emits = any(
        item.source_invocation_id == invocation_id for item in project.triggers
    )
    follows = any(
        item.action_invocation_id == invocation_id for item in project.triggers
    )
    badges = ("⚡" if emits else "") + ("↳" if follows else "")
    return f"{badges} {clip.clip_id}" if badges else clip.clip_id

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
    trackSelected = Signal(str)
    clipMoveRequested = Signal(object, str, int, str)
    clipTrimRequested = Signal(str, int, int)
    audioFadeRequested = Signal(str, int, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioTimelineScene")
        self.setAccessibleName("Timeline multi-pistes du Studio")
        self.setMouseTracking(True)
        self._waveforms: dict[str, WaveformEnvelope] = {}
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._project: StudioProject | None = None
        self._pixels_per_frame = 3.0
        self._playhead = 0
        self._selected: tuple[str, ...] = ()
        self._track_layouts: tuple[TimelineTrackLayout, ...] = ()
        self._clip_layouts: tuple[TimelineClipLayout, ...] = ()
        self._selected_track_id: str | None = None
        self._drag_clip: TimelineClipLayout | None = None
        self._drag_mode: str | None = None
        self._drag_press_frame = 0
        self._drag_target_frame = 0
        self._drag_target_track_id: str | None = None
        self._drag_started = False

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
    @property
    def selected_track_id(self) -> str | None:
        return self._selected_track_id

    @property
    def waveform_asset_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._waveforms))


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

    def set_waveforms(self, waveforms: dict[str, WaveformEnvelope]) -> None:
        self._waveforms = dict(waveforms)
        self.update()


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

    def _display_audio_settings(
        self,
        layout: TimelineClipLayout,
    ) -> AudioClipSettings:
        settings = AudioClipSettings.from_clip(layout.clip)
        if self._drag_clip is layout and self._drag_started:
            if self._drag_mode == "fade-in":
                settings = replace(
                    settings,
                    fade_in_frames=self._drag_target_frame,
                )
            elif self._drag_mode == "fade-out":
                settings = replace(
                    settings,
                    fade_out_frames=self._drag_target_frame,
                )
        return settings

    def _fade_handle_positions(
        self,
        layout: TimelineClipLayout,
        settings: AudioClipSettings,
    ) -> tuple[QPointF, QPointF]:
        top = layout.rect.top() + 3.0
        return (
            QPointF(layout.rect.left() + settings.fade_in_frames * self._pixels_per_frame, top),
            QPointF(layout.rect.right() - settings.fade_out_frames * self._pixels_per_frame, top),
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
            detail = f"{kind_label[row.track.kind]} · Z{z_index}"
            if row.track.kind == TrackKind.AUDIO:
                gain = AudioMixSettings.from_project(self._project).track(
                    row.track.track_id
                ).gain_db
                detail = f"AUDIO · {gain:+.1f} dB"
            painter.drawText(
                QRectF(8, row.rect.top() + 23, 98, 16),
                detail,
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
            if layout.clip.kind == ClipKind.AUDIO and layout.clip.asset_id is not None:
                envelope = self._waveforms.get(layout.clip.asset_id)
                if envelope is not None:
                    width = max(1, int(layout.rect.width()))
                    peaks = waveform_peaks_for_clip(
                        envelope,
                        layout.clip,
                        self._project.settings.fps,
                        width,
                    )
                    painter.setPen(QPen(QColor("#f3dcff"), 1))
                    middle = layout.rect.center().y()
                    amplitude = max(1.0, layout.rect.height() * 0.42)
                    for offset, (minimum, maximum) in enumerate(peaks):
                        x = layout.rect.left() + offset
                        painter.drawLine(
                            QPointF(x, middle - maximum * amplitude),
                            QPointF(x, middle - minimum * amplitude),
                        )
                settings = self._display_audio_settings(layout)
                envelope_path = QPainterPath()
                bottom = layout.rect.bottom() - 3.0
                amplitude = max(1.0, layout.rect.height() - 6.0)
                samples = max(2, min(96, int(layout.rect.width()) + 1))
                for index in range(samples):
                    ratio = index / (samples - 1)
                    local_frame = min(
                        layout.clip.duration_frames,
                        int(round(ratio * layout.clip.duration_frames)),
                    )
                    gain = (
                        1.0
                        if local_frame == layout.clip.duration_frames
                        and settings.fade_out_frames == 0
                        else audio_envelope_gain(
                            settings,
                            local_frame,
                            layout.clip.duration_frames,
                        )
                    )
                    point = QPointF(
                        layout.rect.left() + ratio * layout.rect.width(),
                        bottom - gain * amplitude,
                    )
                    if index == 0:
                        envelope_path.moveTo(point)
                    else:
                        envelope_path.lineTo(point)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#ffd166"), 1.5))
                painter.drawPath(envelope_path)
                if selected:
                    painter.setBrush(QColor("#ffd166"))
                    painter.setPen(QPen(QColor("#1b1010"), 1))
                    for handle in self._fade_handle_positions(layout, settings):
                        painter.drawEllipse(handle, 3.5, 3.5)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                layout.rect.adjusted(6, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                semantic_clip_label(self._project, layout.clip),
            )

        if self._drag_clip is not None and self._drag_started:
            preview = QRectF(self._drag_clip.rect)
            if self._drag_mode == "move":
                preview.moveLeft(self.frame_x(self._drag_target_frame))
                row = next(
                    (
                        item for item in self._track_layouts
                        if item.track.track_id == self._drag_target_track_id
                    ),
                    None,
                )
                if row is not None:
                    preview.moveTop(row.rect.top() + 28)
            elif self._drag_mode == "trim-left":
                preview.setLeft(self.frame_x(self._drag_target_frame))
            elif self._drag_mode == "trim-right":
                preview.setRight(self.frame_x(self._drag_target_frame))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffd166"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(preview)
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
            self._selected_track_id = row.track.track_id
            self.trackSelected.emit(row.track.track_id)
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
            if clip is not None:
                self._selected_track_id = clip.track_id
                self.trackSelected.emit(clip.track_id)
                self._drag_clip = clip
                self._drag_press_frame = self.frame_at_x(point.x())
                self._drag_target_frame = clip.clip.start_frame
                self._drag_target_track_id = clip.track_id
                edge = 7.0
                fade_mode = None
                if clip.clip.kind == ClipKind.AUDIO:
                    settings = AudioClipSettings.from_clip(clip.clip)
                    fade_in_handle, fade_out_handle = self._fade_handle_positions(
                        clip,
                        settings,
                    )
                    near_top = abs(point.y() - fade_in_handle.y()) <= 8.0
                    if near_top and abs(point.x() - fade_in_handle.x()) <= edge:
                        fade_mode = "fade-in"
                        self._drag_press_frame = settings.fade_in_frames
                        self._drag_target_frame = settings.fade_in_frames
                    elif near_top and abs(point.x() - fade_out_handle.x()) <= edge:
                        fade_mode = "fade-out"
                        self._drag_press_frame = settings.fade_out_frames
                        self._drag_target_frame = settings.fade_out_frames
                if fade_mode is not None:
                    self._drag_mode = fade_mode
                elif abs(point.x() - clip.rect.left()) <= edge:
                    self._drag_mode = "trim-left"
                elif abs(point.x() - clip.rect.right()) <= edge:
                    self._drag_mode = "trim-right"
                    self._drag_target_frame = clip.clip.end_frame
                else:
                    self._drag_mode = "move"
            self.seekRequested.emit(self.frame_at_x(point.x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_clip is None or self._drag_mode is None:
            super().mouseMoveEvent(event)
            return
        clip = self._drag_clip.clip
        if self._drag_mode in {"fade-in", "fade-out"}:
            settings = AudioClipSettings.from_clip(clip)
            if self._drag_mode == "fade-in":
                proposed = int(round(
                    (event.position().x() - self._drag_clip.rect.left())
                    / self._pixels_per_frame
                ))
                target = min(
                    clip.duration_frames - settings.fade_out_frames,
                    max(0, proposed),
                )
            else:
                proposed = int(round(
                    (self._drag_clip.rect.right() - event.position().x())
                    / self._pixels_per_frame
                ))
                target = min(
                    clip.duration_frames - settings.fade_in_frames,
                    max(0, proposed),
                )
            self._drag_started = self._drag_started or target != self._drag_press_frame
            self._drag_target_frame = target
            self.update()
            event.accept()
            return
        frame = self.frame_at_x(event.position().x())
        self._drag_started = self._drag_started or frame != self._drag_press_frame
        if self._drag_mode == "move":
            delta = frame - self._drag_press_frame
            self._drag_target_frame = max(0, clip.start_frame + delta)
            row = self._track_at(event.position())
            if row is not None and row.track.kind == next(
                item.track.kind for item in self._track_layouts
                if item.track.track_id == self._drag_clip.track_id
            ):
                self._drag_target_track_id = row.track.track_id
        elif self._drag_mode == "trim-left":
            self._drag_target_frame = min(clip.end_frame - 1, max(0, frame))
        else:
            duration = self._project.settings.duration_frames if self._project else clip.end_frame
            self._drag_target_frame = max(
                clip.start_frame + 1,
                min(duration, frame),
            )
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._drag_clip is None:
            super().mouseReleaseEvent(event)
            return
        layout = self._drag_clip
        mode = self._drag_mode
        target = self._drag_target_frame
        target_track = self._drag_target_track_id or layout.track_id
        started = self._drag_started
        self._drag_clip = None
        self._drag_mode = None
        self._drag_target_track_id = None
        self._drag_started = False
        if started and mode == "move":
            selection = self._selected or (layout.clip.clip_id,)
            self.clipMoveRequested.emit(
                selection, layout.clip.clip_id, target, target_track
            )
        elif started and mode == "trim-left":
            self.clipTrimRequested.emit(layout.clip.clip_id, target, layout.clip.end_frame)
        elif started and mode == "trim-right":
            self.clipTrimRequested.emit(layout.clip.clip_id, layout.clip.start_frame, target)
        elif started and mode in {"fade-in", "fade-out"}:
            settings = AudioClipSettings.from_clip(layout.clip)
            fade_in = target if mode == "fade-in" else settings.fade_in_frames
            fade_out = target if mode == "fade-out" else settings.fade_out_frames
            self.audioFadeRequested.emit(
                layout.clip.clip_id,
                fade_in,
                fade_out,
            )
        self.update()
        event.accept()


class StudioTimeline(QWidget):
    addTrackRequested = Signal(object)
    trackStateRequested = Signal(str, str, bool)
    audioFadeRequested = Signal(str, int, int)
    selectionChanged = Signal(object)
    seekRequested = Signal(int)
    clipMoveRequested = Signal(object, str, int, str)
    clipTrimRequested = Signal(str, int, int)
    splitRequested = Signal(object)
    duplicateRequested = Signal(object)
    deleteRequested = Signal(object)
    trackReorderRequested = Signal(str, int)

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
        self.split_button = QPushButton("Scinder")
        self.duplicate_button = QPushButton("Dupliquer")
        self.delete_button = QPushButton("Supprimer")
        self.track_down = QPushButton("Piste ↓")
        self.track_up = QPushButton("Piste ↑")
        self.snap_button = QPushButton("Aimant")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        for button in (
            self.split_button,
            self.duplicate_button,
            self.delete_button,
            self.track_down,
            self.track_up,
            self.snap_button,
        ):
            toolbar.addWidget(button)
        self.split_button.clicked.connect(
            lambda: self.splitRequested.emit(self.selected_clip_ids)
        )
        self.duplicate_button.clicked.connect(
            lambda: self.duplicateRequested.emit(self.selected_clip_ids)
        )
        self.delete_button.clicked.connect(
            lambda: self.deleteRequested.emit(self.selected_clip_ids)
        )
        self.track_down.clicked.connect(lambda: self._request_track_reorder(-1))
        self.track_up.clicked.connect(lambda: self._request_track_reorder(1))
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
        self.scene.clipMoveRequested.connect(self.clipMoveRequested)
        self.scene.clipTrimRequested.connect(self.clipTrimRequested)
        self.scene.audioFadeRequested.connect(self.audioFadeRequested)
        self._shortcuts = (
            QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self.delete_button.click),
            QShortcut(QKeySequence("Ctrl+D"), self, activated=self.duplicate_button.click),
            QShortcut(QKeySequence("S"), self, activated=self.split_button.click),
        )


    @property
    def selected_clip_ids(self) -> tuple[str, ...]:
        return self.scene.selected_clip_ids

    @property
    def snapping_enabled(self) -> bool:
        return self.snap_button.isChecked()

    def _request_track_reorder(self, direction: int) -> None:
        track_id = self.scene.selected_track_id
        if track_id is not None:
            self.trackReorderRequested.emit(track_id, int(direction))

    def set_project(self, project: StudioProject | None) -> None:
        self.scene.set_project(project)

    def set_waveforms(self, waveforms: dict[str, WaveformEnvelope]) -> None:
        self.scene.set_waveforms(waveforms)

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


from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..studio.model import CameraAnimation


class StudioKeyframeStrip(QWidget):
    """Compact draggable camera-keyframe lane bound to the active artwork clip."""

    seekRequested = Signal(int)
    keyframeMoved = Signal(int, int)
    keyframeCopied = Signal(int, int)
    keyframeDeleteRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioCameraKeyframeStrip")
        self.setAccessibleName("Piste de keyframes caméra")
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._animation = CameraAnimation()
        self._clip_start = 0
        self._clip_duration = 1
        self._playhead = 0
        self._selected_local: int | None = None
        self._drag_origin: int | None = None
        self._drag_target: int | None = None
        self._copy_drag = False
        self._delete_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete),
            self,
            activated=self._delete_selected,
        )

    @property
    def selected_local_frame(self) -> int | None:
        return self._selected_local

    def set_animation(
        self,
        animation: CameraAnimation | None,
        *,
        clip_start: int,
        clip_duration: int,
    ) -> None:
        self._animation = animation or CameraAnimation()
        self._clip_start = max(0, int(clip_start))
        self._clip_duration = max(1, int(clip_duration))
        frames = {keyframe.frame for keyframe in self._animation.keyframes}
        if self._selected_local not in frames:
            self._selected_local = None
        self.update()

    def set_playhead(self, project_frame: int) -> None:
        self._playhead = int(project_frame)
        local = self._playhead - self._clip_start
        frames = {keyframe.frame for keyframe in self._animation.keyframes}
        self._selected_local = local if local in frames else self._selected_local
        self.update()

    def _lane(self) -> QRectF:
        return QRectF(14, 9, max(1, self.width() - 28), max(1, self.height() - 18))

    def _x_for_frame(self, local_frame: int) -> float:
        lane = self._lane()
        denominator = max(1, self._clip_duration - 1)
        return lane.left() + lane.width() * local_frame / denominator

    def _frame_for_x(self, x: float) -> int:
        lane = self._lane()
        progress = (x - lane.left()) / max(1.0, lane.width())
        return min(
            self._clip_duration - 1,
            max(0, int(round(progress * max(1, self._clip_duration - 1)))),
        )

    def _hit_keyframe(self, point: QPointF) -> int | None:
        for keyframe in self._animation.keyframes:
            if abs(point.x() - self._x_for_frame(keyframe.frame)) <= 8:
                return keyframe.frame
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#151922"))
        lane = self._lane()
        center_y = lane.center().y()
        painter.setPen(QPen(QColor("#4b5569"), 2))
        painter.drawLine(lane.left(), center_y, lane.right(), center_y)

        playhead_local = self._playhead - self._clip_start
        if 0 <= playhead_local < self._clip_duration:
            painter.setPen(QPen(QColor("#f0b44d"), 1))
            x = self._x_for_frame(playhead_local)
            painter.drawLine(x, lane.top(), x, lane.bottom())

        for keyframe in self._animation.keyframes:
            frame = (
                self._drag_target
                if self._drag_origin == keyframe.frame and self._drag_target is not None
                else keyframe.frame
            )
            x = self._x_for_frame(frame)
            radius = 6.0
            diamond = QPainterPath()
            diamond.moveTo(x, center_y - radius)
            diamond.lineTo(x + radius, center_y)
            diamond.lineTo(x, center_y + radius)
            diamond.lineTo(x - radius, center_y)
            diamond.closeSubpath()
            selected = keyframe.frame == self._selected_local
            painter.fillPath(
                diamond,
                QColor("#f0b44d") if selected else QColor("#7ec8e3"),
            )
            painter.setPen(QColor("#11151d"))
            painter.drawPath(diamond)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        local = self._hit_keyframe(event.position())
        if local is None:
            project_frame = self._clip_start + self._frame_for_x(event.position().x())
            self.seekRequested.emit(project_frame)
            return
        self._selected_local = local
        self._drag_origin = local
        self._drag_target = local
        self._copy_drag = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self.seekRequested.emit(self._clip_start + local)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        self._drag_target = self._frame_for_x(event.position().x())
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            super().mouseReleaseEvent(event)
            return
        origin = self._drag_origin
        target = self._drag_target if self._drag_target is not None else origin
        copy_drag = self._copy_drag
        self._drag_origin = None
        self._drag_target = None
        self._copy_drag = False
        if target != origin:
            if copy_drag:
                self.keyframeCopied.emit(origin, target)
            else:
                self.keyframeMoved.emit(origin, target)
        self.update()
        event.accept()

    def _delete_selected(self) -> None:
        if self._selected_local is not None:
            self.keyframeDeleteRequested.emit(self._selected_local)


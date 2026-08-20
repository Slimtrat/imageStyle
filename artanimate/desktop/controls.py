from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget


class ParameterSlider(QWidget):
    """Compact slider with an exact value pill and always-visible bounds."""

    valueChanged = Signal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        decimals: int = 0,
        suffix: str = "",
        description: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        if maximum <= minimum or step <= 0:
            raise ValueError("Bornes ou pas invalides pour le slider")
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = float(step)
        self._decimals = int(decimals)
        self._suffix = suffix
        self._step_count = max(1, int(round((self._maximum - self._minimum) / self._step)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(1)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._step_count)
        self.slider.setPageStep(max(1, self._step_count // 12))
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value_label = QLabel()
        self.value_label.setObjectName("sliderValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setMinimumWidth(68)
        value_row.addWidget(self.slider, 1)
        value_row.addWidget(self.value_label)
        layout.addLayout(value_row)

        bounds = QHBoxLayout()
        bounds.setContentsMargins(2, 0, 2, 0)
        self.minimum_label = QLabel(self._format(self._minimum))
        self.maximum_label = QLabel(self._format(self._maximum))
        self.minimum_label.setObjectName("rangeLabel")
        self.maximum_label.setObjectName("rangeLabel")
        bounds.addWidget(self.minimum_label)
        bounds.addStretch(1)
        bounds.addWidget(self.maximum_label)
        layout.addLayout(bounds)

        if description:
            self.setToolTip(description)
            self.slider.setToolTip(description)
        self.slider.valueChanged.connect(self._slider_changed)
        self.setValue(value)

    def _format(self, value: float) -> str:
        if self._decimals == 0:
            rendered = str(int(round(value)))
        else:
            rendered = f"{value:.{self._decimals}f}"
        return f"{rendered}{self._suffix}"

    def _value_from_position(self, position: int) -> float:
        value = min(self._maximum, self._minimum + position * self._step)
        if self._decimals == 0:
            return float(int(round(value)))
        return round(value, self._decimals)

    def _position_from_value(self, value: float) -> int:
        bounded = min(self._maximum, max(self._minimum, float(value)))
        return int(round((bounded - self._minimum) / self._step))

    def _slider_changed(self, position: int) -> None:
        value = self._value_from_position(position)
        self.value_label.setText(self._format(value))
        self.valueChanged.emit(value)

    def value(self) -> int | float:
        value = self._value_from_position(self.slider.value())
        return int(value) if self._decimals == 0 else value

    def setValue(self, value: float) -> None:
        position = self._position_from_value(value)
        if position == self.slider.value():
            self.value_label.setText(self._format(self._value_from_position(position)))
        else:
            self.slider.setValue(position)

    def minimum(self) -> int | float:
        return int(self._minimum) if self._decimals == 0 else self._minimum

    def maximum(self) -> int | float:
        return int(self._maximum) if self._decimals == 0 else self._maximum


class ChromaticSequenceWheel(QWidget):
    """Rotatable six-stage color wheel with a separate neutral indicator."""

    hueChanged = Signal(float)

    _HUES = (0, 60, 120, 180, 240, 300)
    _NAMES = ("Rouges", "Jaunes", "Verts", "Cyans", "Bleus", "Magentas")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._start_hue = 0.0
        self._reverse = False
        self._neutral_position = "last"
        self._outline_mode = "last"
        self._drag_angle: float | None = None
        self._drag_hue = 0.0
        self.setMinimumSize(280, 322)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("Séquence chromatique rotative")
        self.setToolTip(
            "Faites glisser la roue ou utilisez la molette pour choisir la couleur de départ."
        )

    def startHue(self) -> float:
        return self._start_hue

    def setStartHue(self, value: float) -> None:
        normalized = float(value) % 360.0
        if math.isclose(normalized, self._start_hue, abs_tol=1e-6):
            return
        self._start_hue = normalized
        self.update()
        self.hueChanged.emit(normalized)

    def setReverse(self, reverse: bool) -> None:
        if bool(reverse) != self._reverse:
            self._reverse = bool(reverse)
            self.update()

    def setNeutralPosition(self, position: str) -> None:
        if position not in {"first", "last"}:
            raise ValueError("La position des neutres doit être 'first' ou 'last'")
        if position != self._neutral_position:
            self._neutral_position = position
            self.update()

    def setOutlineMode(self, mode: str) -> None:
        if mode not in {"first", "last", "together"}:
            raise ValueError("Mode de contours inconnu")
        if mode != self._outline_mode:
            self._outline_mode = mode
            self.update()

    def _wheel_rect(self) -> QRectF:
        diameter = max(170.0, min(244.0, self.width() - 34.0, self.height() - 88.0))
        return QRectF((self.width() - diameter) / 2.0, 8.0, diameter, diameter)

    @staticmethod
    def _point_angle(point: QPointF, center: QPointF) -> float:
        return math.degrees(math.atan2(point.y() - center.y(), point.x() - center.x()))

    def _selected_name(self) -> str:
        index = int(round(self._start_hue / 60.0)) % 6
        return self._NAMES[index]

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        wheel = self._wheel_rect()

        for index, hue in enumerate(self._HUES):
            painter.setBrush(QColor.fromHsv(hue, 210, 245))
            painter.setPen(QPen(QColor("#ffffff"), 2.0))
            start_degrees = 120.0 - index * 60.0 + self._start_hue
            painter.drawPie(wheel, int(start_degrees * 16), -60 * 16)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#20283a"), 3.0))
        painter.drawEllipse(wheel)

        center = wheel.center()
        marker_radius = wheel.width() * 0.385
        direction = -1.0 if self._reverse else 1.0
        for index in range(6):
            angle = math.radians(-90.0 + direction * index * 60.0)
            marker = QPointF(
                center.x() + math.cos(angle) * marker_radius,
                center.y() + math.sin(angle) * marker_radius,
            )
            badge = QRectF(marker.x() - 13.0, marker.y() - 13.0, 26.0, 26.0)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#20283a"), 2.0))
            painter.drawEllipse(badge)
            painter.setPen(QColor("#172033"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index + 1))

        center_disc = QRectF(center.x() - 46.0, center.y() - 46.0, 92.0, 92.0)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#d8dee8"), 2.0))
        painter.drawEllipse(center_disc)
        painter.setPen(QColor("#172033"))
        direction_text = "↺" if self._reverse else "↻"
        painter.drawText(
            center_disc,
            Qt.AlignmentFlag.AlignCenter,
            f"Départ\n{self._selected_name()}\n{direction_text} {self._start_hue:.0f}°",
        )

        neutral_size = 58.0
        neutral = QRectF(
            center.x() - neutral_size / 2.0,
            wheel.bottom() + 10.0,
            neutral_size,
            neutral_size,
        )
        painter.setPen(QPen(QColor("#8a92a1"), 2.0))
        painter.setBrush(QColor("#111318"))
        painter.drawPie(neutral, 90 * 16, 180 * 16)
        painter.setBrush(QColor("#f8f8f4"))
        painter.drawPie(neutral, 270 * 16, 180 * 16)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(neutral)
        painter.setPen(QColor("#6b7280"))
        neutral_text = "avant" if self._neutral_position == "first" else "après"
        outline_labels = {"first": "début", "last": "fin", "together": "progressifs"}
        caption = (
            f"Noir / blanc séparés · neutres {neutral_text} · "
            f"contours {outline_labels[self._outline_mode]}"
        )
        painter.drawText(
            QRectF(4.0, neutral.bottom() + 1.0, self.width() - 8.0, 22.0),
            Qt.AlignmentFlag.AlignCenter,
            caption,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        wheel = self._wheel_rect()
        offset = event.position() - wheel.center()
        if event.button() == Qt.MouseButton.LeftButton and math.hypot(offset.x(), offset.y()) <= wheel.width() / 2.0:
            self._drag_angle = self._point_angle(event.position(), wheel.center())
            self._drag_hue = self._start_hue
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_angle is not None:
            angle = self._point_angle(event.position(), self._wheel_rect().center())
            delta = angle - self._drag_angle
            if delta > 180.0:
                delta -= 360.0
            elif delta < -180.0:
                delta += 360.0
            self.setStartHue(self._drag_hue - delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_angle is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_angle = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.setStartHue(self._start_hue + steps * 5.0)
            event.accept()
            return
        super().wheelEvent(event)

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from .problems import (
    UserProblem,
    destination_reference_problem,
    source_reference_problem,
)


class PathDropZone(QFrame):
    path_selected = Signal(str)
    path_rejected = Signal(object)

    def __init__(self, title: str, instruction: str, mode: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = mode
        self._path: Path | None = None
        self.setObjectName("dropZone")
        self.setProperty("ready", False)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(5)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        self.path_label = QLabel(instruction)
        self.path_label.setObjectName("pathText")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label, 1)

        action = QPushButton("Parcourir…")
        action.setCursor(Qt.CursorShape.PointingHandCursor)
        action.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(action)
        layout.addLayout(row)

    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, value: str | Path) -> bool:
        path = Path(value)
        problem = self._path_problem(path)
        if problem is not None:
            self._path = None
            self.mark_invalid(problem)
            self.path_rejected.emit(problem)
            return False
        self._path = path.resolve()
        self.path_label.setText(str(self._path))
        self.path_label.setToolTip(str(self._path))
        self.setProperty("ready", True)
        self.setProperty("invalid", False)
        self.style().unpolish(self)
        self.style().polish(self)
        return True

    def mark_invalid(self, problem: UserProblem) -> None:
        self.setProperty("ready", False)
        self.setProperty("invalid", True)
        self.path_label.setText(problem.message)
        self.path_label.setToolTip(problem.display_text)
        self.style().unpolish(self)
        self.style().polish(self)

    def _path_problem(self, path: Path) -> UserProblem | None:
        if self.mode == "directory":
            return destination_reference_problem(path)
        return source_reference_problem(path)

    def _accepts(self, path: Path) -> bool:
        return self._path_problem(path) is None

    def browse(self) -> None:
        if self.mode == "directory":
            selected = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination")
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Choisir une œuvre",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
            )
        if selected and self.set_path(selected):
            self.path_selected.emit(str(self._path))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse()
        else:
            super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            if self.set_path(Path(url.toLocalFile())):
                self.path_selected.emit(str(self._path))
            event.acceptProposedAction()
            return


class ScaledImageLabel(QLabel):
    def __init__(self, placeholder: str, parent: QWidget | None = None):
        super().__init__(placeholder, parent)
        self._source: QPixmap | None = None
        self._placeholder = placeholder
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumSize(260, 260)
        self.setStyleSheet("background:#f7f8fb; border-radius:10px; color:#8a92a1; padding:18px;")

    def set_image(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self.setText("")
        self._rescale()

    def clear_image(self, placeholder: str | None = None) -> None:
        self._source = None
        self.clear()
        self.setText(placeholder or self._placeholder)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source and not self._source.isNull():
            available = self.size()
            available.setWidth(max(1, available.width() - 24))
            available.setHeight(max(1, available.height() - 24))
            self.setPixmap(
                self._source.scaled(
                    available,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class PreviewCard(QFrame):
    def __init__(self, title: str, placeholder: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("previewCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 13)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.image = ScaledImageLabel(placeholder)
        layout.addWidget(self.image, 1)

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCommandLinkButton,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class SettingsCard(QCommandLinkButton):
    """Large entry point that exposes one coherent family of settings."""

    def __init__(
        self,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName("settingsCard")
        self.setDescription(description)
        self.setAccessibleName(f"Ouvrir les réglages {title}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(78)


class SettingsDialog(QDialog):
    """Persistent non-modal settings window.

    The supplied content widget is kept alive when the dialog is closed, so its
    values and signal connections remain the single source of truth for previews
    and final renders.
    """

    def __init__(
        self,
        title: str,
        intro: str,
        content: QWidget,
        parent: QWidget | None = None,
        *,
        minimum_width: int = 520,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{title} — ArtAnimate")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(minimum_width)
        self.resize(max(minimum_width, 560), 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        root.addWidget(heading)

        helper = QLabel(intro)
        helper.setObjectName("muted")
        helper.setWordWrap(True)
        root.addWidget(helper)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("settingsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Fermer")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self.content = content

    def show_raised(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def set_controls_enabled(self, enabled: bool) -> None:
        self.content.setEnabled(enabled)

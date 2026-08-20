from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .history import GenerationRecord


class GenerationCard(QFrame):
    play_requested = Signal(str)
    reveal_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, record: GenerationRecord, parent: QWidget | None = None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("historyCard")
        self.setFixedSize(298, 70)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(8)

        preview = QLabel()
        preview.setObjectName("historyThumbnail")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(72, 50)
        pixmap = self._load_pixmap(record)
        if pixmap is not None:
            preview.setPixmap(
                pixmap.scaled(
                    preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            preview.setText("Aucune vignette")
        layout.addWidget(preview)

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(1)
        title = QLabel(record.effect_label)
        title.setObjectName("historyTitle")
        title.setToolTip(str(record.output_path))
        details.addWidget(title)
        metadata = QLabel(f"{record.display_date} · {record.output_path.name}")
        metadata.setObjectName("historyMetadata")
        metadata.setToolTip(str(record.output_path))
        details.addWidget(metadata)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        play = QPushButton("Lire")
        play.setObjectName("compactButton")
        play.setEnabled(record.available)
        if not record.available:
            play.setToolTip("Le fichier vidéo a été déplacé ou supprimé")
            metadata.setText(f"Fichier introuvable · {record.output_path.name}")
        play.clicked.connect(lambda: self.play_requested.emit(record.output))

        menu_button = QToolButton()
        menu_button.setObjectName("historyMenuButton")
        menu_button.setText("⋯")
        menu_button.setToolTip("Actions sur cette génération")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        play_action = menu.addAction("Lire la vidéo")
        play_action.setEnabled(record.available)
        play_action.triggered.connect(lambda: self.play_requested.emit(record.output))
        reveal_action = menu.addAction("Afficher dans l’Explorateur Windows")
        reveal_action.setEnabled(record.output_path.parent.is_dir())
        reveal_action.triggered.connect(lambda: self.reveal_requested.emit(record.output))
        menu.addSeparator()
        delete_label = (
            "Supprimer définitivement la vidéo…"
            if record.available
            else "Retirer l’entrée introuvable…"
        )
        delete_action = menu.addAction(delete_label)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(record.output))
        menu_button.setMenu(menu)

        actions.addWidget(play)
        actions.addStretch(1)
        actions.addWidget(menu_button)
        details.addLayout(actions)
        layout.addLayout(details, 1)

    @staticmethod
    def _load_pixmap(record: GenerationRecord) -> QPixmap | None:
        candidates = (record.thumbnail_path, record.source_path)
        for path in candidates:
            if path is None or not path.is_file():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap
        return None


class HistoryPanel(QFrame):
    """Horizontal, persistent generation bank shown below the 2D workspace."""

    play_requested = Signal(str)
    reveal_requested = Signal(str)
    delete_requested = Signal(str)
    directory_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("historyPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 7, 11, 7)
        layout.setSpacing(4)

        heading_row = QHBoxLayout()
        heading = QLabel("Historique")
        heading.setObjectName("sectionTitle")
        self.directory_label = QLabel("Aucun dossier de destination")
        self.directory_label.setObjectName("muted")
        self.directory_label.setMaximumWidth(320)
        self.counter = QLabel("0 vidéo")
        self.counter.setObjectName("muted")
        open_directory = QPushButton("Explorateur Windows")
        open_directory.setObjectName("compactButton")
        open_directory.clicked.connect(self.directory_requested)
        heading_row.addWidget(heading)
        heading_row.addWidget(self.directory_label)
        heading_row.addStretch(1)
        heading_row.addWidget(self.counter)
        heading_row.addWidget(open_directory)
        layout.addLayout(heading_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFixedHeight(86)
        self.container = QWidget()
        self.row = QHBoxLayout(self.container)
        self.row.setContentsMargins(0, 0, 0, 4)
        self.row.setSpacing(7)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)
        self.set_records(())

    def set_records(self, records: tuple[GenerationRecord, ...]) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not records:
            empty = QLabel(
                "Les vidéos terminées apparaîtront ici avec leurs réglages et leur vignette."
            )
            empty.setObjectName("historyEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.row.addWidget(empty, 1)
        else:
            for record in records:
                card = GenerationCard(record)
                card.play_requested.connect(self.play_requested)
                card.reveal_requested.connect(self.reveal_requested)
                card.delete_requested.connect(self.delete_requested)
                self.row.addWidget(card)
            self.row.addStretch(1)
        count = len(records)
        self.counter.setText(f"{count} vidéo" if count == 1 else f"{count} vidéos")


    def set_directory(self, directory: Path | None) -> None:
        if directory is None:
            self.directory_label.setText("Aucun dossier de destination")
            self.directory_label.setToolTip("")
            return
        resolved = directory.resolve()
        self.directory_label.setText(resolved.name or str(resolved))
        self.directory_label.setToolTip(str(resolved))

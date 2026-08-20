from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFontDatabase,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class _LogEmitter(QObject):
    record_received = Signal(object)


class QtLogHandler(logging.Handler):
    """Thread-safe bridge from stdlib logging to the Qt main thread."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        self.emitter.record_received.emit(record)


class LogWindow(QDialog):
    MAX_RECORDS = 2_500

    def __init__(self, log_file: Path | None = None, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("ArtAnimate — Logs")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(860, 440)
        self.setMinimumSize(640, 300)
        self._records: list[logging.LogRecord] = []
        self._sources: set[str] = set()
        self._allow_close = False
        self._log_file = log_file

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(9)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.level_filter = QComboBox()
        self.level_filter.addItem("Tous les niveaux", logging.NOTSET)
        self.level_filter.addItem("Info et plus", logging.INFO)
        self.level_filter.addItem("Avertissements", logging.WARNING)
        self.level_filter.addItem("Erreurs", logging.ERROR)
        self.source_filter = QComboBox()
        self.source_filter.addItem("Tous les composants", "")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher dans les logs…")
        self.search.setClearButtonEnabled(True)
        self.auto_scroll = QCheckBox("Suivre")
        self.auto_scroll.setChecked(True)
        filters.addWidget(self.level_filter)
        filters.addWidget(self.source_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.auto_scroll)
        layout.addLayout(filters)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setAcceptRichText(False)
        self.output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.output.setStyleSheet(
            "QTextEdit { background:#111827; color:#d8dee9; border:1px solid #293244; "
            "border-radius:8px; padding:8px; }"
        )
        layout.addWidget(self.output, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("0 entrée")
        self.count_label.setObjectName("muted")
        self.open_log_button = QPushButton("Ouvrir le dossier des logs")
        self.open_log_button.setVisible(log_file is not None)
        self.clear_button = QPushButton("Effacer")
        close_button = QPushButton("Fermer")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        footer.addWidget(self.open_log_button)
        footer.addWidget(self.clear_button)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.level_filter.currentIndexChanged.connect(self.refresh)
        self.source_filter.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self.clear_button.clicked.connect(self.clear_records)
        self.open_log_button.clicked.connect(self.open_log_directory)
        close_button.clicked.connect(self.hide)

    def append_record(self, record: logging.LogRecord) -> None:
        self._records.append(record)
        if len(self._records) > self.MAX_RECORDS:
            del self._records[: len(self._records) - self.MAX_RECORDS]
        source = self._short_source(record.name)
        if source not in self._sources:
            self._sources.add(source)
            self.source_filter.addItem(source, source)
        if self._matches(record):
            self._append_rendered(record)
        self._update_count()

    def refresh(self) -> None:
        self.output.clear()
        for record in self._records:
            if self._matches(record):
                self._append_rendered(record, scroll=False)
        if self.auto_scroll.isChecked():
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())
        self._update_count()

    def clear_records(self) -> None:
        self._records.clear()
        self._sources.clear()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem("Tous les composants", "")
        self.source_filter.blockSignals(False)
        self.output.clear()
        self._update_count()

    def open_log_directory(self) -> None:
        if self._log_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_file.parent)))

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            super().closeEvent(event)
        else:
            event.ignore()
            self.hide()

    def _matches(self, record: logging.LogRecord) -> bool:
        minimum = int(self.level_filter.currentData())
        source = str(self.source_filter.currentData())
        query = self.search.text().strip().casefold()
        if record.levelno < minimum:
            return False
        if source and self._short_source(record.name) != source:
            return False
        if query:
            haystack = f"{record.name} {record.levelname} {record.getMessage()}".casefold()
            return query in haystack
        return True

    def _append_rendered(self, record: logging.LogRecord, scroll: bool = True) -> None:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        source = self._short_source(record.name)
        if record.levelno >= logging.ERROR:
            label, color = "ERROR", QColor("#ff7b86")
        elif record.levelno >= logging.WARNING:
            label, color = "WARN ", QColor("#f4c36a")
        else:
            label, color = "INFO ", QColor("#78b7ff")
        message = record.getMessage()
        if record.exc_info:
            formatter = logging.Formatter()
            message += "\n" + formatter.formatException(record.exc_info)
        line = f"{timestamp}  {label}  {source:<22}  {message}\n"
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        text_format = QTextCharFormat()
        text_format.setForeground(color)
        cursor.insertText(line, text_format)
        if scroll and self.auto_scroll.isChecked():
            self.output.setTextCursor(cursor)
            self.output.ensureCursorVisible()

    def _update_count(self) -> None:
        visible = sum(1 for record in self._records if self._matches(record))
        total = len(self._records)
        suffix = "entrée" if total == 1 else "entrées"
        self.count_label.setText(f"{visible} / {total} {suffix}")

    @staticmethod
    def _short_source(name: str) -> str:
        prefix = "artanimate."
        return name[len(prefix) :] if name.startswith(prefix) else name

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from .studio_document import StudioDocumentController


class StudioRecentMenu(QObject):
    """Keeps the local recent-project menu synchronized with QSettings."""

    def __init__(
        self,
        controller: StudioDocumentController,
        menu: QMenu,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.menu = menu
        self.controller.recent_projects_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.menu.clear()
        projects = self.controller.recent_projects()
        if not projects:
            empty = self.menu.addAction("Aucun projet récent")
            empty.setEnabled(False)
            return
        for project_path in projects:
            action = QAction(project_path.name, self.menu)
            action.setToolTip(str(project_path))
            action.triggered.connect(
                lambda _checked=False, selected=Path(project_path):
                self.controller.open_project(selected)
            )
            self.menu.addAction(action)


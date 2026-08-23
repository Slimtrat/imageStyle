from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ..studio.assets import resolve_asset_path, stored_asset_path
from ..studio.model import MediaAsset, StudioProject
from ..studio.persistence import (
    PROJECT_SUFFIX,
    ProjectSession,
    autosave_path,
    discard_recovery,
    find_recovery,
    load_project,
    normalize_project_path,
    save_autosave,
    save_project,
)
from .studio import StudioPanel


logger = logging.getLogger(__name__)
RECENT_PROJECTS_KEY = "studio/recentProjects"
MAX_RECENT_PROJECTS = 10
AUTOSAVE_INTERVAL_MS = 10_000


class StudioDocumentController(QObject):
    """Owns the local Studio document lifecycle independently of the editor UI."""

    artwork_loaded = Signal(object)
    dirty_changed = Signal(bool)
    recent_projects_changed = Signal()

    def __init__(
        self,
        panel: StudioPanel,
        settings: QSettings,
        parent_widget: QWidget,
    ):
        super().__init__(parent_widget)
        self.panel = panel
        self.settings = settings
        self.parent_widget = parent_widget
        self.session: ProjectSession | None = None
        self._suspend_panel_changes = False
        self.panel.project_changed.connect(self._panel_project_changed)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()

    @property
    def project(self) -> StudioProject | None:
        return self.session.project if self.session is not None else None

    @property
    def dirty(self) -> bool:
        return self.session is not None and self.session.dirty

    def _panel_project_changed(self, project: StudioProject | None) -> None:
        if self._suspend_panel_changes:
            return
        if project is None:
            self.session = None
        elif self.session is not None and self.session.project.project_id == project.project_id:
            self.session.update(project)
        else:
            self.session = ProjectSession.new(project)
        self.dirty_changed.emit(self.dirty)

    def adopt_artwork(self, path: Path) -> bool:
        """Initialize Studio from the shared V2 artwork without replacing a project."""

        if self.session is not None:
            return False
        if not self.panel.set_artwork(path):
            raise ValueError(f"L’œuvre ne peut pas être affichée dans le Studio : {path}")
        self.artwork_loaded.emit(path)
        return True

    def choose_artwork(self) -> bool:
        selected, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "Choisir l’œuvre centrale du Studio",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
        )
        return self.new_project(Path(selected)) if selected else False

    def new_project(self, artwork_path: Path | None = None) -> bool:
        if not self.confirm_replace():
            return False
        if artwork_path is None:
            return self.choose_artwork()
        if not self.panel.set_artwork(artwork_path):
            QMessageBox.critical(
                self.parent_widget,
                "Œuvre illisible",
                f"Le Studio ne peut pas ouvrir {artwork_path.name}.",
            )
            return False
        self.artwork_loaded.emit(artwork_path)
        self.dirty_changed.emit(True)
        return True

    def _choose_project_to_open(self) -> Path | None:
        selected, _ = QFileDialog.getOpenFileName(
            self.parent_widget,
            "Ouvrir un projet Studio",
            "",
            f"Projets ArtAnimate (*{PROJECT_SUFFIX})",
        )
        return Path(selected) if selected else None

    def open_project(self, path: str | Path | None = None) -> bool:
        if not self.confirm_replace():
            return False
        source = Path(path) if path is not None else self._choose_project_to_open()
        if source is None:
            return False
        source = normalize_project_path(source)
        try:
            recovery = find_recovery(source)
            if recovery is not None:
                answer = QMessageBox.question(
                    self.parent_widget,
                    "Récupérer le projet Studio ?",
                    "Une sauvegarde automatique plus récente a été trouvée. "
                    "Voulez-vous récupérer cette version ?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    return False
                if answer == QMessageBox.StandardButton.Yes:
                    project = recovery.project
                else:
                    project = load_project(source)
                    discard_recovery(source)
            else:
                project = load_project(source)
            self._install_loaded_project(project, source)
        except Exception as exc:
            logger.exception("Ouverture du projet Studio impossible : %s", source)
            QMessageBox.critical(
                self.parent_widget,
                "Projet Studio impossible à ouvrir",
                str(exc),
            )
            return False
        self._record_recent(source)
        logger.info("Projet Studio ouvert : %s", source)
        return True

    def _install_loaded_project(self, project: StudioProject, path: Path) -> None:
        self._suspend_panel_changes = True
        try:
            self.panel.set_project(project)
            artwork_path = resolve_asset_path(project.artwork.path, path)
            if artwork_path.exists() and self.panel.canvas.set_artwork(artwork_path):
                self.artwork_loaded.emit(artwork_path)
            else:
                self.panel.canvas.set_artwork(None)
                self.panel.project_status.setText(
                    f"Œuvre centrale introuvable · {artwork_path.name} · relink requis"
                )
            self.session = ProjectSession.loaded(project, path)
        finally:
            self._suspend_panel_changes = False
        self.dirty_changed.emit(False)

    def _choose_save_path(self) -> Path | None:
        initial = str(self.session.path) if self.session and self.session.path else ""
        selected, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "Enregistrer le projet Studio",
            initial,
            f"Projets ArtAnimate (*{PROJECT_SUFFIX})",
        )
        return normalize_project_path(selected) if selected else None

    def _rebase_paths(self, project: StudioProject, destination: Path) -> StudioProject:
        previous_path = self.session.path if self.session is not None else None

        def resolved(stored: str) -> Path:
            if previous_path is not None:
                return resolve_asset_path(stored, previous_path)
            return Path(stored).resolve(strict=False)

        artwork = replace(
            project.artwork,
            path=stored_asset_path(resolved(project.artwork.path), destination),
        )
        assets: list[MediaAsset] = []
        for asset in project.assets:
            assets.append(
                replace(
                    asset,
                    path=stored_asset_path(resolved(asset.path), destination),
                )
            )
        return replace(project, artwork=artwork, assets=tuple(assets)).validate()

    def save(self, path: str | Path | None = None, *, save_as: bool = False) -> bool:
        if self.session is None:
            return False
        destination = None if save_as else self.session.path
        if path is not None:
            destination = normalize_project_path(path)
        if destination is None:
            destination = self._choose_save_path()
        if destination is None:
            return False
        try:
            project = self._rebase_paths(self.session.project, destination)
            save_project(project, destination)
            self._suspend_panel_changes = True
            try:
                self.panel.set_project(project)
            finally:
                self._suspend_panel_changes = False
            self.session = ProjectSession.loaded(project, destination)
        except Exception as exc:
            logger.exception("Enregistrement du projet Studio impossible : %s", destination)
            QMessageBox.critical(
                self.parent_widget,
                "Projet Studio impossible à enregistrer",
                str(exc),
            )
            return False
        self._record_recent(destination)
        self.dirty_changed.emit(False)
        logger.info("Projet Studio enregistré : %s", destination)
        return True

    def autosave(self) -> bool:
        if self.session is None or self.session.path is None or not self.session.dirty:
            return False
        try:
            save_autosave(self.session.project, self.session.path)
        except Exception:
            logger.exception("Autosave Studio impossible : %s", self.session.path)
            return False
        logger.debug("Autosave Studio mis à jour : %s", autosave_path(self.session.path))
        return True

    def confirm_replace(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self.parent_widget,
            "Projet Studio modifié",
            "Enregistrer les changements avant de remplacer le projet Studio ?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def close_allowed(self) -> bool:
        return self.confirm_replace()

    def recent_projects(self) -> tuple[Path, ...]:
        raw = self.settings.value(RECENT_PROJECTS_KEY, [], list)
        paths: list[Path] = []
        for value in raw:
            path = Path(str(value))
            if path.exists() and path not in paths:
                paths.append(path)
        return tuple(paths[:MAX_RECENT_PROJECTS])

    def _record_recent(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        paths = [resolved]
        paths.extend(item for item in self.recent_projects() if item != resolved)
        self.settings.setValue(
            RECENT_PROJECTS_KEY,
            [str(item) for item in paths[:MAX_RECENT_PROJECTS]],
        )
        self.recent_projects_changed.emit()

    def shutdown(self) -> None:
        self.autosave_timer.stop()


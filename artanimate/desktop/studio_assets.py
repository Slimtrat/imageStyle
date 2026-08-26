from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..studio.assets import (
    AssetAvailability,
    check_artwork_asset,
    check_media_asset,
)
from ..studio.model import AssetKind, StudioProject


_STATE_LABELS = {
    AssetAvailability.AVAILABLE: "Disponible",
    AssetAvailability.MISSING: "Manquant",
    AssetAvailability.REPLACED: "Modifié sur disque",
    AssetAvailability.INVALID: "Invalide",
}

_STATE_COLORS = {
    AssetAvailability.AVAILABLE: QColor("#72d69a"),
    AssetAvailability.MISSING: QColor("#ff7b72"),
    AssetAvailability.REPLACED: QColor("#f0b44d"),
    AssetAvailability.INVALID: QColor("#ff7b72"),
}

_KIND_LABELS = {
    AssetKind.IMAGE: "Image",
    AssetKind.VIDEO: "Vidéo",
    AssetKind.AUDIO: "Audio",
}


class StudioAssetPanel(QFrame):
    contextChanged = Signal(object, object)
    """Local-reference registry; all operations remain explicit and non-copying."""

    importRequested = Signal()
    relinkRequested = Signal(str)
    folderRelinkRequested = Signal()
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioAssetPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._project: StudioProject | None = None
        self._project_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        title_row = QHBoxLayout()
        title = QLabel("MÉDIAS LOCAUX · RÉFÉRENCES SANS COPIE")
        title.setObjectName("studioAssetTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.refresh_button = QPushButton("Actualiser")
        self.refresh_button.setObjectName("studioAssetRefresh")
        title_row.addWidget(self.refresh_button)
        layout.addLayout(title_row)

        self.tree = QTreeWidget()
        self.tree.setObjectName("studioAssetTree")
        self.tree.setIconSize(QSize(46, 46))
        self.tree.setHeaderLabels(("Média", "Type", "État", "Utilisé", "Emplacement"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree)

        controls = QHBoxLayout()
        self.import_button = QPushButton("Importer une référence…")
        self.import_button.setObjectName("studioAssetImport")
        self.relink_button = QPushButton("Relink sélection…")
        self.relink_button.setObjectName("studioAssetRelink")
        self.folder_button = QPushButton("Rechercher dans un dossier…")
        self.folder_button.setObjectName("studioAssetRelinkFolder")
        controls.addWidget(self.import_button)
        controls.addWidget(self.relink_button)
        controls.addWidget(self.folder_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.feedback = QLabel("Les fichiers restent à leur emplacement d’origine.")
        self.feedback.setObjectName("studioAssetFeedback")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        self.import_button.clicked.connect(self.importRequested)
        self.relink_button.clicked.connect(self._request_selected_relink)
        self.folder_button.clicked.connect(self.folderRelinkRequested)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(
            lambda _item, _column: self._request_selected_relink()
        )
        self._selection_changed()

    @property
    def project_path(self) -> Path | None:
        return self._project_path

    def set_context(
        self,
        project: StudioProject | None,
        project_path: str | Path | None,
    ) -> None:
        self._project = project
        self._project_path = Path(project_path) if project_path is not None else None
        self.tree.clear()
        if project is None or self._project_path is None:
            self.import_button.setEnabled(False)
            self.folder_button.setEnabled(False)
            self._selection_changed()
            self.contextChanged.emit(project, self._project_path)
            return

        reference_counts: dict[str, int] = {}
        for track in project.tracks:
            for clip in track.clips:
                if clip.asset_id is not None:
                    reference_counts[clip.asset_id] = reference_counts.get(clip.asset_id, 0) + 1

        artwork_check = check_artwork_asset(project.artwork, self._project_path)
        self._add_item(
            project.artwork.asset_id,
            f"Œuvre maîtresse · {Path(project.artwork.path).name}",
            "Œuvre",
            artwork_check.state,
            max(1, reference_counts.get(project.artwork.asset_id, 0)),
            artwork_check.resolved_path,
            dimensions=(project.artwork.width, project.artwork.height),
            metadata={"role": "œuvre maîtresse"},
        )
        for asset in project.assets:
            check = check_media_asset(asset, self._project_path)
            self._add_item(
                asset.asset_id,
                Path(asset.path).name,
                _KIND_LABELS[asset.kind],
                check.state,
                reference_counts.get(asset.asset_id, 0),
                check.resolved_path,
                dimensions=(asset.width, asset.height),
                metadata=asset.metadata or {},
            )
        self.import_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self._selection_changed()
        self.contextChanged.emit(project, self._project_path)

    def _add_item(
        self,
        asset_id: str,
        name: str,
        kind: str,
        state: AssetAvailability,
        references: int,
        path: Path,
        *,
        dimensions: tuple[int | None, int | None],
        metadata: dict[str, object],
    ) -> None:
        item = QTreeWidgetItem(
            (name, kind, _STATE_LABELS[state], str(references), str(path))
        )
        item.setData(0, Qt.ItemDataRole.UserRole, asset_id)
        item.setData(2, Qt.ItemDataRole.UserRole, state.value)
        item.setForeground(2, _STATE_COLORS[state])
        item.setToolTip(4, str(path))
        width, height = dimensions
        details = []
        if width is not None and height is not None:
            details.append(f"{width} × {height}")
        profile = metadata.get("color_profile")
        if profile:
            details.append(str(profile))
        image_format = metadata.get("format")
        if image_format:
            details.append(str(image_format))
        item.setToolTip(0, " · ".join(details) if details else name)
        if state == AssetAvailability.AVAILABLE and path.is_file() and kind in {"Image", "Œuvre"}:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            source_size = reader.size()
            if source_size.isValid():
                reader.setScaledSize(
                    source_size.scaled(
                        QSize(46, 46),
                        Qt.AspectRatioMode.KeepAspectRatio,
                    )
                )
            thumbnail = reader.read()
            if not thumbnail.isNull():
                item.setIcon(0, QIcon(QPixmap.fromImage(thumbnail)))
        self.tree.addTopLevelItem(item)

    def selected_asset_id(self) -> str | None:
        selected = self.tree.selectedItems()
        return str(selected[0].data(0, Qt.ItemDataRole.UserRole)) if selected else None

    def set_feedback(self, message: str) -> None:
        self.feedback.setText(message)

    def _selection_changed(self) -> None:
        self.relink_button.setEnabled(self.selected_asset_id() is not None)

    def _request_selected_relink(self) -> None:
        asset_id = self.selected_asset_id()
        if asset_id is not None:
            self.relinkRequested.emit(asset_id)


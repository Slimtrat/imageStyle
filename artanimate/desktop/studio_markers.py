from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..studio.clock import StudioClock
from ..studio.markers import (
    MarkerKind,
    MarkerOrigin,
    TimelineMarker,
    TimelineMarkerState,
    adjacent_marker,
)
from ..studio.model import StudioProject


_KIND_LABELS = {
    MarkerKind.BEAT: "Beat",
    MarkerKind.DOWNBEAT: "Temps fort",
    MarkerKind.DROP: "Drop",
    MarkerKind.CUSTOM: "Personnalisé",
}

_KIND_COLORS = {
    MarkerKind.BEAT: QColor("#69a7ff"),
    MarkerKind.DOWNBEAT: QColor("#b78cff"),
    MarkerKind.DROP: QColor("#ff6f91"),
    MarkerKind.CUSTOM: QColor("#ffd166"),
}


class StudioMarkerPanel(QFrame):
    addRequested = Signal(int, str)
    updateRequested = Signal(str, int, object, str)
    deleteRequested = Signal(str)
    visibilityRequested = Signal(object)
    selectionRequested = Signal(object)
    seekRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioMarkerPanel")
        self._project: StudioProject | None = None
        self._playhead = 0
        self._selected_marker_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("MARQUEURS · REPÈRES DE MONTAGE")
        title.setObjectName("studioMarkerTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Les marqueurs validés appartiennent au projet. Ils restent présents "
            "même si la musique est retirée."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Afficher"))
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("studioMarkerFilter")
        self.filter_combo.addItem("Tous les marqueurs", None)
        for kind in MarkerKind:
            self.filter_combo.addItem(_KIND_LABELS[kind], kind.value)
        self.filter_combo.currentIndexChanged.connect(self._filter_changed)
        filter_row.addWidget(self.filter_combo, 1)
        layout.addLayout(filter_row)

        navigation = QHBoxLayout()
        self.previous_button = QPushButton("◀ Précédent")
        self.previous_button.setObjectName("studioMarkerPrevious")
        self.next_button = QPushButton("Suivant ▶")
        self.next_button.setObjectName("studioMarkerNext")
        self.add_button = QPushButton("+ Au curseur")
        self.add_button.setObjectName("studioMarkerAdd")
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button.clicked.connect(lambda: self._navigate(1))
        self.add_button.clicked.connect(self._add_at_playhead)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.add_button)
        layout.addLayout(navigation)

        self.tree = QTreeWidget()
        self.tree.setObjectName("studioMarkerTree")
        self.tree.setHeaderLabels(("Timecode", "Type", "Libellé"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tree.currentItemChanged.connect(self._tree_selection_changed)
        layout.addWidget(self.tree, 1)

        layout.addWidget(QLabel("Frame du projet"))
        self.frame_spin = QSpinBox()
        self.frame_spin.setObjectName("studioMarkerFrame")
        self.frame_spin.setRange(0, 0)
        layout.addWidget(self.frame_spin)
        layout.addWidget(QLabel("Type"))
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("studioMarkerKind")
        for kind in MarkerKind:
            self.kind_combo.addItem(_KIND_LABELS[kind], kind.value)
        layout.addWidget(self.kind_combo)
        layout.addWidget(QLabel("Libellé"))
        self.label_edit = QLineEdit()
        self.label_edit.setObjectName("studioMarkerLabel")
        self.label_edit.setMaxLength(120)
        layout.addWidget(self.label_edit)

        edit_controls = QHBoxLayout()
        self.apply_button = QPushButton("Appliquer")
        self.apply_button.setObjectName("studioMarkerApply")
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.setObjectName("studioMarkerDelete")
        self.apply_button.clicked.connect(self._apply)
        self.delete_button.clicked.connect(self._delete)
        edit_controls.addWidget(self.apply_button)
        edit_controls.addWidget(self.delete_button)
        edit_controls.addStretch(1)
        layout.addLayout(edit_controls)

        self.status = QLabel("Aucun marqueur dans le projet.")
        self.status.setObjectName("studioMarkerStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._refresh_enabled()

    @property
    def selected_marker_id(self) -> str | None:
        return self._selected_marker_id

    def set_project(self, project: StudioProject | None) -> None:
        selected = self._selected_marker_id
        self._project = project
        self.filter_combo.blockSignals(True)
        if project is None:
            filter_value = None
            self.frame_spin.setRange(0, 0)
        else:
            state = TimelineMarkerState.from_project(project)
            filter_value = (
                state.visible_kind.value
                if state.visible_kind is not None
                else None
            )
            self.frame_spin.setRange(
                0, project.settings.duration_frames - 1
            )
        index = self.filter_combo.findData(filter_value)
        self.filter_combo.setCurrentIndex(max(0, index))
        self.filter_combo.blockSignals(False)
        self._rebuild_tree(selected)

    def set_playhead(self, frame: int) -> None:
        self._playhead = max(0, int(frame))
        if self._selected_marker_id is None:
            self.frame_spin.setValue(self._playhead)

    def set_selection(self, marker_id: str | None) -> None:
        known = {
            marker.marker_id
            for marker in self._visible_markers()
        }
        selected = marker_id if marker_id in known else None
        self._selected_marker_id = selected
        self.tree.blockSignals(True)
        item = self._item_for_marker(selected)
        self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self._load_selected()
        self._refresh_enabled()

    def set_feedback(self, message: str) -> None:
        self.status.setText(message)

    def _state(self) -> TimelineMarkerState:
        if self._project is None:
            return TimelineMarkerState()
        return TimelineMarkerState.from_project(self._project)

    def _visible_markers(self) -> tuple[TimelineMarker, ...]:
        return self._state().visible_markers()

    def _marker(self, marker_id: str | None) -> TimelineMarker | None:
        if marker_id is None:
            return None
        return next(
            (
                marker
                for marker in self._state().markers
                if marker.marker_id == marker_id
            ),
            None,
        )

    def _item_for_marker(
        self, marker_id: str | None
    ) -> QTreeWidgetItem | None:
        if marker_id is None:
            return None
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == marker_id:
                return item
        return None

    def _rebuild_tree(self, selected: str | None) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        clock = (
            StudioClock(self._project.settings.fps)
            if self._project is not None
            else StudioClock()
        )
        for marker in self._visible_markers():
            item = QTreeWidgetItem(
                (
                    clock.format_timecode(marker.frame),
                    _KIND_LABELS[marker.kind],
                    marker.label,
                )
            )
            item.setData(0, Qt.ItemDataRole.UserRole, marker.marker_id)
            item.setForeground(1, _KIND_COLORS[marker.kind])
            if marker.uncertain and not marker.adjusted:
                item.setToolTip(
                    2,
                    "Proposition incertaine · corrigez-la ou appliquez-la pour la valider.",
                )
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)
        self.tree.setCurrentItem(self._item_for_marker(selected))
        self.tree.blockSignals(False)
        self._selected_marker_id = (
            selected if self._item_for_marker(selected) is not None else None
        )
        self._load_selected()
        self._refresh_enabled()

    def _load_selected(self) -> None:
        marker = self._marker(self._selected_marker_id)
        if marker is None:
            self.frame_spin.setValue(self._playhead)
            self.label_edit.setText("Repère")
            index = self.kind_combo.findData(MarkerKind.CUSTOM.value)
            self.kind_combo.setCurrentIndex(index)
            self.status.setText(
                f"{len(self._state().markers)} marqueur(s) dans le projet."
                if self._project is not None
                else "Aucun projet Studio."
            )
            return
        self.frame_spin.setValue(marker.frame)
        index = self.kind_combo.findData(marker.kind.value)
        self.kind_combo.setCurrentIndex(index)
        self.label_edit.setText(marker.label)
        if marker.origin == MarkerOrigin.DETECTED:
            confidence = (
                f" · confiance {marker.confidence * 100:.0f} %"
                if marker.confidence is not None
                else ""
            )
            state = (
                " · à vérifier"
                if marker.uncertain and not marker.adjusted
                else " · validé"
            )
            self.status.setText(f"Détection musicale{confidence}{state}.")
        else:
            self.status.setText("Marqueur personnalisé.")

    def _tree_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        marker_id = (
            current.data(0, Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        self._selected_marker_id = (
            str(marker_id) if marker_id is not None else None
        )
        self._load_selected()
        self._refresh_enabled()
        self.selectionRequested.emit(self._selected_marker_id)

    def _filter_changed(self, _index: int) -> None:
        raw = self.filter_combo.currentData()
        kind = MarkerKind(str(raw)) if raw is not None else None
        self.visibilityRequested.emit(kind)

    def _navigate(self, direction: int) -> None:
        if self._project is None:
            return
        marker = adjacent_marker(self._project, self._playhead, direction)
        if marker is None:
            self.status.setText("Aucun marqueur visible dans ce filtre.")
            return
        self.seekRequested.emit(marker.frame)
        self.selectionRequested.emit(marker.marker_id)

    def _add_at_playhead(self) -> None:
        self.addRequested.emit(self._playhead, "Repère")

    def _apply(self) -> None:
        marker_id = self._selected_marker_id
        raw_kind = self.kind_combo.currentData()
        if marker_id is not None and raw_kind is not None:
            self.updateRequested.emit(
                marker_id,
                self.frame_spin.value(),
                MarkerKind(str(raw_kind)),
                self.label_edit.text(),
            )

    def _delete(self) -> None:
        if self._selected_marker_id is not None:
            self.deleteRequested.emit(self._selected_marker_id)

    def _refresh_enabled(self) -> None:
        has_project = self._project is not None
        has_markers = bool(self._visible_markers())
        has_selection = self._selected_marker_id is not None
        self.filter_combo.setEnabled(has_project)
        self.previous_button.setEnabled(has_project and has_markers)
        self.next_button.setEnabled(has_project and has_markers)
        self.add_button.setEnabled(has_project)
        self.frame_spin.setEnabled(has_selection)
        self.kind_combo.setEnabled(has_selection)
        self.label_edit.setEnabled(has_selection)
        self.apply_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

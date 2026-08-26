from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..studio.clock import StudioClock
from ..studio.events import compile_timeline_triggers
from ..studio.model import StudioProject
from ..studio.semantic import CapabilityInvocation, CapabilityRegistry


TRIGGER_ID_ROLE = Qt.ItemDataRole.UserRole


class StudioTriggerPanel(QFrame):
    """Compact editor for the semantic event graph stored by the project."""

    triggerAddRequested = Signal(str, str, str, int)
    triggerUpdateRequested = Signal(str, int)
    triggerDeleteRequested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        capabilities: CapabilityRegistry,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studioTriggerPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.registry = capabilities
        self._project: StudioProject | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        title = QLabel("DÉCLENCHEURS SÉMANTIQUES")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        explanation = QLabel(
            "Reliez ce qui arrive à l’œuvre à l’action suivante. "
            "Le Studio recalcule les frames pour l’aperçu et l’export."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Quand cette action…"))
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("studioTriggerSource")
        self.source_combo.currentIndexChanged.connect(self._refresh_events)
        layout.addWidget(self.source_combo)

        self.event_combo = QComboBox()
        self.event_combo.setObjectName("studioTriggerEvent")
        layout.addWidget(self.event_combo)

        layout.addWidget(QLabel("…déclencher cette action"))
        self.action_combo = QComboBox()
        self.action_combo.setObjectName("studioTriggerAction")
        layout.addWidget(self.action_combo)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Décalage"))
        self.offset_frames = QSpinBox()
        self.offset_frames.setObjectName("studioTriggerOffsetFrames")
        self.offset_frames.setRange(-100_000, 100_000)
        self.offset_frames.setSuffix(" fr")
        self.offset_frames.valueChanged.connect(self._refresh_offset_label)
        offset_row.addWidget(self.offset_frames)
        self.offset_label = QLabel("+0,000 s")
        self.offset_label.setObjectName("studioTriggerOffsetTime")
        offset_row.addWidget(self.offset_label)
        offset_row.addStretch(1)
        layout.addLayout(offset_row)

        self.add_button = QPushButton("Créer le lien")
        self.add_button.setObjectName("studioTriggerAdd")
        self.add_button.clicked.connect(self._request_add)
        layout.addWidget(self.add_button)

        self.tree = QTreeWidget()
        self.tree.setObjectName("studioTriggerTree")
        self.tree.setAccessibleName("Déclencheurs sémantiques du projet")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("Source", "Événement", "Action", "Décalage"))
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.setMinimumHeight(130)
        layout.addWidget(self.tree)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Appliquer le décalage")
        self.apply_button.setObjectName("studioTriggerApply")
        self.apply_button.clicked.connect(self._request_update)
        self.delete_button = QPushButton("Supprimer le lien")
        self.delete_button.setObjectName("studioTriggerDelete")
        self.delete_button.clicked.connect(self._request_delete)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

        self.status = QLabel("Aucun projet Studio")
        self.status.setObjectName("studioTriggerStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self._refresh_enabled()

    @property
    def selected_trigger_id(self) -> str | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        value = item.data(0, TRIGGER_ID_ROLE)
        return value if isinstance(value, str) else None

    def set_project(self, project: StudioProject | None) -> None:
        selected_id = self.selected_trigger_id
        self._project = project
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.action_combo.clear()
        if project is not None:
            for invocation in project.invocations:
                label = self._invocation_label(invocation)
                self.source_combo.addItem(label, invocation.invocation_id)
                self.action_combo.addItem(label, invocation.invocation_id)
        self.source_combo.blockSignals(False)
        self._refresh_events()
        self._rebuild_tree(selected_id)
        self._refresh_offset_label()
        self._refresh_enabled()
        if project is None:
            self.status.setText("Aucun projet Studio")
            return
        try:
            compilation = compile_timeline_triggers(project, self.registry)
            count = len(compilation.triggers)
            self.status.setText(
                f"Graphe valide · {count} lien(s) · même compilation pour aperçu/export"
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.status.setText(f"Graphe invalide · {exc}")

    def _invocation_label(self, invocation: CapabilityInvocation) -> str:
        try:
            label = self.registry.get(invocation.capability_id).label
        except KeyError:
            label = invocation.capability_id
        target = f" · {invocation.target_id}" if invocation.target_id else ""
        return f"{label}{target} [{invocation.invocation_id}]"

    def _invocation(self, invocation_id: str | None) -> CapabilityInvocation | None:
        if self._project is None or invocation_id is None:
            return None
        return next(
            (
                item for item in self._project.invocations
                if item.invocation_id == invocation_id
            ),
            None,
        )

    def _events_for(self, invocation: CapabilityInvocation) -> tuple[str, ...]:
        try:
            events = list(self.registry.get(invocation.capability_id).emitted_events)
        except KeyError:
            events = ["completed"]
        values = invocation.parameters.to_dict()
        markers = values.get("markers")
        if isinstance(markers, list):
            for index, marker in enumerate(markers):
                if isinstance(marker, dict) and "frame" in marker:
                    events.append(f"marker:{marker.get('id', index)}")
        beats = values.get("beats")
        if isinstance(beats, list):
            events.extend(f"beat:{index}" for index in range(len(beats)))
        return tuple(dict.fromkeys(events))

    def _refresh_events(self) -> None:
        previous = self.event_combo.currentData()
        self.event_combo.clear()
        invocation = self._invocation(self.source_combo.currentData())
        if invocation is not None:
            labels = {
                "completed": "Action terminée",
                "object-exited": "Objet sorti du cadre",
            }
            for event_id in self._events_for(invocation):
                self.event_combo.addItem(labels.get(event_id, event_id), event_id)
        index = self.event_combo.findData(previous)
        if index >= 0:
            self.event_combo.setCurrentIndex(index)
        self._refresh_enabled()

    def _rebuild_tree(self, selected_id: str | None) -> None:
        self.tree.clear()
        if self._project is None:
            return
        labels = {
            item.invocation_id: self._invocation_label(item)
            for item in self._project.invocations
        }
        selected_item: QTreeWidgetItem | None = None
        for trigger in self._project.triggers:
            item = QTreeWidgetItem(
                (
                    labels.get(trigger.source_invocation_id, trigger.source_invocation_id),
                    trigger.event_id,
                    labels.get(trigger.action_invocation_id, trigger.action_invocation_id),
                    f"{trigger.offset_frames:+d} fr",
                )
            )
            item.setData(0, TRIGGER_ID_ROLE, trigger.trigger_id)
            self.tree.addTopLevelItem(item)
            if trigger.trigger_id == selected_id:
                selected_item = item
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(3)
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        trigger_id = (
            current.data(0, TRIGGER_ID_ROLE) if current is not None else None
        )
        if self._project is not None and isinstance(trigger_id, str):
            trigger = next(
                item for item in self._project.triggers
                if item.trigger_id == trigger_id
            )
            for combo, value in (
                (self.source_combo, trigger.source_invocation_id),
                (self.action_combo, trigger.action_invocation_id),
            ):
                index = combo.findData(value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            event_index = self.event_combo.findData(trigger.event_id)
            if event_index >= 0:
                self.event_combo.setCurrentIndex(event_index)
            self.offset_frames.setValue(trigger.offset_frames)
        self._refresh_enabled()

    def _refresh_offset_label(self) -> None:
        fps = self._project.settings.fps if self._project is not None else 30
        clock = StudioClock(fps)
        value = self.offset_frames.value()
        seconds = clock.frame_to_seconds(abs(value))
        sign = "+" if value >= 0 else "−"
        self.offset_label.setText(f"{sign}{seconds:.3f} s · {fps} FPS")

    def _refresh_enabled(self) -> None:
        has_project = self._project is not None
        can_add = (
            has_project
            and self.source_combo.currentData() is not None
            and self.event_combo.currentData() is not None
            and self.action_combo.currentData() is not None
        )
        selected = self.selected_trigger_id is not None
        self.add_button.setEnabled(can_add)
        self.apply_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def _request_add(self) -> None:
        source_id = self.source_combo.currentData()
        event_id = self.event_combo.currentData()
        action_id = self.action_combo.currentData()
        if all(isinstance(item, str) for item in (source_id, event_id, action_id)):
            self.triggerAddRequested.emit(
                source_id,
                event_id,
                action_id,
                self.offset_frames.value(),
            )

    def _request_update(self) -> None:
        trigger_id = self.selected_trigger_id
        if trigger_id is not None:
            self.triggerUpdateRequested.emit(trigger_id, self.offset_frames.value())

    def _request_delete(self) -> None:
        trigger_id = self.selected_trigger_id
        if trigger_id is not None:
            self.triggerDeleteRequested.emit(trigger_id)

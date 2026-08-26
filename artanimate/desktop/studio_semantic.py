from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
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

from ..studio.adapters.classic_2d import build_legacy_capability_registry
from ..studio.model import StudioProject
from ..studio.semantic import (
    AvailabilityStatus,
    CapabilityDecision,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityParameter,
    CapabilityRegistry,
    RendererPolicyMode,
)


OBJECT_ID_ROLE = Qt.ItemDataRole.UserRole
CAPABILITY_ID_ROLE = Qt.ItemDataRole.UserRole
TARGET_ID_ROLE = Qt.ItemDataRole.UserRole + 1
STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
INVOCATION_ID_ROLE = Qt.ItemDataRole.UserRole


_CATEGORY_LABELS = {
    "artwork": "Œuvre",
    "reveal": "Révéler",
    "camera": "Caméra",
    "scene": "Espace & profondeur",
    "object": "Objets",
    "environment": "Atmosphère",
    "media": "Médias réels",
    "audio": "Audio",
}


class StudioSemanticPanel(QFrame):
    """Artwork-first scene browser and capability inspector."""

    targetSelected = Signal(str)
    invocationSelected = Signal(str)
    capabilityRequested = Signal(str, str, object)
    invocationUpdateRequested = Signal(str, object)
    invocationDeleteRequested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        capabilities: CapabilityRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studioSemanticPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.registry = capabilities or build_legacy_capability_registry()
        self._project: StudioProject | None = None
        self._target_id: str | None = None
        self._capability_id: str | None = None
        self._invocation_id: str | None = None
        self.parameter_controls: dict[str, QWidget] = {}
        self._parameter_specs: dict[str, CapabilityParameter] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        title = QLabel("SCÈNE & POSSIBILITÉS")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.empty_state = QLabel(
            "Importez une œuvre : sa scène et ses possibilités apparaîtront ici."
        )
        self.empty_state.setObjectName("studioSemanticEmptyState")
        self.empty_state.setWordWrap(True)
        layout.addWidget(self.empty_state)

        self.scene_tree = QTreeWidget()
        self.scene_tree.setObjectName("studioSceneTree")
        self.scene_tree.setAccessibleName("Arbre de la scène de l’œuvre")
        self.scene_tree.setHeaderHidden(True)
        self.scene_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.scene_tree.setMinimumHeight(110)
        self.scene_tree.currentItemChanged.connect(self._scene_item_changed)
        layout.addWidget(self.scene_tree)

        capability_label = QLabel("CE QUE VOUS POUVEZ FAIRE")
        capability_label.setObjectName("sectionTitle")
        layout.addWidget(capability_label)
        self.capability_tree = QTreeWidget()
        self.capability_tree.setObjectName("studioCapabilityTree")
        self.capability_tree.setAccessibleName(
            "Actions compatibles avec la sélection de scène"
        )
        self.capability_tree.setColumnCount(2)
        self.capability_tree.setHeaderLabels(("Action", "État"))
        self.capability_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection
        )
        self.capability_tree.setMinimumHeight(155)
        self.capability_tree.currentItemChanged.connect(
            self._capability_item_changed
        )
        layout.addWidget(self.capability_tree)

        self.explanation = QLabel("Sélectionnez une action pour comprendre ses besoins.")
        self.explanation.setObjectName("studioCapabilityExplanation")
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)

        self.renderer_status = QLabel("Renderer · aucun")
        self.renderer_status.setObjectName("studioRendererStatus")
        self.renderer_status.setWordWrap(True)
        layout.addWidget(self.renderer_status)

        self.properties_host = QWidget()
        self.properties_form = QFormLayout(self.properties_host)
        self.properties_form.setContentsMargins(0, 0, 0, 0)
        self.properties_form.setVerticalSpacing(5)
        layout.addWidget(self.properties_host)

        action_row = QHBoxLayout()
        self.add_button = QPushButton("Ajouter à la mise en scène")
        self.add_button.setObjectName("studioAddCapabilityButton")
        self.add_button.clicked.connect(self._request_capability)
        self.apply_button = QPushButton("Appliquer")
        self.apply_button.setObjectName("studioApplyInvocationButton")
        self.apply_button.clicked.connect(self._request_update)
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.apply_button)
        layout.addLayout(action_row)

        invocation_label = QLabel("MISE EN SCÈNE")
        invocation_label.setObjectName("sectionTitle")
        layout.addWidget(invocation_label)
        self.invocation_tree = QTreeWidget()
        self.invocation_tree.setObjectName("studioInvocationTree")
        self.invocation_tree.setAccessibleName("Actions présentes dans la timeline")
        self.invocation_tree.setColumnCount(2)
        self.invocation_tree.setHeaderLabels(("Action", "Cible"))
        self.invocation_tree.setMinimumHeight(100)
        self.invocation_tree.currentItemChanged.connect(
            self._invocation_item_changed
        )
        layout.addWidget(self.invocation_tree)
        self.delete_button = QPushButton("Retirer l’action")
        self.delete_button.setObjectName("studioDeleteInvocationButton")
        self.delete_button.clicked.connect(self._request_delete)
        layout.addWidget(self.delete_button)
        self._update_actions()

    @property
    def project(self) -> StudioProject | None:
        return self._project

    @property
    def selected_target_id(self) -> str | None:
        return self._target_id

    @property
    def selected_capability_id(self) -> str | None:
        return self._capability_id

    @property
    def selected_invocation_id(self) -> str | None:
        return self._invocation_id

    def scene_item(self, object_id: str) -> QTreeWidgetItem | None:
        iterator = self.scene_tree.findItems(
            "*",
            Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive,
        )
        return next(
            (item for item in iterator if item.data(0, OBJECT_ID_ROLE) == object_id),
            None,
        )

    def capability_item(self, capability_id: str) -> QTreeWidgetItem | None:
        iterator = self.capability_tree.findItems(
            "*",
            Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive,
        )
        return next(
            (
                item
                for item in iterator
                if item.data(0, CAPABILITY_ID_ROLE) == capability_id
            ),
            None,
        )

    def invocation_item(self, invocation_id: str) -> QTreeWidgetItem | None:
        iterator = self.invocation_tree.findItems(
            "*",
            Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive,
        )
        return next(
            (
                item
                for item in iterator
                if item.data(0, INVOCATION_ID_ROLE) == invocation_id
            ),
            None,
        )

    def set_project(self, project: StudioProject | None) -> None:
        previous_target = self._target_id
        previous_invocation = self._invocation_id
        self._project = project.validate() if project is not None else None
        self.scene_tree.clear()
        self.capability_tree.clear()
        self.invocation_tree.clear()
        self._target_id = None
        self._capability_id = None
        self._invocation_id = None
        self._clear_properties()
        if self._project is None or self._project.scene is None:
            self.empty_state.show()
            self.explanation.setText("Aucune scène disponible.")
            self.renderer_status.setText("Renderer · aucun")
            self._update_actions()
            return

        self.empty_state.hide()
        scene = self._project.scene
        artwork_root: QTreeWidgetItem | None = None
        for scene_object in scene.objects:
            label = scene_object.label
            if scene_object.confidence < 1.0:
                label += f" · {scene_object.confidence:.0%}"
            item = QTreeWidgetItem((label,))
            item.setData(0, OBJECT_ID_ROLE, scene_object.object_id)
            item.setToolTip(0, scene_object.semantic_type)
            if scene_object.semantic_type == "artwork":
                self.scene_tree.addTopLevelItem(item)
                artwork_root = item
            elif scene_object.semantic_type not in {
                "scene.background",
                "scene.camera",
            } and artwork_root is not None:
                artwork_root.addChild(item)
            else:
                self.scene_tree.addTopLevelItem(item)
        self.scene_tree.expandAll()
        self._populate_invocations()
        self.select_target(
            previous_target
            if previous_target is not None and scene.object_by_id(previous_target)
            else "artwork"
        )
        if previous_invocation and self.invocation_item(previous_invocation):
            self.select_invocation(previous_invocation)

    def select_target(self, object_id: str) -> bool:
        item = self.scene_item(object_id)
        if item is None:
            return False
        self.scene_tree.setCurrentItem(item)
        return True

    def select_invocation(self, invocation_id: str) -> bool:
        item = self.invocation_item(invocation_id)
        if item is None:
            return False
        self.invocation_tree.setCurrentItem(item)
        return True

    def _scene_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        object_id = current.data(0, OBJECT_ID_ROLE) if current is not None else None
        self._target_id = str(object_id) if object_id else None
        self._invocation_id = None
        self._populate_capabilities()
        self._update_actions()
        if self._target_id is not None:
            self.targetSelected.emit(self._target_id)

    def _effective_target(self, descriptor: CapabilityDescriptor) -> str | None:
        if self._project is None or self._project.scene is None:
            return None
        if descriptor.category == "camera":
            return "camera" if self._project.scene.object_by_id("camera") else None
        if descriptor.category in {"media", "audio"}:
            return None
        return self._target_id

    def _populate_capabilities(self) -> None:
        self.capability_tree.clear()
        self._capability_id = None
        self._clear_properties()
        project = self._project
        if project is None or project.scene is None:
            return
        groups: dict[str, QTreeWidgetItem] = {}
        first_available: QTreeWidgetItem | None = None
        for descriptor in self.registry.descriptors():
            target_id = self._effective_target(descriptor)
            decision = self.registry.evaluate(
                descriptor.capability_id,
                project.scene,
                target_id,
            )
            group = groups.get(descriptor.category)
            if group is None:
                group = QTreeWidgetItem(
                    (_CATEGORY_LABELS.get(descriptor.category, descriptor.category), "")
                )
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.capability_tree.addTopLevelItem(group)
                groups[descriptor.category] = group
            status_label = {
                AvailabilityStatus.AVAILABLE: "Disponible",
                AvailabilityStatus.ANALYSIS_REQUIRED: "Analyse requise",
                AvailabilityStatus.UNAVAILABLE: "Indisponible",
            }[decision.status]
            item = QTreeWidgetItem((descriptor.label, status_label))
            item.setData(0, CAPABILITY_ID_ROLE, descriptor.capability_id)
            item.setData(0, TARGET_ID_ROLE, target_id or "")
            item.setData(0, STATUS_ROLE, decision.status.value)
            item.setToolTip(0, descriptor.description or descriptor.capability_id)
            group.addChild(item)
            if decision.available and first_available is None:
                first_available = item
        self.capability_tree.expandAll()
        if first_available is not None:
            self.capability_tree.setCurrentItem(first_available)
        else:
            self.explanation.setText(
                "Aucune action n’est encore compatible avec cette sélection."
            )

    def _decision_for_item(
        self,
        item: QTreeWidgetItem,
    ) -> tuple[CapabilityDescriptor, CapabilityDecision] | None:
        project = self._project
        capability_id = item.data(0, CAPABILITY_ID_ROLE)
        if not capability_id or project is None or project.scene is None:
            return None
        descriptor = self.registry.get(str(capability_id))
        raw_target = item.data(0, TARGET_ID_ROLE)
        target_id = str(raw_target) if raw_target else None
        return descriptor, self.registry.evaluate(
            descriptor.capability_id,
            project.scene,
            target_id,
        )

    def _capability_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        resolved = self._decision_for_item(current) if current is not None else None
        if resolved is None:
            self._capability_id = None
            self._clear_properties()
            self._update_actions()
            return
        descriptor, decision = resolved
        self._capability_id = descriptor.capability_id
        self._invocation_id = None
        if decision.available:
            self.explanation.setText(
                descriptor.description or "Cette action est disponible immédiatement."
            )
        else:
            self.explanation.setText("\n".join(decision.reasons))
        candidates = descriptor.renderer_candidates
        self.renderer_status.setText(
            "Renderer · automatique"
            + (" · " + " → ".join(candidates) if candidates else "")
        )
        self._build_properties(descriptor, {})
        self._update_actions(decision)

    def _populate_invocations(self) -> None:
        self.invocation_tree.clear()
        project = self._project
        if project is None or project.scene is None:
            return
        for invocation in project.invocations:
            try:
                label = self.registry.get(invocation.capability_id).label
            except KeyError:
                label = invocation.capability_id
            target = project.scene.object_by_id(invocation.target_id or "")
            target_label = target.label if target is not None else "Scène"
            item = QTreeWidgetItem((label, target_label))
            item.setData(0, INVOCATION_ID_ROLE, invocation.invocation_id)
            item.setToolTip(0, invocation.capability_id)
            self.invocation_tree.addTopLevelItem(item)

    def _invocation_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        invocation_id = (
            current.data(0, INVOCATION_ID_ROLE) if current is not None else None
        )
        project = self._project
        if not invocation_id or project is None:
            self._invocation_id = None
            self._update_actions()
            return
        invocation = next(
            item
            for item in project.invocations
            if item.invocation_id == invocation_id
        )
        self._invocation_id = invocation.invocation_id
        self._capability_id = invocation.capability_id
        if invocation.target_id is not None:
            self.select_target(invocation.target_id)
            self._invocation_id = invocation.invocation_id
            self._capability_id = invocation.capability_id
        try:
            descriptor = self.registry.get(invocation.capability_id)
        except KeyError:
            self._clear_properties()
            self.explanation.setText(
                "Cette action est conservée, mais sa capability n’est pas installée."
            )
        else:
            self._build_properties(descriptor, invocation.parameters.to_dict())
            self.explanation.setText(descriptor.description or descriptor.label)
        policy = invocation.renderer_policy
        if policy.mode == RendererPolicyMode.AUTOMATIC:
            renderer = "automatique"
        else:
            renderer = policy.mode.value + " · " + " → ".join(policy.renderer_ids)
        self.renderer_status.setText("Renderer · " + renderer)
        self._update_actions()
        self.invocationSelected.emit(invocation.invocation_id)

    def _clear_properties(self) -> None:
        while self.properties_form.rowCount():
            self.properties_form.removeRow(0)
        self.parameter_controls.clear()
        self._parameter_specs.clear()

    def _build_properties(
        self,
        descriptor: CapabilityDescriptor,
        values: dict[str, Any],
    ) -> None:
        self._clear_properties()
        for spec in descriptor.parameters:
            initial = values.get(spec.parameter_id)
            if initial is None and spec.has_default:
                initial = spec.to_dict()["default"]
            control = self._parameter_control(spec, initial)
            control.setObjectName(f"studioCapabilityParameter_{spec.parameter_id}")
            control.setToolTip(spec.description)
            self.properties_form.addRow(spec.label, control)
            self.parameter_controls[spec.parameter_id] = control
            self._parameter_specs[spec.parameter_id] = spec
        if not descriptor.parameters:
            self.properties_form.addRow(QLabel("Aucun réglage nécessaire."))

    @staticmethod
    def _parameter_control(
        spec: CapabilityParameter,
        value: Any,
    ) -> QWidget:
        if spec.value_type == "boolean":
            control = QCheckBox()
            control.setChecked(bool(value))
            return control
        if spec.value_type == "integer":
            control = QSpinBox()
            control.setRange(
                int(spec.minimum if spec.minimum is not None else -1_000_000),
                int(spec.maximum if spec.maximum is not None else 1_000_000),
            )
            control.setValue(int(value or 0))
            return control
        if spec.value_type == "number":
            control = QDoubleSpinBox()
            control.setDecimals(4)
            control.setRange(
                float(spec.minimum if spec.minimum is not None else -1_000_000),
                float(spec.maximum if spec.maximum is not None else 1_000_000),
            )
            control.setValue(float(value or 0.0))
            return control
        if spec.value_type in {"choice", "direction"}:
            control = QComboBox()
            for choice in spec.to_dict()["choices"]:
                control.addItem(str(choice), choice)
            index = control.findData(value)
            control.setCurrentIndex(max(0, index))
            return control
        control = QLineEdit()
        if spec.value_type in {"any", "point"}:
            control.setText(json.dumps(value if value is not None else {}))
        else:
            control.setText("" if value is None else str(value))
        return control

    def parameter_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for parameter_id, control in self.parameter_controls.items():
            spec = self._parameter_specs[parameter_id]
            if isinstance(control, QCheckBox):
                value: Any = control.isChecked()
            elif isinstance(control, QSpinBox):
                value = control.value()
            elif isinstance(control, QDoubleSpinBox):
                value = control.value()
            elif isinstance(control, QComboBox):
                value = control.currentData()
            elif isinstance(control, QLineEdit):
                text = control.text()
                value = json.loads(text) if spec.value_type in {"any", "point"} else text
            else:
                continue
            values[parameter_id] = value
        return values

    def _update_actions(
        self,
        decision: CapabilityDecision | None = None,
    ) -> None:
        if decision is None and self._project is not None and self._capability_id:
            try:
                descriptor = self.registry.get(self._capability_id)
                target = self._effective_target(descriptor)
                decision = self.registry.evaluate(
                    descriptor.capability_id,
                    self._project.scene,
                    target,
                )
            except (KeyError, ValueError):
                decision = None
        self.add_button.setEnabled(
            self._invocation_id is None
            and decision is not None
            and decision.available
        )
        self.apply_button.setEnabled(self._invocation_id is not None)
        self.delete_button.setEnabled(self._invocation_id is not None)

    def _request_capability(self) -> None:
        if self._capability_id is None:
            return
        descriptor = self.registry.get(self._capability_id)
        target_id = self._effective_target(descriptor) or ""
        try:
            values = self.parameter_values()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.explanation.setText(f"Réglage invalide · {exc}")
            return
        self.capabilityRequested.emit(self._capability_id, target_id, values)

    def _request_update(self) -> None:
        if self._invocation_id is None:
            return
        try:
            values = self.parameter_values()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.explanation.setText(f"Réglage invalide · {exc}")
            return
        self.invocationUpdateRequested.emit(self._invocation_id, values)

    def _request_delete(self) -> None:
        if self._invocation_id is not None:
            self.invocationDeleteRequested.emit(self._invocation_id)

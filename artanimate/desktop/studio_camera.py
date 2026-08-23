from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..studio.model import CameraPose, Easing


class StudioCameraInspector(QWidget):
    poseChanged = Signal(object)
    easingChanged = Signal(object)
    addKeyframeRequested = Signal()
    removeKeyframeRequested = Signal()
    copyKeyframeRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioCameraInspector")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("CAMÉRA DE L’ŒUVRE")
        title.setObjectName("studioCameraTitle")
        layout.addWidget(title)

        form = QFormLayout()
        self.x = self._spin("studioCameraX", -1.0, 2.0, 0.5, 0.01, 3)
        self.y = self._spin("studioCameraY", -1.0, 2.0, 0.5, 0.01, 3)
        self.zoom = self._spin("studioCameraZoom", 0.25, 20.0, 1.0, 0.05, 2)
        self.rotation = self._spin("studioCameraRotation", -180.0, 180.0, 0.0, 0.25, 2)
        self.perspective = self._spin("studioCameraPerspective", 0.0, 1.0, 0.0, 0.01, 2)
        self.focus = self._spin("studioCameraFocus", 0.0, 1.0, 1.0, 0.01, 2)
        self.easing = QComboBox()
        self.easing.setObjectName("studioCameraEasing")
        self.easing.addItem("Linéaire", Easing.LINEAR)
        self.easing.addItem("Accélération", Easing.EASE_IN)
        self.easing.addItem("Décélération", Easing.EASE_OUT)
        self.easing.addItem("Doux entrée / sortie", Easing.EASE_IN_OUT)
        form.addRow("Cible X", self.x)
        form.addRow("Cible Y", self.y)
        form.addRow("Zoom", self.zoom)
        form.addRow("Rotation", self.rotation)
        form.addRow("Perspective", self.perspective)
        form.addRow("Focus", self.focus)
        form.addRow("Easing sortant", self.easing)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.reset_button = QPushButton("Cadrage entier")
        self.reset_button.setObjectName("studioCameraReset")
        self.add_keyframe_button = QPushButton("Ajouter keyframe")
        self.add_keyframe_button.setObjectName("studioCameraAddKeyframe")
        self.copy_keyframe_button = QPushButton("Dupliquer +1")
        self.copy_keyframe_button.setObjectName("studioCameraCopyKeyframe")
        self.remove_keyframe_button = QPushButton("Retirer")
        self.remove_keyframe_button.setObjectName("studioCameraRemoveKeyframe")
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.add_keyframe_button)
        buttons.addWidget(self.copy_keyframe_button)
        buttons.addWidget(self.remove_keyframe_button)
        layout.addLayout(buttons)

        for control in self.controls:
            control.valueChanged.connect(self._emit_pose)
        self.easing.currentIndexChanged.connect(
            lambda: self.easingChanged.emit(Easing(self.easing.currentData()))
        )
        self.reset_button.clicked.connect(lambda: self.set_pose(CameraPose(), emit=True))
        self.add_keyframe_button.clicked.connect(self.addKeyframeRequested)
        self.copy_keyframe_button.clicked.connect(self.copyKeyframeRequested)
        self.remove_keyframe_button.clicked.connect(self.removeKeyframeRequested)
        self.set_keyframe_state(False)

    @property
    def controls(self) -> tuple[QDoubleSpinBox, ...]:
        return (self.x, self.y, self.zoom, self.rotation, self.perspective, self.focus)

    def _spin(
        self,
        name: str,
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        decimals: int,
    ) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        control.setDecimals(decimals)
        control.setValue(value)
        control.setKeyboardTracking(False)
        return control

    def pose(self) -> CameraPose:
        return CameraPose(
            x=self.x.value(),
            y=self.y.value(),
            zoom=self.zoom.value(),
            rotation_degrees=self.rotation.value(),
            perspective=self.perspective.value(),
            focus=self.focus.value(),
        ).validate()

    def set_pose(self, pose: CameraPose, *, emit: bool = False) -> None:
        pose.validate()
        values = (
            pose.x,
            pose.y,
            pose.zoom,
            pose.rotation_degrees,
            pose.perspective,
            pose.focus,
        )
        blockers = [QSignalBlocker(control) for control in self.controls]
        for control, value in zip(self.controls, values):
            control.setValue(value)
        del blockers
        if emit:
            self.poseChanged.emit(self.pose())

    def set_easing(self, easing: Easing) -> None:
        index = self.easing.findData(easing)
        if index < 0:
            raise ValueError(f"Easing caméra inconnu : {easing}")
        blocker = QSignalBlocker(self.easing)
        self.easing.setCurrentIndex(index)
        del blocker

    def set_keyframe_state(self, exists: bool) -> None:
        self.remove_keyframe_button.setEnabled(exists)
        self.copy_keyframe_button.setEnabled(exists)
        self.easing.setEnabled(exists)
        self.add_keyframe_button.setText(
            "Mettre à jour" if exists else "Ajouter keyframe"
        )

    def _emit_pose(self) -> None:
        self.poseChanged.emit(self.pose())


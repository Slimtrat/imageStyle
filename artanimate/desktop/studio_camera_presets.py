from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..studio.camera_presets import CameraPreset, PresetApplyMode


class StudioCameraPresetPanel(QWidget):
    presetRequested = Signal(object, float, int, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioCameraPresetPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        title = QLabel("MOUVEMENTS DE MISE EN SCÈNE")
        title.setObjectName("studioCameraPresetTitle")
        layout.addWidget(title)

        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.setObjectName("studioCameraPreset")
        self.preset.addItem("Macro · entrer dans la matière", CameraPreset.MACRO)
        self.preset.addItem("Inspect · parcourir les détails", CameraPreset.INSPECT)
        self.preset.addItem("Reveal · révéler l’œuvre entière", CameraPreset.REVEAL)
        self.preset.addItem("Drift · dérive lente", CameraPreset.DRIFT)
        self.preset.addItem("Handheld · présence organique", CameraPreset.HANDHELD)
        self.intensity = QDoubleSpinBox()
        self.intensity.setObjectName("studioCameraPresetIntensity")
        self.intensity.setRange(0.0, 1.0)
        self.intensity.setSingleStep(0.05)
        self.intensity.setDecimals(2)
        self.intensity.setValue(0.5)
        self.duration = QSpinBox()
        self.duration.setObjectName("studioCameraPresetDuration")
        self.duration.setRange(2, 360)
        self.duration.setValue(90)
        self.mode = QComboBox()
        self.mode.setObjectName("studioCameraPresetMode")
        self.mode.addItem("Remplacer dans la plage", PresetApplyMode.REPLACE)
        self.mode.addItem("Insérer parmi les clés", PresetApplyMode.INSERT)
        form.addRow("Mouvement", self.preset)
        form.addRow("Intensité", self.intensity)
        form.addRow("Durée (frames)", self.duration)
        form.addRow("Application", self.mode)
        layout.addLayout(form)

        self.apply_button = QPushButton("Générer les keyframes")
        self.apply_button.setObjectName("studioCameraPresetApply")
        self.apply_button.clicked.connect(self._request)
        layout.addWidget(self.apply_button)

    def set_remaining_frames(self, frames: int, *, fps: int) -> None:
        maximum = max(1, int(frames))
        self.apply_button.setEnabled(maximum >= 2)
        self.duration.setEnabled(maximum >= 2)
        if maximum >= 2:
            self.duration.setRange(2, maximum)
            suggested = min(maximum, max(2, int(fps) * 3))
            if self.duration.value() > maximum:
                self.duration.setValue(suggested)

    def _request(self) -> None:
        self.presetRequested.emit(
            CameraPreset(self.preset.currentData()),
            self.intensity.value(),
            self.duration.value(),
            PresetApplyMode(self.mode.currentData()),
        )


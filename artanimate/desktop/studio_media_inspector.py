from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..studio.media import StillClipSettings
from ..studio.model import ClipKind, FitMode, StudioProject


@dataclass(frozen=True, slots=True)
class StillInspectorEdit:
    clip_id: str
    duration_frames: int
    fit: FitMode
    opacity: float
    enabled: bool
    settings: StillClipSettings


class StudioMediaInspector(QFrame):
    applyRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioMediaInspector")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._selected_clip_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = QLabel("PLAN RÉEL · IMAGE FIXE")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.status = QLabel("Sélectionnez une image réelle dans la timeline")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.fit = QComboBox()
        self.fit.setObjectName("studioStillFit")
        self.fit.addItem("Remplir · crop", FitMode.COVER)
        self.fit.addItem("Contenir", FitMode.CONTAIN)
        self.fit.addItem("Étirer", FitMode.STRETCH)
        self.duration = QSpinBox()
        self.duration.setObjectName("studioStillDuration")
        self.duration.setRange(1, 2_147_483_647)
        self.duration.setSuffix(" fr")
        self.opacity = QDoubleSpinBox()
        self.opacity.setObjectName("studioStillOpacity")
        self.opacity.setRange(0.0, 100.0)
        self.opacity.setDecimals(1)
        self.opacity.setSuffix(" %")
        self.rotation = QDoubleSpinBox()
        self.rotation.setObjectName("studioStillRotation")
        self.rotation.setRange(-3600.0, 3600.0)
        self.rotation.setDecimals(1)
        self.rotation.setSuffix("°")
        self.crop_x = self._crop_control("studioStillCropX")
        self.crop_y = self._crop_control("studioStillCropY")
        self.crop_width = self._crop_control("studioStillCropWidth")
        self.crop_height = self._crop_control("studioStillCropHeight")
        self.enabled = QCheckBox("Plan visible")
        self.enabled.setObjectName("studioStillEnabled")
        form.addRow("Cadrage", self.fit)
        form.addRow("Durée", self.duration)
        form.addRow("Opacité", self.opacity)
        form.addRow("Rotation", self.rotation)
        form.addRow("Crop X", self.crop_x)
        form.addRow("Crop Y", self.crop_y)
        form.addRow("Largeur crop", self.crop_width)
        form.addRow("Hauteur crop", self.crop_height)
        form.addRow(self.enabled)
        layout.addLayout(form)

        self.apply_button = QPushButton("Appliquer au plan réel")
        self.apply_button.setObjectName("studioStillApply")
        self.apply_button.clicked.connect(self._request_apply)
        layout.addWidget(self.apply_button)
        layout.addStretch(1)
        self._set_enabled(False)

    @staticmethod
    def _crop_control(name: str) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setRange(0.0, 100.0)
        control.setDecimals(1)
        control.setSingleStep(1.0)
        control.setSuffix(" %")
        return control

    @property
    def selected_clip_id(self) -> str | None:
        return self._selected_clip_id

    def _set_enabled(self, enabled: bool) -> None:
        for control in (
            self.fit,
            self.duration,
            self.opacity,
            self.rotation,
            self.crop_x,
            self.crop_y,
            self.crop_width,
            self.crop_height,
            self.enabled,
            self.apply_button,
        ):
            control.setEnabled(enabled)

    def set_selection(self, project: StudioProject | None, clip_ids: tuple[str, ...]) -> None:
        resolved = next(
            (
                (track, clip)
                for track in project.tracks
                for clip in track.clips
                if clip.kind == ClipKind.STILL and clip.clip_id in clip_ids
            ),
            None,
        ) if project is not None else None
        if resolved is None:
            self._selected_clip_id = None
            self.status.setText("Sélectionnez une image réelle dans la timeline")
            self._set_enabled(False)
            return
        track, clip = resolved
        settings = StillClipSettings.from_clip(clip)
        self._selected_clip_id = clip.clip_id
        self.duration.setMaximum(project.settings.duration_frames - clip.start_frame)
        self.duration.setValue(clip.duration_frames)
        self.fit.setCurrentIndex(max(0, self.fit.findData(clip.fit)))
        self.opacity.setValue(clip.opacity * 100.0)
        self.rotation.setValue(settings.rotation_degrees)
        self.crop_x.setValue(settings.crop_x * 100.0)
        self.crop_y.setValue(settings.crop_y * 100.0)
        self.crop_width.setValue(settings.crop_width * 100.0)
        self.crop_height.setValue(settings.crop_height * 100.0)
        self.enabled.setChecked(clip.enabled)
        asset = next((item for item in project.assets if item.asset_id == clip.asset_id), None)
        dimensions = f"{asset.width} × {asset.height}" if asset and asset.width and asset.height else "dimensions inconnues"
        self.status.setText(f"{track.name} · {dimensions} · {clip.duration_frames} frames")
        self._set_enabled(not track.locked)

    def _request_apply(self) -> None:
        if self._selected_clip_id is None:
            return
        settings = StillClipSettings(
            crop_x=self.crop_x.value() / 100.0,
            crop_y=self.crop_y.value() / 100.0,
            crop_width=self.crop_width.value() / 100.0,
            crop_height=self.crop_height.value() / 100.0,
            rotation_degrees=self.rotation.value(),
        )
        self.applyRequested.emit(
            StillInspectorEdit(
                self._selected_clip_id,
                self.duration.value(),
                FitMode(self.fit.currentData()),
                self.opacity.value() / 100.0,
                self.enabled.isChecked(),
                settings,
            )
        )

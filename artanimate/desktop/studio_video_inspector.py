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
from ..studio.video import (
    NativeAudioMode,
    VideoClipSettings,
    video_source_frame_count,
)


@dataclass(frozen=True, slots=True)
class VideoInspectorEdit:
    clip_id: str
    source_in_frame: int
    duration_frames: int
    fit: FitMode
    opacity: float
    enabled: bool
    settings: VideoClipSettings


class StudioVideoInspector(QFrame):
    """Non-destructive project-frame editor for one local real-video clip."""

    applyRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioVideoInspector")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._selected_clip_id: str | None = None
        self._source_frame_count = 1
        self._project_duration_limit = 1
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = QLabel("PLAN RÉEL · VIDÉO LOCALE")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.status = QLabel("Sélectionnez une vidéo réelle dans la timeline")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.source_in = QSpinBox()
        self.source_in.setObjectName("studioVideoSourceIn")
        self.source_in.setRange(0, 2_147_483_647)
        self.source_in.setSuffix(" fr")
        self.duration = QSpinBox()
        self.duration.setObjectName("studioVideoDuration")
        self.duration.setRange(1, 2_147_483_647)
        self.duration.setSuffix(" fr")
        self.fit = QComboBox()
        self.fit.setObjectName("studioVideoFit")
        self.fit.addItem("Remplir · crop", FitMode.COVER)
        self.fit.addItem("Contenir", FitMode.CONTAIN)
        self.fit.addItem("Étirer", FitMode.STRETCH)
        self.opacity = QDoubleSpinBox()
        self.opacity.setObjectName("studioVideoOpacity")
        self.opacity.setRange(0.0, 100.0)
        self.opacity.setDecimals(1)
        self.opacity.setSuffix(" %")
        self.rotation = QDoubleSpinBox()
        self.rotation.setObjectName("studioVideoRotation")
        self.rotation.setRange(-3600.0, 3600.0)
        self.rotation.setDecimals(1)
        self.rotation.setSuffix("°")
        self.crop_x = self._crop_control("studioVideoCropX")
        self.crop_y = self._crop_control("studioVideoCropY")
        self.crop_width = self._crop_control("studioVideoCropWidth")
        self.crop_height = self._crop_control("studioVideoCropHeight")
        self.native_audio = QComboBox()
        self.native_audio.setObjectName("studioVideoNativeAudio")
        self.native_audio.addItem("Ignorer l’audio natif", NativeAudioMode.IGNORE)
        self.native_audio.addItem("Conserver comme référence", NativeAudioMode.REFERENCE)
        self.enabled = QCheckBox("Plan visible")
        self.enabled.setObjectName("studioVideoEnabled")
        form.addRow("Source In", self.source_in)
        form.addRow("Durée", self.duration)
        form.addRow("Cadrage", self.fit)
        form.addRow("Opacité", self.opacity)
        form.addRow("Rotation", self.rotation)
        form.addRow("Crop X", self.crop_x)
        form.addRow("Crop Y", self.crop_y)
        form.addRow("Largeur crop", self.crop_width)
        form.addRow("Hauteur crop", self.crop_height)
        form.addRow("Audio vidéo", self.native_audio)
        form.addRow(self.enabled)
        layout.addLayout(form)

        self.apply_button = QPushButton("Appliquer au plan vidéo")
        self.apply_button.setObjectName("studioVideoApply")
        self.apply_button.clicked.connect(self._request_apply)
        self.source_in.valueChanged.connect(self._sync_ranges)
        layout.addWidget(self.apply_button)
        layout.addStretch(1)
        self._set_enabled(False)

    @staticmethod
    def _crop_control(name: str) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setRange(0.0, 100.0)
        control.setDecimals(1)
        control.setSuffix(" %")
        return control

    @property
    def selected_clip_id(self) -> str | None:
        return self._selected_clip_id

    def _set_enabled(self, enabled: bool) -> None:
        for control in (
            self.source_in,
            self.duration,
            self.fit,
            self.opacity,
            self.rotation,
            self.crop_x,
            self.crop_y,
            self.crop_width,
            self.crop_height,
            self.native_audio,
            self.enabled,
            self.apply_button,
        ):
            control.setEnabled(enabled)

    def _sync_ranges(self, _value: int | None = None) -> None:
        if self._updating:
            return
        self.duration.setMaximum(
            max(
                1,
                min(
                    self._project_duration_limit,
                    self._source_frame_count - self.source_in.value(),
                ),
            )
        )

    def set_selection(self, project: StudioProject | None, clip_ids: tuple[str, ...]) -> None:
        resolved = next(
            (
                (track, clip)
                for track in project.tracks
                for clip in track.clips
                if clip.kind == ClipKind.VIDEO and clip.clip_id in clip_ids
            ),
            None,
        ) if project is not None else None
        if resolved is None:
            self._selected_clip_id = None
            self.status.setText("Sélectionnez une vidéo réelle dans la timeline")
            self._set_enabled(False)
            return
        assert project is not None
        track, clip = resolved
        settings = VideoClipSettings.from_clip(clip)
        asset = next(item for item in project.assets if item.asset_id == clip.asset_id)
        self._selected_clip_id = clip.clip_id
        self._source_frame_count = video_source_frame_count(project, asset.asset_id)
        self._project_duration_limit = project.settings.duration_frames - clip.start_frame
        self._updating = True
        try:
            self.source_in.setMaximum(max(0, self._source_frame_count - 1))
            self.source_in.setValue(clip.source_in_frame)
            self.duration.setMaximum(self._project_duration_limit)
            self.duration.setValue(clip.duration_frames)
            self.fit.setCurrentIndex(max(0, self.fit.findData(clip.fit)))
            self.opacity.setValue(clip.opacity * 100.0)
            self.rotation.setValue(settings.transform.rotation_degrees)
            self.crop_x.setValue(settings.transform.crop_x * 100.0)
            self.crop_y.setValue(settings.transform.crop_y * 100.0)
            self.crop_width.setValue(settings.transform.crop_width * 100.0)
            self.crop_height.setValue(settings.transform.crop_height * 100.0)
            self.native_audio.setCurrentIndex(
                max(0, self.native_audio.findData(settings.native_audio_mode))
            )
            self.enabled.setChecked(clip.enabled)
        finally:
            self._updating = False
        self._sync_ranges()
        fps = float((asset.metadata or {}).get("native_fps", 0.0))
        self.status.setText(
            f"{track.name} · {asset.width} × {asset.height} · "
            f"{fps:.3g} FPS natifs · source {clip.source_in_frame}"
        )
        self._set_enabled(not track.locked)

    def _request_apply(self) -> None:
        if self._selected_clip_id is None:
            return
        transform = StillClipSettings(
            crop_x=self.crop_x.value() / 100.0,
            crop_y=self.crop_y.value() / 100.0,
            crop_width=self.crop_width.value() / 100.0,
            crop_height=self.crop_height.value() / 100.0,
            rotation_degrees=self.rotation.value(),
        )
        self.applyRequested.emit(
            VideoInspectorEdit(
                self._selected_clip_id,
                self.source_in.value(),
                self.duration.value(),
                FitMode(self.fit.currentData()),
                self.opacity.value() / 100.0,
                self.enabled.isChecked(),
                VideoClipSettings(
                    transform,
                    NativeAudioMode(self.native_audio.currentData()),
                ),
            )
        )

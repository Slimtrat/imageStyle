from __future__ import annotations

from dataclasses import dataclass
from math import ceil

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

from ..studio.audio import AudioClipSettings, AudioFadeCurve, AudioMixSettings
from ..studio.model import ClipKind, StudioProject, TrackKind


@dataclass(frozen=True, slots=True)
class AudioInspectorEdit:
    clip_id: str
    track_id: str
    source_in_frame: int
    duration_frames: int
    gain_db: float
    fade_in_frames: int
    fade_out_frames: int
    fade_in_curve: AudioFadeCurve
    fade_out_curve: AudioFadeCurve
    enabled: bool
    track_gain_db: float
    track_muted: bool


class StudioAudioInspector(QFrame):
    """Frame-based, non-destructive audio clip and track editor."""

    applyRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioAudioInspector")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._selected_clip_id: str | None = None
        self._selected_track_id: str | None = None
        self._project_duration_limit = 1
        self._source_duration_frames: int | None = None
        self._updating_ranges = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = QLabel("MIX AUDIO DE LA MISE EN SCÈNE")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.selection_status = QLabel("Sélectionnez un clip audio dans la timeline")
        self.selection_status.setObjectName("muted")
        self.selection_status.setWordWrap(True)
        layout.addWidget(self.selection_status)

        clip_form = QFormLayout()
        clip_form.setContentsMargins(0, 0, 0, 0)
        self.source_in = QSpinBox()
        self.source_in.setObjectName("studioAudioSourceIn")
        self.source_in.setRange(0, 2_147_483_647)
        self.source_in.setSuffix(" fr")
        self.duration = QSpinBox()
        self.duration.setObjectName("studioAudioDuration")
        self.duration.setRange(1, 2_147_483_647)
        self.duration.setSuffix(" fr")
        self.clip_gain = self._gain_control("studioAudioClipGain")
        self.fade_in = self._frame_control("studioAudioFadeIn")
        self.fade_out = self._frame_control("studioAudioFadeOut")
        self.fade_in_curve = self._curve_control("studioAudioFadeInCurve")
        self.fade_out_curve = self._curve_control("studioAudioFadeOutCurve")
        self.clip_enabled = QCheckBox("Clip audible")
        self.clip_enabled.setObjectName("studioAudioClipEnabled")
        clip_form.addRow("Source In", self.source_in)
        clip_form.addRow("Durée", self.duration)
        clip_form.addRow("Gain clip", self.clip_gain)
        clip_form.addRow("Fade-in", self.fade_in)
        clip_form.addRow("Courbe d’entrée", self.fade_in_curve)
        clip_form.addRow("Fade-out", self.fade_out)
        clip_form.addRow("Courbe de sortie", self.fade_out_curve)
        clip_form.addRow(self.clip_enabled)
        layout.addLayout(clip_form)

        track_title = QLabel("PISTE AUDIO")
        track_title.setObjectName("sectionTitle")
        layout.addWidget(track_title)
        track_form = QFormLayout()
        track_form.setContentsMargins(0, 0, 0, 0)
        self.track_gain = self._gain_control("studioAudioTrackGain")
        self.track_muted = QCheckBox("Piste muette")
        self.track_muted.setObjectName("studioAudioTrackMuted")
        track_form.addRow("Gain piste", self.track_gain)
        track_form.addRow(self.track_muted)
        layout.addLayout(track_form)

        self.apply_button = QPushButton("Appliquer au mix")
        self.apply_button.setObjectName("studioAudioApplyButton")
        self.apply_button.clicked.connect(self._request_apply)
        self.source_in.valueChanged.connect(self._sync_ranges)
        self.duration.valueChanged.connect(self._sync_ranges)
        self.fade_in.valueChanged.connect(self._sync_ranges)
        self.fade_out.valueChanged.connect(self._sync_ranges)
        layout.addWidget(self.apply_button)
        layout.addStretch(1)
        self._set_controls_enabled(False)

    @staticmethod
    def _gain_control(name: str) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setObjectName(name)
        control.setRange(-60.0, 12.0)
        control.setDecimals(1)
        control.setSingleStep(0.5)
        control.setSuffix(" dB")
        return control

    @staticmethod
    def _frame_control(name: str) -> QSpinBox:
        control = QSpinBox()
        control.setObjectName(name)
        control.setRange(0, 2_147_483_647)
        control.setSuffix(" fr")
        return control

    @staticmethod
    def _curve_control(name: str) -> QComboBox:
        control = QComboBox()
        control.setObjectName(name)
        control.addItem("Puissance égale", AudioFadeCurve.EQUAL_POWER)
        control.addItem("Linéaire", AudioFadeCurve.LINEAR)
        return control

    @property
    def selected_clip_id(self) -> str | None:
        return self._selected_clip_id

    def _set_controls_enabled(self, enabled: bool) -> None:
        for control in (
            self.source_in,
            self.duration,
            self.clip_gain,
            self.fade_in,
            self.fade_out,
            self.fade_in_curve,
            self.fade_out_curve,
            self.clip_enabled,
            self.track_gain,
            self.track_muted,
            self.apply_button,
        ):
            control.setEnabled(enabled)

    def _sync_ranges(self, _value: int | None = None) -> None:
        if self._updating_ranges:
            return
        self._updating_ranges = True
        try:
            duration_limit = self._project_duration_limit
            if self._source_duration_frames is not None:
                duration_limit = min(
                    duration_limit,
                    max(1, self._source_duration_frames - self.source_in.value()),
                )
                self.source_in.setMaximum(max(0, self._source_duration_frames - 1))
            self.duration.setMaximum(max(1, duration_limit))
            duration = self.duration.value()
            self.fade_in.setMaximum(max(0, duration - self.fade_out.value()))
            self.fade_out.setMaximum(max(0, duration - self.fade_in.value()))
        finally:
            self._updating_ranges = False

    def set_selection(
        self,
        project: StudioProject | None,
        clip_ids: tuple[str, ...],
    ) -> None:
        resolved = next(
            (
                (track, clip)
                for track in project.tracks
                for clip in track.clips
                if track.kind == TrackKind.AUDIO
                and clip.kind == ClipKind.AUDIO
                and clip.clip_id in clip_ids
            ),
            None,
        ) if project is not None else None
        if resolved is None:
            self._selected_clip_id = None
            self._selected_track_id = None
            self.selection_status.setText("Sélectionnez un clip audio dans la timeline")
            self._set_controls_enabled(False)
            return

        track, clip = resolved
        settings = AudioClipSettings.from_clip(clip)
        mix = AudioMixSettings.from_project(project)
        asset = next(
            (item for item in project.assets if item.asset_id == clip.asset_id),
            None,
        )
        seconds = (asset.metadata or {}).get("duration_seconds") if asset else None
        self._selected_clip_id = clip.clip_id
        self._selected_track_id = track.track_id
        self._project_duration_limit = project.settings.duration_frames - clip.start_frame
        self._source_duration_frames = (
            max(1, ceil(float(seconds) * project.settings.fps))
            if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds > 0
            else None
        )
        self._updating_ranges = True
        try:
            self.source_in.setValue(clip.source_in_frame)
            self.duration.setMaximum(self._project_duration_limit)
            self.duration.setValue(clip.duration_frames)
            self.clip_gain.setValue(settings.gain_db)
            self.fade_in.setMaximum(clip.duration_frames)
            self.fade_out.setMaximum(clip.duration_frames)
            self.fade_in.setValue(settings.fade_in_frames)
            self.fade_out.setValue(settings.fade_out_frames)
            self.fade_in_curve.setCurrentIndex(
                max(0, self.fade_in_curve.findData(settings.fade_in_curve))
            )
            self.fade_out_curve.setCurrentIndex(
                max(0, self.fade_out_curve.findData(settings.fade_out_curve))
            )
            self.clip_enabled.setChecked(clip.enabled)
            self.track_gain.setValue(mix.track(track.track_id).gain_db)
            self.track_muted.setChecked(track.muted)
        finally:
            self._updating_ranges = False
        self._sync_ranges()
        self.selection_status.setText(
            f"{track.name} · {clip.duration_frames} frames · source {clip.source_in_frame}"
        )
        self._set_controls_enabled(not track.locked)

    def _request_apply(self) -> None:
        if self._selected_clip_id is None or self._selected_track_id is None:
            return
        self.applyRequested.emit(
            AudioInspectorEdit(
                self._selected_clip_id,
                self._selected_track_id,
                self.source_in.value(),
                self.duration.value(),
                self.clip_gain.value(),
                self.fade_in.value(),
                self.fade_out.value(),
                AudioFadeCurve(self.fade_in_curve.currentData()),
                AudioFadeCurve(self.fade_out_curve.currentData()),
                self.clip_enabled.isChecked(),
                self.track_gain.value(),
                self.track_muted.isChecked(),
            )
        )

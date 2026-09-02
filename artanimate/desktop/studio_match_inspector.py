from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..studio.manual_match import (
    ManualMatchSettings,
    ManualMatchTransform,
    MatchCrop,
    MatchPoint,
)
from ..studio.model import ClipKind, Easing, StudioProject, TransitionKind
from ..studio.spatial_match import SpatialMatchSettings
from ..studio.transitions import transition_by_id, transition_clip_pair
from ..studio.video import video_source_frame_count


@dataclass(frozen=True, slots=True)
class MatchInspectorEdit:
    transition_id: str
    duration_frames: int
    reference_source_frame: int
    overlay_opacity: float
    easing: Easing
    transform: ManualMatchTransform


class StudioMatchInspector(QWidget):
    """Editable contract for one artwork-to-real manual match."""

    applyRequested = Signal(object)
    previewRequested = Signal(str, float)
    rejectRequested = Signal(str)
    restoreRequested = Signal(str)
    referenceFrameRequested = Signal(str, int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioMatchInspector")
        self._project: StudioProject | None = None
        self._transition_id: str | None = None
        self._transition_kind: TransitionKind | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.summary = QLabel("Sélectionnez un match virtuel → réel.")
        self.summary.setObjectName("studioMatchSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.diagnostic = QLabel("")
        self.diagnostic.setObjectName("studioMatchDiagnostic")
        self.diagnostic.setWordWrap(True)
        self.diagnostic.hide()
        layout.addWidget(self.diagnostic)

        preview_group = QGroupBox("Comparaison")
        preview_form = QFormLayout(preview_group)
        self.preview_mode = QComboBox()
        self.preview_mode.setObjectName("studioMatchPreviewMode")
        self.preview_mode.addItem("Avant · dernière frame virtuelle", "before")
        self.preview_mode.addItem("Overlay réglable", "overlay")
        self.preview_mode.addItem("Après · référence réelle", "after")
        preview_form.addRow("Vue", self.preview_mode)
        self.overlay_opacity = self._percent_spin("studioMatchOverlayOpacity", 50.0)
        preview_form.addRow("Opacité réelle", self.overlay_opacity)
        layout.addWidget(preview_group)

        timing_group = QGroupBox("Transition")
        timing_form = QFormLayout(timing_group)
        self.duration = QSpinBox()
        self.duration.setObjectName("studioMatchDuration")
        self.duration.setRange(2, 1_000_000)
        self.duration.setSuffix(" frames")
        timing_form.addRow("Durée", self.duration)
        self.reference_frame = QSpinBox()
        self.reference_frame.setObjectName("studioMatchReferenceFrame")
        self.reference_frame.setRange(0, 1_000_000)
        self.reference_frame.setSuffix(" f source")
        timing_form.addRow("Référence réelle", self.reference_frame)
        self.easing = QComboBox()
        self.easing.setObjectName("studioMatchEasing")
        for value, label in (
            (Easing.LINEAR, "Linéaire"),
            (Easing.EASE_IN, "Accélération"),
            (Easing.EASE_OUT, "Décélération"),
            (Easing.EASE_IN_OUT, "Doux"),
        ):
            self.easing.addItem(label, value)
        timing_form.addRow("Interpolation", self.easing)
        layout.addWidget(timing_group)

        placement_group = QGroupBox("Placement de la captation réelle")
        placement_form = QFormLayout(placement_group)
        self.position_x = self._percent_spin("studioMatchPositionX", 50.0, -100.0, 200.0)
        self.position_y = self._percent_spin("studioMatchPositionY", 50.0, -100.0, 200.0)
        self.scale = self._percent_spin("studioMatchScale", 100.0, 5.0, 2000.0)
        self.rotation = self._number_spin(
            "studioMatchRotation",
            0.0,
            -3600.0,
            3600.0,
            " °",
        )
        placement_form.addRow("Position X", self.position_x)
        placement_form.addRow("Position Y", self.position_y)
        placement_form.addRow("Échelle", self.scale)
        placement_form.addRow("Rotation", self.rotation)
        layout.addWidget(placement_group)

        crop_group = QGroupBox("Zone de l’œuvre dans le réel")
        crop_form = QFormLayout(crop_group)
        self.crop_x = self._percent_spin("studioMatchCropX", 0.0)
        self.crop_y = self._percent_spin("studioMatchCropY", 0.0)
        self.crop_width = self._percent_spin("studioMatchCropWidth", 100.0, 0.1)
        self.crop_height = self._percent_spin("studioMatchCropHeight", 100.0, 0.1)
        crop_form.addRow("Gauche", self.crop_x)
        crop_form.addRow("Haut", self.crop_y)
        crop_form.addRow("Largeur", self.crop_width)
        crop_form.addRow("Hauteur", self.crop_height)
        layout.addWidget(crop_group)

        self.corner_tabs = QTabWidget()
        self.corner_tabs.setObjectName("studioMatchCornerTabs")
        self.source_corners = self._corner_editor(
            self.corner_tabs,
            "Source",
            "studioMatchSourceCorner",
            -100.0,
            100.0,
        )
        self.target_corners = self._corner_editor(
            self.corner_tabs,
            "Cible",
            "studioMatchTargetCorner",
            -200.0,
            200.0,
        )
        layout.addWidget(self.corner_tabs)

        geometry_buttons = QHBoxLayout()
        self.reset_button = QPushButton("Réinitialiser la géométrie")
        self.reset_button.setObjectName("studioMatchReset")
        self.restore_button = QPushButton("Restaurer l’automatique")
        self.restore_button.setObjectName("studioMatchRestoreAutomatic")
        geometry_buttons.addWidget(self.reset_button)
        geometry_buttons.addWidget(self.restore_button)
        layout.addLayout(geometry_buttons)
        buttons = QHBoxLayout()
        self.reject_button = QPushButton("Refuser")
        self.reject_button.setObjectName("studioMatchReject")
        self.apply_button = QPushButton("Appliquer le match")
        self.apply_button.setObjectName("studioMatchApply")
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.apply_button.clicked.connect(self._emit_apply)
        self.reset_button.clicked.connect(
            lambda: self.set_transform(ManualMatchTransform())
        )
        self.restore_button.clicked.connect(self._emit_restore)
        self.reject_button.clicked.connect(self._emit_reject)
        self.preview_mode.currentIndexChanged.connect(self._emit_preview)
        self.overlay_opacity.valueChanged.connect(self._emit_preview)
        self.reference_frame.valueChanged.connect(self._emit_reference_frame)
        self.restore_button.hide()
        self.reject_button.hide()
        self._set_enabled(False)

    @staticmethod
    def _number_spin(
        object_name: str,
        value: float,
        minimum: float,
        maximum: float,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName(object_name)
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    @classmethod
    def _percent_spin(
        cls,
        object_name: str,
        value: float,
        minimum: float = 0.0,
        maximum: float = 100.0,
    ) -> QDoubleSpinBox:
        return cls._number_spin(object_name, value, minimum, maximum, " %")

    def _corner_editor(
        self,
        tabs: QTabWidget,
        title: str,
        prefix: str,
        minimum: float,
        maximum: float,
    ) -> tuple[tuple[QDoubleSpinBox, QDoubleSpinBox], ...]:
        page = QWidget()
        grid = QGridLayout(page)
        grid.addWidget(QLabel("Coin"), 0, 0)
        grid.addWidget(QLabel("X"), 0, 1)
        grid.addWidget(QLabel("Y"), 0, 2)
        rows = []
        for index, label in enumerate(("HG", "HD", "BD", "BG"), start=1):
            x = self._percent_spin(f"{prefix}{index - 1}X", 0.0, minimum, maximum)
            y = self._percent_spin(f"{prefix}{index - 1}Y", 0.0, minimum, maximum)
            grid.addWidget(QLabel(label), index, 0)
            grid.addWidget(x, index, 1)
            grid.addWidget(y, index, 2)
            rows.append((x, y))
        tabs.addTab(page, title)
        return tuple(rows)

    @property
    def selected_transition_id(self) -> str | None:
        return self._transition_id

    @property
    def selected_transition_kind(self) -> TransitionKind | None:
        return self._transition_kind

    def _editable_widgets(self) -> tuple[QWidget, ...]:
        corners = tuple(
            widget
            for row in (*self.source_corners, *self.target_corners)
            for widget in row
        )
        return (
            self.preview_mode,
            self.overlay_opacity,
            self.duration,
            self.reference_frame,
            self.easing,
            self.position_x,
            self.position_y,
            self.scale,
            self.rotation,
            self.crop_x,
            self.crop_y,
            self.crop_width,
            self.crop_height,
            self.corner_tabs,
            self.reset_button,
            self.restore_button,
            self.reject_button,
            self.apply_button,
            *corners,
        )

    def _set_enabled(self, enabled: bool) -> None:
        for widget in self._editable_widgets():
            widget.setEnabled(enabled)

    def set_selection(
        self,
        project: StudioProject | None,
        transition_id: str | None,
    ) -> None:
        self._project = project
        self._transition_id = None
        self._transition_kind = None
        if project is None or transition_id is None:
            self.summary.setText("Sélectionnez un match virtuel → réel.")
            self.diagnostic.hide()
            self._set_enabled(False)
            return
        try:
            transition = transition_by_id(project, transition_id)
        except KeyError:
            self.summary.setText("Le match sélectionné n’existe plus.")
            self._set_enabled(False)
            return
        if transition.kind not in {TransitionKind.MATCH, TransitionKind.SPATIAL_MATCH}:
            self.summary.setText("Cette transition n’est pas un raccord éditable.")
            self.diagnostic.hide()
            self._set_enabled(False)
            return
        pair = transition_clip_pair(project, transition)
        if transition.kind == TransitionKind.SPATIAL_MATCH:
            spatial = SpatialMatchSettings.from_transition(transition)
            reference_source_frame = spatial.reference_source_frame
            overlay_opacity = spatial.overlay_opacity
            easing = spatial.easing
            transform = spatial.editor_transform
        else:
            manual = ManualMatchSettings.from_transition(transition)
            reference_source_frame = manual.reference_source_frame
            overlay_opacity = manual.overlay_opacity
            easing = manual.easing
            transform = manual.transform
        self._loading = True
        try:
            self._transition_id = transition.transition_id
            self._transition_kind = transition.kind
            if transition.kind == TransitionKind.SPATIAL_MATCH:
                solution = spatial.solution
                partial = any(
                    x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0
                    for x, y in solution.target_quad
                )
                confidence = "faible" if solution.confidence < 0.65 else "solide"
                warning = " · cadrage partiel" if partial else ""
                self.summary.setText(
                    f"{pair.from_clip.clip_id} → {pair.to_clip.clip_id}\n"
                    "La proposition reste temporaire jusqu’à son acceptation."
                )
                self.diagnostic.setText(
                    f"AKAZE {confidence}{warning} · confiance "
                    f"{solution.confidence:.0%} · {solution.inliers} inliers · "
                    f"erreur {solution.reprojection_error:.2f} px · "
                    f"état {spatial.review_status}"
                )
                self.diagnostic.show()
                self.restore_button.show()
                self.reject_button.show()
                self.apply_button.setText("Accepter le raccord")
            else:
                self.summary.setText(
                    f"{pair.from_clip.clip_id} → {pair.to_clip.clip_id}\n"
                    "Le réel reste transformé après la fin du blend."
                )
                self.diagnostic.hide()
                self.restore_button.hide()
                self.reject_button.hide()
                self.apply_button.setText("Appliquer le match")
            self.duration.setMaximum(project.settings.duration_frames)
            self.duration.setValue(transition.duration_frames)
            if pair.to_clip.kind == ClipKind.VIDEO and pair.to_clip.asset_id is not None:
                video_source_frame_count(project, pair.to_clip.asset_id)
                minimum = pair.to_clip.source_in_frame
                maximum = minimum + pair.to_clip.duration_frames - 1
            else:
                minimum = 0
                maximum = 0
            self.reference_frame.setRange(minimum, maximum)
            self.reference_frame.setValue(reference_source_frame)
            self.overlay_opacity.setValue(overlay_opacity * 100.0)
            self.easing.setCurrentIndex(max(0, self.easing.findData(easing)))
            self.set_transform(transform)
        finally:
            self._loading = False
        self._set_enabled(True)

    def set_transform(self, transform: ManualMatchTransform) -> None:
        transform.validate()
        loading = self._loading
        self._loading = True
        try:
            self.position_x.setValue(transform.position_x * 100.0)
            self.position_y.setValue(transform.position_y * 100.0)
            self.scale.setValue(transform.scale * 100.0)
            self.rotation.setValue(transform.rotation_degrees)
            crop = transform.source_crop
            self.crop_x.setValue(crop.x * 100.0)
            self.crop_y.setValue(crop.y * 100.0)
            self.crop_width.setValue(crop.width * 100.0)
            self.crop_height.setValue(crop.height * 100.0)
            for widgets, point in zip(
                self.source_corners,
                transform.source_corner_offsets,
                strict=True,
            ):
                widgets[0].setValue(point.x * 100.0)
                widgets[1].setValue(point.y * 100.0)
            for widgets, point in zip(
                self.target_corners,
                transform.target_corner_offsets,
                strict=True,
            ):
                widgets[0].setValue(point.x * 100.0)
                widgets[1].setValue(point.y * 100.0)
        finally:
            self._loading = loading

    @staticmethod
    def _points(
        widgets: tuple[tuple[QDoubleSpinBox, QDoubleSpinBox], ...],
    ) -> tuple[MatchPoint, ...]:
        return tuple(
            MatchPoint(x.value() / 100.0, y.value() / 100.0)
            for x, y in widgets
        )

    def transform(self) -> ManualMatchTransform:
        return ManualMatchTransform(
            source_crop=MatchCrop(
                self.crop_x.value() / 100.0,
                self.crop_y.value() / 100.0,
                self.crop_width.value() / 100.0,
                self.crop_height.value() / 100.0,
            ),
            source_corner_offsets=self._points(self.source_corners),
            position_x=self.position_x.value() / 100.0,
            position_y=self.position_y.value() / 100.0,
            scale=self.scale.value() / 100.0,
            rotation_degrees=self.rotation.value(),
            target_corner_offsets=self._points(self.target_corners),
        ).validate()

    def _emit_apply(self) -> None:
        if self._transition_id is None:
            return
        self.applyRequested.emit(
            MatchInspectorEdit(
                self._transition_id,
                self.duration.value(),
                self.reference_frame.value(),
                self.overlay_opacity.value() / 100.0,
                Easing(self.easing.currentData()),
                self.transform(),
            )
        )

    def _emit_preview(self, *_args: object) -> None:
        if self._loading or self._transition_id is None:
            return
        self.previewRequested.emit(
            str(self.preview_mode.currentData()),
            self.overlay_opacity.value() / 100.0,
        )

    def _emit_reject(self) -> None:
        if self._transition_id is not None:
            self.rejectRequested.emit(self._transition_id)

    def _emit_restore(self) -> None:
        if self._transition_id is not None:
            self.restoreRequested.emit(self._transition_id)

    def _emit_reference_frame(self, frame: int) -> None:
        if (
            not self._loading
            and self._transition_id is not None
            and self._transition_kind == TransitionKind.SPATIAL_MATCH
        ):
            self.referenceFrameRequested.emit(self._transition_id, int(frame))

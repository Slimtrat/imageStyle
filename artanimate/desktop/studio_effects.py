from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.config import RenderConfig
from ..core.effects import EffectDescriptor, effect_descriptors
from ..studio.effect_2d import settings_for_effect_clip
from ..studio.model import ClipKind, StudioProject
from .controls import ParameterSlider


class StudioEffectInspector(QFrame):
    """Artwork-relative 2D layer inspector driven by effect documentation."""

    addRequested = Signal(object, float, float, float)
    applyRequested = Signal(str, object, float, float, float, bool)
    duplicateRequested = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], RenderConfig] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("studioEffectInspector")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._config_provider = config_provider or RenderConfig
        self._snapshot = RenderConfig()
        self._selected_clip_id: str | None = None
        self._descriptors = effect_descriptors()
        self._controls: dict[str, dict[str, QWidget]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = QLabel("CALQUES D’EFFETS 2D")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.selection_status = QLabel("Nouveau calque lié à l’œuvre")
        self.selection_status.setObjectName("muted")
        self.selection_status.setWordWrap(True)
        layout.addWidget(self.selection_status)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.effect_combo = QComboBox()
        self.effect_combo.setObjectName("studioEffectSelector")
        for descriptor in self._descriptors:
            self.effect_combo.addItem(descriptor.selector_label, descriptor.key)
            index = self.effect_combo.count() - 1
            self.effect_combo.setItemData(index, descriptor.description, 3)
        self.effect_combo.currentIndexChanged.connect(self._effect_changed)
        form.addRow("Effet", self.effect_combo)
        layout.addLayout(form)

        self.description = QLabel()
        self.description.setObjectName("studioEffectDescription")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.parameter_stack = QStackedWidget()
        self.parameter_stack.setObjectName("studioEffectParameters")
        for descriptor in self._descriptors:
            page, controls = self._build_parameter_page(descriptor)
            self.parameter_stack.addWidget(page)
            self._controls[descriptor.key] = controls
        layout.addWidget(self.parameter_stack)

        timing = QFormLayout()
        timing.setContentsMargins(0, 0, 0, 0)
        self.duration = ParameterSlider(0.5, 2.0, 1.0, 0.1, 1, " s")
        self.duration.setObjectName("studioEffectDuration")
        self.intensity = ParameterSlider(0.0, 1.0, 1.0, 0.05, 2)
        self.intensity.setObjectName("studioEffectIntensity")
        self.opacity = ParameterSlider(0.0, 1.0, 1.0, 0.05, 2)
        self.opacity.setObjectName("studioEffectOpacity")
        self.enabled = QCheckBox("Calque actif")
        self.enabled.setChecked(True)
        timing.addRow("Durée", self.duration)
        timing.addRow("Intensité", self.intensity)
        timing.addRow("Opacité", self.opacity)
        timing.addRow(self.enabled)
        layout.addLayout(timing)

        row = QHBoxLayout()
        self.add_button = QPushButton("Ajouter ici")
        self.add_button.setObjectName("studioAddEffectButton")
        self.apply_button = QPushButton("Appliquer")
        self.apply_button.setObjectName("studioApplyEffectButton")
        self.duplicate_button = QPushButton("Dupliquer")
        self.duplicate_button.setObjectName("studioDuplicateEffectButton")
        row.addWidget(self.add_button)
        row.addWidget(self.apply_button)
        row.addWidget(self.duplicate_button)
        layout.addLayout(row)
        self.add_button.clicked.connect(self._request_add)
        self.apply_button.clicked.connect(self._request_apply)
        self.duplicate_button.clicked.connect(self._request_duplicate)
        self.prepare_new()

    def _build_parameter_page(
        self,
        descriptor: EffectDescriptor,
    ) -> tuple[QWidget, dict[str, QWidget]]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(5)
        controls: dict[str, QWidget] = {}
        for parameter in descriptor.parameters:
            if parameter.control == "choice":
                control: QWidget = QComboBox()
                for choice in parameter.choices:
                    control.addItem(choice.label, choice.value)
            else:
                if None in {
                    parameter.minimum,
                    parameter.maximum,
                    parameter.default,
                    parameter.step,
                }:
                    raise ValueError(
                        f"Documentation incomplète : {descriptor.key}/{parameter.key}"
                    )
                control = ParameterSlider(
                    parameter.minimum,
                    parameter.maximum,
                    parameter.default,
                    parameter.step,
                    parameter.decimals,
                    parameter.suffix,
                    parameter.description,
                )
            control.setObjectName(f"studioEffect_{descriptor.key}_{parameter.key}")
            control.setToolTip(parameter.description)
            control.setAccessibleDescription(parameter.description)
            label = QLabel(parameter.label)
            label.setToolTip(parameter.description)
            form.addRow(label, control)
            controls[parameter.key] = control
        if not controls:
            empty = QLabel("Cet effet ne demande aucun réglage supplémentaire.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            form.addRow(empty)
        return page, controls

    @property
    def selected_clip_id(self) -> str | None:
        return self._selected_clip_id

    def _descriptor(self, index: int | None = None) -> EffectDescriptor:
        selected = self.effect_combo.currentIndex() if index is None else int(index)
        return self._descriptors[max(0, selected)]

    def _effect_changed(self, index: int) -> None:
        selected = max(0, int(index))
        self.parameter_stack.setCurrentIndex(selected)
        descriptor = self._descriptor(selected)
        self.description.setText(descriptor.description)
        self.description.setToolTip(descriptor.description)
        self._load_effect_fields(self._snapshot, descriptor.key)

    def _provider_snapshot(self) -> RenderConfig:
        provided = self._config_provider()
        if not isinstance(provided, RenderConfig):
            raise TypeError("Le fournisseur de réglages 2D doit retourner RenderConfig")
        return RenderConfig.from_dict(provided.to_dict())

    def _load_effect_fields(self, config: RenderConfig, effect: str) -> None:
        for field, control in self._controls[effect].items():
            value = getattr(config, field)
            if isinstance(control, QComboBox):
                index = control.findData(value)
                if index >= 0:
                    control.setCurrentIndex(index)
            elif isinstance(control, ParameterSlider):
                control.setValue(float(value))

    def _read_config(self) -> RenderConfig:
        values = self._snapshot.to_dict()
        effect = str(self.effect_combo.currentData())
        values["effect"] = effect
        for field, control in self._controls[effect].items():
            if isinstance(control, QComboBox):
                values[field] = control.currentData()
            elif isinstance(control, ParameterSlider):
                values[field] = control.value()
        return RenderConfig.from_dict(values)

    def prepare_new(self) -> None:
        self._selected_clip_id = None
        self._snapshot = self._provider_snapshot()
        index = self.effect_combo.findData(self._snapshot.effect)
        self.effect_combo.setCurrentIndex(max(0, index))
        self._load_effect_fields(self._snapshot, str(self.effect_combo.currentData()))
        self.selection_status.setText("Nouveau calque lié à l’œuvre")
        self.duration.setValue(1.0)
        self.intensity.setValue(1.0)
        self.opacity.setValue(1.0)
        self.enabled.setChecked(True)
        self._update_selection_actions()

    def set_selection(
        self,
        project: StudioProject | None,
        clip_ids: tuple[str, ...],
    ) -> None:
        clip = next(
            (
                clip
                for track in project.tracks
                for clip in track.clips
                if clip.clip_id in clip_ids and clip.kind == ClipKind.EFFECT_2D
            ),
            None,
        ) if project is not None else None
        if clip is None:
            self._selected_clip_id = None
            self.selection_status.setText("Nouveau calque lié à l’œuvre")
            self._update_selection_actions()
            return
        settings = settings_for_effect_clip(clip)
        self._selected_clip_id = clip.clip_id
        self._snapshot = settings.config
        index = self.effect_combo.findData(settings.effect)
        self.effect_combo.setCurrentIndex(max(0, index))
        self._load_effect_fields(self._snapshot, settings.effect)
        self.duration.setValue(clip.duration_frames / project.settings.fps)
        self.intensity.setValue(settings.intensity)
        self.opacity.setValue(clip.opacity)
        self.enabled.setChecked(clip.enabled)
        descriptor = self._descriptor()
        self.selection_status.setText(
            f"{descriptor.selector_label} · {clip.duration_frames / project.settings.fps:g} s"
        )
        self._update_selection_actions()

    def _update_selection_actions(self) -> None:
        selected = self._selected_clip_id is not None
        self.apply_button.setEnabled(selected)
        self.duplicate_button.setEnabled(selected)
        self.enabled.setEnabled(selected)

    def _request_add(self) -> None:
        self._snapshot = self._provider_snapshot()
        config = self._read_config()
        self.addRequested.emit(
            config,
            float(self.duration.value()),
            float(self.intensity.value()),
            float(self.opacity.value()),
        )

    def _request_apply(self) -> None:
        if self._selected_clip_id is None:
            return
        config = self._read_config()
        self.applyRequested.emit(
            self._selected_clip_id,
            config,
            float(self.duration.value()),
            float(self.intensity.value()),
            float(self.opacity.value()),
            self.enabled.isChecked(),
        )

    def _request_duplicate(self) -> None:
        if self._selected_clip_id is not None:
            self.duplicateRequested.emit(self._selected_clip_id)

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..studio.model import Easing, StudioProject, TransitionKind
from ..studio.transitions import DissolveSettings, transition_by_id


@dataclass(frozen=True, slots=True)
class TransitionInspectorEdit:
    transition_id: str
    duration_frames: int
    easing: Easing


class StudioTransitionInspector(QWidget):
    """Properties for a semantic cut relationship, independent of clip renderers."""

    applyRequested = Signal(object)
    deleteRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioTransitionInspector")
        self._project: StudioProject | None = None
        self._transition_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.summary = QLabel("Sélectionnez un fondu dans la timeline.")
        self.summary.setObjectName("studioTransitionSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        form = QFormLayout()
        self.duration = QSpinBox()
        self.duration.setObjectName("studioTransitionDuration")
        self.duration.setRange(2, 1_000_000)
        self.duration.setSuffix(" frames")
        form.addRow("Durée", self.duration)
        self.easing = QComboBox()
        self.easing.setObjectName("studioTransitionEasing")
        for value, label in (
            (Easing.LINEAR, "Linéaire"),
            (Easing.EASE_IN, "Accélération"),
            (Easing.EASE_OUT, "Décélération"),
            (Easing.EASE_IN_OUT, "Doux"),
        ):
            self.easing.addItem(label, value)
        form.addRow("Interpolation", self.easing)
        layout.addLayout(form)

        self.apply_button = QPushButton("Appliquer au fondu")
        self.apply_button.setObjectName("studioTransitionApply")
        self.delete_button = QPushButton("Retrouver le cut")
        self.delete_button.setObjectName("studioTransitionDelete")
        self.apply_button.clicked.connect(self._emit_apply)
        self.delete_button.clicked.connect(self._emit_delete)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.delete_button)
        layout.addStretch(1)
        self._set_enabled(False)

    @property
    def selected_transition_id(self) -> str | None:
        return self._transition_id

    def _set_enabled(self, enabled: bool) -> None:
        self.duration.setEnabled(enabled)
        self.easing.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def set_selection(
        self,
        project: StudioProject | None,
        transition_id: str | None,
    ) -> None:
        self._project = project
        self._transition_id = None
        if project is None or transition_id is None:
            self.summary.setText("Sélectionnez un fondu dans la timeline.")
            self._set_enabled(False)
            return
        try:
            transition = transition_by_id(project, transition_id)
        except KeyError:
            self.summary.setText("Le fondu sélectionné n’existe plus.")
            self._set_enabled(False)
            return
        if transition.kind != TransitionKind.DISSOLVE:
            self.summary.setText("Cette transition n’est pas un fondu éditable.")
            self._set_enabled(False)
            return
        self._transition_id = transition.transition_id
        self.summary.setText(
            f"{transition.from_clip_id} → {transition.to_clip_id}\n"
            f"Frames {transition.start_frame} à "
            f"{transition.start_frame + transition.duration_frames - 1}"
        )
        self.duration.setMaximum(project.settings.duration_frames)
        self.duration.setValue(transition.duration_frames)
        settings = DissolveSettings.from_transition(transition)
        index = self.easing.findData(settings.easing)
        self.easing.setCurrentIndex(max(0, index))
        self._set_enabled(True)

    def _emit_apply(self) -> None:
        if self._transition_id is None:
            return
        easing = self.easing.currentData()
        self.applyRequested.emit(
            TransitionInspectorEdit(
                self._transition_id,
                self.duration.value(),
                Easing(easing),
            )
        )

    def _emit_delete(self) -> None:
        if self._transition_id is not None:
            self.deleteRequested.emit(self._transition_id)

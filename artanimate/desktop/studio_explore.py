from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..studio.explore import (
    ExplorePlanRole,
    explore_clip,
    is_explore_project,
    recommend_explore_zones,
)
from ..studio.model import StudioProject, TrackKind


class StudioExplorePanel(QWidget):
    """Guided entry point that only emits standard StudioProject edits."""

    createRequested = Signal(str, str)
    acceptRequested = Signal()
    rejectRequested = Signal()
    proposalInvalidated = Signal()
    realMediaRequested = Signal()
    musicRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioExplorePanel")
        self._project: StudioProject | None = None
        self._proposal_ready = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("PARCOURS EXPLORE · 12 SECONDES ÉDITABLES")
        title.setObjectName("studioExploreTitle")
        layout.addWidget(title)
        description = QLabel(
            "Macro → Inspection → Reveal → Réel. Chaque plan, keyframe et "
            "transition reste un élément ordinaire de la timeline."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        zones = QGroupBox("Zones de départ")
        zones_form = QFormLayout(zones)
        self.macro_zone = QComboBox()
        self.macro_zone.setObjectName("studioExploreMacroZone")
        self.inspection_zone = QComboBox()
        self.inspection_zone.setObjectName("studioExploreInspectionZone")
        zones_form.addRow("Macro", self.macro_zone)
        zones_form.addRow("Inspection", self.inspection_zone)
        layout.addWidget(zones)

        self.zone_help = QLabel(
            "L’œuvre entière reste disponible même sans analyse locale."
        )
        self.zone_help.setWordWrap(True)
        self.zone_help.setObjectName("studioExploreZoneHelp")
        layout.addWidget(self.zone_help)

        self.create_button = QPushButton("Prévisualiser le parcours")
        self.create_button.setObjectName("studioExploreCreate")
        layout.addWidget(self.create_button)
        decision_row = QHBoxLayout()
        self.accept_button = QPushButton("Accepter")
        self.accept_button.setObjectName("studioExploreAccept")
        self.reject_button = QPushButton("Refuser")
        self.reject_button.setObjectName("studioExploreReject")
        decision_row.addWidget(self.accept_button)
        decision_row.addWidget(self.reject_button)
        layout.addLayout(decision_row)

        completion = QGroupBox("Compléter le Reel")
        completion_layout = QVBoxLayout(completion)
        self.real_button = QPushButton("Choisir la photo ou vidéo réelle…")
        self.real_button.setObjectName("studioExploreChooseReal")
        self.music_button = QPushButton("Choisir la musique locale…")
        self.music_button.setObjectName("studioExploreChooseMusic")
        completion_layout.addWidget(self.real_button)
        completion_layout.addWidget(self.music_button)
        layout.addWidget(completion)

        self.summary = QLabel("Ouvrez une œuvre pour construire Explore.")
        self.summary.setObjectName("studioExploreSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addStretch(1)

        self.create_button.clicked.connect(self._emit_create)
        self.accept_button.clicked.connect(self.acceptRequested)
        self.reject_button.clicked.connect(self.rejectRequested)
        self.macro_zone.currentIndexChanged.connect(self._selection_changed)
        self.inspection_zone.currentIndexChanged.connect(self._selection_changed)
        self.real_button.clicked.connect(self.realMediaRequested)
        self.music_button.clicked.connect(self.musicRequested)
        self.set_project(None)

    @staticmethod
    def _zone_id(clip) -> str | None:
        values = clip.parameters or {}
        explore = values.get("explore") if isinstance(values, Mapping) else None
        zone = explore.get("zone_object_id") if isinstance(explore, Mapping) else None
        return str(zone) if isinstance(zone, str) and zone else None

    @staticmethod
    def _select(combo: QComboBox, object_id: str | None) -> None:
        index = combo.findData(object_id or "artwork")
        combo.setCurrentIndex(max(0, index))

    def set_project(self, project: StudioProject | None) -> None:
        self._project = project
        self._proposal_ready = False
        self.accept_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        self.macro_zone.clear()
        self.inspection_zone.clear()
        if project is None or project.scene is None:
            self.create_button.setEnabled(False)
            self.real_button.setEnabled(False)
            self.music_button.setEnabled(False)
            self.summary.setText("Ouvrez une œuvre pour construire Explore.")
            return

        choices = tuple(
            scene_object
            for scene_object in project.scene.objects
            if scene_object.bounds is not None
            and scene_object.semantic_type
            not in {"scene.background", "scene.camera"}
        )
        for scene_object in choices:
            label = (
                "Œuvre entière"
                if scene_object.object_id == "artwork"
                else scene_object.label
            )
            self.macro_zone.addItem(label, scene_object.object_id)
            self.inspection_zone.addItem(label, scene_object.object_id)

        macro = explore_clip(project, ExplorePlanRole.MACRO)
        inspection = explore_clip(project, ExplorePlanRole.INSPECTION)
        recommendation = recommend_explore_zones(project)
        self._select(
            self.macro_zone,
            (
                self._zone_id(macro)
                if macro is not None
                else recommendation.macro_zone_id
            ),
        )
        self._select(
            self.inspection_zone,
            self._zone_id(inspection)
            if inspection is not None
            else recommendation.inspection_zone_id,
        )
        self.create_button.setEnabled(bool(choices))
        explore_ready = is_explore_project(project)
        placeholder = explore_clip(project, ExplorePlanRole.REAL_PLACEHOLDER)
        audio_track = next(
            (track for track in project.tracks if track.kind == TrackKind.AUDIO),
            None,
        )
        has_music = audio_track is not None and bool(audio_track.clips)
        self.real_button.setEnabled(explore_ready and placeholder is not None)
        self.music_button.setEnabled(explore_ready and not has_music)
        self.create_button.setText(
            "Prévisualiser une variante"
            if explore_ready
            else "Prévisualiser le parcours"
        )
        self.real_button.setText(
            "Média réel lié"
            if explore_ready and placeholder is None
            else "Choisir la photo ou vidéo réelle…"
        )
        self.music_button.setText(
            "Musique liée" if has_music else "Choisir la musique locale…"
        )
        if len(choices) == 1:
            self.zone_help.setText(
                "Seule l’œuvre entière est disponible. Créez des zones dans "
                "Analyse locale pour cibler des détails."
            )
        else:
            self.zone_help.setText(
                f"{len(choices) - 1} zone(s) locale(s) disponible(s), plus l’œuvre entière."
            )
        if explore_ready:
            real_state = "à choisir" if placeholder is not None else "lié"
            music_state = "liée" if has_music else "à choisir"
            self.summary.setText(
                "Explore prêt · plans 1–4 éditables · "
                f"réel {real_state} · musique {music_state}."
            )
        else:
            self.summary.setText(
                "Les zones ci-dessus sont suggérées automatiquement. Prévisualisez "
                "le parcours avant de l’insérer en une seule opération annulable."
            )

    def _emit_create(self) -> None:
        macro = self.macro_zone.currentData()
        inspection = self.inspection_zone.currentData()
        if isinstance(macro, str) and isinstance(inspection, str):
            self.createRequested.emit(macro, inspection)

    def _selection_changed(self, _index: int = -1) -> None:
        if self._proposal_ready:
            self.proposalInvalidated.emit()
            self.clear_proposal_preview(
                "Zones modifiées · générez un nouvel aperçu avant d’accepter."
            )

    def set_proposal_preview(
        self,
        *,
        macro_label: str,
        inspection_label: str,
    ) -> None:
        self._proposal_ready = True
        self.accept_button.setEnabled(True)
        self.reject_button.setEnabled(True)
        self.summary.setText(
            f"Aperçu actif · Macro sur {macro_label} · Inspection sur "
            f"{inspection_label} · Reveal sur l’œuvre entière. "
            "Lisez le parcours avec le transport, puis acceptez ou refusez."
        )

    def clear_proposal_preview(self, message: str | None = None) -> None:
        self._proposal_ready = False
        self.accept_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        if message is not None:
            self.summary.setText(message)

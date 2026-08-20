from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QDir, QProcess, QSettings, QStandardPaths, QThread, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..branding import LOGO_PATH
from ..core.config import RenderConfig
from ..core.effects import EffectCapability, EffectDescriptor, effect_descriptors
from ..observability import attach_handler, configure_file_logging, detach_handler
from .controls import ChromaticSequenceWheel, ParameterSlider
from .history import GenerationHistory
from .history_widgets import HistoryPanel
from .log_window import LogWindow, QtLogHandler
from .preview import PREVIEW_INTERVAL_MS, PreviewWorker
from .style import APP_STYLESHEET
from .widgets import PathDropZone, PreviewCard, ScaledImageLabel
from .worker import RenderWorker


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        log_file: Path | None = None,
        startup_warning: str | None = None,
        history_root: Path | None = None,
    ):
        super().__init__()
        self.setWindowTitle("ArtAnimate — Atelier d’animation")
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setMinimumSize(1100, 760)
        self.resize(1420, 900)
        self.settings = QSettings("ArtAnimate", "Desktop")
        self._thread: QThread | None = None
        self._worker: RenderWorker | None = None
        self._close_when_done = False
        self._auto_filename = True
        self._last_video: Path | None = None
        self._unread_logs = 0
        self._preview_thread: QThread | None = None
        self._preview_worker: PreviewWorker | None = None
        self._preview_revision = 0
        self._preview_pending = False
        self._preview_frames: tuple[QImage, ...] = ()
        self._preview_frame_index = 0
        self._closing_for_preview = False
        self._render_source: Path | None = None
        self._render_config: RenderConfig | None = None
        self._render_thumbnail: QImage | None = None

        history_location = history_root or (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "history"
        )
        self.history_store = GenerationHistory(history_location)
        self._history_records = self.history_store.load()

        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.timeout.connect(self._begin_preview)
        self._preview_playback = QTimer(self)
        self._preview_playback.setInterval(PREVIEW_INTERVAL_MS)
        self._preview_playback.timeout.connect(self._advance_preview)

        saved_geometry = self.settings.value("windowGeometry")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(24, 20, 24, 20)
        page.setSpacing(16)

        page.addLayout(self._build_header())

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("workspaceTabs")
        self.two_d_page = QWidget()
        two_d_layout = QVBoxLayout(self.two_d_page)
        two_d_layout.setContentsMargins(2, 10, 2, 2)
        two_d_layout.setSpacing(12)
        two_d_layout.addLayout(self._build_drop_zones())

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(self._build_previews(), 1)
        body.addWidget(self._build_controls())
        two_d_layout.addLayout(body, 1)
        self.history_panel = HistoryPanel()
        self.history_panel.set_records(self._history_records)
        two_d_layout.addWidget(self.history_panel)
        two_d_layout.addWidget(self._build_progress())

        self.workspace_tabs.addTab(self.two_d_page, "Atelier 2D")
        self.workspace_tabs.addTab(
            self._build_coming_soon(),
            "Studio 3D · Coming soon",
        )
        page.addWidget(self.workspace_tabs, 1)
        self._build_menus()

        self.log_window = LogWindow(log_file, self)
        self.log_handler = QtLogHandler()
        self.log_handler.emitter.record_received.connect(self._receive_log_record)
        attach_handler(self.log_handler, logging.INFO)

        self._connect_signals()
        self._restore_destination()
        self._effect_changed()
        self._order_changed()
        self._neutral_changed()
        self._outline_changed()
        logger.info("Interface desktop prête")
        if startup_warning:
            logger.warning(startup_warning)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setNativeMenuBar(False)

        file_menu = menu_bar.addMenu("&Fichier")
        choose_source = QAction("Choisir une œuvre…", self)
        choose_source.setShortcut("Ctrl+O")
        choose_source.triggered.connect(lambda: self.source_zone.browse())
        choose_destination = QAction("Choisir le dossier de destination…", self)
        choose_destination.setShortcut("Ctrl+Shift+O")
        choose_destination.triggered.connect(lambda: self.destination_zone.browse())
        open_destination = QAction("Ouvrir la destination dans l’Explorateur", self)
        open_destination.triggered.connect(self._open_destination_folder)
        quit_action = QAction("Quitter", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addActions((choose_source, choose_destination, open_destination))
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        generation_menu = menu_bar.addMenu("&Génération")
        self.preview_action = QAction("Actualiser le prérendu", self)
        self.preview_action.setShortcut("F5")
        self.preview_action.triggered.connect(self._force_preview)
        self.generate_action = QAction("Créer la vidéo", self)
        self.generate_action.setShortcut("Ctrl+Return")
        self.generate_action.triggered.connect(self._start_render)
        self.cancel_action = QAction("Annuler le rendu", self)
        self.cancel_action.setShortcut("Esc")
        self.cancel_action.setEnabled(False)
        self.cancel_action.triggered.connect(self._cancel_render)
        generation_menu.addActions(
            (self.preview_action, self.generate_action, self.cancel_action)
        )

        view_menu = menu_bar.addMenu("&Affichage")
        show_2d = QAction("Atelier 2D", self)
        show_2d.triggered.connect(lambda: self.workspace_tabs.setCurrentIndex(0))
        show_3d = QAction("Studio 3D · Coming soon", self)
        show_3d.triggered.connect(lambda: self.workspace_tabs.setCurrentIndex(1))
        show_logs = QAction("Logs", self)
        show_logs.setShortcut("Ctrl+L")
        show_logs.triggered.connect(self._show_logs)
        view_menu.addActions((show_2d, show_3d, show_logs))

        history_menu = menu_bar.addMenu("&Historique")
        refresh = QAction("Actualiser la banque", self)
        refresh.triggered.connect(self._refresh_history)
        open_current = QAction("Ouvrir la destination actuelle", self)
        open_current.triggered.connect(self._open_destination_folder)
        open_data = QAction("Ouvrir les données de l’historique", self)
        open_data.triggered.connect(self._open_history_data)
        history_menu.addActions((refresh, open_current, open_data))

    def _build_coming_soon(self) -> QWidget:
        page = QWidget()
        page.setObjectName("comingSoonPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.addStretch(1)
        badge = QLabel("COMING SOON")
        badge.setObjectName("comingSoonBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Mise en scène 3D")
        title.setObjectName("comingSoonTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message = QLabel(
            "Table, lampe, pièce légèrement éclairée et caméra mobile arriveront "
            "après la consolidation de l’atelier 2D."
        )
        message.setObjectName("comingSoonText")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        self.coming_soon_feedback = QLabel(
            "Aucun réglage 3D factice : ce studio sera activé avec son vrai moteur."
        )
        self.coming_soon_feedback.setObjectName("muted")
        self.coming_soon_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(18)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addWidget(self.coming_soon_feedback)
        layout.addStretch(1)
        return page

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.brand_logo = QLabel()
        self.brand_logo.setAccessibleName("Logo ArtAnimate")
        self.brand_logo.setFixedSize(68, 68)
        logo = QPixmap(str(LOGO_PATH))
        if not logo.isNull():
            self.brand_logo.setPixmap(
                logo.scaled(
                    self.brand_logo.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            logger.error("Logo ArtAnimate illisible : %s", LOGO_PATH)
        layout.addWidget(self.brand_logo)
        text = QVBoxLayout()
        text.setSpacing(1)
        brand = QLabel("ArtAnimate")
        brand.setObjectName("brand")
        tagline = QLabel("Transformez une œuvre en film chromatique, directement sur votre ordinateur.")
        tagline.setObjectName("tagline")
        text.addWidget(brand)
        text.addWidget(tagline)
        layout.addLayout(text)
        layout.addStretch(1)
        self.log_button = QPushButton("Logs")
        self.log_button.setToolTip("Afficher les informations, avertissements et erreurs")
        layout.addWidget(self.log_button, 0, Qt.AlignmentFlag.AlignBottom)
        local = QLabel("Traitement 100 % local")
        local.setObjectName("muted")
        layout.addWidget(local, 0, Qt.AlignmentFlag.AlignBottom)
        return layout

    def _build_drop_zones(self) -> QHBoxLayout:
        self.source_zone = PathDropZone(
            "1. Œuvre source",
            "Glissez une image ici ou cliquez sur Parcourir…",
            "image",
        )
        self.destination_zone = PathDropZone(
            "2. Dossier de destination",
            "Glissez un dossier ici ou cliquez sur Parcourir…",
            "directory",
        )
        layout = QHBoxLayout()
        layout.setSpacing(16)
        layout.addWidget(self.source_zone, 1)
        layout.addWidget(self.destination_zone, 1)
        return layout

    def _build_previews(self) -> QHBoxLayout:
        self.source_preview = PreviewCard(
            "Image originale",
            "L’aperçu de l’œuvre apparaîtra ici.",
        )

        self.output_card = QFrame()
        self.output_card.setObjectName("previewCard")
        output_layout = QVBoxLayout(self.output_card)
        output_layout.setContentsMargins(13, 12, 13, 13)
        output_layout.setSpacing(10)
        heading_row = QHBoxLayout()
        self.output_heading = QLabel("Prérendu / rendu")
        self.output_heading.setObjectName("sectionTitle")
        self.preview_quality = QLabel("Sélectionnez une œuvre")
        self.preview_quality.setObjectName("previewBadge")
        heading_row.addWidget(self.output_heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.preview_quality)
        output_layout.addLayout(heading_row)

        self.output_stack = QStackedWidget()
        self.live_preview = ScaledImageLabel(
            "Le film se dessinera ici pendant le rendu, puis sera lisible à la fin."
        )
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(260, 260)
        self.video_widget.setStyleSheet("background:#10131a; border-radius:10px;")
        self.output_stack.addWidget(self.live_preview)
        self.output_stack.addWidget(self.video_widget)
        output_layout.addWidget(self.output_stack, 1)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setMuted(True)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.video_actions = QWidget()
        action_layout = QHBoxLayout(self.video_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton("Pause")
        self.open_folder_button = QPushButton("Ouvrir le dossier")
        action_layout.addWidget(self.play_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.open_folder_button)
        self.video_actions.hide()
        output_layout.addWidget(self.video_actions)

        layout = QHBoxLayout()
        layout.setSpacing(16)
        layout.addWidget(self.source_preview, 1)
        layout.addWidget(self.output_card, 1)
        return layout

    def _build_controls(self) -> QScrollArea:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(390)
        card.setMaximumWidth(450)
        content = QVBoxLayout(card)
        content.setContentsMargins(18, 16, 18, 18)
        content.setSpacing(12)

        title = QLabel("Paramètres")
        title.setObjectName("sectionTitle")
        content.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        descriptors = effect_descriptors()
        self._effect_descriptors = {descriptor.key: descriptor for descriptor in descriptors}
        self.effect_combo = self._combo(
            tuple((descriptor.selector_label, descriptor.key) for descriptor in descriptors)
        )
        for index, descriptor in enumerate(descriptors):
            self.effect_combo.setItemData(
                index,
                descriptor.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        self.order_combo = self._combo(
            (
                ("Roue chromatique — sens horaire", "chromatic"),
                ("Roue chromatique — sens antihoraire", "reverse"),
                ("Surfaces — grandes zones d’abord", "area"),
                ("Lumière — clair vers sombre", "luminance"),
            )
        )
        self.neutral_combo = self._combo(
            (("Après les couleurs", "last"), ("Avant les couleurs", "first"))
        )
        self.outline_combo = self._combo(
            (
                ("À la fin — dessin de clôture", "last"),
                ("Au début — structure d’abord", "first"),
                ("Progressifs — avec les couleurs", "together"),
            )
        )
        self.format_combo = self._combo(
            (("MP4 — H.264", ".mp4"), ("WebM — VP9", ".webm"), ("MOV — H.264", ".mov"))
        )

        self.width_spin = self._slider(320, 3840, 1280, 160, 0, " px", "Largeur de la vidéo exportée")
        self.duration_spin = self._slider(3.0, 120.0, 12.0, 0.5, 1, " s", "Durée totale, pauses incluses")
        self.fps_spin = self._slider(12, 60, 30, 1, 0, " i/s", "Fluidité de la vidéo")
        self.colors_spin = self._slider(4, 64, 24, 1, 0, "", "Nombre de nuances analysées")
        self.shape_completion = self._slider(
            0,
            4,
            2,
            1,
            0,
            "",
            "Complète les petits trous dans les aplats sans modifier l’image finale",
        )
        self.background_tolerance = self._slider(
            0.0,
            30.0,
            11.0,
            0.5,
            1,
            " ΔE",
            "Tolérance utilisée pour séparer le fond de l’œuvre",
        )
        self.outline_luma = self._slider(
            0,
            70,
            36,
            1,
            0,
            " L*",
            "Luminosité maximale reconnue comme contour sombre",
        )
        self.overlap_slider = self._slider(
            0.0,
            0.8,
            0.16,
            0.02,
            2,
            "",
            "Chevauchement temporel entre deux familles de couleurs",
        )
        self.seed_spin = self._slider(0, 9999, 7, 1, 0, "", "Graine du mouvement déterministe")

        form.addRow("Animation", self.effect_combo)
        form.addRow("Séquence", self.order_combo)
        form.addRow("Noir & blanc", self.neutral_combo)
        form.addRow("Contours", self.outline_combo)
        form.addRow("Format", self.format_combo)
        content.addLayout(form)

        self.mode_description = QLabel()
        self.mode_description.setObjectName("helperText")
        self.mode_description.setWordWrap(True)
        content.addWidget(self.mode_description)
        self.order_description = QLabel()
        self.order_description.setObjectName("helperText")
        self.order_description.setWordWrap(True)
        content.addWidget(self.order_description)

        self.sequence_panel = QFrame()
        self.sequence_panel.setObjectName("sequenceCard")
        sequence_layout = QVBoxLayout(self.sequence_panel)
        sequence_layout.setContentsMargins(10, 10, 10, 10)
        sequence_layout.setSpacing(4)
        sequence_title = QLabel("Séquence chromatique")
        sequence_title.setObjectName("sectionTitle")
        sequence_layout.addWidget(sequence_title)
        sequence_help = QLabel("Glissez la roue : la couleur placée sous 1 ouvre l’animation.")
        sequence_help.setObjectName("muted")
        sequence_help.setWordWrap(True)
        sequence_layout.addWidget(sequence_help)
        self.chromatic_wheel = ChromaticSequenceWheel()
        sequence_layout.addWidget(self.chromatic_wheel)
        content.addWidget(self.sequence_panel)

        quality_title = QLabel("Qualité & sortie")
        quality_title.setObjectName("sectionTitle")
        content.addWidget(quality_title)
        quality_form = QFormLayout()
        quality_form.setHorizontalSpacing(12)
        quality_form.setVerticalSpacing(9)
        quality_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        quality_form.addRow("Largeur", self.width_spin)
        quality_form.addRow("Durée", self.duration_spin)
        quality_form.addRow("Fluidité", self.fps_spin)
        quality_form.addRow("Nuances", self.colors_spin)
        quality_form.addRow("Formes complètes", self.shape_completion)
        quality_form.addRow("Fond", self.background_tolerance)
        quality_form.addRow("Seuil contour", self.outline_luma)
        quality_form.addRow("Chevauchement", self.overlap_slider)
        quality_form.addRow("Graine", self.seed_spin)
        content.addLayout(quality_form)

        mode_title = QLabel("Réglages du mouvement")
        mode_title.setObjectName("sectionTitle")
        content.addWidget(mode_title)
        self.mode_stack = QStackedWidget()
        self._effect_controls: dict[str, dict[str, QWidget]] = {}
        self._effect_page_indexes: dict[str, int] = {}
        for descriptor in descriptors:
            page, controls = self._build_effect_page(descriptor)
            self._effect_controls[descriptor.key] = controls
            self._effect_page_indexes[descriptor.key] = self.mode_stack.addWidget(page)
        content.addWidget(self.mode_stack)

        output_title = QLabel("Nom du fichier")
        output_title.setObjectName("sectionTitle")
        content.addWidget(output_title)
        self.output_name = QLineEdit("animation-sand.mp4")
        self.output_name.setPlaceholderText("mon-animation.mp4")
        content.addWidget(self.output_name)
        content.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(card)
        scroll.setMinimumWidth(410)
        scroll.setMaximumWidth(470)
        return scroll

    def _build_effect_page(
        self,
        descriptor: EffectDescriptor,
    ) -> tuple[QWidget, dict[str, QWidget]]:
        """Build one effect page entirely from its validated JSON documentation."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        controls: dict[str, QWidget] = {}
        for parameter in descriptor.parameters:
            if parameter.control == "choice":
                control: QWidget = self._combo(
                    tuple((choice.label, choice.value) for choice in parameter.choices)
                )
            else:
                if None in {
                    parameter.minimum,
                    parameter.maximum,
                    parameter.default,
                    parameter.step,
                }:
                    raise ValueError(f"Slider incomplet : {descriptor.key}/{parameter.key}")
                control = self._slider(
                    parameter.minimum,
                    parameter.maximum,
                    parameter.default,
                    parameter.step,
                    parameter.decimals,
                    parameter.suffix,
                    parameter.description,
                )
            control.setToolTip(parameter.description)
            label = QLabel(parameter.label)
            label.setToolTip(parameter.description)
            form.addRow(label, control)
            controls[parameter.key] = control
        return page, controls

    def _build_progress(self) -> QFrame:
        card = QFrame()
        card.setObjectName("progressCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)
        status_column = QVBoxLayout()
        status_column.setSpacing(5)
        self.status_label = QLabel("Prêt à créer votre animation.")
        self.status_label.setObjectName("muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        status_column.addWidget(self.status_label)
        status_column.addWidget(self.progress_bar)
        layout.addLayout(status_column, 1)
        self.percent_label = QLabel("0 %")
        self.percent_label.setObjectName("sectionTitle")
        self.percent_label.setMinimumWidth(48)
        layout.addWidget(self.percent_label)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.hide()
        self.generate_button = QPushButton("Créer la vidéo")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.setDefault(True)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.generate_button)
        return card

    @staticmethod
    def _combo(items: tuple[tuple[str, str], ...]) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        return combo

    @staticmethod
    def _slider(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        decimals: int,
        suffix: str = "",
        description: str = "",
    ) -> ParameterSlider:
        return ParameterSlider(
            minimum,
            maximum,
            value,
            step,
            decimals,
            suffix,
            description,
        )

    def _connect_signals(self) -> None:
        self.source_zone.path_selected.connect(self._source_selected)
        self.destination_zone.path_selected.connect(self._destination_selected)
        self.effect_combo.currentIndexChanged.connect(self._effect_changed)
        self.order_combo.currentIndexChanged.connect(self._order_changed)
        self.neutral_combo.currentIndexChanged.connect(self._neutral_changed)
        self.outline_combo.currentIndexChanged.connect(self._outline_changed)
        self.chromatic_wheel.hueChanged.connect(self._hue_changed)
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        self.output_name.textEdited.connect(self._filename_edited)
        self.generate_button.clicked.connect(self._start_render)
        self.cancel_button.clicked.connect(self._cancel_render)
        self.play_button.clicked.connect(self._toggle_playback)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        self.log_button.clicked.connect(self._show_logs)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._media_error)
        self.history_panel.play_requested.connect(self._play_history)
        self.history_panel.reveal_requested.connect(self._reveal_history_file)
        self.history_panel.delete_requested.connect(self._delete_history_video)
        self.history_panel.directory_requested.connect(self._open_destination_folder)
        self.workspace_tabs.currentChanged.connect(self._workspace_tab_changed)

        preview_combos = (
            self.effect_combo,
            self.order_combo,
            self.neutral_combo,
            self.outline_combo,
        )
        for combo in preview_combos:
            combo.currentIndexChanged.connect(lambda *_: self._schedule_preview())
        preview_sliders = (
            self.width_spin,
            self.duration_spin,
            self.fps_spin,
            self.colors_spin,
            self.shape_completion,
            self.background_tolerance,
            self.outline_luma,
            self.overlap_slider,
            self.seed_spin,
        )
        for slider in preview_sliders:
            slider.valueChanged.connect(lambda *_: self._schedule_preview())
        for controls in self._effect_controls.values():
            for control in controls.values():
                if isinstance(control, QComboBox):
                    control.currentIndexChanged.connect(
                        lambda *_: self._schedule_preview()
                    )
                elif isinstance(control, ParameterSlider):
                    control.valueChanged.connect(lambda *_: self._schedule_preview())
        self.chromatic_wheel.hueChanged.connect(lambda *_: self._schedule_preview())

    def _show_logs(self) -> None:
        self._unread_logs = 0
        self.log_button.setText("Logs")
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def _receive_log_record(self, record: logging.LogRecord) -> None:
        self.log_window.append_record(record)
        if record.levelno >= logging.WARNING and not self.log_window.isVisible():
            self._unread_logs += 1
            self.log_button.setText(f"Logs ({self._unread_logs})")

    def _restore_destination(self) -> None:
        saved = self.settings.value("destination", "", str)
        if saved and Path(saved).is_dir():
            self.destination_zone.set_path(saved)
        self.history_panel.set_directory(self.destination_zone.path)

    def _source_selected(self, value: str) -> None:
        path = Path(value)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            logger.error("Aperçu impossible pour l’image : %s", path)
            QMessageBox.warning(self, "Image illisible", "Cette image ne peut pas être affichée.")
            return
        self.source_preview.image.set_image(pixmap)
        logger.info("Image sélectionnée : %s", path.resolve())
        if self.destination_zone.path is None:
            self.destination_zone.set_path(path.parent)
        self.history_panel.set_directory(self.destination_zone.path)
        self._auto_filename = True
        self._suggest_filename()
        self._schedule_preview(120)

    def _destination_selected(self, value: str) -> None:
        destination = Path(value)
        self.history_panel.set_directory(destination)
        self.settings.setValue("destination", str(destination.resolve()))
        logger.info("Dossier de destination sélectionné : %s", destination.resolve())

    def _filename_edited(self) -> None:
        self._auto_filename = False

    def _effect_changed(self) -> None:
        effect = str(self.effect_combo.currentData())
        descriptor = self._effect_descriptors[effect]
        self.mode_stack.setCurrentIndex(self._effect_page_indexes[effect])
        self.mode_description.setText(descriptor.description)
        self.effect_combo.setToolTip(descriptor.description)
        logger.info("Mode sélectionné : %s", effect)
        if hasattr(self, "sequence_panel"):
            self._order_changed()
        if self._auto_filename:
            self._suggest_filename()

    def _order_changed(self) -> None:
        order = str(self.order_combo.currentData())
        effect = str(self.effect_combo.currentData())
        descriptor = self._effect_descriptors[effect]
        uses_wheel = order in {"chromatic", "reverse"} and descriptor.supports(
            EffectCapability.CHROMATIC_SEQUENCE
        )
        self.sequence_panel.setVisible(uses_wheel)
        self.neutral_combo.setEnabled(uses_wheel)
        self.chromatic_wheel.setReverse(order == "reverse")
        descriptions = {
            "chromatic": "Les couleurs suivent les numéros 1 → 6 dans le sens horaire.",
            "reverse": "Les couleurs suivent les numéros 1 → 6 dans le sens antihoraire.",
            "area": "Les plus grandes surfaces sont dessinées avant les détails.",
            "luminance": "Les zones claires apparaissent avant les zones sombres.",
        }
        self.order_description.setText(descriptions[order])
        logger.info("Séquence sélectionnée : %s", order)

    def _neutral_changed(self) -> None:
        position = str(self.neutral_combo.currentData())
        self.chromatic_wheel.setNeutralPosition(position)
        logger.info("Position des neutres : %s", position)

    def _outline_changed(self) -> None:
        mode = str(self.outline_combo.currentData())
        self.chromatic_wheel.setOutlineMode(mode)
        logger.info("Mode des contours : %s", mode)

    def _hue_changed(self, hue: float) -> None:
        logger.info("Départ de la roue chromatique : %.1f°", hue)

    def _format_changed(self) -> None:
        suffix = str(self.format_combo.currentData())
        current = Path(self.output_name.text().strip() or "animation")
        self.output_name.setText(current.with_suffix(suffix).name)

    def _suggest_filename(self) -> None:
        source = self.source_zone.path
        stem = source.stem if source else "animation"
        effect = str(self.effect_combo.currentData())
        suffix = str(self.format_combo.currentData())
        self.output_name.setText(f"{stem}-{effect}{suffix}")

    def build_config(self) -> RenderConfig:
        effect = str(self.effect_combo.currentData())
        values = {
            "effect": effect,
            "order": str(self.order_combo.currentData()),
            "neutral_position": str(self.neutral_combo.currentData()),
            "start_hue": self.chromatic_wheel.startHue(),
            "outline": str(self.outline_combo.currentData()),
            "duration": self.duration_spin.value(),
            "fps": self.fps_spin.value(),
            "width": self.width_spin.value(),
            "colors": self.colors_spin.value(),
            "shape_completion": self.shape_completion.value(),
            "background_tolerance": self.background_tolerance.value(),
            "outline_luma": self.outline_luma.value(),
            "overlap": self.overlap_slider.value(),
            "seed": self.seed_spin.value(),
        }
        for field_name, control in self._effect_controls[effect].items():
            if isinstance(control, QComboBox):
                values[field_name] = str(control.currentData())
            elif isinstance(control, ParameterSlider):
                values[field_name] = control.value()
            else:
                raise TypeError(f"Contrôle de paramètre non pris en charge : {field_name}")
        return RenderConfig.from_dict({**RenderConfig().to_dict(), **values})

    def _force_preview(self) -> None:
        self.workspace_tabs.setCurrentIndex(0)
        self._schedule_preview(0)

    def _refresh_history(self) -> None:
        self._history_records = self.history_store.load()
        self.history_panel.set_records(self._history_records)
        self.history_panel.set_directory(self.destination_zone.path)
        logger.info("Banque de générations actualisée")

    def _open_destination_folder(self) -> None:
        folder = self.destination_zone.path
        if folder is None or not folder.is_dir():
            logger.warning("Explorateur demandé sans destination valide")
            QMessageBox.information(
                self,
                "Destination manquante",
                "Choisissez d’abord un dossier de destination.",
            )
            return
        logger.info("Ouverture de la destination : %s", folder.resolve())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _open_history_data(self) -> None:
        try:
            self.history_store.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Dossier d’historique inaccessible : %s", exc)
            QMessageBox.warning(self, "Historique inaccessible", str(exc))
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.history_store.root.resolve()))
        )

    def _schedule_preview(self, delay_ms: int = 450) -> None:
        if self.source_zone.path is None or self._worker is not None:
            return
        self._preview_revision += 1
        if self._preview_worker is not None:
            self._preview_worker.cancel()
        self._preview_debounce.start(max(0, delay_ms))

    def _begin_preview(self) -> None:
        source = self.source_zone.path
        if source is None or self._worker is not None or self._closing_for_preview:
            return
        if self._preview_thread is not None:
            self._preview_pending = True
            if self._preview_worker is not None:
                self._preview_worker.cancel()
            return
        try:
            config = self.build_config()
        except ValueError as exc:
            logger.warning("Prérendu ignoré, paramètres invalides : %s", exc)
            self.preview_quality.setText("Paramètres invalides")
            return

        revision = self._preview_revision
        self.player.stop()
        self._preview_playback.stop()
        self._preview_frames = ()
        self.output_stack.setCurrentWidget(self.live_preview)
        self.video_actions.hide()
        self.output_heading.setText("Prérendu de l’effet")
        self.preview_quality.setText("Calcul basse définition…")
        self.live_preview.clear_image("Mise à jour du prérendu…")

        thread = QThread(self)
        worker = PreviewWorker(source, config, revision)
        self._preview_thread = thread
        self._preview_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(self._preview_ready)
        worker.failed.connect(self._preview_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._preview_thread_finished)
        thread.start()

    def _preview_ready(
        self,
        revision: int,
        frames: object,
        quality: str,
    ) -> None:
        if revision != self._preview_revision or not isinstance(frames, tuple):
            return
        self._preview_frames = frames
        self._preview_frame_index = 0
        self.output_heading.setText("Prérendu de l’effet")
        self.preview_quality.setText(quality)
        self._advance_preview()
        self._preview_playback.start()

    def _preview_failed(self, revision: int, message: str) -> None:
        if revision != self._preview_revision:
            return
        self.preview_quality.setText("Prérendu indisponible")
        self.live_preview.clear_image(f"Prérendu impossible : {message}")

    def _advance_preview(self) -> None:
        if not self._preview_frames:
            return
        frame = self._preview_frames[self._preview_frame_index]
        self.live_preview.set_image(QPixmap.fromImage(frame))
        self._preview_frame_index = (self._preview_frame_index + 1) % len(
            self._preview_frames
        )

    def _preview_thread_finished(self) -> None:
        thread = self._preview_thread
        self._preview_worker = None
        self._preview_thread = None
        if thread is not None:
            thread.deleteLater()
        if self._closing_for_preview:
            QTimer.singleShot(0, self.close)
            return
        if self._preview_pending:
            self._preview_pending = False
            self._preview_debounce.start(40)

    def _suspend_preview(self) -> None:
        self._preview_revision += 1
        self._preview_pending = False
        self._preview_debounce.stop()
        self._preview_playback.stop()
        self._preview_frames = ()
        if self._preview_worker is not None:
            self._preview_worker.cancel()

    def _capture_render_thumbnail(self, image: QImage) -> None:
        self._render_thumbnail = image.scaled(
            480,
            270,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _record_generation(self) -> None:
        if self._last_video is None or self._render_source is None or self._render_config is None:
            logger.warning("Génération terminée sans contexte d’historique complet")
            return
        descriptor = self._effect_descriptors[self._render_config.effect]
        try:
            self.history_store.add(
                self._last_video,
                self._render_source,
                self._render_config,
                descriptor.selector_label,
                self._render_thumbnail,
            )
            self._history_records = self.history_store.load()
            self.history_panel.set_records(self._history_records)
        except OSError:
            logger.exception("Impossible d’enregistrer la génération dans l’historique")

    def _play_history(self, output: str) -> None:
        path = Path(output)
        if not path.is_file():
            logger.warning("Vidéo historique introuvable : %s", path)
            QMessageBox.warning(
                self,
                "Vidéo introuvable",
                "Cette génération a été déplacée ou supprimée de son dossier de destination.",
            )
            return
        self._suspend_preview()
        self._last_video = path.resolve()
        self.output_heading.setText("Génération de l’historique")
        self.preview_quality.setText(path.name)
        self.player.setSource(QUrl.fromLocalFile(str(self._last_video)))
        self.video_actions.show()
        self.player.play()
        self.status_label.setText(f"Lecture historique : {path.name}")
        logger.info("Lecture depuis l’historique : %s", path.resolve())

    def _reveal_history_file(self, output: str) -> None:
        path = Path(output).resolve()
        if sys.platform == "win32" and path.parent.is_dir():
            logger.info("Sélection dans l’Explorateur Windows : %s", path)
            QProcess.startDetached(
                "explorer.exe",
                ["/select,", QDir.toNativeSeparators(str(path))],
            )
            return
        if path.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _delete_history_video(self, output: str) -> None:
        path = Path(output).resolve()
        if path.is_file():
            answer = QMessageBox.warning(
                self,
                "Supprimer définitivement la vidéo ?",
                f"{path.name} sera supprimée du disque et de l’historique. "
                "Cette action est irréversible.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                logger.info("Suppression historique annulée : %s", path)
                return
            is_current = (
                self._last_video is not None and self._last_video.resolve() == path
            )
            if is_current:
                self.player.stop()
                self.player.setSource(QUrl())
            try:
                path.unlink()
            except OSError as exc:
                logger.exception("Suppression de vidéo impossible : %s", path)
                QMessageBox.critical(self, "Suppression impossible", str(exc))
                return
            logger.info("Vidéo supprimée par l’utilisateur : %s", path)
        else:
            answer = QMessageBox.question(
                self,
                "Retirer l’entrée ?",
                "Le fichier est déjà introuvable. Retirer cette entrée de l’historique ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.history_store.remove(path)
        except OSError as exc:
            logger.exception("Nettoyage de l’historique impossible")
            QMessageBox.warning(self, "Historique non actualisé", str(exc))
        if self._last_video is not None and self._last_video.resolve() == path:
            self.player.stop()
            self._last_video = None
            self.output_stack.setCurrentWidget(self.live_preview)
            self.video_actions.hide()
            self._schedule_preview(120)
        self._refresh_history()

    def _workspace_tab_changed(self, index: int) -> None:
        if index == 1:
            logger.info("Onglet Studio 3D consulté : fonctionnalité à venir")

    def _start_render(self) -> None:
        source = self.source_zone.path
        destination_dir = self.destination_zone.path
        if source is None:
            logger.warning("Création refusée : aucune image source")
            QMessageBox.information(self, "Œuvre manquante", "Choisissez ou déposez une image source.")
            return
        if destination_dir is None:
            logger.warning("Création refusée : aucun dossier de destination")
            QMessageBox.information(
                self,
                "Destination manquante",
                "Choisissez ou déposez un dossier de destination.",
            )
            return
        name = Path(self.output_name.text().strip()).name
        if not name:
            logger.warning("Création refusée : nom de fichier vide")
            QMessageBox.information(self, "Nom manquant", "Donnez un nom au fichier vidéo.")
            return
        suffix = str(self.format_combo.currentData())
        name = str(Path(name).with_suffix(suffix))
        self.output_name.setText(name)
        destination = destination_dir / name
        if destination.exists():
            answer = QMessageBox.question(
                self,
                "Remplacer la vidéo ?",
                f"{destination.name} existe déjà. Voulez-vous la remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                logger.info("Remplacement de fichier refusé : %s", destination)
                return

        try:
            config = self.build_config()
        except ValueError as exc:
            logger.warning("Paramètres invalides : %s", exc)
            QMessageBox.warning(self, "Paramètres invalides", str(exc))
            return

        self._suspend_preview()
        self._render_source = source.resolve()
        self._render_config = config
        self._render_thumbnail = None
        self.player.stop()
        self.output_heading.setText("Rendu final en cours")
        self.preview_quality.setText(f"{config.width} px · {config.fps} i/s")
        self.output_stack.setCurrentWidget(self.live_preview)
        self.live_preview.clear_image("Analyse de l’œuvre…")
        self.video_actions.hide()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0 %")
        self._set_running(True)

        logger.info("Création lancée : %s -> %s", source, destination)
        self._thread = QThread(self)
        self._worker = RenderWorker(source, destination, config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.preview.connect(self._update_preview)
        self._worker.thumbnail.connect(self._capture_render_thumbnail)
        self._worker.status.connect(self.status_label.setText)
        self._worker.finished.connect(self._render_finished)
        self._worker.cancelled.connect(self._render_cancelled)
        self._worker.failed.connect(self._render_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _set_running(self, running: bool) -> None:
        self.generate_button.setEnabled(not running)
        self.generate_action.setEnabled(not running)
        self.preview_action.setEnabled(not running)
        self.cancel_action.setEnabled(running)
        self.cancel_button.setVisible(running)
        self.source_zone.setEnabled(not running)
        self.destination_zone.setEnabled(not running)

    def _cancel_render(self) -> None:
        if self._worker:
            logger.info("Annulation demandée depuis l’interface")
            self.status_label.setText("Annulation en cours…")
            self.cancel_button.setEnabled(False)
            self._worker.cancel()

    def _update_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)
        self.percent_label.setText(f"{value} %")

    def _update_preview(self, image: QImage) -> None:
        self.live_preview.set_image(QPixmap.fromImage(image))

    def _render_finished(self, output: str) -> None:
        self._last_video = Path(output)
        logger.info("Vidéo prête : %s", self._last_video)
        self._record_generation()
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"Vidéo prête : {self._last_video.name}")
        self.output_heading.setText("Vidéo générée")
        self.preview_quality.setText(self._last_video.name)
        self.progress_bar.setValue(100)
        self.percent_label.setText("100 %")
        self.play_button.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(str(self._last_video)))
        self.video_actions.show()
        self.player.play()

    def _render_cancelled(self) -> None:
        logger.warning("Rendu annulé depuis l’interface")
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Rendu annulé. Aucun fichier partiel conservé.")
        self.progress_bar.setValue(0)
        self.percent_label.setText("0 %")
        self._schedule_preview(120)

    def _render_failed(self, message: str) -> None:
        logger.error("Rendu échoué : %s", message)
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Le rendu a échoué.")
        QMessageBox.critical(self, "Erreur de rendu", message)
        self._schedule_preview(120)

    def _thread_finished(self) -> None:
        thread = self._thread
        self._worker = None
        self._thread = None
        if thread:
            thread.deleteLater()
        if self._close_when_done:
            self.close()

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText(
            "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Lire"
        )

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            self.output_stack.setCurrentWidget(self.video_widget)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()

    def _media_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        logger.warning("Lecture vidéo intégrée indisponible : %s", message)
        self.output_stack.setCurrentWidget(self.live_preview)
        self.play_button.setEnabled(False)
        self.status_label.setText(
            f"Vidéo créée, mais lecture intégrée indisponible : {message}"
        )

    def _open_output_folder(self) -> None:
        if self._last_video:
            logger.info("Ouverture du dossier : %s", self._last_video.parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_video.parent)))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker:
            answer = QMessageBox.question(
                self,
                "Rendu en cours",
                "Annuler le rendu et fermer ArtAnimate ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_when_done = True
            self._cancel_render()
            event.ignore()
            return
        self._preview_debounce.stop()
        self._preview_playback.stop()
        if self._preview_thread is not None and self._preview_thread.isRunning():
            self._closing_for_preview = True
            if self._preview_worker is not None:
                self._preview_worker.cancel()
            event.ignore()
            return
        self.settings.setValue("windowGeometry", self.saveGeometry())
        if self.destination_zone.path:
            self.settings.setValue("destination", str(self.destination_zone.path))
        logger.info("Fermeture de l’interface desktop")
        self.log_window.allow_close()
        self.log_window.close()
        detach_handler(self.log_handler)
        super().closeEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ArtAnimate")
    app.setOrganizationName("ArtAnimate")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyleSheet(APP_STYLESHEET)
    log_path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "artanimate.log"
    startup_warning = None
    try:
        configure_file_logging(log_path, logging.INFO)
    except OSError as exc:
        startup_warning = f"Journal persistant indisponible : {exc}"
        log_path = None
    logger.info("Démarrage du client desktop")
    window = MainWindow(log_path, startup_warning)
    window.show()
    result = app.exec()
    logger.info("Arrêt du client desktop")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

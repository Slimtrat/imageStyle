from __future__ import annotations

import logging
import os
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
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..branding import LOGO_PATH
from ..core.config import RenderConfig
from ..core.effects import EffectCapability, EffectDescriptor, effect_descriptors
from ..core.video import VideoFrameEncoder
from ..observability import attach_handler, configure_file_logging, detach_handler
from .controls import ChromaticSequenceWheel, ParameterSlider
from .history import GenerationHistory
from .history_widgets import HistoryPanel
from .log_window import LogWindow, QtLogHandler
from .preview import PREVIEW_INTERVAL_MS, PreviewWorker
from .settings_windows import SettingsCard, SettingsDialog
from .studio3d import Studio3DPanel
from .studio3d_export import Studio3DFrameWorker, capture_requires_retry, qimage_to_rgb
from .problems import (
    UserInputError,
    UserProblem,
    translate_exception,
    validate_destination_path,
    validate_render_paths,
    validate_source_path,
)
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
        self.setWindowTitle(f"ArtAnimate {__version__} — Atelier d’animation")
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
        self._studio_preview_frames: tuple[QImage, ...] = ()
        self._preview_progresses: tuple[float, ...] = ()
        self._preview_frame_index = 0
        self._closing_for_preview = False
        self._render_source: Path | None = None
        self._render_config: RenderConfig | None = None
        self._render_thumbnail: QImage | None = None
        self._studio_thread: QThread | None = None
        self._studio_worker: Studio3DFrameWorker | None = None
        self._studio_encoder: VideoFrameEncoder | None = None
        self._studio_pending_frame: tuple[int, int] | None = None
        self._studio_capture_retries = 0
        self._studio_failure: UserProblem | None = None
        self._studio_source: Path | None = None
        self._studio_output: Path | None = None
        self._studio_config: RenderConfig | None = None
        self._studio_thumbnail: QImage | None = None
        self._studio_output_size = (1280, 720)

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
        self.workspace_tabs.addTab(self._build_studio_3d(), "Studio 3D")
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

        settings_menu = menu_bar.addMenu("&Réglages")
        settings_specs = (
            ("effect", "Effet & mouvement…", "Ctrl+1"),
            ("colors", "Couleurs & séquence…", "Ctrl+2"),
            ("analysis", "Analyse de l’œuvre…", "Ctrl+3"),
            ("video", "Vidéo & fichier…", "Ctrl+4"),
        )
        self.settings_actions: dict[str, QAction] = {}
        for key, label, shortcut in settings_specs:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(
                lambda _checked=False, selected=key: self._open_settings(selected)
            )
            settings_menu.addAction(action)
            self.settings_actions[key] = action

        view_menu = menu_bar.addMenu("&Affichage")
        show_2d = QAction("Atelier 2D", self)
        show_2d.triggered.connect(lambda: self.workspace_tabs.setCurrentIndex(0))
        show_3d = QAction("Studio 3D", self)
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

    def _build_studio_3d(self) -> QWidget:
        self.studio_3d = Studio3DPanel()
        self.studio_3d.choose_source_requested.connect(self.source_zone.browse)
        self.studio_3d.choose_destination_requested.connect(
            self.destination_zone.browse
        )
        self.studio_3d.refresh_preview_requested.connect(
            lambda: self._schedule_preview(0)
        )
        self.studio_3d.effect_selected.connect(self._studio_effect_selected)
        self.studio_3d.edit_effect_requested.connect(
            self._open_studio_effect_settings
        )
        self.studio_3d.export_requested.connect(self._start_studio_render)
        self.studio_3d.cancel_export_requested.connect(self._cancel_studio_render)
        self.studio_3d.play_output_requested.connect(self._play_studio_output)
        self.studio_3d.reveal_output_requested.connect(self._reveal_studio_output)
        return self.studio_3d

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
        self.version_badge = QLabel(f"VERSION {__version__}")
        self.version_badge.setObjectName("versionBadge")
        self.version_badge.setToolTip("Version installée d’ArtAnimate")
        text.addWidget(self.version_badge)
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

    def _build_controls(self) -> QWidget:
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
                ("Progressifs — avec les couleurs", "together"),
                ("À la fin — dessin de clôture", "last"),
                ("Au début — structure d’abord", "first"),
            )
        )
        self.format_combo = self._combo(
            (("MP4 — H.264", ".mp4"), ("WebM — VP9", ".webm"), ("MOV — H.264", ".mov"))
        )
        self.quality_combo = self._combo(
            (
                ("Studio — fluide et détaillé", "studio"),
                ("Rapide — rendu direct", "fast"),
            )
        )
        self.quality_combo.setToolTip(
            "Studio lisse chaque image dans le temps et optimise l’encodage des aplats."
        )

        self.width_spin = self._slider(320, 3840, 1280, 160, 0, " px", "Largeur de la vidéo exportée")
        self.duration_spin = self._slider(3.0, 120.0, 18.0, 0.5, 1, " s", "Durée totale, pauses incluses · 18 s offre un mouvement posé")
        self.fps_spin = self._slider(12, 60, 30, 1, 0, " i/s", "Fluidité de la vidéo")
        self.colors_spin = self._slider(4, 64, 24, 1, 0, "", "Nombre de nuances analysées")
        self.shape_completion = self._slider(
            0, 4, 2, 1, 0, "",
            "Complète les petits trous dans les aplats sans modifier l’image finale",
        )
        self.background_tolerance = self._slider(
            0.0, 30.0, 11.0, 0.5, 1, " ΔE",
            "Tolérance utilisée pour séparer le fond de l’œuvre",
        )
        self.outline_luma = self._slider(
            0, 70, 36, 1, 0, " L*",
            "Luminosité maximale reconnue comme contour sombre",
        )
        self.overlap_slider = self._slider(
            0.0, 0.8, 0.28, 0.02, 2, "",
            "Chevauchement temporel entre deux familles de couleurs",
        )
        self.seed_spin = self._slider(
            0, 9999, 7, 1, 0, "", "Graine du mouvement déterministe"
        )

        self.mode_description = QLabel()
        self.mode_description.setObjectName("helperText")
        self.mode_description.setWordWrap(True)
        self.order_description = QLabel()
        self.order_description.setObjectName("helperText")
        self.order_description.setWordWrap(True)

        self.mode_stack = QStackedWidget()
        self.mode_stack.setObjectName("effectModeStack")
        self._effect_controls: dict[str, dict[str, QWidget]] = {}
        self._effect_page_indexes: dict[str, int] = {}
        for descriptor in descriptors:
            page, controls = self._build_effect_page(descriptor)
            self._effect_controls[descriptor.key] = controls
            self._effect_page_indexes[descriptor.key] = self.mode_stack.addWidget(page)

        self.sequence_panel = QFrame()
        self.sequence_panel.setObjectName("sequenceCard")
        sequence_layout = QVBoxLayout(self.sequence_panel)
        sequence_layout.setContentsMargins(14, 14, 14, 14)
        sequence_layout.setSpacing(7)
        sequence_title = QLabel("Séquence chromatique interactive")
        sequence_title.setObjectName("sectionTitle")
        sequence_layout.addWidget(sequence_title)
        sequence_help = QLabel(
            "Tournez la roue : la couleur placée sous 1 ouvre l’animation, "
            "puis les secteurs 2 à 6 suivent."
        )
        sequence_help.setObjectName("muted")
        sequence_help.setWordWrap(True)
        sequence_layout.addWidget(sequence_help)
        self.chromatic_wheel = ChromaticSequenceWheel()
        self.chromatic_wheel.setMinimumSize(410, 450)
        self.chromatic_wheel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        sequence_layout.addWidget(self.chromatic_wheel, 1)

        self.output_name = QLineEdit("animation-sand.mp4")
        self.output_name.setPlaceholderText("mon-animation.mp4")

        effect_content = QWidget()
        effect_layout = QVBoxLayout(effect_content)
        effect_layout.setContentsMargins(4, 4, 4, 4)
        effect_layout.setSpacing(14)
        effect_form = QFormLayout()
        effect_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        effect_form.addRow("Animation", self.effect_combo)
        effect_layout.addLayout(effect_form)
        effect_layout.addWidget(self.mode_description)
        effect_title = QLabel("Réglages propres à l’effet")
        effect_title.setObjectName("sectionTitle")
        effect_layout.addWidget(effect_title)
        effect_layout.addWidget(self.mode_stack)
        seed_form = QFormLayout()
        seed_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        seed_form.addRow("Variation", self.seed_spin)
        effect_layout.addLayout(seed_form)
        effect_layout.addStretch(1)

        color_content = QWidget()
        color_layout = QVBoxLayout(color_content)
        color_layout.setContentsMargins(4, 4, 4, 4)
        color_layout.setSpacing(12)
        color_form = QFormLayout()
        color_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        color_form.addRow("Séquence", self.order_combo)
        color_form.addRow("Noir & blanc", self.neutral_combo)
        color_form.addRow("Contours", self.outline_combo)
        color_layout.addLayout(color_form)
        color_layout.addWidget(self.order_description)
        color_layout.addWidget(self.sequence_panel, 1)
        overlap_form = QFormLayout()
        overlap_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        overlap_form.addRow("Chevauchement", self.overlap_slider)
        color_layout.addLayout(overlap_form)

        analysis_content = QWidget()
        analysis_layout = QVBoxLayout(analysis_content)
        analysis_layout.setContentsMargins(4, 4, 4, 4)
        analysis_layout.setSpacing(12)
        analysis_help = QLabel(
            "Ces réglages définissent comment ArtAnimate reconnaît les aplats, "
            "complète leurs formes et isole le fond et les contours."
        )
        analysis_help.setObjectName("helperText")
        analysis_help.setWordWrap(True)
        analysis_layout.addWidget(analysis_help)
        analysis_form = QFormLayout()
        analysis_form.setVerticalSpacing(13)
        analysis_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        analysis_form.addRow("Nuances", self.colors_spin)
        analysis_form.addRow("Formes complètes", self.shape_completion)
        analysis_form.addRow("Séparation du fond", self.background_tolerance)
        analysis_form.addRow("Seuil des contours", self.outline_luma)
        analysis_layout.addLayout(analysis_form)
        analysis_layout.addStretch(1)

        video_content = QWidget()
        video_layout = QVBoxLayout(video_content)
        video_layout.setContentsMargins(4, 4, 4, 4)
        video_layout.setSpacing(12)
        video_form = QFormLayout()
        video_form.setVerticalSpacing(13)
        video_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        video_form.addRow("Format", self.format_combo)
        video_form.addRow("Qualité", self.quality_combo)
        video_form.addRow("Largeur", self.width_spin)
        video_form.addRow("Durée", self.duration_spin)
        video_form.addRow("Fluidité", self.fps_spin)
        video_form.addRow("Nom du fichier", self.output_name)
        video_layout.addLayout(video_form)
        video_layout.addStretch(1)

        self._settings_dialogs = {
            "effect": SettingsDialog(
                "Effet & mouvement",
                "Choisissez la matière animée, puis réglez uniquement son comportement.",
                effect_content,
                self,
            ),
            "colors": SettingsDialog(
                "Couleurs & séquence",
                "Construisez l’ordre de révélation. La roue dispose ici de tout l’espace nécessaire.",
                color_content,
                self,
                minimum_width=660,
            ),
            "analysis": SettingsDialog(
                "Analyse de l’œuvre",
                "Ajustez la lecture des formes seulement si le prérendu découpe mal l’image.",
                analysis_content,
                self,
            ),
            "video": SettingsDialog(
                "Vidéo & fichier",
                "Définissez la qualité, la durée et le nom du fichier final.",
                video_content,
                self,
            ),
        }
        self._settings_dialogs["colors"].resize(720, 820)

        sidebar = QFrame()
        sidebar.setObjectName("card")
        sidebar.setMinimumWidth(315)
        sidebar.setMaximumWidth(350)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(10)
        title = QLabel("Réglages")
        title.setObjectName("sectionTitle")
        helper = QLabel("Ouvrez un panneau. Chaque choix actualise le prérendu.")
        helper.setObjectName("muted")
        helper.setWordWrap(True)
        sidebar_layout.addWidget(title)
        sidebar_layout.addWidget(helper)

        card_specs = (
            ("effect", "Effet & mouvement", "Choisir le mode et son comportement"),
            ("colors", "Couleurs & séquence", "Ordre, roue, neutres et contours"),
            ("analysis", "Analyse de l’œuvre", "Nuances, formes, fond et contours"),
            ("video", "Vidéo & fichier", "Format, dimensions, durée et nom"),
        )
        self._settings_cards: dict[str, SettingsCard] = {}
        for key, label, description in card_specs:
            panel = SettingsCard(label, description)
            panel.clicked.connect(
                lambda _checked=False, selected=key: self._open_settings(selected)
            )
            self._settings_cards[key] = panel
            sidebar_layout.addWidget(panel)
        sidebar_layout.addStretch(1)
        shortcut_help = QLabel("Raccourcis : Ctrl+1 à Ctrl+4")
        shortcut_help.setObjectName("muted")
        sidebar_layout.addWidget(shortcut_help)
        self._update_settings_summaries()
        return sidebar

    def _build_effect_page(
        self,
        descriptor: EffectDescriptor,
    ) -> tuple[QWidget, dict[str, QWidget]]:
        """Build one effect page entirely from its validated JSON documentation."""
        page = QWidget()
        page.setObjectName("effectModePage")
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
            control.setAccessibleDescription(parameter.description)
            label = QLabel(parameter.label)
            label.setToolTip(parameter.description)
            form.addRow(label, control)
            help_label = QLabel(self._parameter_help_text(parameter))
            help_label.setObjectName("parameterHelp")
            help_label.setWordWrap(True)
            help_label.setToolTip(parameter.description)
            form.addRow(help_label)
            controls[parameter.key] = control
        return page, controls

    @staticmethod
    def _parameter_help_text(parameter) -> str:
        """Turn compact JSON metadata into permanent, non-technical guidance."""
        if parameter.control == "choice":
            options = " · ".join(choice.label for choice in parameter.choices)
            return f"{parameter.description} Choix disponibles : {options}."

        def display(value: float | None) -> str:
            if value is None:
                return "—"
            rendered = f"{value:.{parameter.decimals}f}".replace(".", ",")
            return f"{rendered}{parameter.suffix}"

        return (
            f"{parameter.description} Repères : minimum {display(parameter.minimum)} · "
            f"conseillé {display(parameter.default)} · maximum {display(parameter.maximum)}."
        )

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
        self.source_zone.path_rejected.connect(
            lambda problem: self._handle_path_problem(self.source_zone, problem)
        )
        self.destination_zone.path_rejected.connect(
            lambda problem: self._handle_path_problem(
                self.destination_zone, problem
            )
        )
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
                    control.currentIndexChanged.connect(
                        lambda *_: self._sync_studio_effect()
                    )
                elif isinstance(control, ParameterSlider):
                    control.valueChanged.connect(lambda *_: self._schedule_preview())
        self.chromatic_wheel.hueChanged.connect(lambda *_: self._schedule_preview())

        summary_combos = (
            self.effect_combo,
            self.order_combo,
            self.neutral_combo,
            self.outline_combo,
            self.format_combo,
            self.quality_combo,
        )
        for combo in summary_combos:
            combo.currentIndexChanged.connect(
                lambda *_: self._update_settings_summaries()
            )
        for slider in preview_sliders:
            slider.valueChanged.connect(
                lambda *_: self._update_settings_summaries()
            )
        self.chromatic_wheel.hueChanged.connect(
            lambda *_: self._update_settings_summaries()
        )
        self.output_name.textChanged.connect(
            lambda *_: self._update_settings_summaries()
        )

    def _open_settings(self, key: str) -> None:
        self.workspace_tabs.setCurrentIndex(0)
        self._show_settings_dialog(key)

    def _open_studio_effect_settings(self) -> None:
        self._show_settings_dialog("effect")
        logger.info("Réglages de l’effet ouverts depuis le Studio 3D")

    def _show_settings_dialog(self, key: str) -> None:
        for other_key, other_dialog in self._settings_dialogs.items():
            if other_key != key:
                other_dialog.hide()
        dialog = self._settings_dialogs[key]
        dialog.show_raised()
        logger.info("Panneau de réglages ouvert : %s", key)

    def _update_settings_summaries(self) -> None:
        if not hasattr(self, "_settings_cards"):
            return
        effect = str(self.effect_combo.currentData())
        effect_label = self._effect_descriptors[effect].selector_label
        effect_count = len(self._effect_controls[effect])
        self._settings_cards["effect"].setDescription(
            f"{effect_label} · {effect_count} paramètres"
        )
        descriptor = self._effect_descriptors[effect]
        if descriptor.supports(EffectCapability.DETECTED_CONTOURS):
            color_summary = "Trajet automatique · aucun ordre chromatique"
        elif descriptor.supports(EffectCapability.GLOBAL_REVEAL):
            color_summary = "Passage global unique · roue chromatique non utilisée"
        elif descriptor.supports(EffectCapability.FRAME_COMPOSITOR):
            color_summary = "Composition directe · aucun ordre chromatique"
        else:
            order = self.order_combo.currentText().replace(
                "Roue chromatique — ", "Roue · "
            )
            color_summary = f"{order} · départ {self.chromatic_wheel.startHue():.0f}°"
        self._settings_cards["colors"].setDescription(color_summary)
        self._settings_cards["analysis"].setDescription(
            f"{int(self.colors_spin.value())} nuances · formes {int(self.shape_completion.value())}/4"
        )
        profile = self.quality_combo.currentText().split("—", 1)[0].strip()
        self._settings_cards["video"].setDescription(
            f"{profile} · {int(self.width_spin.value())} px · "
            f"{self.duration_spin.value():g} s · {int(self.fps_spin.value())} i/s"
        )

    def _show_problem(self, problem: UserProblem, *, critical: bool = False) -> None:
        if critical:
            logger.error(
                "Problème utilisateur [%s] : %s | action=%s | détails=%s",
                problem.code,
                problem.message,
                problem.action,
                problem.technical_details or "aucun",
            )
        else:
            logger.warning(
                "Problème utilisateur [%s] : %s | action=%s",
                problem.code,
                problem.message,
                problem.action,
            )
        box = QMessageBox(self)
        box.setIcon(
            QMessageBox.Icon.Critical if critical else QMessageBox.Icon.Warning
        )
        box.setWindowTitle(problem.title)
        box.setText(problem.message)
        box.setInformativeText(f"Que faire : {problem.action}")
        if problem.technical_details:
            box.setDetailedText(problem.technical_details)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _handle_path_problem(self, zone: PathDropZone, problem: object) -> None:
        if not isinstance(problem, UserProblem):
            problem = translate_exception(ValueError(str(problem)))
        zone.mark_invalid(problem)
        self.status_label.setText(f"{problem.title} — {problem.action}")
        self._show_problem(problem)

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
        temporary_root = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        ).resolve()
        saved_path = Path(saved).resolve() if saved else None
        if (
            saved_path is not None
            and saved_path.is_dir()
            and not saved_path.is_relative_to(temporary_root)
        ):
            self.destination_zone.set_path(saved_path)
        elif saved:
            self.settings.remove("destination")
            logger.warning("Destination temporaire ou obsolète oubliée : %s", saved)
        self.history_panel.set_directory(self.destination_zone.path)
        self.studio_3d.set_destination(self.destination_zone.path)

    def _source_selected(self, value: str) -> None:
        try:
            path = validate_source_path(Path(value))
        except UserInputError as exc:
            self._handle_path_problem(self.source_zone, exc.problem)
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            problem = UserProblem(
                "source_qt_unreadable",
                "Aperçu de l’image impossible",
                f"Le fichier « {path.name} » est lisible, mais son aperçu ne peut pas être affiché.",
                "Enregistrez une copie PNG ou JPEG de l’œuvre, puis sélectionnez-la.",
                str(path),
            )
            self._handle_path_problem(self.source_zone, problem)
            return
        self.source_preview.image.set_image(pixmap)
        self.studio_3d.set_source(path)
        logger.info("Image sélectionnée : %s", path)
        if self.destination_zone.path is None:
            self.destination_zone.set_path(path.parent)
        self.history_panel.set_directory(self.destination_zone.path)
        self.studio_3d.set_destination(self.destination_zone.path)
        self._auto_filename = True
        self._suggest_filename()
        self._schedule_preview(120)

    def _destination_selected(self, value: str) -> None:
        try:
            destination = validate_destination_path(Path(value))
        except UserInputError as exc:
            self._handle_path_problem(self.destination_zone, exc.problem)
            return
        self.history_panel.set_directory(destination)
        self.studio_3d.set_destination(destination)
        self.settings.setValue("destination", str(destination))
        logger.info("Dossier de destination sélectionné : %s", destination)

    def _filename_edited(self) -> None:
        self._auto_filename = False

    def _effect_changed(self) -> None:
        effect = str(self.effect_combo.currentData())
        descriptor = self._effect_descriptors[effect]
        self.mode_stack.setCurrentIndex(self._effect_page_indexes[effect])
        self.mode_description.setText(descriptor.description)
        self.effect_combo.setToolTip(descriptor.description)
        logger.info("Mode sélectionné : %s", effect)
        self._sync_studio_effect()
        if hasattr(self, "sequence_panel"):
            self._order_changed()
        if self._auto_filename:
            self._suggest_filename()

    def _studio_effect_selected(self, effect: str) -> None:
        effect_index = self.effect_combo.findData(effect)
        if effect_index < 0:
            logger.error("Effet Studio 3D inconnu : %s", effect)
            return
        if effect_index != self.effect_combo.currentIndex():
            self.effect_combo.setCurrentIndex(effect_index)

    def _sync_studio_effect(self) -> None:
        effect = str(self.effect_combo.currentData())
        rgb_mode = "channels"
        direction = "left"
        rgb_control = self._effect_controls.get("rgb_fade", {}).get("rgb_mode")
        direction_control = self._effect_controls.get(effect, {}).get("direction")
        if direction_control is None:
            direction_control = self._effect_controls.get("wave", {}).get("direction")
        halo_control = self._effect_controls.get("vertical_halo", {}).get(
            "halo_direction"
        )
        if isinstance(rgb_control, QComboBox):
            rgb_mode = str(rgb_control.currentData())
        if effect == "vertical_halo" and isinstance(halo_control, QComboBox):
            direction = str(halo_control.currentData())
        elif isinstance(direction_control, QComboBox):
            direction = str(direction_control.currentData())
        self.studio_3d.set_effect(effect, rgb_mode, direction)

    def _order_changed(self) -> None:
        order = str(self.order_combo.currentData())
        effect = str(self.effect_combo.currentData())
        descriptor = self._effect_descriptors[effect]
        direct_compositor = (
            descriptor.supports(EffectCapability.FRAME_COMPOSITOR)
            or descriptor.supports(EffectCapability.DETECTED_CONTOURS)
            or descriptor.supports(EffectCapability.GLOBAL_REVEAL)
        )
        uses_wheel = (
            not direct_compositor
            and order in {"chromatic", "reverse"}
            and descriptor.supports(EffectCapability.CHROMATIC_SEQUENCE)
        )
        self.order_combo.setEnabled(not direct_compositor)
        self.outline_combo.setEnabled(not direct_compositor)
        self.overlap_slider.setEnabled(not direct_compositor)
        self.sequence_panel.setVisible(uses_wheel)
        self.neutral_combo.setEnabled(uses_wheel)
        self.chromatic_wheel.setReverse(order == "reverse")
        descriptions = {
            "chromatic": "Les couleurs suivent les numéros 1 → 6 dans le sens horaire.",
            "reverse": "Les couleurs suivent les numéros 1 → 6 dans le sens antihoraire.",
            "area": "Les plus grandes surfaces sont dessinées avant les détails.",
            "luminance": "Les zones claires apparaissent avant les zones sombres.",
        }
        if direct_compositor:
            if descriptor.supports(EffectCapability.DETECTED_CONTOURS):
                self.order_description.setText(
                    "La découpeuse détecte et ordonne directement les formes : la roue "
                    "chromatique, les neutres et le placement manuel des contours ne "
                    "modifient pas son trajet."
                )
            elif descriptor.supports(EffectCapability.GLOBAL_REVEAL):
                self.order_description.setText(
                    "Pigment Sweep traverse toute l’œuvre en un seul passage. Chaque "
                    "pigment vise son pixel : la roue chromatique, les neutres, le "
                    "chevauchement et l’ordre des contours ne modifient pas ce trajet."
                )
            else:
                self.order_description.setText(
                    f"{descriptor.selector_label} compose l’image entière : ordre "
                    "chromatique, neutres et contours ne sont pas utilisés."
                )
        else:
            self.order_description.setText(descriptions[order])
        self._update_settings_summaries()
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
            "quality": str(self.quality_combo.currentData()),
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
        self._studio_preview_frames = ()
        self._preview_progresses = ()
        self.output_stack.setCurrentWidget(self.live_preview)
        self.video_actions.hide()
        self.output_heading.setText("Prérendu de l’effet")
        self.preview_quality.setText("Calcul basse définition…")
        self.live_preview.clear_image("Mise à jour du prérendu…")
        self.studio_3d.set_loading()

        thread = QThread(self)
        worker = PreviewWorker(source, config, revision)
        self._preview_thread = thread
        self._preview_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(self._preview_ready)
        worker.scene_ready.connect(self._preview_scene_ready)
        worker.failed.connect(self._preview_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._preview_thread_finished)
        thread.start()

    def _preview_scene_ready(self, revision: int, scene_data: object) -> None:
        if revision != self._preview_revision:
            return
        self.studio_3d.set_scene_data(scene_data)

    def _preview_ready(
        self,
        revision: int,
        frames: object,
        studio_frames: object,
        progresses: object,
        quality: str,
    ) -> None:
        if (
            revision != self._preview_revision
            or not isinstance(frames, tuple)
            or not isinstance(studio_frames, tuple)
            or not isinstance(progresses, tuple)
            or len(frames) != len(progresses)
            or len(studio_frames) != len(progresses)
        ):
            return
        self._preview_frames = frames
        self._studio_preview_frames = studio_frames
        self._preview_progresses = progresses
        self._preview_frame_index = 0
        self.output_heading.setText("Prérendu de l’effet")
        self.preview_quality.setText(quality)
        self._advance_preview()
        self._preview_playback.start()

    def _preview_failed(self, revision: int, problem: object) -> None:
        if revision != self._preview_revision:
            return
        if not isinstance(problem, UserProblem):
            problem = translate_exception(
                ValueError(str(problem)),
                "preview",
                source=self.source_zone.path,
            )
        if problem.code.startswith("source_"):
            self.source_zone.mark_invalid(problem)
        self.preview_quality.setText(problem.title)
        self.live_preview.clear_image(problem.display_text)
        self.status_label.setText(f"{problem.title} — {problem.action}")

    def _advance_preview(self) -> None:
        if not self._preview_frames:
            return
        frame_index = self._preview_frame_index
        frame = self._preview_frames[frame_index]
        studio_frame = self._studio_preview_frames[frame_index]
        self.live_preview.set_image(QPixmap.fromImage(frame))
        self.studio_3d.set_frame(
            studio_frame,
            frame_index,
            len(self._preview_frames),
            self._preview_progresses[frame_index],
        )
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
        self._studio_preview_frames = ()
        self._preview_progresses = ()
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
        if index != 1:
            return
        self.studio_3d.activate()
        if self._preview_frames:
            frame_index = self._preview_frame_index % len(self._preview_frames)
            self.studio_3d.set_frame(
                self._studio_preview_frames[frame_index],
                frame_index,
                len(self._preview_frames),
                self._preview_progresses[frame_index],
            )
        elif self.source_zone.path is not None:
            self._schedule_preview(0)
        logger.info("Studio 3D interactif ouvert")

    def _start_studio_render(self) -> None:
        if self._worker is not None or self._studio_worker is not None:
            return
        self.workspace_tabs.setCurrentIndex(1)
        self.studio_3d.activate()
        if self.studio_3d.scene_errors:
            QMessageBox.critical(
                self,
                "Moteur 3D indisponible",
                "Le moteur de scène n’a pas démarré. Consultez les logs pour le détail.",
            )
            return
        settings = self.studio_3d.export_settings()
        try:
            source, destination = validate_render_paths(
                self.source_zone.path,
                self.destination_zone.path,
                settings.output_name,
                settings.suffix,
            )
            config = self.build_config()
        except UserInputError as exc:
            problem = exc.problem
            if problem.code.startswith("source_"):
                self.source_zone.mark_invalid(problem)
            elif problem.code.startswith("destination_"):
                self.destination_zone.mark_invalid(problem)
            self.studio_3d.fail_export(problem.display_text)
            self._show_problem(problem)
            return
        except ValueError as exc:
            problem = translate_exception(exc, "render")
            self.studio_3d.fail_export(problem.display_text)
            self._show_problem(problem)
            return

        if destination.exists():
            answer = QMessageBox.question(
                self,
                "Remplacer la vidéo 3D ?",
                f"{destination.name} existe déjà. Voulez-vous la remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                logger.info("Remplacement du rendu 3D refusé : %s", destination)
                return

        total = max(2, int(round(config.duration * config.fps)))
        try:
            encoder = VideoFrameEncoder(
                destination,
                settings.width,
                settings.height,
                config.fps,
                crf=config.crf,
                quality=config.quality,
                total_frames=total,
            )
            encoder.open()
        except Exception as exc:
            problem = translate_exception(
                exc, "render", source=source, destination=destination.parent
            )
            self.studio_3d.fail_export(problem.display_text)
            self._show_problem(problem, critical=True)
            return

        self._suspend_preview()
        self.player.stop()
        self._studio_encoder = encoder
        self._studio_source = source.resolve()
        self._studio_output = destination.resolve()
        self._studio_config = config
        self._studio_thumbnail = None
        self._studio_failure = None
        self._studio_pending_frame = None
        self._studio_capture_retries = 0
        self._studio_output_size = (settings.width, settings.height)
        studio_direction = (
            config.halo_direction
            if config.effect == "vertical_halo"
            else config.direction
        )
        self.studio_3d.set_effect(config.effect, config.rgb_mode, studio_direction)
        self.studio_3d.begin_export(total)
        self._set_studio_running(True)
        self.status_label.setText("Rendu du Studio 3D en cours…")

        logger.info(
            "Création 3D lancée : %s -> %s, cadre=%dx%d, caméra=%s",
            source,
            destination,
            settings.width,
            settings.height,
            self.studio_3d.camera_state(),
        )
        thread = QThread(self)
        worker = Studio3DFrameWorker(source, config)
        self._studio_thread = thread
        self._studio_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.prepared.connect(self._studio_render_prepared)
        worker.scene_ready.connect(self.studio_3d.set_scene_data)
        worker.frame_ready.connect(self._studio_frame_ready)
        worker.finished.connect(self._studio_render_finished)
        worker.cancelled.connect(self._studio_render_cancelled)
        worker.failed.connect(self._studio_render_failed)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._studio_thread_finished)
        thread.start()

    def _studio_render_prepared(
        self, total: int, texture_width: int, texture_height: int
    ) -> None:
        self.studio_3d.export_status.setText(
            f"Texture {texture_width}×{texture_height} prête · {total} images à capturer"
        )

    def _studio_frame_ready(
        self,
        image: QImage,
        index: int,
        total: int,
        progress: float,
    ) -> None:
        if self._studio_worker is None or self._studio_encoder is None:
            return
        if self._studio_pending_frame is not None:
            self._studio_failure = translate_exception(
                RuntimeError("Deux images 3D attendent simultanément la capture"),
                "render",
                source=self._studio_source,
                destination=(self._studio_output.parent if self._studio_output else None),
            )
            self._studio_worker.cancel()
            return
        self.studio_3d.set_frame(image, index, total, progress)
        self._studio_pending_frame = (index, total)
        self._studio_capture_retries = 0
        QTimer.singleShot(24, self._capture_studio_frame)

    def _capture_studio_frame(self) -> None:
        pending = self._studio_pending_frame
        worker = self._studio_worker
        encoder = self._studio_encoder
        if pending is None or worker is None or encoder is None:
            return
        index, total = pending
        try:
            width, height = self._studio_output_size
            captured = self.studio_3d.capture_frame(width, height)
            rgb_frame = qimage_to_rgb(captured)
            if capture_requires_retry(rgb_frame):
                self._studio_capture_retries += 1
                if self._studio_capture_retries <= 5:
                    logger.warning(
                        "Capture GPU 3D vide à l’image %d/%d · nouvelle tentative %d/5",
                        index + 1,
                        total,
                        self._studio_capture_retries,
                    )
                    QTimer.singleShot(36, self._capture_studio_frame)
                    return
                raise RuntimeError(
                    f"Le moteur 3D a produit 5 captures vides à l’image {index + 1}/{total}"
                )
            encoder.write(rgb_frame)
            self._studio_capture_retries = 0
            if self._studio_thumbnail is None and index >= total // 2:
                self._studio_thumbnail = captured.scaled(
                    480,
                    270,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self.studio_3d.update_export_progress(index + 1, total)
            self.progress_bar.setValue(int(round((index + 1) * 100 / total)))
            self.percent_label.setText(f"{int(round((index + 1) * 100 / total))} %")
            self._studio_pending_frame = None
            worker.acknowledge()
        except Exception as exc:
            logger.exception("Capture ou encodage d’une image 3D impossible")
            self._studio_failure = translate_exception(
                exc,
                "render",
                source=self._studio_source,
                destination=(self._studio_output.parent if self._studio_output else None),
            )
            self._studio_pending_frame = None
            worker.cancel()

    def _studio_render_finished(self) -> None:
        encoder = self._studio_encoder
        output = self._studio_output
        source = self._studio_source
        config = self._studio_config
        if encoder is None or output is None or source is None or config is None:
            self._studio_render_failed(
                translate_exception(RuntimeError("Contexte du rendu 3D incomplet"))
            )
            return
        try:
            result = encoder.finish()
            self._studio_encoder = None
            self._last_video = result
            descriptor = self._effect_descriptors[config.effect]
            self.history_store.add(
                result,
                source,
                config,
                f"Studio 3D · {descriptor.selector_label}",
                self._studio_thumbnail,
            )
            self._refresh_history()
            self.studio_3d.finish_export(result)
            self.status_label.setText(f"Vidéo 3D prête : {result.name}")
            self.progress_bar.setValue(100)
            self.percent_label.setText("100 %")
            self._set_studio_running(False)
            logger.info("Vidéo du Studio 3D prête : %s", result)
        except Exception as exc:
            logger.exception("Finalisation du rendu 3D impossible")
            problem = translate_exception(
                exc, "render", source=source, destination=output.parent
            )
            self._studio_encoder = None
            self.studio_3d.fail_export(problem.display_text)
            self._set_studio_running(False)
            self._show_problem(problem, critical=True)

    def _cancel_studio_render(self) -> None:
        if self._studio_worker is None:
            return
        self.studio_3d.export_status.setText("Annulation du rendu 3D…")
        self._studio_worker.cancel()

    def _studio_render_cancelled(self) -> None:
        if self._studio_encoder is not None:
            self._studio_encoder.abort()
            self._studio_encoder = None
        problem = self._studio_failure
        self._studio_failure = None
        self._studio_pending_frame = None
        self._set_studio_running(False)
        if problem is None:
            self.studio_3d.cancel_export()
            self.status_label.setText("Rendu 3D annulé.")
            logger.warning("Rendu du Studio 3D annulé")
        else:
            self.studio_3d.fail_export(problem.display_text)
            self.status_label.setText(f"{problem.title} — {problem.action}")
            self._show_problem(problem, critical=True)

    def _studio_render_failed(self, problem: object) -> None:
        if not isinstance(problem, UserProblem):
            problem = translate_exception(
                RuntimeError(str(problem)),
                "render",
                source=self._studio_source,
                destination=(self._studio_output.parent if self._studio_output else None),
            )
        if self._studio_encoder is not None:
            self._studio_encoder.abort()
            self._studio_encoder = None
        self._studio_pending_frame = None
        self._set_studio_running(False)
        self.studio_3d.fail_export(problem.display_text)
        self.status_label.setText(f"{problem.title} — {problem.action}")
        self._show_problem(problem, critical=True)

    def _studio_thread_finished(self) -> None:
        thread = self._studio_thread
        self._studio_worker = None
        self._studio_thread = None
        self._studio_pending_frame = None
        if thread is not None:
            thread.deleteLater()
        if self._close_when_done:
            self.close()

    def _set_studio_running(self, running: bool) -> None:
        self.generate_button.setEnabled(not running)
        self.generate_action.setEnabled(not running)
        self.preview_action.setEnabled(not running)
        self.source_zone.setEnabled(not running)
        self.destination_zone.setEnabled(not running)
        for card in self._settings_cards.values():
            card.setEnabled(not running)
        for dialog in self._settings_dialogs.values():
            dialog.set_controls_enabled(not running)
        for action in self.settings_actions.values():
            action.setEnabled(not running)

    def _play_studio_output(self) -> None:
        if self._studio_output is None:
            return
        self.workspace_tabs.setCurrentIndex(0)
        self._play_history(str(self._studio_output))

    def _reveal_studio_output(self) -> None:
        if self._studio_output is not None:
            self._reveal_history_file(str(self._studio_output))

    def _start_render(self) -> None:
        if self._studio_worker is not None:
            return
        suffix = str(self.format_combo.currentData())
        try:
            source, destination = validate_render_paths(
                self.source_zone.path,
                self.destination_zone.path,
                self.output_name.text(),
                suffix,
            )
        except UserInputError as exc:
            problem = exc.problem
            if problem.code.startswith("source_"):
                self.source_zone.mark_invalid(problem)
            elif problem.code.startswith("destination_"):
                self.destination_zone.mark_invalid(problem)
            self.status_label.setText(f"{problem.title} — {problem.action}")
            self._show_problem(problem)
            return
        self.output_name.setText(destination.name)
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
            problem = translate_exception(exc, "render")
            self.status_label.setText(f"{problem.title} — {problem.action}")
            self._show_problem(problem)
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
        for card in self._settings_cards.values():
            card.setEnabled(not running)
        for dialog in self._settings_dialogs.values():
            dialog.set_controls_enabled(not running)
        for action in self.settings_actions.values():
            action.setEnabled(not running)
        self.studio_3d.export_button.setEnabled(not running)

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
        self.studio_3d.set_frame(image)

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

    def _render_failed(self, problem: object) -> None:
        if not isinstance(problem, UserProblem):
            problem = translate_exception(
                RuntimeError(str(problem)),
                "render",
                source=self._render_source,
                destination=(
                    self.destination_zone.path
                    if self.destination_zone.path is not None
                    else None
                ),
            )
        logger.error("Rendu échoué [%s] : %s", problem.code, problem.technical_details)
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"{problem.title} — {problem.action}")
        if problem.code.startswith("source_"):
            self.source_zone.mark_invalid(problem)
        elif problem.code.startswith("destination_") or problem.code == "disk_full":
            self.destination_zone.mark_invalid(problem)
        self._show_problem(problem, critical=True)
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
        if self._studio_worker:
            answer = QMessageBox.question(
                self,
                "Rendu 3D en cours",
                "Annuler le rendu 3D et fermer ArtAnimate ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_when_done = True
            self._cancel_studio_render()
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
    app.setApplicationVersion(__version__)
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
    if os.environ.get("ARTANIMATE_START_WORKSPACE", "").casefold() == "3d":
        QTimer.singleShot(0, lambda: window.workspace_tabs.setCurrentIndex(1))
    result = app.exec()
    logger.info("Arrêt du client desktop")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

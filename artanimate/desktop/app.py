from __future__ import annotations

import logging
from pathlib import Path
import sys

from PySide6.QtCore import QSettings, QStandardPaths, QThread, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
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
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.config import RenderConfig
from ..observability import attach_handler, configure_file_logging, detach_handler
from .log_window import LogWindow, QtLogHandler
from .style import APP_STYLESHEET
from .widgets import PathDropZone, PreviewCard, ScaledImageLabel
from .worker import RenderWorker


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        log_file: Path | None = None,
        startup_warning: str | None = None,
    ):
        super().__init__()
        self.setWindowTitle("ArtAnimate — Atelier d’animation")
        self.setMinimumSize(1100, 760)
        self.resize(1420, 900)
        self.settings = QSettings("ArtAnimate", "Desktop")
        self._thread: QThread | None = None
        self._worker: RenderWorker | None = None
        self._close_when_done = False
        self._auto_filename = True
        self._last_video: Path | None = None
        self._unread_logs = 0

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
        page.addLayout(self._build_drop_zones())

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(self._build_previews(), 1)
        body.addWidget(self._build_controls())
        page.addLayout(body, 1)
        page.addWidget(self._build_progress())

        self.log_window = LogWindow(log_file, self)
        self.log_handler = QtLogHandler()
        self.log_handler.emitter.record_received.connect(self._receive_log_record)
        attach_handler(self.log_handler, logging.INFO)

        self._connect_signals()
        self._restore_destination()
        self._effect_changed()
        logger.info("Interface desktop prête")
        if startup_warning:
            logger.warning(startup_warning)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
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
        heading = QLabel("Rendu généré")
        heading.setObjectName("sectionTitle")
        output_layout.addWidget(heading)

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
        card.setMinimumWidth(360)
        card.setMaximumWidth(410)
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

        self.effect_combo = self._combo((("Sable", "sand"), ("Vague", "wave")))
        self.order_combo = self._combo(
            (
                ("Chromatique", "chromatic"),
                ("Chromatique inversé", "reverse"),
                ("Grandes zones d’abord", "area"),
                ("Clair vers sombre", "luminance"),
            )
        )
        self.outline_combo = self._combo(
            (("À la fin", "last"), ("Au début", "first"), ("Progressifs", "together"))
        )
        self.format_combo = self._combo(
            (("MP4 — H.264", ".mp4"), ("WebM — VP9", ".webm"), ("MOV — H.264", ".mov"))
        )

        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 3840)
        self.width_spin.setSingleStep(160)
        self.width_spin.setValue(1280)
        self.width_spin.setSuffix(" px")

        self.duration_spin = self._double(3.0, 120.0, 12.0, 0.5, 1, " s")
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(12, 60)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" i/s")
        self.colors_spin = QSpinBox()
        self.colors_spin.setRange(4, 64)
        self.colors_spin.setValue(24)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999_999)
        self.seed_spin.setValue(7)

        form.addRow("Mode", self.effect_combo)
        form.addRow("Ordre", self.order_combo)
        form.addRow("Contours", self.outline_combo)
        form.addRow("Format", self.format_combo)
        form.addRow("Largeur", self.width_spin)
        form.addRow("Durée", self.duration_spin)
        form.addRow("Fluidité", self.fps_spin)
        form.addRow("Nuances", self.colors_spin)
        form.addRow("Graine", self.seed_spin)
        content.addLayout(form)

        mode_title = QLabel("Réglages du mode")
        mode_title.setObjectName("sectionTitle")
        content.addWidget(mode_title)
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._build_sand_page())
        self.mode_stack.addWidget(self._build_wave_page())
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
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(430)
        return scroll

    def _build_sand_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(9)
        self.grain_density = self._double(0.0, 0.02, 0.0025, 0.0005, 4)
        self.grain_size = self._double(0.5, 4.0, 1.35, 0.1, 2, " px")
        self.sand_turbulence = self._double(0.0, 0.35, 0.10, 0.01, 2)
        form.addRow("Densité des grains", self.grain_density)
        form.addRow("Taille des grains", self.grain_size)
        form.addRow("Irrégularité", self.sand_turbulence)
        return page

    def _build_wave_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(9)
        self.direction_combo = self._combo(
            (
                ("Gauche → droite", "left"),
                ("Droite → gauche", "right"),
                ("Haut → bas", "top"),
                ("Bas → haut", "bottom"),
                ("Diagonale", "diagonal"),
                ("Depuis le centre", "radial"),
            )
        )
        self.wave_amplitude = self._double(0.0, 0.20, 0.055, 0.005, 3)
        self.wave_frequency = self._double(0.5, 10.0, 2.7, 0.1, 2)
        self.wave_turbulence = self._double(0.0, 0.35, 0.10, 0.01, 2)
        self.soft_edge = self._double(0.001, 0.10, 0.012, 0.002, 3)
        form.addRow("Direction", self.direction_combo)
        form.addRow("Amplitude", self.wave_amplitude)
        form.addRow("Fréquence", self.wave_frequency)
        form.addRow("Turbulence", self.wave_turbulence)
        form.addRow("Bord progressif", self.soft_edge)
        return page

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
    def _double(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        decimals: int,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setSingleStep(step)
        control.setValue(value)
        control.setSuffix(suffix)
        return control

    def _connect_signals(self) -> None:
        self.source_zone.path_selected.connect(self._source_selected)
        self.effect_combo.currentIndexChanged.connect(self._effect_changed)
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
        self._auto_filename = True
        self._suggest_filename()

    def _filename_edited(self) -> None:
        self._auto_filename = False

    def _effect_changed(self) -> None:
        self.mode_stack.setCurrentIndex(self.effect_combo.currentIndex())
        logger.info("Mode sélectionné : %s", self.effect_combo.currentData())
        if self._auto_filename:
            self._suggest_filename()

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
            "outline": str(self.outline_combo.currentData()),
            "duration": self.duration_spin.value(),
            "fps": self.fps_spin.value(),
            "width": self.width_spin.value(),
            "colors": self.colors_spin.value(),
            "seed": self.seed_spin.value(),
        }
        if effect == "sand":
            values.update(
                grain_density=self.grain_density.value(),
                grain_size=self.grain_size.value(),
                turbulence=self.sand_turbulence.value(),
            )
        else:
            values.update(
                direction=str(self.direction_combo.currentData()),
                wave_amplitude=self.wave_amplitude.value(),
                wave_frequency=self.wave_frequency.value(),
                turbulence=self.wave_turbulence.value(),
                soft_edge=self.soft_edge.value(),
            )
        return RenderConfig.from_dict({**RenderConfig().to_dict(), **values})

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

        self.player.stop()
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
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"Vidéo prête : {self._last_video.name}")
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

    def _render_failed(self, message: str) -> None:
        logger.error("Rendu échoué : %s", message)
        self._set_running(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Le rendu a échoué.")
        QMessageBox.critical(self, "Erreur de rendu", message)

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

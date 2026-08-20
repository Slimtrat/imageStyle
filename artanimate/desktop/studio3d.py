from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..branding import LOGO_PATH
from .controls import ParameterSlider


logger = logging.getLogger(__name__)
QML_SCENE_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "qml" / "Studio3D.qml"
)
CAMERA_PRESETS = {
    "artwork": (0.0, 7.0, 640.0),
    "table": (-10.0, 9.0, 900.0),
    "room": (-22.0, 12.0, 1060.0),
}


@dataclass(frozen=True, slots=True)
class StudioExportSettings:
    output_name: str
    suffix: str
    long_edge: int
    aspect: float

    @staticmethod
    def _even(value: float) -> int:
        rounded = max(2, int(round(value)))
        return rounded if rounded % 2 == 0 else rounded + 1

    @property
    def width(self) -> int:
        if self.aspect >= 1.0:
            return self._even(self.long_edge)
        return self._even(self.long_edge * self.aspect)

    @property
    def height(self) -> int:
        if self.aspect >= 1.0:
            return self._even(self.long_edge / self.aspect)
        return self._even(self.long_edge)


class StudioTextureProvider(QQuickImageProvider):
    """Thread-safe image provider used as the animated artwork texture."""

    def __init__(self, initial: QImage | None = None):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = Lock()
        self._image = QImage(initial) if initial is not None else QImage()

    def update(self, image: QImage) -> None:
        if image.isNull():
            return
        with self._lock:
            self._image = image.convertToFormat(QImage.Format.Format_RGBA8888)

    def requestImage(
        self,
        _identifier: str,
        size: QSize,
        requested_size: QSize,
    ) -> QImage:
        with self._lock:
            image = QImage(self._image)
        if image.isNull():
            image = QImage(16, 16, QImage.Format.Format_RGBA8888)
            image.fill(QColor("#202633"))
        if requested_size.isValid() and not requested_size.isEmpty():
            image = image.scaled(
                requested_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


class Studio3DPanel(QWidget):
    """Interactive scene, framing console and final 3D video capture surface."""

    choose_source_requested = Signal()
    choose_destination_requested = Signal()
    refresh_preview_requested = Signal()
    export_requested = Signal()
    cancel_export_requested = Signal()
    play_output_requested = Signal()
    reveal_output_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studio3DPage")
        self._texture_revision = 0
        self._scene_errors: tuple[str, ...] = ()
        self._scene_loaded = False
        self._current_aspect = 1.6
        self._current_effect = "sand"
        self._rgb_mode = "channels"
        self._effect_direction = "left"
        self._effect_progress = 0.0
        self._output_auto = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 10, 2, 2)
        layout.setSpacing(12)
        layout.addLayout(self._build_heading())

        content = QHBoxLayout()
        content.setSpacing(14)
        self.view = QQuickWidget()
        self.view.setObjectName("studio3DView")
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.setClearColor(QColor("#11151f"))
        self.view.setMinimumSize(620, 470)
        self.view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        initial = QImage(str(LOGO_PATH))
        self._provider = StudioTextureProvider(initial)
        self.view.engine().addImageProvider("artanimate", self._provider)
        self.view.statusChanged.connect(self._scene_status_changed)
        content.addWidget(self.view, 1)
        content.addWidget(self._build_controls())
        layout.addLayout(content, 1)

        if not initial.isNull():
            self.set_frame(initial)

    @property
    def scene_errors(self) -> tuple[str, ...]:
        return self._scene_errors

    def is_ready(self) -> bool:
        return self.view.status() == QQuickWidget.Status.Ready

    def activate(self) -> None:
        """Load the heavier 3D engine only when the user opens its workspace."""
        if self._scene_loaded:
            return
        self._scene_loaded = True
        logger.info("Initialisation du moteur Studio 3D")
        self.view.setSource(QUrl.fromLocalFile(str(QML_SCENE_PATH)))

    def _build_heading(self) -> QHBoxLayout:
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("Studio 3D · cadrage & export")
        title.setObjectName("studioTitle")
        subtitle = QLabel(
            "Une pièce vide, une table de poker, votre œuvre et une lumière suspendue."
        )
        subtitle.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(subtitle)
        row.addLayout(text)
        row.addStretch(1)
        badge = QLabel("TEMPS RÉEL · EXPORT")
        badge.setObjectName("studioLiveBadge")
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_controls(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("studioControlsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(340)

        panel = QFrame()
        panel.setObjectName("studioControls")
        panel.setMinimumWidth(318)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Œuvre & scène")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.artwork_status = QLabel(
            "Choisissez une œuvre pour lancer son animation dans la pièce."
        )
        self.artwork_status.setObjectName("studioStatus")
        self.artwork_status.setWordWrap(True)
        layout.addWidget(self.artwork_status)

        source_row = QHBoxLayout()
        choose = QPushButton("Œuvre…")
        choose.clicked.connect(self.choose_source_requested)
        refresh = QPushButton("Recalculer")
        refresh.clicked.connect(self.refresh_preview_requested)
        source_row.addWidget(choose)
        source_row.addWidget(refresh)
        layout.addLayout(source_row)

        camera_title = QLabel("Cadrage caméra")
        camera_title.setObjectName("sectionTitle")
        layout.addWidget(camera_title)
        self.camera_preset = QComboBox()
        self.camera_preset.addItem("Œuvre · face", "artwork")
        self.camera_preset.addItem("Table de poker · héro", "table")
        self.camera_preset.addItem("Pièce vide · plan large", "room")
        self.camera_preset.setCurrentIndex(1)
        self.camera_preset.currentIndexChanged.connect(self._apply_selected_preset)
        layout.addWidget(self.camera_preset)

        form = QFormLayout()
        form.setSpacing(8)
        self.yaw_slider = ParameterSlider(
            -70, 70, -10, 1, 0, "°", "Rotation horizontale de la caméra."
        )
        self.pitch_slider = ParameterSlider(
            -2, 32, 9, 1, 0, "°", "Hauteur du point de vue."
        )
        self.distance_slider = ParameterSlider(
            560, 1150, 900, 10, 0, "", "Distance entre la caméra et l’œuvre."
        )
        self.lamp_slider = ParameterSlider(
            0.2, 5.0, 2.2, 0.1, 1, "×", "Intensité de la suspension au-dessus de la table."
        )
        form.addRow("Angle", self.yaw_slider)
        form.addRow("Hauteur", self.pitch_slider)
        form.addRow("Distance", self.distance_slider)
        form.addRow("Suspension", self.lamp_slider)
        layout.addLayout(form)

        self.yaw_slider.valueChanged.connect(
            lambda value: self._set_scene_property("cameraYaw", value)
        )
        self.pitch_slider.valueChanged.connect(
            lambda value: self._set_scene_property("cameraPitch", -value)
        )
        self.distance_slider.valueChanged.connect(
            lambda value: self._set_scene_property("cameraDistance", value)
        )
        self.lamp_slider.valueChanged.connect(
            lambda value: self._set_scene_property("lampBrightness", value)
        )

        hint = QLabel(
            "Le cadre blanc est la sortie vidéo. Glissez dans la scène pour orbiter ; "
            "la molette règle la distance."
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        export_title = QLabel("Vidéo 3D")
        export_title.setObjectName("sectionTitle")
        layout.addWidget(export_title)
        export_form = QFormLayout()
        export_form.setSpacing(8)
        self.ratio_combo = QComboBox()
        self.ratio_combo.addItem("Horizontal · 16:9", 16 / 9)
        self.ratio_combo.addItem("Carré · 1:1", 1.0)
        self.ratio_combo.addItem("Vertical · 9:16", 9 / 16)
        self.ratio_combo.currentIndexChanged.connect(self._output_ratio_changed)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItem("HD · 1280 px", 1280)
        self.resolution_combo.addItem("Full HD · 1920 px", 1920)
        self.resolution_combo.addItem("Brouillon · 854 px", 854)
        self.format_combo = QComboBox()
        self.format_combo.addItem("MP4 · H.264", ".mp4")
        self.format_combo.addItem("MOV · H.264", ".mov")
        self.format_combo.addItem("WebM · VP9", ".webm")
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        export_form.addRow("Cadre", self.ratio_combo)
        export_form.addRow("Définition", self.resolution_combo)
        export_form.addRow("Format", self.format_combo)
        layout.addLayout(export_form)

        self.output_name = QLineEdit("animation-studio3d.mp4")
        self.output_name.setPlaceholderText("nom-video-3d.mp4")
        self.output_name.textEdited.connect(self._filename_edited)
        layout.addWidget(self.output_name)
        self.destination_label = QLabel("Destination : choisissez un dossier")
        self.destination_label.setObjectName("muted")
        self.destination_label.setWordWrap(True)
        layout.addWidget(self.destination_label)
        destination_button = QPushButton("Choisir la destination…")
        destination_button.clicked.connect(self.choose_destination_requested)
        layout.addWidget(destination_button)

        self.export_button = QPushButton("Créer la vidéo 3D")
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(self.export_requested)
        self.cancel_button = QPushButton("Annuler le rendu 3D")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.clicked.connect(self.cancel_export_requested)
        self.cancel_button.hide()
        layout.addWidget(self.export_button)
        layout.addWidget(self.cancel_button)

        self.export_status = QLabel("Prêt à cadrer.")
        self.export_status.setObjectName("studioStatus")
        self.export_status.setWordWrap(True)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_progress.setTextVisible(True)
        layout.addWidget(self.export_status)
        layout.addWidget(self.export_progress)

        result_row = QHBoxLayout()
        self.play_output_button = QPushButton("Lire")
        self.play_output_button.clicked.connect(self.play_output_requested)
        self.reveal_output_button = QPushButton("Afficher le fichier")
        self.reveal_output_button.clicked.connect(self.reveal_output_requested)
        self.play_output_button.hide()
        self.reveal_output_button.hide()
        result_row.addWidget(self.play_output_button)
        result_row.addWidget(self.reveal_output_button)
        layout.addLayout(result_row)
        layout.addStretch(1)

        self._export_controls = (
            choose,
            refresh,
            self.camera_preset,
            self.yaw_slider,
            self.pitch_slider,
            self.distance_slider,
            self.lamp_slider,
            self.ratio_combo,
            self.resolution_combo,
            self.format_combo,
            self.output_name,
            destination_button,
        )
        scroll.setWidget(panel)
        return scroll

    def _scene_status_changed(self, status: QQuickWidget.Status) -> None:
        if status == QQuickWidget.Status.Ready:
            self._scene_errors = ()
            logger.info("Moteur du Studio 3D prêt")
            self._apply_selected_preset()
            self._publish_scene_state()
            return
        if status == QQuickWidget.Status.Error:
            self._scene_errors = tuple(error.toString() for error in self.view.errors())
            self.artwork_status.setText(
                "Le moteur 3D n’a pas pu démarrer. Consultez les logs pour le détail."
            )
            logger.error("Chargement du Studio 3D impossible : %s", self._scene_errors)

    def _set_scene_property(self, name: str, value: object) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty(name, value)

    def _apply_selected_preset(self, *_args: object) -> None:
        key = str(self.camera_preset.currentData())
        yaw, pitch, distance = CAMERA_PRESETS[key]
        self.yaw_slider.setValue(yaw)
        self.pitch_slider.setValue(pitch)
        self.distance_slider.setValue(distance)
        self._set_scene_property("cameraYaw", yaw)
        self._set_scene_property("cameraPitch", -pitch)
        self._set_scene_property("cameraDistance", distance)
        logger.info("Cadrage 3D sélectionné : %s", key)

    def reset_camera(self) -> None:
        self.camera_preset.setCurrentIndex(1)
        self._apply_selected_preset()

    def _output_ratio_changed(self, *_args: object) -> None:
        self._set_scene_property("outputAspect", float(self.ratio_combo.currentData()))

    def _format_changed(self, *_args: object) -> None:
        suffix = str(self.format_combo.currentData())
        current = Path(self.output_name.text().strip() or "animation-studio3d")
        self.output_name.setText(current.with_suffix(suffix).name)

    def _filename_edited(self) -> None:
        self._output_auto = False

    def suggest_output(self, source: Path) -> None:
        if not self._output_auto:
            return
        suffix = str(self.format_combo.currentData())
        self.output_name.setText(f"{source.stem}-studio3d{suffix}")

    def set_destination(self, destination: Path | None) -> None:
        if destination is None:
            self.destination_label.setText("Destination : choisissez un dossier")
            self.destination_label.setToolTip("")
            return
        self.destination_label.setText(f"Destination : {destination.name}")
        self.destination_label.setToolTip(str(destination.resolve()))

    def export_settings(self) -> StudioExportSettings:
        return StudioExportSettings(
            output_name=self.output_name.text(),
            suffix=str(self.format_combo.currentData()),
            long_edge=int(self.resolution_combo.currentData()),
            aspect=float(self.ratio_combo.currentData()),
        )

    def camera_state(self) -> dict[str, float]:
        root = self.view.rootObject()
        if root is None:
            return {
                "yaw": float(self.yaw_slider.value()),
                "pitch": -float(self.pitch_slider.value()),
                "distance": float(self.distance_slider.value()),
                "lamp": float(self.lamp_slider.value()),
            }
        return {
            "yaw": float(root.property("cameraYaw")),
            "pitch": float(root.property("cameraPitch")),
            "distance": float(root.property("cameraDistance")),
            "lamp": float(root.property("lampBrightness")),
        }

    def set_source(self, path: Path) -> bool:
        image = QImage(str(path))
        if image.isNull():
            logger.warning("Texture 3D illisible : %s", path)
            return False
        self.set_frame(image)
        self.suggest_output(path)
        self.artwork_status.setText(
            f"{path.name} · préparation de l’animation avec les réglages 2D…"
        )
        return True

    def set_effect(
        self,
        effect: str,
        rgb_mode: str = "channels",
        direction: str = "left",
    ) -> None:
        self._current_effect = effect
        self._rgb_mode = rgb_mode
        self._effect_direction = direction
        self._set_scene_property("effectKind", effect)
        self._set_scene_property("rgbMode", rgb_mode)
        self._set_scene_property("effectDirection", direction)

    def set_loading(self) -> None:
        self.artwork_status.setText("Calcul du mouvement basse définition…")

    def set_frame(
        self,
        image: QImage,
        frame_index: int | None = None,
        frame_count: int | None = None,
        progress: float | None = None,
    ) -> None:
        if image.isNull():
            return
        self._provider.update(image)
        self._texture_revision += 1
        self._current_aspect = image.width() / max(1, image.height())
        if progress is not None:
            self._effect_progress = max(0.0, min(1.0, float(progress)))
        elif frame_index is not None and frame_count and frame_count > 1:
            self._effect_progress = frame_index / (frame_count - 1)
        self._publish_texture()
        self._set_scene_property("effectProgress", self._effect_progress)
        if frame_index is not None and frame_count:
            self.artwork_status.setText(
                f"Effet 3D en temps réel · image {frame_index + 1}/{frame_count}"
            )

    def _publish_texture(self) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty(
                "artworkSource",
                f"image://artanimate/frame/{self._texture_revision}",
            )
            root.setProperty("artworkAspect", self._current_aspect)

    def _publish_scene_state(self) -> None:
        self._publish_texture()
        self._set_scene_property("lampBrightness", self.lamp_slider.value())
        self._set_scene_property("effectKind", self._current_effect)
        self._set_scene_property("rgbMode", self._rgb_mode)
        self._set_scene_property("effectDirection", self._effect_direction)
        self._set_scene_property("effectProgress", self._effect_progress)
        self._output_ratio_changed()

    def begin_export(self, total_frames: int) -> None:
        for control in self._export_controls:
            control.setEnabled(False)
        self.view.setEnabled(False)
        self.export_button.hide()
        self.cancel_button.show()
        self.play_output_button.hide()
        self.reveal_output_button.hide()
        self.export_progress.setValue(0)
        self.export_status.setText(
            f"Préparation de {total_frames} images de scène…"
        )
        self._set_scene_property("showHud", False)

    def update_export_progress(self, done: int, total: int) -> None:
        percent = int(round(done * 100 / max(1, total)))
        self.export_progress.setValue(percent)
        self.export_status.setText(
            f"Capture et encodage de la scène · {done}/{total} images"
        )

    def finish_export(self, output: Path) -> None:
        self._restore_after_export()
        self.export_progress.setValue(100)
        self.export_status.setText(f"Vidéo 3D prête : {output.name}")
        self.play_output_button.show()
        self.reveal_output_button.show()

    def fail_export(self, message: str) -> None:
        self._restore_after_export()
        self.export_status.setText(message)

    def cancel_export(self) -> None:
        self._restore_after_export()
        self.export_progress.setValue(0)
        self.export_status.setText("Rendu 3D annulé. Aucun fichier partiel conservé.")

    def _restore_after_export(self) -> None:
        for control in self._export_controls:
            control.setEnabled(True)
        self.view.setEnabled(True)
        self.cancel_button.hide()
        self.export_button.show()
        self._set_scene_property("showHud", True)

    def capture_frame(self, width: int, height: int) -> QImage:
        """Capture the center crop represented by the on-screen framing guide."""
        raw = self.view.grabFramebuffer()
        if raw.isNull():
            raise RuntimeError("Le moteur 3D n’a produit aucune image")
        target_aspect = width / height
        raw_aspect = raw.width() / raw.height()
        if raw_aspect > target_aspect:
            crop_height = raw.height()
            crop_width = int(round(crop_height * target_aspect))
            left = (raw.width() - crop_width) // 2
            top = 0
        else:
            crop_width = raw.width()
            crop_height = int(round(crop_width / target_aspect))
            left = 0
            top = (raw.height() - crop_height) // 2
        cropped = raw.copy(QRect(left, top, crop_width, crop_height))
        return cropped.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

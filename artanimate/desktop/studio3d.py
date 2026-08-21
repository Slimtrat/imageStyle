from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QRect, QSize, QSignalBlocker, Qt, QUrl, Signal
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
from ..core.effects import EffectDescriptor, effect_descriptors
from .controls import ParameterSlider
from .studio3d_camera import CAMERA_MOTIONS, camera_motion
from .studio3d_particles import (
    StudioParticleModel,
    StudioSceneData,
    studio_laser_cursor,
)
from .studio3d_wave import (
    OrganicWaveGeometry,
    OrganicWaveSettings,
    artwork_dimensions,
)


logger = logging.getLogger(__name__)
QML_SCENE_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "qml" / "Studio3D.qml"
)
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
    effect_selected = Signal(str)
    edit_effect_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studio3DPage")
        self._texture_revision = 0
        self._scene_errors: tuple[str, ...] = ()
        self._scene_loaded = False
        self._current_aspect = 1.6
        self._current_effect = "sand"
        self._effect_descriptors: dict[str, EffectDescriptor] = {
            descriptor.key: descriptor for descriptor in effect_descriptors()
        }
        self._rgb_mode = "channels"
        self._effect_direction = "left"
        self._effect_progress = 0.0
        self._camera_motion = camera_motion("flyover")
        self._wave_settings = OrganicWaveSettings()
        self._wave_geometry = OrganicWaveGeometry()
        self._wave_base_frame = QImage()
        self._output_auto = True
        self._particle_model = StudioParticleModel()
        self._scene_data: StudioSceneData | None = None

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
        self.view.rootContext().setContextProperty(
            "pigmentParticleModel", self._particle_model
        )
        self.view.rootContext().setContextProperty(
            "organicWaveGeometry", self._wave_geometry
        )
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
            "Choisissez l’animation, cadrez la scène et exportez sans quitter ce studio."
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

        effect_title = QLabel("Animation de l’œuvre")
        effect_title.setObjectName("sectionTitle")
        layout.addWidget(effect_title)
        self.effect_combo = QComboBox()
        for descriptor in self._effect_descriptors.values():
            self.effect_combo.addItem(descriptor.selector_label, descriptor.key)
            self.effect_combo.setItemData(
                self.effect_combo.count() - 1,
                descriptor.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        self.effect_combo.currentIndexChanged.connect(
            self._studio_effect_selection_changed
        )
        layout.addWidget(self.effect_combo)
        self.effect_description = QLabel()
        self.effect_description.setObjectName("helperText")
        self.effect_description.setWordWrap(True)
        layout.addWidget(self.effect_description)
        self.effect_settings_button = QPushButton("Comprendre et régler cet effet…")
        self.effect_settings_button.clicked.connect(self.edit_effect_requested)
        layout.addWidget(self.effect_settings_button)
        shared_hint = QLabel(
            "Ces réglages pilotent directement le prérendu et la vidéo 3D."
        )
        shared_hint.setObjectName("muted")
        shared_hint.setWordWrap(True)
        layout.addWidget(shared_hint)
        self._update_effect_description()

        camera_title = QLabel("Mouvement caméra")
        camera_title.setObjectName("sectionTitle")
        layout.addWidget(camera_title)
        self.camera_preset = QComboBox()
        for preset in CAMERA_MOTIONS:
            self.camera_preset.addItem(preset.label, preset.key)
            self.camera_preset.setItemData(
                self.camera_preset.count() - 1,
                preset.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        self.camera_preset.setCurrentIndex(0)
        self.camera_preset.currentIndexChanged.connect(self._apply_selected_preset)
        layout.addWidget(self.camera_preset)

        form = QFormLayout()
        form.setSpacing(8)
        self.yaw_slider = ParameterSlider(
            -45, 45, 0, 1, 0, "°",
            "Orientation du cadrage final autour de l’œuvre.",
        )
        self.pitch_slider = ParameterSlider(
            58, 82, 78, 1, 0, "°",
            "Plongée du cadrage final. Le rail rase-motte y revient automatiquement.",
        )
        self.distance_slider = ParameterSlider(
            420, 1400, 560, 10, 0, "",
            "Distance finale. En vertical, ArtAnimate recule si nécessaire pour garder toute l’œuvre.",
        )
        self.orbit_slider = ParameterSlider(
            -0.25, 0.25, 0.0, 0.01, 2, " tour",
            "Rotation subtile ajoutée au trajet, limitée à un quart de tour.",
        )
        self.camera_motion_slider = ParameterSlider(
            0.0, 1.25, 1.0, 0.05, 2, "×",
            "Amplitude du survol ou de la dérive. Zéro conserve uniquement la plongée finale.",
        )
        self.lamp_slider = ParameterSlider(
            0.2, 5.0, 2.4, 0.1, 1, "×", "Intensité de la suspension au-dessus du meuble."
        )
        self.lamp_motion_slider = ParameterSlider(
            0.0, 1.0, 0.65, 0.05, 2, "", "Amplitude de l’oscillation lente de la suspension."
        )
        form.addRow("Angle final", self.yaw_slider)
        form.addRow("Plongée finale", self.pitch_slider)
        form.addRow("Distance finale", self.distance_slider)
        form.addRow("Rotation douce", self.orbit_slider)
        form.addRow("Amplitude trajet", self.camera_motion_slider)
        form.addRow("Suspension", self.lamp_slider)
        form.addRow("Mouvement", self.lamp_motion_slider)
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
        self.orbit_slider.valueChanged.connect(
            lambda value: self._set_scene_property("cameraOrbitTurns", value)
        )
        self.camera_motion_slider.valueChanged.connect(
            lambda value: self._set_scene_property("cameraMotionStrength", value)
        )
        self.lamp_slider.valueChanged.connect(
            lambda value: self._set_scene_property("lampBrightness", value)
        )
        self.lamp_motion_slider.valueChanged.connect(
            lambda value: self._set_scene_property("lampMotion", value)
        )

        hint = QLabel(
            "Le rail Signature traverse la matière au ras de l’œuvre, puis atteint "
            "la plongée finale avant la fin. Angle et distance règlent cette arrivée."
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
            self.effect_combo,
            self.effect_settings_button,
            self.camera_preset,
            self.yaw_slider,
            self.pitch_slider,
            self.distance_slider,
            self.orbit_slider,
            self.camera_motion_slider,
            self.lamp_slider,
            self.lamp_motion_slider,
            self.ratio_combo,
            self.resolution_combo,
            self.format_combo,
            self.output_name,
            destination_button,
        )
        scroll.setWidget(panel)
        return scroll

    def _update_effect_description(self) -> None:
        effect = str(self.effect_combo.currentData())
        descriptor = self._effect_descriptors[effect]
        self.effect_description.setText(descriptor.description)
        self.effect_combo.setToolTip(descriptor.description)

    def _studio_effect_selection_changed(self, *_args: object) -> None:
        effect = str(self.effect_combo.currentData())
        if not effect:
            return
        self._update_effect_description()
        self.effect_selected.emit(effect)
        logger.info("Effet sélectionné depuis le Studio 3D : %s", effect)

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
        preset = camera_motion(key)
        self._camera_motion = preset
        self.yaw_slider.setValue(preset.yaw)
        self.pitch_slider.setValue(preset.pitch)
        self.distance_slider.setValue(preset.distance)
        self.orbit_slider.setValue(preset.rotation_turns)
        self.camera_motion_slider.setValue(preset.strength)
        self.camera_preset.setToolTip(preset.description)
        self._set_scene_property("cameraYaw", preset.yaw)
        self._set_scene_property("cameraPitch", -preset.pitch)
        self._set_scene_property("cameraDistance", preset.distance)
        self._set_scene_property("cameraPivotY", preset.pivot_y)
        self._set_scene_property("cameraOrbitTurns", preset.rotation_turns)
        self._set_scene_property("cameraMotion", preset.motion)
        self._set_scene_property("cameraMotionStrength", preset.strength)
        logger.info("Mouvement caméra 3D sélectionné : %s", key)

    def reset_camera(self) -> None:
        self.camera_preset.setCurrentIndex(0)
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

    def camera_state(self) -> dict[str, float | str]:
        root = self.view.rootObject()
        if root is None:
            return {
                "yaw": float(self.yaw_slider.value()),
                "pitch": -float(self.pitch_slider.value()),
                "distance": float(self.distance_slider.value()),
                "orbit_turns": float(self.orbit_slider.value()),
                "motion": self._camera_motion.motion,
                "motion_strength": float(self.camera_motion_slider.value()),
                "lamp": float(self.lamp_slider.value()),
                "lamp_motion": float(self.lamp_motion_slider.value()),
            }
        return {
            "yaw": float(root.property("cameraYaw")),
            "pitch": float(root.property("cameraPitch")),
            "distance": float(root.property("cameraDistance")),
            "orbit_turns": float(root.property("cameraOrbitTurns")),
            "motion": str(root.property("cameraMotion")),
            "motion_strength": float(root.property("cameraMotionStrength")),
            "lamp": float(root.property("lampBrightness")),
            "lamp_motion": float(root.property("lampMotion")),
        }

    def set_scene_data(self, data: StudioSceneData) -> None:
        """Publish analysis-backed particles and the exact effect stage timeline."""
        self._scene_data = data
        self._particle_model.replace(data.particles)
        self._set_scene_property("effectStageCount", max(1, data.stage_count))
        self._set_scene_property("effectOutlineStage", data.outline_stage)
        self._set_scene_property(
            "paintStageTargetU", [stage.target_u for stage in data.tool_stages]
        )
        self._set_scene_property(
            "paintStageTargetV", [stage.target_v for stage in data.tool_stages]
        )
        self._set_scene_property(
            "paintStageColors",
            ["#%02x%02x%02x" % stage.color for stage in data.tool_stages],
        )
        self._set_scene_property("paintDropSize", data.paint_drop_size)
        self._set_scene_property("paintFallRatio", data.paint_fall_ratio)
        self._publish_laser_cursor()
        logger.info(
            "Scène 3D synchronisée : grains=%d, passages=%d, contour=%d, points laser=%d",
            len(data.particles),
            data.stage_count,
            data.outline_stage,
            len(data.laser_path),
        )

    def _publish_laser_cursor(self) -> None:
        cursor = studio_laser_cursor(
            self._scene_data, self._current_effect, self._effect_progress
        )
        self._set_scene_property("laserCursorU", cursor.target_u)
        self._set_scene_property("laserCursorV", cursor.target_v)
        self._set_scene_property("laserCursorOn", cursor.beam_on)

    def set_source(self, path: Path) -> bool:
        image = QImage(str(path))
        if image.isNull():
            logger.warning("Texture 3D illisible : %s", path)
            return False
        self._particle_model.replace(())
        self._wave_base_frame = QImage()
        self._wave_geometry.set_source(image)
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
        wave_settings: OrganicWaveSettings | None = None,
    ) -> None:
        previous_effect = self._current_effect
        self._current_effect = effect
        if effect == "wave" and previous_effect != effect:
            self._wave_base_frame = QImage()
        if wave_settings is not None:
            self._wave_settings = wave_settings
        effect_index = self.effect_combo.findData(effect)
        if effect_index >= 0 and effect_index != self.effect_combo.currentIndex():
            blocker = QSignalBlocker(self.effect_combo)
            self.effect_combo.setCurrentIndex(effect_index)
            del blocker
            self._update_effect_description()
        self._rgb_mode = rgb_mode
        self._effect_direction = direction
        self._set_scene_property("effectKind", effect)
        self._set_scene_property("rgbMode", rgb_mode)
        self._set_scene_property("effectDirection", direction)
        self._wave_geometry.configure(self._wave_settings, direction)
        self._publish_laser_cursor()
        if effect == "wave":
            logger.info(
                "Matière Vague 3D : amplitude=%.3f, fréquence=%.2f, "
                "turbulence=%.2f, densités=%.2f",
                self._wave_settings.amplitude,
                self._wave_settings.frequency,
                self._wave_settings.turbulence,
                self._wave_settings.density_contrast,
            )

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
        self._current_aspect = image.width() / max(1, image.height())
        self._wave_geometry.set_dimensions(
            *artwork_dimensions(self._current_aspect)
        )
        if progress is not None:
            self._effect_progress = max(0.0, min(1.0, float(progress)))
        elif frame_index is not None and frame_count and frame_count > 1:
            self._effect_progress = frame_index / (frame_count - 1)
        self._wave_geometry.set_progress(self._effect_progress)
        self._publish_laser_cursor()

        texture = image
        if self._current_effect == "wave":
            if self._effect_progress <= 0.005:
                self._wave_base_frame = QImage(image)
            elif not self._wave_base_frame.isNull():
                texture = self._wave_geometry.composite_deposit(
                    self._wave_base_frame, image
                )
        self._provider.update(texture)
        self._texture_revision += 1
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
        self._set_scene_property("lampMotion", self.lamp_motion_slider.value())
        self._set_scene_property("cameraOrbitTurns", self.orbit_slider.value())
        self._set_scene_property("cameraMotion", self._camera_motion.motion)
        self._set_scene_property(
            "cameraMotionStrength", self.camera_motion_slider.value()
        )
        self._set_scene_property("effectKind", self._current_effect)
        self._set_scene_property("rgbMode", self._rgb_mode)
        self._set_scene_property("effectDirection", self._effect_direction)
        self._set_scene_property("effectProgress", self._effect_progress)
        self._publish_laser_cursor()
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

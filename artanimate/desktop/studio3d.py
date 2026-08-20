from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
        size.setWidth(image.width())
        size.setHeight(image.height())
        if requested_size.isValid() and not requested_size.isEmpty():
            image = image.scaled(
                requested_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return image


class Studio3DPanel(QWidget):
    """Interactive 3D presentation scene sharing the 2D preview frames."""

    choose_source_requested = Signal()
    refresh_preview_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studio3DPage")
        self._texture_revision = 0
        self._scene_errors: tuple[str, ...] = ()
        self._scene_loaded = False
        self._current_aspect = 1.6

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
        title = QLabel("Studio 3D")
        title.setObjectName("studioTitle")
        subtitle = QLabel(
            "Votre effet 2D devient une œuvre éclairée dans une scène manipulable."
        )
        subtitle.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(subtitle)
        row.addLayout(text)
        row.addStretch(1)
        badge = QLabel("TEMPS RÉEL")
        badge.setObjectName("studioLiveBadge")
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_controls(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("studioControls")
        panel.setFixedWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Mise en scène")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.artwork_status = QLabel(
            "Choisissez une œuvre dans l’atelier 2D pour lancer son animation."
        )
        self.artwork_status.setObjectName("studioStatus")
        self.artwork_status.setWordWrap(True)
        layout.addWidget(self.artwork_status)

        choose = QPushButton("Choisir une œuvre…")
        choose.clicked.connect(self.choose_source_requested)
        refresh = QPushButton("Recalculer l’effet")
        refresh.clicked.connect(self.refresh_preview_requested)
        layout.addWidget(choose)
        layout.addWidget(refresh)

        form = QFormLayout()
        form.setSpacing(10)
        self.yaw_slider = ParameterSlider(
            -70, 70, -18, 1, 0, "°", "Rotation horizontale de la caméra."
        )
        self.pitch_slider = ParameterSlider(
            -2, 32, 11, 1, 0, "°", "Hauteur du point de vue."
        )
        self.distance_slider = ParameterSlider(
            560, 1100, 780, 10, 0, "", "Distance entre la caméra et l’œuvre."
        )
        self.lamp_slider = ParameterSlider(
            0.2, 4.0, 1.8, 0.1, 1, "×", "Intensité de la lampe de table."
        )
        form.addRow("Angle", self.yaw_slider)
        form.addRow("Hauteur", self.pitch_slider)
        form.addRow("Distance", self.distance_slider)
        form.addRow("Lampe", self.lamp_slider)
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

        reset = QPushButton("Recentrer la caméra")
        reset.setObjectName("compactButton")
        reset.clicked.connect(self.reset_camera)
        layout.addWidget(reset)
        hint = QLabel(
            "Glissez directement dans la scène pour tourner autour de l’œuvre. "
            "La molette règle la distance."
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _scene_status_changed(self, status: QQuickWidget.Status) -> None:
        if status == QQuickWidget.Status.Ready:
            self._scene_errors = ()
            logger.info("Moteur du Studio 3D prêt")
            self.reset_camera()
            self._set_scene_property("lampBrightness", self.lamp_slider.value())
            self._publish_texture()
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

    def reset_camera(self) -> None:
        self.yaw_slider.setValue(-18)
        self.pitch_slider.setValue(11)
        self.distance_slider.setValue(780)
        self._set_scene_property("cameraYaw", -18.0)
        self._set_scene_property("cameraPitch", -11.0)
        self._set_scene_property("cameraDistance", 780.0)

    def set_source(self, path: Path) -> bool:
        image = QImage(str(path))
        if image.isNull():
            logger.warning("Texture 3D illisible : %s", path)
            return False
        self.set_frame(image)
        self.artwork_status.setText(
            f"{path.name} · préparation de l’animation avec les réglages 2D…"
        )
        return True

    def set_loading(self) -> None:
        self.artwork_status.setText("Calcul du mouvement basse définition…")

    def set_frame(
        self,
        image: QImage,
        frame_index: int | None = None,
        frame_count: int | None = None,
    ) -> None:
        if image.isNull():
            return
        self._provider.update(image)
        self._texture_revision += 1
        self._current_aspect = image.width() / max(1, image.height())
        self._publish_texture()
        if frame_index is not None and frame_count:
            self.artwork_status.setText(
                f"Effet animé en temps réel · image {frame_index + 1}/{frame_count}"
            )

    def _publish_texture(self) -> None:
        root = self.view.rootObject()
        if root is not None:
            root.setProperty(
                "artworkSource",
                f"image://artanimate/frame/{self._texture_revision}",
            )
            root.setProperty("artworkAspect", self._current_aspect)

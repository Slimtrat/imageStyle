from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QCloseEvent, QFont, QImage, QKeySequence, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.config import RenderConfig
from ..studio.analysis import (
    SceneAnalysisResult,
    add_manual_mask,
    add_manual_selection,
    apply_scene_analysis,
    remove_scene_object,
    update_scene_object_bounds,
)
from ..studio.assets import fingerprint_file
from ..studio.camera import (
    copy_camera_keyframe,
    move_camera_keyframe,
    remove_camera_keyframe,
    resolve_camera_pose,
    set_camera_keyframe_easing,
    upsert_camera_keyframe,
)
from ..studio.clock import StudioClock
from ..studio.events import compile_timeline_triggers
from ..studio.effect_2d import (
    add_effect_clip,
    settings_for_effect_clip,
    update_effect_clip,
)
from ..studio.semantic_actions import (
    add_semantic_action_clip,
    is_semantic_action_capability,
    is_semantic_action_clip,
)
from ..studio.camera_presets import CameraPreset, PresetApplyMode, apply_camera_preset
from ..studio.adapters.legacy_project import project_as_semantic
from ..studio.semantic import Bounds, CapabilityInvocation, SemanticScene, TimelineTrigger
from ..studio.history import StudioHistory
from ..studio.model import (
    AssetKind,
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    ClipKind,
    FitMode,
    Easing,
    StudioProject,
    TrackKind,
)
from .studio_audio import StudioAudioMonitor
from .studio_waveform import StudioWaveformController
from ..studio.timeline import add_track, delete_clips, set_track_state
from .studio_camera import StudioCameraInspector
from .studio_analysis import StudioAnalysisController, StudioAnalysisPanel
from .studio_camera_presets import StudioCameraPresetPanel
from .studio_assets import StudioAssetPanel
from .studio_keyframes import StudioKeyframeStrip
from .studio_effects import StudioEffectInspector
from .studio_semantic import StudioSemanticPanel
from .studio_triggers import StudioTriggerPanel
from .studio_preview import StudioPreviewController
from .studio_timeline import StudioTimeline
from .studio_timeline_actions import StudioTimelineActions
from .studio_transport import StudioTransport


class StudioCanvas(QWidget):
    """Artwork-first 9:16 canvas used by the V3 Studio workspace."""

    cameraPoseChanged = Signal(object)
    artworkChanged = Signal(object)
    semanticTargetSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioCanvas")
        self.setAccessibleName("Canvas vertical du Studio")
        self.setMinimumSize(250, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._artwork = QImage()
        self._artwork_name = ""
        self._artwork_path: Path | None = None
        self._preview_frame = QImage()
        self._preview_frame_index = -1
        self._preview_pending = False
        self._playhead_frame = 0
        self._playhead_fps = 30
        self._camera_pose = CameraPose()
        self._dragging_camera = False
        self._last_pointer = None
        self._semantic_scene: SemanticScene | None = None
        self._semantic_target_id: str | None = None

    def sizeHint(self) -> QSize:
        return QSize(360, 640)

    def set_artwork(self, path: Path | None) -> bool:
        if path is None:
            self._artwork = QImage()
            self._artwork_name = ""
            self._artwork_path = None
            self.clear_preview()
            self.artworkChanged.emit(None)
            self.update()
            return True
        image = QImage(str(path))
        if image.isNull():
            return False
        self._artwork = image
        self._artwork_name = path.name
        self._artwork_path = path.resolve(strict=False)
        self.clear_preview()
        self.artworkChanged.emit(self._artwork_path)
        self.update()
        return True

    @property
    def artwork_path(self) -> Path | None:
        return self._artwork_path

    @property
    def semantic_target_id(self) -> str | None:
        return self._semantic_target_id

    def set_semantic_scene(self, scene: SemanticScene | None) -> None:
        self._semantic_scene = scene
        known = (
            scene is not None
            and self._semantic_target_id is not None
            and scene.object_by_id(self._semantic_target_id) is not None
        )
        if not known:
            self._semantic_target_id = (
                "artwork"
                if scene is not None and scene.object_by_id("artwork") is not None
                else None
            )
        self.update()

    def set_semantic_target(self, object_id: str) -> bool:
        if self._semantic_scene is None:
            return False
        if self._semantic_scene.object_by_id(object_id) is None:
            return False
        self._semantic_target_id = object_id
        self.update()
        return True

    def _semantic_selection_rect(self, object_id: str, frame: QRect) -> QRectF:
        scene = self._semantic_scene
        scene_object = scene.object_by_id(object_id) if scene is not None else None
        if scene_object is None:
            return QRectF()
        if scene_object.semantic_type in {"scene.background", "scene.camera"}:
            return QRectF(frame)
        bounds = scene_object.bounds
        artwork = self._artwork_rect(frame)
        if bounds is None or artwork.isEmpty():
            return artwork
        return QRectF(
            artwork.left() + bounds.x * artwork.width(),
            artwork.top() + bounds.y * artwork.height(),
            bounds.width * artwork.width(),
            bounds.height * artwork.height(),
        )

    def _semantic_target_at(self, point: QPointF, frame: QRect) -> str:
        scene = self._semantic_scene
        if scene is None:
            return "artwork"
        candidates = [
            item for item in scene.objects
            if item.bounds is not None
            and item.semantic_type not in {"artwork", "scene.background", "scene.camera"}
            and self._semantic_selection_rect(item.object_id, frame).contains(point)
        ]
        if candidates:
            return min(candidates, key=lambda item: item.bounds.width * item.bounds.height).object_id
        return "artwork"

    @property
    def preview_frame_index(self) -> int:
        return self._preview_frame_index

    @property
    def preview_pending(self) -> bool:
        return self._preview_pending

    def set_preview_frame(self, frame: int, image: QImage) -> None:
        self._preview_frame = QImage(image)
        self._preview_frame_index = int(frame)
        self._preview_pending = False
        self.update()

    def set_preview_pending(self, pending: bool) -> None:
        self._preview_pending = bool(pending)
        self.update()

    def clear_preview(self) -> None:
        self._preview_frame = QImage()
        self._preview_frame_index = -1
        self._preview_pending = False
        self.update()

    @property
    def playhead_frame(self) -> int:
        return self._playhead_frame

    def set_playhead(self, frame: int, fps: int) -> None:
        self._playhead_frame = max(0, int(frame))
        self._playhead_fps = int(fps)
        self.update()

    @property
    def camera_pose(self) -> CameraPose:
        return self._camera_pose

    def set_camera_pose(self, pose: CameraPose, *, emit: bool = False) -> None:
        self._camera_pose = pose.validate()
        self.update()
        if emit:
            self.cameraPoseChanged.emit(self._camera_pose)

    def frame_rect(self) -> QRect:
        margin = 18
        available_width = max(1, self.width() - margin * 2)
        available_height = max(1, self.height() - margin * 2)
        width_from_height = int(round(available_height * 9 / 16))
        if width_from_height <= available_width:
            frame_width = width_from_height
            frame_height = available_height
        else:
            frame_width = available_width
            frame_height = int(round(frame_width * 16 / 9))
        left = (self.width() - frame_width) // 2
        top = (self.height() - frame_height) // 2
        return QRect(left, top, frame_width, frame_height)

    def _artwork_rect(self, frame: QRect) -> QRectF:
        if self._artwork.isNull():
            return QRectF()
        source_ratio = self._artwork.width() / self._artwork.height()
        frame_ratio = frame.width() / frame.height()
        if source_ratio >= frame_ratio:
            width = frame.width()
            height = width / source_ratio
        else:
            height = frame.height()
            width = height * source_ratio
        return QRectF(
            frame.center().x() - width / 2,
            frame.center().y() - height / 2,
            width,
            height,
        )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10131a"))
        frame = self.frame_rect()

        shadow = frame.adjusted(6, 8, 10, 12)
        painter.fillRect(shadow, QColor(0, 0, 0, 80))
        painter.fillRect(frame, QColor("#171b24"))

        if self._artwork.isNull():
            painter.setPen(QColor("#9ba6bb"))
            title_font = QFont(self.font())
            title_font.setPointSize(12)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(
                frame.adjusted(24, 0, -24, 0),
                Qt.AlignmentFlag.AlignCenter,
                "Importez une œuvre\npour construire son récit",
            )
        elif (
            not self._preview_frame.isNull()
            and self._preview_frame_index == self._playhead_frame
            and not self._preview_pending
        ):
            painter.drawImage(frame, self._preview_frame)
            painter.setPen(QColor(255, 255, 255, 190))
            painter.drawText(
                frame.adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                self._artwork_name,
            )
        else:
            base = self._artwork_rect(frame)
            pose = self._camera_pose
            painter.save()
            painter.setClipRect(frame)
            painter.translate(frame.center())
            painter.rotate(pose.rotation_degrees)
            target = QRectF(
                -pose.x * base.width() * pose.zoom,
                -pose.y * base.height() * pose.zoom,
                base.width() * pose.zoom,
                base.height() * pose.zoom,
            )
            painter.drawImage(target, self._artwork)
            painter.restore()
            painter.setPen(QColor(255, 255, 255, 190))
            painter.drawText(
                frame.adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                self._artwork_name,
            )
        if self._semantic_target_id is not None and not self._artwork.isNull():
            selection = self._semantic_selection_rect(self._semantic_target_id, frame)
            if not selection.isEmpty():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#66d9ff"), 2))
                painter.drawRoundedRect(selection, 3, 3)
                selected = self._semantic_scene.object_by_id(self._semantic_target_id) if self._semantic_scene else None
                if selected is not None:
                    painter.setPen(QColor("#bcefff"))
                    painter.drawText(
                        selection.adjusted(4, 4, -4, -4),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                        selected.label,
                    )

        guide_pen = QPen(QColor(255, 255, 255, 55), 1, Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        safe = frame.adjusted(
            int(frame.width() * 0.08),
            int(frame.height() * 0.08),
            -int(frame.width() * 0.08),
            -int(frame.height() * 0.08),
        )
        painter.drawRect(safe)
        painter.drawLine(frame.center().x(), frame.top(), frame.center().x(), frame.bottom())
        painter.drawLine(frame.left(), frame.center().y(), frame.right(), frame.center().y())

        painter.setPen(QColor("#8f9bb1"))
        painter.drawText(
            QRect(frame.left(), frame.bottom() + 3, frame.width(), 14),
            Qt.AlignmentFlag.AlignCenter,
            "1080 × 1920 · 9:16",
        )
        painter.setPen(QColor(255, 255, 255, 180))
        painter.drawText(
            frame.adjusted(12, 12, -12, -12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            StudioClock(self._playhead_fps).format_timecode(self._playhead_frame),
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.frame_rect().contains(event.position().toPoint())
            and not self._artwork.isNull()
        ):
            target_id = self._semantic_target_at(event.position(), self.frame_rect())
            self.set_semantic_target(target_id)
            self.semanticTargetSelected.emit(target_id)
            self._dragging_camera = True
            self._last_pointer = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging_camera and self._last_pointer is not None:
            delta = event.position() - self._last_pointer
            self._last_pointer = event.position()
            base = self._artwork_rect(self.frame_rect())
            if base.width() > 0 and base.height() > 0:
                pose = replace(
                    self._camera_pose,
                    x=min(2.0, max(-1.0, self._camera_pose.x - delta.x() / (base.width() * self._camera_pose.zoom))),
                    y=min(2.0, max(-1.0, self._camera_pose.y - delta.y() / (base.height() * self._camera_pose.zoom))),
                )
                self.set_camera_pose(pose, emit=True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_camera:
            self._dragging_camera = False
            self._last_pointer = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self.frame_rect().contains(event.position().toPoint()) and not self._artwork.isNull():
            factor = 2.0 ** (event.angleDelta().y() / 600.0)
            zoom = min(20.0, max(0.25, self._camera_pose.zoom * factor))
            self.set_camera_pose(replace(self._camera_pose, zoom=zoom), emit=True)
            event.accept()
            return
        super().wheelEvent(event)

class StudioTrackSummary(QFrame):
    """Live summary of the artwork-specific tracks present in StudioProject."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioTrackSummary")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)
        self.title = QLabel("TIMELINE · AUCUN PROJET")
        self.title.setObjectName("studioTimelineTitle")
        self._layout.addWidget(self.title)
        self._rows: list[QLabel] = []

    def set_project(self, project: StudioProject | None) -> None:
        for row in self._rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        if project is None:
            self.title.setText("TIMELINE · AUCUN PROJET")
            return
        clock = StudioClock(project.settings.fps)
        self.title.setText(
            f"TIMELINE · {clock.format_timecode(project.settings.duration_frames - 1)} "
            f"· {project.settings.fps} FPS"
        )
        icon = {
            TrackKind.VIDEO: "CAM / IMAGE",
            TrackKind.EFFECT: "ACTIONS",
            TrackKind.AUDIO: "AUDIO",
        }
        for track in project.tracks:
            row = QLabel(f"{icon[track.kind]:<12}  {track.name}    {len(track.clips)} clip(s)")
            row.setObjectName(f"studioTrack_{track.track_id}")
            row.setMinimumHeight(24)
            self._layout.addWidget(row)
            self._rows.append(row)


class StudioPanel(QWidget):
    choose_artwork_requested = Signal()
    project_changed = Signal(object)
    frame_requested = Signal(int)
    history_changed = Signal(bool, str, bool, str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        effect_config_provider: Callable[[], RenderConfig] | None = None,
        analysis_cache_dir: str | Path | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("studioV3Panel")
        self._project: StudioProject | None = None
        self._replaying_history = False
        self.history = StudioHistory(max_entries=200)
        self.undo_action = QAction("Annuler", self)
        self.undo_action.setShortcuts(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("Rétablir", self)
        self.redo_action.setShortcuts(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        self.addActions((self.undo_action, self.redo_action))
        self.undo_button = QPushButton("Annuler")
        self.undo_button.setObjectName("studioUndoButton")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Rétablir")
        self.redo_button.setObjectName("studioRedoButton")
        self.redo_button.clicked.connect(self.redo)
        self.preview_controller = StudioPreviewController(self)
        self.preview_controller.frameReady.connect(self._preview_ready)
        self.preview_controller.renderingChanged.connect(self._preview_rendering_changed)
        self.preview_controller.failed.connect(self._preview_failed)

        cache_root = (
            Path(analysis_cache_dir)
            if analysis_cache_dir is not None
            else Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.CacheLocation
                )
            ) / "ArtAnimate" / "scene-analysis"
        )
        self.analysis_controller = StudioAnalysisController(
            self,
            cache_dir=cache_root,
        )
        self.analysis_controller.analysisReady.connect(self._analysis_ready)
        self.analysis_controller.runningChanged.connect(self._analysis_running_changed)
        self.analysis_controller.failed.connect(self._analysis_failed)
        self.analysis_controller.cancelled.connect(self._analysis_cancelled)
        self.waveform_controller = StudioWaveformController(
            self,
            cache_dir=cache_root / "waveforms",
        )
        self.waveform_controller.waveformsReady.connect(self._waveforms_ready)
        self.waveform_controller.runningChanged.connect(self._waveform_running_changed)
        self.waveform_controller.failed.connect(self._waveform_failed)
        self._waveforms = {}

        self._analysis_project_id: str | None = None
        page = QVBoxLayout(self)
        page.setContentsMargins(8, 10, 8, 4)
        page.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Studio")
        title.setObjectName("studioV3Title")
        title_font = QFont(title.font())
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel(
            "La caméra raconte l’œuvre · la 2D et la 3D enrichissent le récit · le réel le conclut"
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("studioV3Subtitle")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        badge = QLabel("V3 · ARTWORK-FIRST")
        badge.setObjectName("studioV3Badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setMinimumWidth(150)
        header.addWidget(badge)
        proxy_label = QLabel("Aperçu")
        proxy_label.setObjectName("studioProxyLabel")
        header.addWidget(proxy_label)
        self.proxy_resolution = QComboBox()
        self.proxy_resolution.setObjectName("studioProxyResolution")
        for label, width in (("270p", 270), ("360p", 360), ("540p", 540)):
            self.proxy_resolution.addItem(label, width)
        self.proxy_resolution.setCurrentIndex(1)
        self.proxy_resolution.currentIndexChanged.connect(self._proxy_resolution_changed)
        header.addWidget(self.proxy_resolution)
        header.addWidget(self.undo_button)
        header.addWidget(self.redo_button)
        self.import_button = QPushButton("Importer une œuvre…")
        self.import_button.setObjectName("studioImportArtworkButton")
        self.import_button.clicked.connect(self.choose_artwork_requested)
        header.addWidget(self.import_button)
        page.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.canvas = StudioCanvas()
        self.canvas.artworkChanged.connect(self._artwork_changed)
        body.addWidget(self.canvas, 1)

        inspector = QFrame()
        inspector.setObjectName("studioInspector")
        inspector.setFrameShape(QFrame.Shape.StyledPanel)
        inspector.setMinimumWidth(250)
        inspector.setMaximumWidth(330)
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.addWidget(QLabel("PROJET STUDIO"))
        self.project_status = QLabel("Aucune œuvre sélectionnée")
        self.project_status.setObjectName("studioProjectStatus")
        self.project_status.setWordWrap(True)
        inspector_layout.addWidget(self.project_status)
        self.format_status = QLabel("Reel vertical · 1080 × 1920 · 30 FPS · 12 s")
        self.format_status.setObjectName("studioFormatStatus")
        self.format_status.setWordWrap(True)
        inspector_layout.addWidget(self.format_status)
        self.preview_status = QLabel("Proxy 360p · en attente d’une œuvre")
        self.preview_status.setObjectName("studioPreviewStatus")
        self.preview_status.setWordWrap(True)
        inspector_layout.addWidget(self.preview_status)
        principle = QLabel(
            "L’œuvre reste la source maîtresse. Les médias réels servent sa révélation, "
            "ils ne la remplacent pas."
        )
        principle.setObjectName("studioArtworkFirstPrinciple")
        principle.setWordWrap(True)
        inspector_layout.addWidget(principle)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setObjectName("studioInspectorTabs")
        self.semantic_panel = StudioSemanticPanel()
        self.semantic_panel.targetSelected.connect(self.canvas.set_semantic_target)
        self.canvas.semanticTargetSelected.connect(self.semantic_panel.select_target)
        self.semantic_panel.invocationSelected.connect(
            self._semantic_invocation_selected
        )
        self.semantic_panel.capabilityRequested.connect(self._semantic_add_capability)
        self.semantic_panel.invocationUpdateRequested.connect(self._semantic_update_invocation)
        self.semantic_panel.invocationDeleteRequested.connect(self._semantic_delete_invocation)
        self.trigger_panel = StudioTriggerPanel(
            capabilities=self.semantic_panel.registry,
        )
        self.trigger_panel.triggerAddRequested.connect(self._trigger_add)
        self.trigger_panel.triggerUpdateRequested.connect(self._trigger_update)
        self.trigger_panel.triggerDeleteRequested.connect(self._trigger_delete)


        camera_page = QWidget()
        self.analysis_panel = StudioAnalysisPanel()
        self.analysis_panel.analysisRequested.connect(self._request_scene_analysis)
        self.analysis_panel.cancelRequested.connect(self.analysis_controller.cancel_pending)
        self.analysis_panel.selectionRequested.connect(self._add_manual_selection)
        self.analysis_panel.correctionRequested.connect(self._correct_scene_object)
        self.analysis_panel.maskRequested.connect(self._choose_manual_mask)
        self.analysis_panel.ignoreRequested.connect(self._ignore_scene_object)
        self.semantic_panel.targetSelected.connect(
            self.analysis_panel.set_selected_target
        )

        camera_layout = QVBoxLayout(camera_page)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_inspector = StudioCameraInspector()
        self.camera_inspector.poseChanged.connect(self._camera_pose_edited)
        self.camera_inspector.addKeyframeRequested.connect(self._add_camera_keyframe)
        self.camera_inspector.removeKeyframeRequested.connect(
            self._remove_camera_keyframe
        )
        self.camera_inspector.copyKeyframeRequested.connect(self._copy_current_camera_keyframe)
        self.camera_inspector.easingChanged.connect(self._camera_easing_changed)
        camera_layout.addWidget(self.camera_inspector)
        self.camera_presets = StudioCameraPresetPanel()
        self.camera_presets.presetRequested.connect(self._apply_camera_preset)
        camera_layout.addWidget(self.camera_presets)
        camera_layout.addStretch(1)
        self.effect_inspector = StudioEffectInspector(effect_config_provider)
        self.effect_inspector.addRequested.connect(self._add_effect_layer)
        self.effect_inspector.applyRequested.connect(self._apply_effect_layer)
        self.effect_inspector.duplicateRequested.connect(
            lambda clip_id: self.timeline_actions.duplicate_clips((clip_id,))
        )
        self.inspector_tabs.addTab(self.semantic_panel, "Scène & actions")
        self.inspector_tabs.addTab(self.analysis_panel, "Analyse locale")
        self.inspector_tabs.addTab(self.trigger_panel, "Déclencheurs")
        self.inspector_tabs.addTab(camera_page, "Caméra")
        self.inspector_tabs.addTab(self.effect_inspector, "Réglages 2D")
        inspector_layout.addWidget(self.inspector_tabs, 1)
        body.addWidget(inspector)
        page.addLayout(body, 1)

        self.transport = StudioTransport()
        self.audio_monitor = StudioAudioMonitor(self)
        self.audio_monitor.failed.connect(self._audio_monitor_failed)
        self.transport.playbackChanged.connect(self._audio_playback_changed)

        self.transport.frameChanged.connect(self._frame_changed)
        self.canvas.cameraPoseChanged.connect(self._camera_pose_edited)
        page.addWidget(self.transport)

        self.keyframe_strip = StudioKeyframeStrip()
        self.keyframe_strip.seekRequested.connect(self.transport.seek)
        self.keyframe_strip.keyframeMoved.connect(self._move_camera_keyframe)
        self.keyframe_strip.keyframeCopied.connect(self._copy_camera_keyframe)
        self.keyframe_strip.keyframeDeleteRequested.connect(
            self._remove_camera_keyframe_at
        )
        page.addWidget(self.keyframe_strip)

        self.timeline = StudioTimeline()
        self.timeline.seekRequested.connect(self.transport.seek)
        self.timeline.addTrackRequested.connect(self._add_timeline_track)
        self.timeline.trackStateRequested.connect(self._timeline_track_state)
        self.timeline.selectionChanged.connect(self._timeline_selection_changed)
        self.timeline_actions = StudioTimelineActions(self)

        self.track_summary = StudioTrackSummary()
        self.asset_panel = StudioAssetPanel()
        self.asset_panel.contextChanged.connect(self._asset_context_changed)
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("studioEditorTabs")
        self.editor_tabs.addTab(self.timeline, "Timeline")
        self.editor_tabs.addTab(self.asset_panel, "Médias locaux")
        page.addWidget(self.editor_tabs, 1)
        self._refresh_history_actions()

    @property
    def project(self) -> StudioProject | None:
        return self._project

    def set_artwork(self, path: Path) -> bool:
        if not self.canvas.set_artwork(path):
            return False
        project = StudioProject.new(path)
        self.set_project(project, reset_history=True)
        return True

    def set_project(
        self,
        project: StudioProject | None,
        *,
        reset_history: bool = False,
        label: str = "Modifier le projet",
        merge_key: str | None = None,
    ) -> None:
        self.preview_controller.cancel_pending()
        self.analysis_controller.cancel_pending(notify=False)
        validated = project.validate() if project is not None else None
        self.waveform_controller.cancel_pending(notify=False)
        if not self._replaying_history:
            current = self.history.current
            if (
                reset_history
                or validated is None
                or current is None
                or current.project_id != validated.project_id
            ):
                self.history.reset(validated)
            else:
                self.history.commit(validated, label, merge_key=merge_key)
        self._project = validated
        self.track_summary.set_project(self._project)
        scene = self._project.scene if self._project is not None else None
        self.canvas.set_semantic_scene(scene)
        self.semantic_panel.set_project(self._project)
        self.analysis_panel.set_project(self._project)
        self.trigger_panel.set_project(self._project)
        self.audio_monitor.set_project(
            self._project,
            self.asset_panel.project_path,
        )
        self.timeline.set_project(self._project)
        valid_audio_assets = (
            {asset.asset_id for asset in self._project.assets if asset.kind == AssetKind.AUDIO}
            if self._project is not None else set()
        )
        self._waveforms = {
            key: value for key, value in self._waveforms.items()
            if key in valid_audio_assets
        }
        self.timeline.set_waveforms(self._waveforms)
        self.effect_inspector.set_selection(
            self._project, self.timeline.selected_clip_ids
        )
        if self._project is None:
            self.transport.set_project(30, 1)
            self.canvas.set_artwork(None)
            self.project_status.setText("Aucune œuvre sélectionnée")
            self.format_status.setText("Reel vertical · 1080 × 1920 · 30 FPS · 12 s")
            self.canvas.clear_preview()
            self.preview_status.setText(f"Proxy {self.preview_controller.proxy_width}p · en attente d’une œuvre")
        else:
            settings = self._project.settings
            self.transport.set_project(settings.fps, settings.duration_frames)
            duration = settings.duration_frames / settings.fps
            self.project_status.setText(
                f"Œuvre centrale · {Path(self._project.artwork.path).name}"
            )
            self.format_status.setText(
                f"Reel vertical · {settings.width} × {settings.height} · "
                f"{settings.fps} FPS · {duration:g} s"
            )
        self._refresh_history_actions()
        self.project_changed.emit(self._project)

    def commit_project(
        self,
        project: StudioProject,
        label: str,
        *,
        merge_key: str | None = None,
    ) -> bool:
        validated = project.validate()
        current = self._project
        if current is None or current.project_id != validated.project_id:
            self.set_project(validated, reset_history=True)
            return False
        if not self.history.commit(validated, label, merge_key=merge_key):
            return False
        frame = min(self.transport.current_frame, validated.settings.duration_frames - 1)
        timing_changed = (
            current.settings.fps != validated.settings.fps
            or current.settings.duration_frames != validated.settings.duration_frames
        )
        self._project = validated
        self.track_summary.set_project(validated)
        self.canvas.set_semantic_scene(validated.scene)
        self.semantic_panel.set_project(validated)
        self.analysis_panel.set_project(validated)
        self.trigger_panel.set_project(validated)
        self.audio_monitor.set_project(
            validated,
            self.asset_panel.project_path,
        )
        self.timeline.set_project(validated)
        valid_audio_assets = {
            asset.asset_id for asset in validated.assets
            if asset.kind == AssetKind.AUDIO
        }
        self._waveforms = {
            key: value for key, value in self._waveforms.items()
            if key in valid_audio_assets
        }
        self.timeline.set_waveforms(self._waveforms)
        self.effect_inspector.set_selection(
            validated, self.timeline.selected_clip_ids
        )
        if timing_changed:
            self.transport.set_project(
                validated.settings.fps,
                validated.settings.duration_frames,
            )
        duration = validated.settings.duration_frames / validated.settings.fps
        self.format_status.setText(
            f"Reel vertical · {validated.settings.width} × {validated.settings.height} · "
            f"{validated.settings.fps} FPS · {duration:g} s"
        )
        self._refresh_history_actions()
        self.project_changed.emit(validated)
        self.transport.seek(frame, force_signal=True)
        return True

    def _refresh_history_actions(self) -> None:
        undo_label = self.history.undo_label or ""
        redo_label = self.history.redo_label or ""
        undo_text = f"Annuler · {undo_label}" if undo_label else "Annuler"
        redo_text = f"Rétablir · {redo_label}" if redo_label else "Rétablir"
        self.undo_action.setText(undo_text)
        self.redo_action.setText(redo_text)
        self.undo_action.setEnabled(self.history.can_undo)
        self.redo_action.setEnabled(self.history.can_redo)
        self.undo_button.setEnabled(self.history.can_undo)
        self.redo_button.setEnabled(self.history.can_redo)
        self.undo_button.setToolTip(undo_text)
        self.redo_button.setToolTip(redo_text)
        self.history_changed.emit(
            self.history.can_undo,
            undo_label,
            self.history.can_redo,
            redo_label,
        )

    def _restore_history_project(self, project: StudioProject, message: str) -> None:
        frame = self.transport.current_frame
        self._replaying_history = True
        try:
            self.set_project(project)
        finally:
            self._replaying_history = False
        self.transport.seek(
            min(frame, project.settings.duration_frames - 1),
            force_signal=True,
        )
        self.project_status.setText(message)

    def undo(self) -> bool:
        label = self.history.undo_label
        if label is None:
            return False
        project = self.history.undo()
        self._restore_history_project(project, f"Annulé · {label}")
        return True

    def redo(self) -> bool:
        label = self.history.redo_label
        if label is None:
            return False
        project = self.history.redo()
        self._restore_history_project(project, f"Rétabli · {label}")
        return True


    def _frame_changed(self, frame: int) -> None:
        fps = self._project.settings.fps if self._project is not None else 30
        self.canvas.set_playhead(frame, fps)
        active = self._active_camera_clip(frame)
        if active is not None:
            _track_index, _clip_index, clip = active
            local_frame = frame - clip.start_frame
            pose = resolve_camera_pose(clip.camera, local_frame)
            animation = clip.camera or CameraAnimation()
            self.canvas.set_camera_pose(pose)
            self.camera_inspector.set_pose(pose)
            exact = next(
                (
                    keyframe
                    for keyframe in animation.keyframes
                    if keyframe.frame == local_frame
                ),
                None,
            )
            self.camera_inspector.set_keyframe_state(exact is not None)
            if exact is not None:
                self.camera_inspector.set_easing(exact.easing)
            self.keyframe_strip.set_animation(
                animation,
                clip_start=clip.start_frame,
                clip_duration=clip.duration_frames,
            )
            self.camera_presets.set_remaining_frames(
                clip.duration_frames - local_frame, fps=fps
            )
        else:
            self.camera_inspector.set_keyframe_state(False)
            self.keyframe_strip.set_animation(
                CameraAnimation(), clip_start=0, clip_duration=1
            )
            self.camera_presets.set_remaining_frames(1, fps=fps)
        self.keyframe_strip.set_playhead(frame)
        self.timeline.set_playhead(frame)
        self._request_preview(frame)
        self.audio_monitor.sync_frame(frame, playing=self.transport.is_playing)
        self.frame_requested.emit(frame)

    def _audio_playback_changed(self, playing: bool) -> None:
        self.audio_monitor.sync_frame(
            self.transport.current_frame,
            playing=playing,
        )

    def _asset_context_changed(
        self,
        project: StudioProject | None,
        project_path: Path | None,
    ) -> None:
        self.audio_monitor.set_project(project, project_path)
        if project is not None and project_path is not None:
            self.audio_monitor.sync_frame(
                self.transport.current_frame,
                playing=self.transport.is_playing,
            )
            self.waveform_controller.request(project, project_path)
        else:
            self._waveforms = {}
            self.timeline.set_waveforms({})

    def _waveforms_ready(self, waveforms: object) -> None:
        if not isinstance(waveforms, dict):
            return
        self._waveforms = dict(waveforms)
        self.timeline.set_waveforms(self._waveforms)
        if self._waveforms:
            self.asset_panel.set_feedback(
                f"Waveform locale prête · {len(self._waveforms)} piste(s) en cache"
            )

    def _waveform_running_changed(self, running: bool) -> None:
        if running:
            self.asset_panel.set_feedback("Calcul local de la waveform…")

    def _waveform_failed(self, message: str) -> None:
        self.asset_panel.set_feedback(f"Waveform indisponible · {message}")

    def _audio_monitor_failed(self, message: str) -> None:
        self.asset_panel.set_feedback(message)
        self.project_status.setText(message)

    def _artwork_changed(self, path: Path | None) -> None:
        if path is None:
            self.preview_controller.cancel_pending()
            return
        self._request_preview(self.transport.current_frame)

    def _request_scene_analysis(self) -> None:
        project = self._project
        artwork_path = self.canvas.artwork_path
        if project is None or artwork_path is None:
            self.analysis_panel.set_feedback(
                "Analyse impossible · aucune œuvre locale n’est ouverte."
            )
            return
        self._analysis_project_id = project.project_id
        self.analysis_controller.request(project, artwork_path)

    def _analysis_running_changed(self, running: bool) -> None:
        self.analysis_panel.set_busy(running)

    def _analysis_ready(self, result: SceneAnalysisResult) -> None:
        project = self._project
        artwork_path = self.canvas.artwork_path
        if (
            project is None
            or artwork_path is None
            or project.project_id != self._analysis_project_id
        ):
            return
        try:
            current = fingerprint_file(artwork_path)
            if current.fingerprint != result.source_fingerprint:
                self.analysis_panel.set_feedback(
                    "Analyse ignorée · le fichier de l’œuvre a changé pendant le calcul."
                )
                return
            updated = apply_scene_analysis(project, result)
            self.commit_project(updated, "Analyser l’œuvre localement")
            source = "cache local" if result.cache_hit else "calcul local"
            self.analysis_panel.set_feedback(
                f"Scène enrichie · masque + profondeur · {source}."
            )
            self.semantic_panel.select_target("auto-foreground")
        except (OSError, TypeError, ValueError) as exc:
            self.analysis_panel.set_feedback(f"Analyse non appliquée · {exc}")

    def _analysis_failed(self, message: str) -> None:
        self.analysis_panel.set_feedback(f"Analyse locale impossible · {message}")

    def _analysis_cancelled(self) -> None:
        self.analysis_panel.set_feedback(
            "Analyse annulée · la scène précédente est conservée."
        )

    def _project_reference_path(self) -> Path:
        project = self._project
        if project is None:
            return Path.cwd() / "untitled.artanimate"
        artwork = Path(project.artwork.path)
        parent = (
            artwork.resolve(strict=False).parent
            if artwork.is_absolute()
            else Path.cwd()
        )
        return parent / f".{project.project_id}.artanimate"

    def _add_manual_selection(self, bounds: Bounds, label: str) -> None:
        project = self._project
        if project is None:
            return
        try:
            updated, scene_object = add_manual_selection(
                project,
                bounds,
                label=label,
            )
            self.commit_project(updated, "Ajouter une zone manuelle")
            self.semantic_panel.select_target(scene_object.object_id)
            self.analysis_panel.set_feedback(
                f"Zone ajoutée · {scene_object.label}."
            )
        except (TypeError, ValueError) as exc:
            self.analysis_panel.set_feedback(f"Zone non ajoutée · {exc}")

    def _choose_manual_mask(
        self,
        bounds: Bounds,
        label: str,
        path: str | Path | None = None,
    ) -> None:
        project = self._project
        if project is None:
            return
        source = Path(path) if path is not None else None
        if source is None:
            selected, _filter = QFileDialog.getOpenFileName(
                self,
                "Choisir un masque local",
                "",
                "Images de masque (*.png *.jpg *.jpeg *.tif *.tiff *.webp)",
            )
            if not selected:
                return
            source = Path(selected)
        try:
            updated, scene_object = add_manual_mask(
                project,
                source,
                self._project_reference_path(),
                bounds,
                label=label,
            )
            self.commit_project(updated, "Ajouter un masque manuel")
            self.semantic_panel.select_target(scene_object.object_id)
            self.analysis_panel.set_feedback(
                f"Masque référencé · {source.name} · aucun pixel dans le projet."
            )
        except (OSError, TypeError, ValueError) as exc:
            self.analysis_panel.set_feedback(f"Masque non ajouté · {exc}")

    def _correct_scene_object(
        self,
        object_id: str,
        bounds: Bounds,
        label: str,
    ) -> None:
        project = self._project
        if project is None:
            return
        try:
            updated = update_scene_object_bounds(
                project,
                object_id,
                bounds,
                label=label,
            )
            self.commit_project(
                updated,
                "Corriger une détection",
                merge_key=f"scene-object-bounds:{object_id}",
            )
            self.semantic_panel.select_target(object_id)
            self.analysis_panel.set_feedback("Détection corrigée manuellement.")
        except (KeyError, TypeError, ValueError) as exc:
            self.analysis_panel.set_feedback(f"Correction impossible · {exc}")

    def _ignore_scene_object(self, object_id: str) -> None:
        project = self._project
        if project is None:
            return
        try:
            updated = remove_scene_object(project, object_id)
            self.commit_project(updated, "Ignorer une détection")
            self.semantic_panel.select_target("artwork")
            self.analysis_panel.set_feedback(
                "Détection ignorée · les actions qui la ciblaient ont été retirées."
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.analysis_panel.set_feedback(f"Détection conservée · {exc}")

    def _request_preview(self, frame: int) -> None:
        if self._project is None or self.canvas.artwork_path is None:
            return
        self.canvas.set_preview_pending(True)
        self.preview_controller.request(
            self._project,
            self.canvas.artwork_path,
            frame,
            resource_base=(
                self.asset_panel.project_path.parent if self.asset_panel.project_path else None
            ),
        )

    def _preview_ready(self, frame: int, image: QImage, cached: bool) -> None:
        if frame != self.transport.current_frame:
            return
        self.canvas.set_preview_frame(frame, image)
        state = "cache" if cached else "calculé"
        self.preview_status.setText(
            f"Proxy {self.preview_controller.proxy_width}p · frame {frame + 1} · {state}"
        )

    def _preview_rendering_changed(self, rendering: bool) -> None:
        if rendering:
            self.canvas.set_preview_pending(True)
            self.preview_status.setText(
                f"Proxy {self.preview_controller.proxy_width}p · calcul en cours…"
            )
        elif self.canvas.preview_pending:
            self.canvas.set_preview_pending(False)

    def _preview_failed(self, message: str) -> None:
        self.canvas.set_preview_pending(False)
        self.preview_status.setText(f"Proxy indisponible · {message}")

    def _proxy_resolution_changed(self, index: int) -> None:
        width = int(self.proxy_resolution.itemData(index))
        self.preview_controller.set_proxy_width(width)
        self._request_preview(self.transport.current_frame)


    def _active_camera_clip(self, frame: int):
        if self._project is None:
            return None
        artwork_kinds = {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}
        for track_index, track in enumerate(self._project.tracks):
            if track.kind != TrackKind.VIDEO or track.hidden:
                continue
            for clip_index, clip in enumerate(track.clips):
                if (
                    clip.enabled
                    and clip.kind in artwork_kinds
                    and clip.start_frame <= frame < clip.end_frame
                ):
                    return track_index, clip_index, clip
        return None

    def _replace_camera_animation(
        self,
        animation,
        *,
        label: str = "Ajuster la caméra",
        merge_key: str | None = None,
    ) -> None:
        if self._project is None:
            return
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        track_index, clip_index, clip = active
        updated_clip = replace(clip, camera=animation)
        clips = list(self._project.tracks[track_index].clips)
        clips[clip_index] = updated_clip
        tracks = list(self._project.tracks)
        tracks[track_index] = replace(tracks[track_index], clips=tuple(clips))
        project = replace(self._project, tracks=tuple(tracks)).validate()
        self.commit_project(project, label, merge_key=merge_key)

    def _camera_pose_edited(
        self,
        pose: CameraPose,
        *,
        label: str = "Ajuster la caméra",
        merge_key: str | None = None,
    ) -> None:
        frame = self.transport.current_frame
        active = self._active_camera_clip(frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        local_frame = frame - clip.start_frame
        animation = upsert_camera_keyframe(clip.camera, local_frame, pose)
        self.canvas.set_camera_pose(pose)
        self.camera_inspector.set_pose(pose)
        self._replace_camera_animation(
            animation,
            label=label,
            merge_key=merge_key or f"camera-pose:{clip.clip_id}:{local_frame}",
        )

    def _add_camera_keyframe(self) -> None:
        self._camera_pose_edited(
            self.camera_inspector.pose(),
            label="Ajouter un keyframe caméra",
        )

    def _remove_camera_keyframe(self) -> None:
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        self._remove_camera_keyframe_at(
            self.transport.current_frame - clip.start_frame
        )

    def _remove_camera_keyframe_at(self, local_frame: int) -> None:
        frame = self.transport.current_frame
        active = self._active_camera_clip(frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        try:
            animation = remove_camera_keyframe(clip.camera, local_frame)
        except KeyError:
            return
        self._replace_camera_animation(
            animation,
            label="Supprimer un keyframe caméra",
        )
        current_local = frame - clip.start_frame
        pose = resolve_camera_pose(animation, current_local)
        self.canvas.set_camera_pose(pose)
        self.camera_inspector.set_pose(pose)
        self._frame_changed(frame)

    def _move_camera_keyframe(self, source: int, target: int) -> None:
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        try:
            animation = move_camera_keyframe(
                clip.camera,
                source,
                target,
                clip_duration_frames=clip.duration_frames,
            )
        except (KeyError, ValueError) as exc:
            self.project_status.setText(f"Keyframe inchangé · {exc}")
            self._frame_changed(self.transport.current_frame)
            return
        self._replace_camera_animation(
            animation,
            label="Déplacer un keyframe caméra",
        )
        self.transport.seek(clip.start_frame + target)

    def _copy_camera_keyframe(self, source: int, target: int) -> None:
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        try:
            animation = copy_camera_keyframe(
                clip.camera,
                source,
                target,
                clip_duration_frames=clip.duration_frames,
            )
        except (KeyError, ValueError) as exc:
            self.project_status.setText(f"Keyframe inchangé · {exc}")
            self._frame_changed(self.transport.current_frame)
            return
        self._replace_camera_animation(
            animation,
            label="Copier un keyframe caméra",
        )
        self.transport.seek(clip.start_frame + target)

    def _copy_current_camera_keyframe(self) -> None:
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        source = self.transport.current_frame - clip.start_frame
        occupied = {keyframe.frame for keyframe in (clip.camera or CameraAnimation()).keyframes}
        target = next(
            (frame for frame in range(source + 1, clip.duration_frames) if frame not in occupied),
            None,
        )
        if target is None:
            self.project_status.setText("Aucune image libre après ce keyframe")
            return
        self._copy_camera_keyframe(source, target)

    def _camera_easing_changed(self, easing: Easing) -> None:
        easing = Easing(easing)
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        local_frame = self.transport.current_frame - clip.start_frame
        try:
            animation = set_camera_keyframe_easing(clip.camera, local_frame, easing)
        except KeyError:
            return
        self._replace_camera_animation(
            animation,
            label="Changer l’interpolation caméra",
            merge_key=f"camera-easing:{clip.clip_id}:{local_frame}",
        )

    def _commit_timeline_project(
        self,
        project: StudioProject,
        label: str = "Modifier la timeline",
        *,
        merge_key: str | None = None,
    ) -> None:
        self.commit_project(project, label, merge_key=merge_key)

    def _apply_camera_preset(
        self,
        preset: CameraPreset,
        intensity: float,
        duration_frames: int,
        mode: PresetApplyMode,
    ) -> None:
        project = self._project
        frame = self.transport.current_frame
        active = self._active_camera_clip(frame)
        if project is None or active is None:
            return
        _track_index, _clip_index, clip = active
        local_frame = frame - clip.start_frame
        remaining = clip.duration_frames - local_frame
        duration = min(int(duration_frames), remaining)
        if duration < 2:
            self.project_status.setText(
                "Preset caméra impossible · moins de deux frames disponibles"
            )
            return
        artwork_width = project.artwork.width or self.canvas._artwork.width()
        artwork_height = project.artwork.height or self.canvas._artwork.height()
        artwork_ratio = (
            artwork_width / artwork_height
            if artwork_width > 0 and artwork_height > 0
            else 1.0
        )
        try:
            animation = apply_camera_preset(
                clip.camera,
                CameraPreset(preset),
                start_frame=local_frame,
                duration_frames=duration,
                clip_duration_frames=clip.duration_frames,
                artwork_ratio=artwork_ratio,
                project_ratio=project.settings.width / project.settings.height,
                intensity=float(intensity),
                seed=project.project_id,
                mode=PresetApplyMode(mode),
            )
        except (TypeError, ValueError) as exc:
            self.project_status.setText(f"Preset caméra inchangé · {exc}")
            return
        self._replace_camera_animation(
            animation,
            label=f"Appliquer le mouvement {CameraPreset(preset).value}",
        )
        self.project_status.setText(
            f"Mouvement {CameraPreset(preset).value} · {len(animation.keyframes)} keyframes éditables"
        )


    def _trigger_add(
        self,
        source_invocation_id: str,
        event_id: str,
        action_invocation_id: str,
        offset_frames: int,
    ) -> None:
        project = self._project
        if project is None:
            return
        try:
            trigger = TimelineTrigger(
                f"trigger-{uuid4().hex}",
                source_invocation_id,
                event_id,
                action_invocation_id,
                int(offset_frames),
            )
            updated = replace(project, triggers=project.triggers + (trigger,))
            compile_timeline_triggers(updated, self.semantic_panel.registry)
            self.commit_project(updated, "Créer un déclencheur sémantique")
            self.project_status.setText(
                f"Déclencheur créé · {event_id} · {offset_frames:+d} frame(s)"
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.trigger_panel.status.setText(f"Lien inchangé · {exc}")
            self.project_status.setText(f"Déclencheur refusé · {exc}")

    def _trigger_update(self, trigger_id: str, offset_frames: int) -> None:
        project = self._project
        if project is None:
            return
        try:
            found = False
            triggers = []
            for trigger in project.triggers:
                if trigger.trigger_id == trigger_id:
                    trigger = replace(trigger, offset_frames=int(offset_frames))
                    found = True
                triggers.append(trigger)
            if not found:
                raise KeyError(f"Déclencheur introuvable : {trigger_id}")
            updated = replace(project, triggers=tuple(triggers))
            compile_timeline_triggers(updated, self.semantic_panel.registry)
            self.commit_project(
                updated,
                "Décaler un déclencheur sémantique",
                merge_key=f"trigger-offset:{trigger_id}",
            )
            self.project_status.setText(
                f"Déclencheur décalé · {offset_frames:+d} frame(s)"
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.trigger_panel.status.setText(f"Décalage inchangé · {exc}")
            self.project_status.setText(f"Déclencheur inchangé · {exc}")

    def _trigger_delete(self, trigger_id: str) -> None:
        project = self._project
        if project is None:
            return
        triggers = tuple(
            trigger for trigger in project.triggers
            if trigger.trigger_id != trigger_id
        )
        if len(triggers) == len(project.triggers):
            self.trigger_panel.status.setText(
                f"Déclencheur introuvable · {trigger_id}"
            )
            return
        updated = replace(project, triggers=triggers)
        self.commit_project(updated, "Supprimer un déclencheur sémantique")
        self.project_status.setText("Déclencheur supprimé")

    def _semantic_binding_for(self, invocation_id: str):
        if self._project is None:
            return None
        try:
            return project_as_semantic(self._project).binding_for(invocation_id)
        except KeyError:
            return None

    def _semantic_bound_clip(self, invocation_id: str):
        binding = self._semantic_binding_for(invocation_id)
        if binding is None or self._project is None:
            return None
        for track_index, track in enumerate(self._project.tracks):
            if track.track_id != binding.track_id:
                continue
            for clip_index, clip in enumerate(track.clips):
                if clip.clip_id == binding.clip_id:
                    return binding, track_index, clip_index, clip
        return None

    def _semantic_invocation_selected(self, invocation_id: str) -> None:
        resolved = self._semantic_bound_clip(invocation_id)
        if resolved is None:
            return
        _binding, _track_index, _clip_index, clip = resolved
        self.timeline.scene.set_selection((clip.clip_id,))

    def _semantic_add_capability(
        self,
        capability_id: str,
        target_id: str,
        values: object,
    ) -> None:
        project = self._project
        if project is None or not isinstance(values, dict):
            return
        try:
            descriptor = self.semantic_panel.registry.get(capability_id)
            if capability_id.startswith("reveal."):
                renderer_id = descriptor.renderer_candidates[0]
                effect = renderer_id.removeprefix("classic.effect.")
                config_values = self.effect_inspector.source_config_snapshot().to_dict()
                config_values["effect"] = effect
                config = RenderConfig.from_dict(config_values)
                self._add_effect_layer(
                    config,
                    1.0,
                    float(values.get("intensity", 1.0)),
                    float(values.get("opacity", 1.0)),
                )
                return
            if capability_id == "camera.animate":
                self.inspector_tabs.setCurrentWidget(
                    self.camera_inspector.parentWidget()
                )
                self._add_camera_keyframe()
                return
            if capability_id in {"artwork.present", "scene.depth_present"}:
                active = self._active_camera_clip(self.transport.current_frame)
                if active is None:
                    raise ValueError("aucun plan de l’œuvre sous la tête de lecture")
                track_index, clip_index, clip = active
                if capability_id == "scene.depth_present":
                    settings = values.get("settings")
                    if not isinstance(settings, dict):
                        settings = {}
                    parameters = {"schema_version": 1, **settings}
                    updated_clip = replace(
                        clip,
                        kind=ClipKind.ARTWORK_3D,
                        parameters=parameters,
                        source_in_frame=int(values.get("source_in_frame", 0)),
                        opacity=float(values.get("opacity", 1.0)),
                        fit=FitMode(values.get("fit", FitMode.CONTAIN.value)),
                    )
                    label = "Mettre l’œuvre en profondeur"
                else:
                    updated_clip = replace(
                        clip,
                        kind=ClipKind.ARTWORK_2D,
                        parameters=None,
                        source_in_frame=int(values.get("source_in_frame", 0)),
                        opacity=float(values.get("opacity", 1.0)),
                        fit=FitMode(values.get("fit", FitMode.CONTAIN.value)),
                    )
                    label = "Présenter l’œuvre en 2D"
                tracks = list(project.tracks)
                clips = list(tracks[track_index].clips)
                clips[clip_index] = updated_clip
                tracks[track_index] = replace(tracks[track_index], clips=tuple(clips))
                self.commit_project(replace(project, tracks=tuple(tracks)), label)
                return

            semantic_action = is_semantic_action_capability(capability_id)
            parameters = descriptor.normalize_parameters(values)
            start = self.transport.current_frame
            duration = min(
                project.settings.fps * (2 if semantic_action else 1),
                project.settings.duration_frames - start,
            )
            invocation = CapabilityInvocation.create(
                capability_id,
                start_frame=start,
                duration_frames=max(1, duration),
                target_id=target_id or None,
                parameters=parameters,
            )
            if semantic_action:
                updated, action_clip = add_semantic_action_clip(project, invocation)
            else:
                updated = replace(
                    project,
                    invocations=(*project.invocations, invocation),
                )
            self.commit_project(updated, f"Ajouter l’action {descriptor.label}")
            self.semantic_panel.select_invocation(invocation.invocation_id)
            if semantic_action:
                self.timeline.scene.set_selection((action_clip.clip_id,))
        except (IndexError, KeyError, TypeError, ValueError, PermissionError) as exc:
            self.project_status.setText(f"Action inchangée · {exc}")

    def _semantic_update_invocation(
        self,
        invocation_id: str,
        values: object,
    ) -> None:
        project = self._project
        if project is None or not isinstance(values, dict):
            return
        try:
            invocation = next(
                item for item in project.invocations
                if item.invocation_id == invocation_id
            )
            resolved = self._semantic_bound_clip(invocation_id)
            if resolved is None:
                descriptor = self.semantic_panel.registry.get(
                    invocation.capability_id
                )
                normalized = descriptor.normalize_parameters(values)
                invocations = tuple(
                    replace(item, parameters=normalized)
                    if item.invocation_id == invocation_id else item
                    for item in project.invocations
                )
                self.commit_project(
                    replace(project, invocations=invocations),
                    f"Régler l’action {descriptor.label}",
                    merge_key=f"semantic-invocation:{invocation_id}",
                )
                return

            binding, track_index, clip_index, clip = resolved
            if is_semantic_action_clip(clip):
                descriptor = self.semantic_panel.registry.get(
                    invocation.capability_id
                )
                normalized = descriptor.normalize_parameters(values)
                invocations = tuple(
                    replace(item, parameters=normalized)
                    if item.invocation_id == invocation_id else item
                    for item in project.invocations
                )
                self.commit_project(
                    replace(project, invocations=invocations),
                    f"Régler l’action {descriptor.label}",
                    merge_key=f"semantic-invocation:{invocation_id}",
                )
                return
            if binding.role == "effect":
                settings = settings_for_effect_clip(clip)
                config = RenderConfig.from_dict(values["render_config"])
                updated, updated_clip = update_effect_clip(
                    project,
                    clip.clip_id,
                    config=config,
                    duration_seconds=clip.duration_frames / project.settings.fps,
                    intensity=float(values.get("intensity", settings.intensity)),
                    opacity=float(values.get("opacity", clip.opacity)),
                    enabled=clip.enabled,
                )
            else:
                if binding.role == "camera":
                    keyframes = []
                    for item in values.get("keyframes", []):
                        pose = item["pose"]
                        keyframes.append(
                            CameraKeyframe(
                                int(item["frame"]),
                                CameraPose(
                                    x=float(pose["x"]),
                                    y=float(pose["y"]),
                                    zoom=float(pose["zoom"]),
                                    rotation_degrees=float(pose["rotation_degrees"]),
                                    perspective=float(pose["perspective"]),
                                    focus=float(pose["focus"]),
                                ),
                                Easing(item.get("easing", Easing.EASE_IN_OUT.value)),
                            )
                        )
                    updated_clip = replace(
                        clip,
                        camera=CameraAnimation(
                            tuple(sorted(keyframes, key=lambda item: item.frame))
                        ),
                    )
                else:
                    changes = {
                        "source_in_frame": int(values.get("source_in_frame", clip.source_in_frame)),
                        "opacity": float(values.get("opacity", clip.opacity)),
                        "fit": FitMode(values.get("fit", clip.fit.value)),
                    }
                    if invocation.capability_id == "scene.depth_present":
                        settings = values.get("settings", clip.parameters or {})
                        if not isinstance(settings, dict):
                            raise TypeError("les réglages 3D doivent être un objet")
                        changes["parameters"] = settings
                    updated_clip = replace(clip, **changes)
                tracks = list(project.tracks)
                clips = list(tracks[track_index].clips)
                clips[clip_index] = updated_clip
                tracks[track_index] = replace(tracks[track_index], clips=tuple(clips))
                updated = replace(project, tracks=tuple(tracks))
            self.commit_project(
                updated,
                f"Régler l’action {invocation.capability_id}",
                merge_key=f"semantic-invocation:{invocation_id}",
            )
            self.timeline.scene.set_selection((updated_clip.clip_id,))
        except (KeyError, StopIteration, TypeError, ValueError, PermissionError) as exc:
            self.project_status.setText(f"Action inchangée · {exc}")

    def _semantic_delete_invocation(self, invocation_id: str) -> None:
        project = self._project
        if project is None:
            return
        try:
            resolved = self._semantic_bound_clip(invocation_id)
            if resolved is None:
                invocations = tuple(
                    item for item in project.invocations
                    if item.invocation_id != invocation_id
                )
                if len(invocations) == len(project.invocations):
                    raise KeyError("action introuvable")
                triggers = tuple(
                    item for item in project.triggers
                    if item.source_invocation_id != invocation_id
                    and item.action_invocation_id != invocation_id
                )
                updated = replace(
                    project,
                    invocations=invocations,
                    triggers=triggers,
                )
            else:
                binding, track_index, clip_index, clip = resolved
                if binding.role == "camera":
                    tracks = list(project.tracks)
                    clips = list(tracks[track_index].clips)
                    clips[clip_index] = replace(clip, camera=None)
                    tracks[track_index] = replace(
                        tracks[track_index], clips=tuple(clips)
                    )
                    updated = replace(project, tracks=tuple(tracks))
                else:
                    updated = delete_clips(project, (clip.clip_id,))
            self.commit_project(updated, "Retirer une action de la mise en scène")
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self.project_status.setText(f"Action inchangée · {exc}")

    def _timeline_selection_changed(self, value: object) -> None:
        clip_ids = (
            tuple(str(item) for item in value)
            if isinstance(value, (tuple, list))
            else ()
        )
        self.effect_inspector.set_selection(self._project, clip_ids)
        if self._project is not None and clip_ids:
            selected = next(
                (
                    clip for track in self._project.tracks
                    for clip in track.clips
                    if clip.clip_id == clip_ids[0]
                ),
                None,
            )
            current_id = self.semantic_panel.selected_invocation_id
            current_binding = (
                self._semantic_binding_for(current_id)
                if current_id is not None else None
            )
            already_represents_clip = (
                current_binding is not None
                and current_binding.clip_id == clip_ids[0]
            )
            if selected is not None and selected.invocation_id is not None and not already_represents_clip:
                self.semantic_panel.select_invocation(selected.invocation_id)
        if self.effect_inspector.selected_clip_id is not None:
            self.inspector_tabs.setCurrentWidget(self.effect_inspector)

    def _add_effect_layer(
        self,
        config: RenderConfig,
        duration_seconds: float,
        intensity: float,
        opacity: float,
    ) -> None:
        project = self._project
        if project is None:
            return
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            self.project_status.setText(
                "Effet 2D impossible · aucun plan de l’œuvre sous la tête de lecture"
            )
            return
        _track_index, _clip_index, target = active
        try:
            updated, clip = add_effect_clip(
                project,
                config,
                start_frame=self.transport.current_frame,
                duration_seconds=float(duration_seconds),
                intensity=float(intensity),
                opacity=float(opacity),
                target_clip_id=target.clip_id,
            )
            self.commit_project(
                updated,
                f"Ajouter l’effet {settings_for_effect_clip(clip).effect}",
            )
            self.timeline.scene.set_selection((clip.clip_id,))
            self.inspector_tabs.setCurrentWidget(self.effect_inspector)
            self.project_status.setText(
                f"Effet 2D ajouté · {duration_seconds:g} s · lié à l’œuvre"
            )
        except (TypeError, ValueError, PermissionError) as exc:
            self.project_status.setText(f"Effet 2D inchangé · {exc}")

    def _apply_effect_layer(
        self,
        clip_id: str,
        config: RenderConfig,
        duration_seconds: float,
        intensity: float,
        opacity: float,
        enabled: bool,
    ) -> None:
        project = self._project
        if project is None:
            return
        try:
            updated, clip = update_effect_clip(
                project,
                clip_id,
                config=config,
                duration_seconds=float(duration_seconds),
                intensity=float(intensity),
                opacity=float(opacity),
                enabled=bool(enabled),
            )
            settings = settings_for_effect_clip(clip)
            self.commit_project(
                updated,
                f"Régler l’effet {settings.effect}",
                merge_key=f"effect-settings:{clip_id}",
            )
            self.timeline.scene.set_selection((clip.clip_id,))
            state = "actif" if clip.enabled else "désactivé"
            self.project_status.setText(
                f"Effet 2D {state} · intensité {settings.intensity:.0%} · "
                f"opacité {clip.opacity:.0%}"
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            self.project_status.setText(f"Effet 2D inchangé · {exc}")

    def _add_timeline_track(self, kind: TrackKind) -> None:
        if self._project is None:
            return
        project, track = add_track(self._project, TrackKind(kind))
        self._commit_timeline_project(project, f"Ajouter la piste {track.name}")
        self.project_status.setText(
            f"Piste ajoutée · {track.name} · couche Z{len(project.tracks) - 1}"
        )

    def _timeline_track_state(self, track_id: str, field: str, value: bool) -> None:
        if self._project is None:
            return
        changes = {
            "muted": {"muted": value},
            "locked": {"locked": value},
            "hidden": {"hidden": value},
        }
        try:
            kwargs = changes[field]
        except KeyError:
            return
        project = set_track_state(self._project, track_id, **kwargs)
        action = {"muted": "audio", "locked": "verrou", "hidden": "visibilité"}[
            field
        ]
        self._commit_timeline_project(project, f"Changer {action} de la piste")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        self.preview_controller.shutdown()
        self.analysis_controller.shutdown()
        self.audio_monitor.shutdown()
        self.waveform_controller.shutdown()

    def activate(self) -> None:
        self.canvas.update()


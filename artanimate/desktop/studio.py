from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..studio.camera import (
    copy_camera_keyframe,
    move_camera_keyframe,
    remove_camera_keyframe,
    resolve_camera_pose,
    set_camera_keyframe_easing,
    upsert_camera_keyframe,
)
from ..studio.clock import StudioClock
from ..studio.model import CameraAnimation, CameraPose, ClipKind, Easing, StudioProject, TrackKind
from ..studio.timeline import add_track, set_track_state
from .studio_camera import StudioCameraInspector
from .studio_assets import StudioAssetPanel
from .studio_keyframes import StudioKeyframeStrip
from .studio_timeline import StudioTimeline
from .studio_transport import StudioTransport


class StudioCanvas(QWidget):
    """Artwork-first 9:16 canvas used by the V3 Studio workspace."""

    cameraPoseChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioCanvas")
        self.setAccessibleName("Canvas vertical du Studio")
        self.setMinimumSize(250, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._artwork = QImage()
        self._artwork_name = ""
        self._playhead_frame = 0
        self._playhead_fps = 30
        self._camera_pose = CameraPose()
        self._dragging_camera = False
        self._last_pointer = None

    def sizeHint(self) -> QSize:
        return QSize(360, 640)

    def set_artwork(self, path: Path | None) -> bool:
        if path is None:
            self._artwork = QImage()
            self._artwork_name = ""
            self.update()
            return True
        image = QImage(str(path))
        if image.isNull():
            return False
        self._artwork = image
        self._artwork_name = path.name
        self.update()
        return True

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
            TrackKind.EFFECT: "FX 2D / 3D",
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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioV3Panel")
        self._project: StudioProject | None = None

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
        self.import_button = QPushButton("Importer une œuvre…")
        self.import_button.setObjectName("studioImportArtworkButton")
        self.import_button.clicked.connect(self.choose_artwork_requested)
        header.addWidget(self.import_button)
        page.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.canvas = StudioCanvas()
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
        principle = QLabel(
            "L’œuvre reste la source maîtresse. Les médias réels servent sa révélation, "
            "ils ne la remplacent pas."
        )
        principle.setObjectName("studioArtworkFirstPrinciple")
        principle.setWordWrap(True)
        inspector_layout.addWidget(principle)
        self.camera_inspector = StudioCameraInspector()
        self.camera_inspector.poseChanged.connect(self._camera_pose_edited)
        self.camera_inspector.addKeyframeRequested.connect(self._add_camera_keyframe)
        self.camera_inspector.removeKeyframeRequested.connect(
            self._remove_camera_keyframe
        )
        self.camera_inspector.copyKeyframeRequested.connect(self._copy_current_camera_keyframe)
        self.camera_inspector.easingChanged.connect(self._camera_easing_changed)
        inspector_layout.addWidget(self.camera_inspector)
        inspector_layout.addStretch(1)
        body.addWidget(inspector)
        page.addLayout(body, 1)

        self.transport = StudioTransport()
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

        self.track_summary = StudioTrackSummary()
        self.asset_panel = StudioAssetPanel()
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("studioEditorTabs")
        self.editor_tabs.addTab(self.timeline, "Timeline")
        self.editor_tabs.addTab(self.asset_panel, "Médias locaux")
        page.addWidget(self.editor_tabs, 1)

    @property
    def project(self) -> StudioProject | None:
        return self._project

    def set_artwork(self, path: Path) -> bool:
        if not self.canvas.set_artwork(path):
            return False
        project = StudioProject.new(path)
        self.set_project(project)
        return True

    def set_project(self, project: StudioProject | None) -> None:
        self._project = project.validate() if project is not None else None
        self.track_summary.set_project(self._project)
        self.timeline.set_project(self._project)
        if self._project is None:
            self.transport.set_project(30, 1)
            self.canvas.set_artwork(None)
            self.project_status.setText("Aucune œuvre sélectionnée")
            self.format_status.setText("Reel vertical · 1080 × 1920 · 30 FPS · 12 s")
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
        self.project_changed.emit(self._project)

    def _frame_changed(self, frame: int) -> None:
        fps = self._project.settings.fps if self._project is not None else 30
        self.canvas.set_playhead(frame, fps)
        active = self._active_camera_clip(frame)
        if active is not None:
            _track_index, _clip_index, clip = active
            local_frame = frame - clip.start_frame
            pose = resolve_camera_pose(clip.camera, local_frame)
            self.canvas.set_camera_pose(pose)
            self.camera_inspector.set_pose(pose)
            exact = next(
                (
                    keyframe
                    for keyframe in clip.camera.keyframes
                    if keyframe.frame == local_frame
                ),
                None,
            )
            self.camera_inspector.set_keyframe_state(exact is not None)
            if exact is not None:
                self.camera_inspector.set_easing(exact.easing)
            self.keyframe_strip.set_animation(
                clip.camera,
                clip_start=clip.start_frame,
                clip_duration=clip.duration_frames,
            )
        else:
            self.camera_inspector.set_keyframe_state(False)
            self.keyframe_strip.set_animation(
                CameraAnimation(), clip_start=0, clip_duration=1
            )
        self.keyframe_strip.set_playhead(frame)
        self.timeline.set_playhead(frame)
        self.frame_requested.emit(frame)

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

    def _replace_camera_animation(self, animation) -> None:
        if self._project is None:
            return
        frame = self.transport.current_frame
        active = self._active_camera_clip(frame)
        if active is None:
            return
        track_index, clip_index, clip = active
        updated_clip = replace(clip, camera=animation)
        clips = list(self._project.tracks[track_index].clips)
        clips[clip_index] = updated_clip
        tracks = list(self._project.tracks)
        tracks[track_index] = replace(tracks[track_index], clips=tuple(clips))
        self._project = replace(self._project, tracks=tuple(tracks)).validate()
        self.track_summary.set_project(self._project)
        self.timeline.set_project(self._project)
        updated = self._active_camera_clip(frame)
        if updated is not None:
            _track_index, _clip_index, updated_clip = updated
            self.keyframe_strip.set_animation(
                updated_clip.camera,
                clip_start=updated_clip.start_frame,
                clip_duration=updated_clip.duration_frames,
            )
        self.project_changed.emit(self._project)
        self._frame_changed(frame)

    def _camera_pose_edited(self, pose: CameraPose) -> None:
        frame = self.transport.current_frame
        active = self._active_camera_clip(frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        local_frame = frame - clip.start_frame
        animation = upsert_camera_keyframe(clip.camera, local_frame, pose)
        self.canvas.set_camera_pose(pose)
        self.camera_inspector.set_pose(pose)
        self._replace_camera_animation(animation)

    def _add_camera_keyframe(self) -> None:
        self._camera_pose_edited(self.camera_inspector.pose())

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
        self._replace_camera_animation(animation)
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
        self._replace_camera_animation(animation)
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
        self._replace_camera_animation(animation)
        self.transport.seek(clip.start_frame + target)

    def _copy_current_camera_keyframe(self) -> None:
        active = self._active_camera_clip(self.transport.current_frame)
        if active is None:
            return
        _track_index, _clip_index, clip = active
        source = self.transport.current_frame - clip.start_frame
        occupied = {keyframe.frame for keyframe in clip.camera.keyframes}
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
        self._replace_camera_animation(animation)
    def _commit_timeline_project(self, project: StudioProject) -> None:
        frame = self.transport.current_frame
        self._project = project.validate()
        self.track_summary.set_project(self._project)
        self.timeline.set_project(self._project)
        self.project_changed.emit(self._project)
        self.transport.seek(frame, force_signal=True)

    def _add_timeline_track(self, kind: TrackKind) -> None:
        if self._project is None:
            return
        project, track = add_track(self._project, TrackKind(kind))
        self._commit_timeline_project(project)
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
        self._commit_timeline_project(project)


    def activate(self) -> None:
        self.canvas.update()


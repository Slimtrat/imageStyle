from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from artanimate.core.video import VideoFrameEncoder
from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController
from artanimate.desktop.studio_video_inspector import StudioVideoInspector
from artanimate.studio.assets import register_media_asset
from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.video import NativeAudioMode, add_video_clip


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def encode_video(path: Path, *, frames: int = 8, fps: int = 24) -> None:
    encoder = VideoFrameEncoder(path, 64, 48, fps, quality="fast", total_frames=frames)
    try:
        for index in range(frames):
            encoder.write(np.full((48, 64, 3), (index * 20, 80, 180), dtype=np.uint8))
        encoder.finish()
    except Exception:
        encoder.abort()
        raise


def test_video_inspector_edits_source_range_transform_and_audio_policy(app, tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    video = tmp_path / "capture.mp4"
    Image.new("RGB", (90, 160), "white").save(artwork)
    encode_video(video)
    project = StudioProject.new(artwork)
    project, asset, _created = register_media_asset(
        project,
        video,
        tmp_path / "reel.artanimate",
    )
    project, clip = add_video_clip(project, asset.asset_id, start_frame=30)
    inspector = StudioVideoInspector()
    captured = []
    inspector.applyRequested.connect(captured.append)

    inspector.set_selection(project, (clip.clip_id,))
    inspector.source_in.setValue(2)
    inspector.duration.setValue(6)
    inspector.rotation.setValue(-7.5)
    inspector.native_audio.setCurrentIndex(
        inspector.native_audio.findData(NativeAudioMode.REFERENCE)
    )
    inspector.apply_button.click()

    assert inspector.selected_clip_id == clip.clip_id
    assert captured[0].source_in_frame == 2
    assert captured[0].duration_frames == 6
    assert captured[0].settings.transform.rotation_degrees == pytest.approx(-7.5)
    assert captured[0].settings.native_audio_mode == NativeAudioMode.REFERENCE


def test_document_imports_and_places_video_as_one_undoable_command(app, tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    video = tmp_path / "capture.mp4"
    Image.new("RGB", (90, 160), "white").save(artwork)
    encode_video(video)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    panel = StudioPanel()
    controller = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", "VideoImport"),
        QWidget(),
    )
    try:
        assert controller.new_project(artwork)
        panel.transport.seek(12)
        assert controller.import_media(video)
        clip = next(
            item
            for track in panel.project.tracks
            for item in track.clips
            if item.kind == ClipKind.VIDEO
        )
        assert clip.start_frame == 12
        assert panel.timeline.selected_clip_ids == (clip.clip_id,)
        assert panel.history.undo_label == f"Importer et placer la vidéo {video.name}"
        assert panel.undo()
        assert panel.project.assets == ()
        assert all(
            item.kind != ClipKind.VIDEO
            for track in panel.project.tracks
            for item in track.clips
        )
        assert video.is_file()
    finally:
        controller.shutdown()

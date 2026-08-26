from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import wave

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.studio.audio import (
    AudioClipSettings,
    AudioFadeCurve,
    AudioMixSettings,
    add_audio_clip,
)
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, ClipKind, StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Signal:
    def connect(self, _callback) -> None:
        pass


class _Player:
    def __init__(self) -> None:
        self.errorOccurred = _Signal()
        self.mediaStatusChanged = _Signal()
        self.position_ms = 0
        self.state = QMediaPlayer.PlaybackState.StoppedState

    def setSource(self, _source) -> None:
        pass

    def position(self) -> int:
        return self.position_ms

    def setPosition(self, value: int) -> None:
        self.position_ms = value

    def playbackState(self):
        return self.state

    def play(self) -> None:
        self.state = QMediaPlayer.PlaybackState.PlayingState

    def pause(self) -> None:
        self.state = QMediaPlayer.PlaybackState.PausedState

    def stop(self) -> None:
        self.state = QMediaPlayer.PlaybackState.StoppedState

    def deleteLater(self) -> None:
        pass


class _Output:
    def __init__(self) -> None:
        self.volume = 0.0

    def setVolume(self, value: float) -> None:
        self.volume = value

    def deleteLater(self) -> None:
        pass


def _project(tmp_path: Path) -> tuple[StudioProject, str]:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    Image.new("RGB", (100, 160), "white").save(artwork)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\0\x20" * 240_000)
    asset = import_media_asset(
        audio,
        AssetKind.AUDIO,
        tmp_path / "reel.artanimate",
        asset_id="music",
    )
    project = replace(
        StudioProject.new(artwork, duration_seconds=5),
        assets=(asset,),
    ).validate()
    project, clip = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=60,
    )
    return project, clip.clip_id


def _clip(project: StudioProject, clip_id: str):
    return next(
        clip
        for track in project.tracks
        for clip in track.clips
        if clip.clip_id == clip_id and clip.kind == ClipKind.AUDIO
    )


def _panel(project: StudioProject) -> StudioPanel:
    panel = StudioPanel()
    panel.audio_monitor._channel_factory = lambda _parent: (_Player(), _Output())
    panel.resize(1200, 1000)
    panel.set_project(project, reset_history=True)
    panel.show()
    QApplication.processEvents()
    return panel


def test_audio_inspector_applies_serialized_mix_and_undo_redo(app, tmp_path: Path) -> None:
    project, clip_id = _project(tmp_path)
    panel = _panel(project)
    try:
        panel.timeline.scene.set_selection((clip_id,))
        inspector = panel.audio_inspector
        assert panel.inspector_tabs.currentWidget() is inspector

        inspector.source_in.setValue(10)
        inspector.duration.setValue(40)
        inspector.clip_gain.setValue(3.0)
        inspector.fade_in.setValue(8)
        inspector.fade_out.setValue(12)
        inspector.fade_in_curve.setCurrentIndex(
            inspector.fade_in_curve.findData(AudioFadeCurve.LINEAR)
        )
        inspector.fade_out_curve.setCurrentIndex(
            inspector.fade_out_curve.findData(AudioFadeCurve.LINEAR)
        )
        inspector.track_gain.setValue(-2.0)
        inspector.track_muted.setChecked(True)
        inspector.apply_button.click()

        assert panel.project is not None
        edited = _clip(panel.project, clip_id)
        settings = AudioClipSettings.from_clip(edited)
        assert (edited.source_in_frame, edited.duration_frames) == (10, 40)
        assert (settings.gain_db, settings.fade_in_frames, settings.fade_out_frames) == (
            3.0,
            8,
            12,
        )
        assert settings.fade_in_curve == settings.fade_out_curve == AudioFadeCurve.LINEAR
        assert AudioMixSettings.from_project(panel.project).track("audio-main").gain_db == -2.0
        assert next(track for track in panel.project.tracks if track.track_id == "audio-main").muted
        assert panel.history.undo_label == "Régler le mix audio"

        assert panel.undo()
        restored = _clip(panel.project, clip_id)
        assert (restored.source_in_frame, restored.duration_frames) == (0, 60)
        assert AudioMixSettings.from_project(panel.project).track("audio-main").gain_db == 0.0
        assert not next(
            track for track in panel.project.tracks if track.track_id == "audio-main"
        ).muted
        assert panel.redo()
        assert _clip(panel.project, clip_id).source_in_frame == 10
    finally:
        panel.shutdown()
        panel.close()


def test_timeline_fade_handle_is_frame_exact_and_reversible(app, tmp_path: Path) -> None:
    project, clip_id = _project(tmp_path)
    panel = _panel(project)
    try:
        scene = panel.timeline.scene
        scene.set_selection((clip_id,))
        layout = next(item for item in scene.clip_layouts if item.clip.clip_id == clip_id)
        start = QPoint(int(layout.rect.left()), int(layout.rect.top() + 3))
        destination = QPoint(
            int(layout.rect.left() + 6 * scene.pixels_per_frame),
            start.y(),
        )

        QTest.mousePress(scene, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(scene, destination)
        QTest.mouseRelease(scene, Qt.MouseButton.LeftButton, pos=destination)

        assert panel.project is not None
        assert AudioClipSettings.from_clip(_clip(panel.project, clip_id)).fade_in_frames == 6
        assert panel.history.undo_label == "Régler les fondus audio"
        assert panel.undo()
        assert AudioClipSettings.from_clip(_clip(panel.project, clip_id)).fade_in_frames == 0
        assert panel.redo()
        assert AudioClipSettings.from_clip(_clip(panel.project, clip_id)).fade_in_frames == 6
    finally:
        panel.shutdown()
        panel.close()

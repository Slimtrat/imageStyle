from __future__ import annotations

import os
from pathlib import Path
import wave

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QWidget

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_document import StudioDocumentController
from artanimate.studio.model import ClipKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _Signal:
    def connect(self, _callback) -> None:
        pass


class _Player:
    def __init__(self) -> None:
        self.errorOccurred = _Signal()
        self.position_ms = 0
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.play_count = 0
        self.stopped = False

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
        self.play_count += 1

    def pause(self) -> None:
        self.state = QMediaPlayer.PlaybackState.PausedState

    def stop(self) -> None:
        self.stopped = True
        self.state = QMediaPlayer.PlaybackState.StoppedState

    def deleteLater(self) -> None:
        pass


class _Output:
    def setVolume(self, _value: float) -> None:
        pass

    def deleteLater(self) -> None:
        pass


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\0\0" * 48_000)


def test_import_places_audio_at_playhead_and_transport_remains_master(
    app,
    tmp_path: Path,
) -> None:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    artwork = tmp_path / "artwork.png"
    audio = tmp_path / "music.wav"
    Image.new("RGB", (120, 80), (80, 120, 180)).save(artwork)
    _write_wav(audio)

    panel = StudioPanel()
    players: list[_Player] = []

    def factory(_parent):
        player = _Player()
        players.append(player)
        return player, _Output()

    panel.audio_monitor._channel_factory = factory
    document = StudioDocumentController(
        panel,
        QSettings("ArtAnimateTests", f"Audio-{tmp_path.name}"),
        QWidget(),
    )
    try:
        assert document.new_project(artwork)
        panel.transport.seek(30)
        assert document.import_media(audio)
        app.processEvents()

        assert panel.project is not None
        assert len(panel.project.assets) == 1
        audio_clips = tuple(
            clip
            for track in panel.project.tracks
            for clip in track.clips
            if clip.kind == ClipKind.AUDIO
        )
        assert len(audio_clips) == 1
        clip = audio_clips[0]
        assert (clip.start_frame, clip.duration_frames) == (30, 30)
        assert panel.timeline.selected_clip_ids == (clip.clip_id,)
        assert panel.history.undo_label == f"Importer et placer l’audio {audio.name}"
        assert panel.audio_monitor.active_clip_ids == (clip.clip_id,)

        panel.transport.play()
        assert players[-1].play_count == 1
        panel.transport.seek(45)
        assert players[-1].position_ms == 500

        panel._timeline_track_state("audio-main", "muted", True)
        assert panel.audio_monitor.active_clip_ids == ()
        assert panel.undo()
        assert panel.audio_monitor.active_clip_ids == (clip.clip_id,)

        audio.unlink()
        document.refresh_assets()
        assert "Audio manquant ignoré" in panel.asset_panel.feedback.text()
        assert panel.project is not None
    finally:
        document.shutdown()

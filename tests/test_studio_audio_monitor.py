from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import wave

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_audio import StudioAudioMonitor
from artanimate.studio.audio import add_audio_clip
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, StudioProject


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class FakePlayer:
    def __init__(self) -> None:
        self.errorOccurred = FakeSignal()
        self.source = None
        self.position_ms = 0
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.play_count = 0
        self.pause_count = 0
        self.stop_count = 0
        self.deleted = False

    def setSource(self, source) -> None:
        self.source = source

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
        self.pause_count += 1

    def stop(self) -> None:
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.stop_count += 1

    def deleteLater(self) -> None:
        self.deleted = True


class FakeOutput:
    def __init__(self) -> None:
        self.volume = None
        self.deleted = False

    def setVolume(self, value: float) -> None:
        self.volume = value

    def deleteLater(self) -> None:
        self.deleted = True


def _project(tmp_path: Path) -> tuple[StudioProject, Path]:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    Image.new("RGB", (100, 80), (100, 130, 170)).save(artwork)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(30_000)
        output.writeframes(b"\0\0" * 60_000)
    project_path = tmp_path / "reel.artanimate"
    asset = import_media_asset(audio, AssetKind.AUDIO, project_path, asset_id="music")
    project = replace(
        StudioProject.new(artwork, duration_seconds=4),
        assets=(asset,),
    ).validate()
    project, _clip = add_audio_clip(
        project,
        "music",
        start_frame=10,
        source_in_frame=5,
        duration_frames=30,
    )
    return project, project_path


def test_monitor_is_slaved_to_seek_play_pause_and_releases_channels(
    app,
    tmp_path: Path,
) -> None:
    channels: list[tuple[FakePlayer, FakeOutput]] = []

    def factory(_parent):
        channel = (FakePlayer(), FakeOutput())
        channels.append(channel)
        return channel

    project, project_path = _project(tmp_path)
    monitor = StudioAudioMonitor(channel_factory=factory)
    active = []
    monitor.activeClipsChanged.connect(active.append)
    monitor.set_project(project, project_path)

    monitor.sync_frame(15, playing=False)
    player, output = channels[0]
    assert player.position_ms == 333
    assert player.source.isLocalFile()
    assert output.volume == 1.0
    assert monitor.channel_count == 1

    monitor.sync_frame(15, playing=True)
    assert player.play_count == 1
    player.position_ms = 0
    monitor.sync_frame(16, playing=True)
    assert player.position_ms == 366

    monitor.sync_frame(16, playing=False)
    assert player.pause_count == 1
    monitor.sync_frame(50, playing=False)
    assert monitor.channel_count == 0
    assert player.stop_count == 1
    assert player.deleted and output.deleted
    assert active[-1] == ()

    monitor.shutdown()

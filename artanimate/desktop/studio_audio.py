from __future__ import annotations

from dataclasses import dataclass
from math import pow
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..studio.audio import AudioPlaybackTarget, audio_monitor_frame
from ..studio.model import StudioProject


ChannelFactory = Callable[[QObject], tuple[Any, Any]]


@dataclass(slots=True)
class _MonitorChannel:
    player: Any
    output: Any
    path: Path
    desired_position_ms: int = 0
    desired_playing: bool = False


def _qt_channel(parent: QObject) -> tuple[QMediaPlayer, QAudioOutput]:
    output = QAudioOutput(parent)
    player = QMediaPlayer(parent)
    player.setAudioOutput(output)
    return player, output


class StudioAudioMonitor(QObject):
    """Local audio outputs slaved to the canonical frame-based Studio transport."""

    failed = Signal(str)
    activeClipsChanged = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        channel_factory: ChannelFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_factory = channel_factory or _qt_channel
        self._project: StudioProject | None = None
        self._project_path: Path | None = None
        self._channels: dict[str, _MonitorChannel] = {}
        self._missing: tuple[str, ...] = ()
        self._active: tuple[str, ...] = ()

    @property
    def active_clip_ids(self) -> tuple[str, ...]:
        return self._active

    @property
    def channel_count(self) -> int:
        return len(self._channels)

    def set_project(
        self,
        project: StudioProject | None,
        project_path: str | Path | None = None,
    ) -> None:
        self._release_all()
        self._project = project
        self._project_path = Path(project_path) if project_path is not None else None
        self._missing = ()
        self._set_active(())

    def sync_frame(self, frame: int, *, playing: bool) -> None:
        project = self._project
        if project is None:
            self._release_all()
            self._set_active(())
            return
        state = audio_monitor_frame(project, frame, self._project_path)
        if state.missing_asset_ids != self._missing:
            self._missing = state.missing_asset_ids
            if self._missing:
                self.failed.emit(
                    "Audio manquant ignoré · " + ", ".join(self._missing)
                )
        desired = {item.clip_id: item for item in state.targets}
        for clip_id in tuple(self._channels):
            if clip_id not in desired:
                self._release(clip_id)
        for target in state.targets:
            self._sync_target(target, playing=playing)
        self._set_active(tuple(item.clip_id for item in state.targets))

    def _sync_target(self, target: AudioPlaybackTarget, *, playing: bool) -> None:
        channel = self._channels.get(target.clip_id)
        if channel is None or channel.path != target.path:
            if channel is not None:
                self._release(target.clip_id)
            player, output = self._channel_factory(self)
            channel = _MonitorChannel(player, output, target.path)
            self._channels[target.clip_id] = channel
            error_signal = getattr(player, "errorOccurred", None)
            if error_signal is not None:
                error_signal.connect(
                    lambda _error, message, clip_id=target.clip_id: self.failed.emit(
                        f"Audio {clip_id} indisponible · {message}"
                    )
                )
            status_signal = getattr(player, "mediaStatusChanged", None)
            if status_signal is not None:
                status_signal.connect(
                    lambda status, clip_id=target.clip_id: self._media_status_changed(
                        clip_id, status
                    )
                )
            player.setSource(QUrl.fromLocalFile(str(target.path)))
        channel.desired_position_ms = target.position_ms
        channel.desired_playing = playing
        volume = min(1.0, max(0.0, pow(10.0, target.gain_db / 20.0)))
        channel.output.setVolume(volume)
        tolerance_ms = max(20, 1500 // self._project.settings.fps)
        current_position = int(channel.player.position())
        current_state = channel.player.playbackState()
        if not playing:
            if current_state == QMediaPlayer.PlaybackState.PlayingState:
                channel.player.pause()
            if current_position != target.position_ms:
                channel.player.setPosition(target.position_ms)
            return
        if abs(current_position - target.position_ms) > tolerance_ms:
            channel.player.setPosition(target.position_ms)
        if current_state != QMediaPlayer.PlaybackState.PlayingState:
            channel.player.play()

    def _media_status_changed(
        self,
        clip_id: str,
        status: QMediaPlayer.MediaStatus,
    ) -> None:
        channel = self._channels.get(clip_id)
        if channel is None:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.failed.emit(f"Audio {clip_id} illisible par le lecteur local")
            return
        if status not in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            return
        channel.player.setPosition(channel.desired_position_ms)
        if channel.desired_playing:
            channel.player.play()
        elif channel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            channel.player.pause()


    def _set_active(self, clip_ids: tuple[str, ...]) -> None:
        if clip_ids == self._active:
            return
        self._active = clip_ids
        self.activeClipsChanged.emit(clip_ids)

    def _release(self, clip_id: str) -> None:
        channel = self._channels.pop(clip_id, None)
        if channel is None:
            return
        channel.player.stop()
        delete_player = getattr(channel.player, "deleteLater", None)
        if delete_player is not None:
            delete_player()
        delete_output = getattr(channel.output, "deleteLater", None)
        if delete_output is not None:
            delete_output()

    def _release_all(self) -> None:
        for clip_id in tuple(self._channels):
            self._release(clip_id)

    def shutdown(self) -> None:
        self._release_all()
        self._project = None
        self._project_path = None
        self._set_active(())

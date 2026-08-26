from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from time import monotonic
import wave

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio_timeline import StudioTimeline
from artanimate.desktop.studio_waveform import (
    StudioWaveformController,
    StudioWaveformWorker,
    WaveformRequest,
)
from artanimate.studio.audio import add_audio_clip
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, StudioProject
from artanimate.studio.waveform import WaveformCache


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> tuple[StudioProject, Path, Path]:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (100, 80), (80, 120, 180)).save(artwork)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        section = (b"\0\x20" * 4_000) + (b"\0\x60" * 4_000)
        output.writeframes(section)
    asset = import_media_asset(audio, AssetKind.AUDIO, project_path, asset_id="music")
    project = replace(
        StudioProject.new(artwork, duration_seconds=3),
        assets=(asset,),
    ).validate()
    project, _clip = add_audio_clip(
        project,
        "music",
        start_frame=0,
        duration_frames=30,
    )
    return project, audio, project_path


def test_controller_calculates_off_ui_thread_and_timeline_paints_all_zooms(
    app,
    tmp_path: Path,
) -> None:
    project, _audio, project_path = _project(tmp_path)
    controller = StudioWaveformController(cache_dir=tmp_path / "cache")
    ready = QSignalSpy(controller.waveformsReady)
    running = QSignalSpy(controller.runningChanged)

    controller.request(project, project_path)
    assert running.count() and running.at(0)[0] is True
    deadline = monotonic() + 5.0
    while ready.count() == 0 and monotonic() < deadline:
        QTest.qWait(20)
    assert ready.count() == 1
    waveforms = ready.at(ready.count() - 1)[0]
    assert set(waveforms) == {"music"}

    timeline = StudioTimeline()
    timeline.set_project(project)
    timeline.set_waveforms(waveforms)
    assert timeline.scene.waveform_asset_ids == ("music",)
    for zoom in (75, 300, 1_800):
        timeline.zoom.setValue(zoom)
        image = timeline.scene.grab().toImage()
        assert not image.isNull()

    controller.shutdown()


def test_worker_cancellation_is_explicit_and_does_not_publish_results(
    app,
    tmp_path: Path,
) -> None:
    project, audio, _project_path = _project(tmp_path)
    fingerprint = project.assets[0].fingerprint
    assert fingerprint is not None
    worker = StudioWaveformWorker(
        7,
        (WaveformRequest("music", audio, fingerprint),),
        WaveformCache(tmp_path / "cancelled-cache"),
    )
    ready = QSignalSpy(worker.ready)
    cancelled = QSignalSpy(worker.cancelled)
    worker.cancel()
    worker.run()

    assert ready.count() == 0
    assert cancelled.count() == 1 and cancelled.at(0)[0] == 7
    assert worker.cancellation.is_set()

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from time import monotonic
import wave

import numpy as np
from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_music_analysis import (
    MusicAnalysisRequest,
    StudioMusicAnalysisWorker,
)
from artanimate.studio.assets import import_media_asset
from artanimate.studio.model import AssetKind, StudioProject
from artanimate.studio.music_analysis import (
    MusicAnalysisCache,
    MusicAnalysisSettings,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_click_track(path: Path, sample_rate: int = 8_000) -> None:
    seconds = 8
    sample_count = seconds * sample_rate
    values = np.zeros(sample_count, dtype=np.float64)
    for beat_index, beat in enumerate(np.arange(0.5, 7.8, 0.5)):
        start = int(beat * sample_rate)
        length = int(sample_rate * 0.05)
        local = np.arange(length) / sample_rate
        amplitude = 0.9 if beat_index % 4 == 0 else 0.5
        values[start : start + length] += (
            amplitude
            * np.exp(-local * 55.0)
            * np.sin(2.0 * np.pi * 90.0 * local)
        )
    encoded = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(encoded.tobytes())


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(20)
    assert predicate()


def test_rhythm_panel_analyzes_persists_settings_and_reuses_cache(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    audio = tmp_path / "music.wav"
    project_path = tmp_path / "reel.artanimate"
    Image.new("RGB", (120, 80), "navy").save(artwork)
    _write_click_track(audio)
    asset = import_media_asset(
        audio,
        AssetKind.AUDIO,
        project_path,
        asset_id="music",
    )
    project = replace(
        StudioProject.new(artwork, fps=30, duration_seconds=8),
        assets=(asset,),
    ).validate()
    panel = StudioPanel(analysis_cache_dir=tmp_path / "cache")
    try:
        panel.set_project(project, reset_history=True)
        panel.asset_panel.set_context(project, project_path)
        rhythm = panel.music_analysis_panel
        assert rhythm.selected_asset_id == "music"
        assert rhythm.analyze_button.isEnabled()

        rhythm.sensitivity_slider.setValue(85)
        rhythm.analyze_button.click()
        assert rhythm.cancel_button.isEnabled()
        _wait_until(
            app,
            lambda: panel.music_analysis_controller.active_job_count == 0,
        )

        assert "BPM" in rhythm.status.text()
        assert "calcul local" in rhythm.status.text()
        assert rhythm.events.topLevelItemCount() > 0
        assert rhythm.events.horizontalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert panel.project is not None
        assert MusicAnalysisSettings.from_project(panel.project) == (
            MusicAnalysisSettings(0.85)
        )
        assert panel.history.undo_label == "Régler la sensibilité musicale"

        rhythm.analyze_button.click()
        _wait_until(
            app,
            lambda: panel.music_analysis_controller.active_job_count == 0,
        )
        assert "cache local" in rhythm.status.text()
    finally:
        panel.shutdown()


def test_worker_cancellation_never_publishes_partial_analysis(
    app,
    tmp_path: Path,
) -> None:
    audio = tmp_path / "cancel.wav"
    _write_click_track(audio)
    worker = StudioMusicAnalysisWorker(
        3,
        MusicAnalysisRequest(
            "music",
            audio,
            "cancel-fingerprint",
            30,
            MusicAnalysisSettings(),
        ),
        MusicAnalysisCache(tmp_path / "cancel-cache"),
    )
    ready = QSignalSpy(worker.ready)
    cancelled = QSignalSpy(worker.cancelled)
    worker.cancel()
    worker.run()

    assert ready.count() == 0
    assert cancelled.count() == 1
    assert not tuple((tmp_path / "cancel-cache").glob("*.json"))

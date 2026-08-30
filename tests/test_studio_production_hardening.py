from __future__ import annotations

from dataclasses import replace
import errno
import os
from pathlib import Path
from threading import current_thread, enumerate as enumerate_threads
from time import monotonic, sleep

from PIL import Image
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.studio import analysis as studio_analysis
from artanimate.desktop import studio_preview
from artanimate.desktop.problems import UserProblem, translate_studio_exception
from artanimate.desktop.studio_analysis import StudioAnalysisController
from artanimate.desktop.studio_export import StudioExportController
from artanimate.desktop.studio_preview import StudioPreviewController
from artanimate.desktop.studio_waveform import StudioWaveformController
from artanimate.studio.media import StillClipSettings
from artanimate.studio.model import (
    AssetKind,
    Clip,
    ClipKind,
    MediaAsset,
    StudioProject,
    Track,
    TrackKind,
)
from artanimate.studio.source_registry import ArtworkSourceRegistry
from artanimate.studio.timeline import snap_frame, timeline_snap_targets


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app: QApplication, predicate, timeout: float = 3.0) -> None:
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    app.processEvents()
    assert predicate()


def test_studio_problem_keeps_a_concrete_recovery_action() -> None:
    corrupt = translate_studio_exception(
        ValueError("Vidéo locale illisible : broken.mp4"),
        "preview",
    )
    gpu = translate_studio_exception(
        RuntimeError("Le moteur 3D a produit 6 captures vides consécutives"),
        "export",
    )

    assert corrupt.code == "studio_media_unreadable"
    assert "Reliez" in corrupt.action
    assert "Que faire" in corrupt.display_text
    assert gpu.code == "studio_3d_unavailable"
    assert "GPU" in gpu.action


def test_studio_problem_preserves_missing_file_and_disk_full_diagnostics(
    tmp_path: Path,
) -> None:
    missing = translate_studio_exception(
        FileNotFoundError("gone"),
        "preview",
        source=tmp_path / "moved.png",
    )
    disk = translate_studio_exception(
        OSError(errno.ENOSPC, "full"),
        "waveform",
    )

    assert missing.code == "source_not_found"
    assert disk.code == "disk_full"


def test_analysis_atomic_writes_clean_temporaries_on_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    png = tmp_path / "mask.png"
    manifest = tmp_path / "analysis.json"

    def fail_replace(*_args) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(studio_analysis.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        studio_analysis._atomic_png(Image.new("L", (4, 4), 255), png)
    with pytest.raises(OSError, match="replace failed"):
        studio_analysis._atomic_json({"ok": True}, manifest)

    assert not (tmp_path / "mask.tmp.png").exists()
    assert not (tmp_path / "analysis.json.tmp").exists()


def test_async_preview_publishes_a_user_problem(app, tmp_path: Path, monkeypatch) -> None:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (32, 32), "navy").save(artwork)
    project = StudioProject.new(artwork)
    controller = StudioPreviewController(cache_bytes=1024)
    failures: list[UserProblem] = []
    controller.failed.connect(failures.append)

    def fail_render(*_args, **_kwargs):
        raise ValueError("Vidéo locale illisible : capture.mp4")

    monkeypatch.setattr(studio_preview, "render_studio_preview_frame", fail_render)
    try:
        controller.request(project, artwork, 0)
        _wait(app, lambda: bool(failures) and controller.active_job_count == 0)
        assert failures[0].code == "studio_media_unreadable"
        assert failures[0].action
    finally:
        controller.shutdown()


def test_every_studio_controller_owns_and_releases_its_worker_threads(
    app,
    tmp_path: Path,
) -> None:
    controllers = (
        StudioPreviewController(cache_bytes=1024),
        StudioAnalysisController(cache_dir=tmp_path / "analysis"),
        StudioWaveformController(cache_dir=tmp_path / "waveforms"),
        StudioExportController(),
    )
    names: list[str] = []
    try:
        for controller in controllers:
            name = controller._executor.submit(lambda: current_thread().name).result(2)
            names.append(name)
            assert name.startswith(controller.worker_thread_prefix)
    finally:
        for controller in controllers:
            controller.shutdown()
    app.processEvents()

    alive = {thread.name for thread in enumerate_threads()}
    assert not alive.intersection(names)


def test_source_registry_enforces_combined_decoded_frame_budgets(tmp_path: Path) -> None:
    paths = (tmp_path / "a.png", tmp_path / "b.png")
    for index, path in enumerate(paths):
        Image.new("RGB", (10, 10), (index * 100, 40, 80)).save(path)
    registry = ArtworkSourceRegistry(
        max_artwork_cache_bytes=350,
        max_still_cache_bytes=350,
        max_effect_cache_bytes=2,
        max_video_cache_bytes=2,
    )

    for index, path in enumerate(paths):
        registry.artwork(path, None)
        registry.still_image(
            MediaAsset(
                f"still-{index}",
                AssetKind.IMAGE,
                str(path),
                width=10,
                height=10,
            ),
            path,
            StillClipSettings(),
            30,
        )

    assert registry.artwork_cache_bytes == 300
    assert registry.still_cache_bytes == 300
    assert registry.cache_bytes <= registry.cache_budget_bytes
    assert registry.media_source_count == 1
    registry.clear()
    assert registry.cache_bytes == 0


def test_large_timeline_seek_targets_remain_exact(tmp_path: Path) -> None:
    artwork = tmp_path / "art.png"
    still = tmp_path / "still.png"
    Image.new("RGB", (16, 16), "white").save(artwork)
    Image.new("RGB", (16, 16), "red").save(still)
    project = StudioProject.new(artwork, duration_seconds=30)
    asset = MediaAsset(
        "stress-still",
        AssetKind.IMAGE,
        str(still),
        fingerprint="stress",
        width=16,
        height=16,
    )
    clips = tuple(
        Clip(
            f"stress-{frame}",
            ClipKind.STILL,
            frame,
            1,
            asset_id=asset.asset_id,
        )
        for frame in range(600)
    )
    stress_track = Track("stress-video", TrackKind.VIDEO, "Stress", clips)
    project = replace(
        project,
        assets=(asset,),
        tracks=(*project.tracks, stress_track),
    ).validate()

    targets = timeline_snap_targets(project, playhead=777)

    assert set(range(601)) <= set(targets)
    assert 777 in targets
    for frame in range(600):
        assert snap_frame(frame, targets, threshold_frames=1) == frame
    assert snap_frame(601, targets, threshold_frames=1) == 600
    assert snap_frame(776, targets, threshold_frames=1) == 777

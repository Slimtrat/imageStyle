from __future__ import annotations

import os
from pathlib import Path
from threading import Event
import time

from PIL import Image, ImageDraw
import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio import StudioPanel
from artanimate.desktop.studio_analysis import StudioAnalysisController
from artanimate.studio.analysis import AnalysisCancelled, SceneAnalysisRequest
from artanimate.studio.model import StudioProject
from artanimate.studio.semantic import Bounds


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _artwork(path: Path) -> None:
    image = Image.new("RGB", (180, 120), (235, 225, 205))
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 15, 130, 110), fill=(25, 80, 170))
    image.save(path)


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def test_async_analysis_enriches_scene_and_is_undoable(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "art.png"
    _artwork(artwork)
    panel = StudioPanel(analysis_cache_dir=tmp_path / "cache")
    try:
        assert panel.set_artwork(artwork)
        panel.analysis_panel.analyze_button.click()
        assert panel.analysis_panel.cancel_button.isEnabled()
        _wait_until(app, lambda: panel.analysis_controller.active_job_count == 0)

        assert panel.project is not None and panel.project.scene is not None
        foreground = panel.project.scene.object_by_id("auto-foreground")
        assert foreground is not None
        assert foreground.affordance_ids >= {"movable", "frame-exitable"}
        assert {item.kind for item in foreground.resource_refs} == {"mask"}
        artwork_object = panel.project.scene.object_by_id("artwork")
        assert {item.kind for item in artwork_object.resource_refs} >= {"depth"}
        assert panel.history.undo_label == "Analyser l’œuvre localement"
        assert panel.semantic_panel.selected_target_id.startswith("auto-interest-")
        assert "région(s) proposée(s)" in panel.analysis_panel.status.text()
        assert "score" in panel.analysis_panel.selection_summary.text()

        assert panel.undo()
        assert panel.project.scene.object_by_id("auto-foreground") is None
        assert panel.redo()
        assert panel.project.scene.object_by_id("auto-foreground") is not None

        panel.analysis_panel.analyze_button.click()
        _wait_until(app, lambda: panel.analysis_controller.active_job_count == 0)
        assert "cache local" in panel.analysis_panel.status.text()
    finally:
        panel.shutdown()


def test_manual_zone_mask_correction_ignore_and_undo(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "manual-art.png"
    mask = tmp_path / "manual-mask.png"
    _artwork(artwork)
    Image.new("L", (180, 120), 255).save(mask)
    panel = StudioPanel(analysis_cache_dir=tmp_path / "cache")
    try:
        assert panel.set_artwork(artwork)
        analysis = panel.analysis_panel
        analysis.label_edit.setText("Visage")
        analysis.bounds_x.setValue(0.1)
        analysis.bounds_y.setValue(0.2)
        analysis.bounds_width.setValue(0.4)
        analysis.bounds_height.setValue(0.5)
        analysis.add_selection_button.click()

        manual_id = panel.semantic_panel.selected_target_id
        assert manual_id is not None and manual_id.startswith("manual-")
        assert panel.history.undo_label == "Ajouter une zone manuelle"
        analysis.bounds_x.setValue(0.2)
        analysis.correct_button.click()
        corrected = panel.project.scene.object_by_id(manual_id)
        assert corrected.bounds.x == 0.2
        assert corrected.attributes["corrected_manually"] is True

        analysis.ignore_button.click()
        assert panel.project.scene.object_by_id(manual_id) is None
        assert panel.undo()
        assert panel.project.scene.object_by_id(manual_id) is not None

        panel._choose_manual_mask(
            Bounds(0.2, 0.2, 0.4, 0.5),
            "Silhouette",
            mask,
        )
        masked_id = panel.semantic_panel.selected_target_id
        masked = panel.project.scene.object_by_id(masked_id)
        assert masked.semantic_type == "object.manual-mask"
        assert masked.resource_refs[0].kind == "mask"
        assert any(
            asset.asset_id == masked.resource_refs[0].asset_id
            for asset in panel.project.assets
        )
        assert panel.undo()
        assert panel.project.scene.object_by_id(masked_id) is None
    finally:
        panel.shutdown()


class _BlockingAnalyzer:
    analyzer_id = "test.blocking"
    version = "1"

    def __init__(self) -> None:
        self.started = Event()

    def analyze(self, request: SceneAnalysisRequest):
        self.started.set()
        while not request.cancelled.wait(0.01):
            pass
        raise AnalysisCancelled("annulée")


def test_analysis_controller_cancels_worker_without_result(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "cancel-art.png"
    _artwork(artwork)
    analyzer = _BlockingAnalyzer()
    controller = StudioAnalysisController(
        analyzer=analyzer,
        cache_dir=tmp_path / "cache",
    )
    results: list[object] = []
    cancellations: list[bool] = []
    controller.analysisReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))
    try:
        controller.request(StudioProject.new(artwork), artwork)
        assert analyzer.started.wait(2.0)
        controller.cancel_pending()
        _wait_until(app, lambda: controller.active_job_count == 0)
        assert results == []
        assert cancellations
    finally:
        controller.shutdown()

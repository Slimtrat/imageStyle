import os
from pathlib import Path

import pytest
from PIL import Image


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")
pytest.importorskip("PySide6")

from PySide6.QtGui import QImage
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from artanimate.desktop.studio3d import QML_SCENE_PATH, Studio3DPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_studio_scene_asset_contains_room_lamp_and_camera() -> None:
    scene = QML_SCENE_PATH.read_text(encoding="utf-8")

    assert "View3D" in scene
    assert "PerspectiveCamera" in scene
    assert "PointLight" in scene
    assert "SpotLight" in scene
    assert "sideboardBody" in scene
    assert "horizontalArtwork" in scene
    assert "artworkContactShadow" in scene
    assert "overheadLamp" in scene
    assert "lampMotion" in scene
    assert "dark-walnut-v2.png" in scene
    assert "model: sandParticleModel" in scene
    assert "cameraOrbitTurns" in scene
    assert "effectToolIsOutline" in scene
    assert "artworkSource" in scene
    assert "MouseArea" in scene
    assert "effectKind" in scene
    assert "effectDirection" in scene
    assert "Repeater3D" in scene
    assert "CADRE EXPORT" in scene


def test_studio_panel_loads_scene_and_accepts_animated_frames(
    app,
    tmp_path: Path,
) -> None:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (180, 120), (220, 45, 80)).save(artwork)
    panel = Studio3DPanel()
    try:
        panel.activate()
        app.processEvents()
        assert panel.view.status() != QQuickWidget.Status.Error, panel.scene_errors
        assert panel.set_source(artwork)

        frame = QImage(str(artwork))
        panel.set_frame(frame, 2, 20)
        app.processEvents()

        root = panel.view.rootObject()
        assert root is not None
        assert root.property("artworkSource").toString().startswith(
            "image://artanimate/"
        )
        assert root.property("artworkAspect") == pytest.approx(1.5)
        assert root.property("lampMotion") == pytest.approx(0.65)
        assert panel.camera_state()["lamp_motion"] == pytest.approx(0.65)
        assert panel.camera_state()["orbit_turns"] == pytest.approx(0.0)
        panel.camera_preset.setCurrentIndex(3)
        assert root.property("cameraOrbitTurns") == pytest.approx(1.0)
        assert root.property("cameraPitch") == pytest.approx(-58.0)
        panel.set_effect("wave", direction="right")
        assert root.property("effectKind") == "wave"
        assert root.property("effectDirection") == "right"
        assert "image 3/20" in panel.artwork_status.text()
    finally:
        panel.close()

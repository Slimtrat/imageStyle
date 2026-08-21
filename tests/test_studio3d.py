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
from artanimate.desktop.studio3d_wave import OrganicWaveSettings


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
    assert "organicWaveArtwork" in scene
    assert "geometry: organicWaveGeometry" in scene
    assert "CustomMaterial" not in scene
    assert "Wave fronts skim" not in scene
    assert "VAGUE 3D · MASSE PIGMENTAIRE · DENSITÉS VARIABLES" in scene
    assert "artworkContactShadow" in scene
    assert "overheadLamp" in scene
    assert "lampMotion" in scene
    assert "dark-walnut-v2.png" in scene
    assert "model: pigmentParticleModel" in scene
    assert "cameraOrbitTurns" in scene
    assert "cameraMotion" in scene
    assert "flyoverWeight" in scene
    assert "fitDistance" in scene
    assert "effectToolIsOutline" in scene
    assert "eulerRotation.y: -3" in scene
    assert "smootherstep(effectToolLinearProgress)" in scene
    assert "id: screenprintBoundary" in scene
    assert "id: screenprintWhiteLine" in scene
    assert "id: skyLaserDeck" in scene
    assert "id: skyLaserCore" in scene
    assert "id: skyLaserAura" in scene
    assert "id: skyLaserImpact" in scene
    assert "id: effectLaserEmitter" not in scene
    assert "id: effectLaserCollar" not in scene
    assert "id: laserGantry" not in scene
    assert "root.artworkWidth * root.laserTargetU" in scene
    assert "(root.laserTargetV - 0.5) * root.artworkDepth" in scene
    assert "RAYON DU CIEL · TRACÉ DES CONTOURS" in scene
    assert "LIGNE DE SÉRIGRAPHIE · COUCHE" in scene
    assert "id: paintDropDeck" in scene
    assert "id: paintBrushDeck" not in scene
    assert "GOUTTE EN CHUTE" in scene
    assert "paintStageTargetU" in scene
    assert "artworkSource" in scene
    assert "generateMipmaps: false" in scene
    assert "mipFilter: Texture.None" in scene
    assert "root.effectToolProgress / Math.max(root.paintFallRatio" in scene
    assert "brightness: 0.18 * (1.0 - paintDropDeck.impactProgress)" not in scene
    assert "MouseArea" in scene
    assert "effectKind" in scene
    assert "effectDirection" in scene
    assert "pigment_sweep" in scene
    assert "overshootU" in scene
    assert "reboundResidual" in scene
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
        density_min, density_max = panel._wave_geometry.density_range
        assert 0.0 <= density_min <= density_max <= 1.0
        assert root.property("lampMotion") == pytest.approx(0.65)
        assert panel.camera_state()["lamp_motion"] == pytest.approx(0.65)
        assert panel.camera_state()["orbit_turns"] == pytest.approx(0.0)
        selected: list[str] = []
        panel.effect_selected.connect(selected.append)
        wow_index = panel.effect_combo.findData("screenprint_laser")
        panel.effect_combo.setCurrentIndex(wow_index)
        assert selected == ["screenprint_laser"]
        assert "contours noirs" in panel.effect_description.text()
        panel.set_effect("vertical_halo")
        assert panel.effect_combo.currentData() == "vertical_halo"
        assert selected == ["screenprint_laser"]
        assert panel.camera_preset.count() == 3
        assert panel.camera_preset.currentData() == "flyover"
        assert root.property("cameraMotion") == "flyover"
        drift_index = panel.camera_preset.findData("top_drift")
        panel.camera_preset.setCurrentIndex(drift_index)
        assert root.property("cameraMotion") == "top_drift"
        assert root.property("cameraPitch") == pytest.approx(-78.0)
        assert root.property("cameraMotionStrength") == pytest.approx(0.62)
        panel.set_effect(
            "wave",
            direction="right",
            wave_settings=OrganicWaveSettings(
                amplitude=0.09,
                frequency=3.8,
                turbulence=0.17,
                soft_edge=0.028,
                density_contrast=0.84,
            ),
        )
        assert root.property("effectKind") == "wave"
        assert root.property("effectDirection") == "right"
        panel.set_frame(frame, progress=0.5)
        assert panel._wave_geometry.maximum_height > 12.0
        panel.set_frame(frame, progress=1.0)
        assert panel._wave_geometry.maximum_height == pytest.approx(0.0)
        assert "image 3/20" in panel.artwork_status.text()
    finally:
        panel.close()

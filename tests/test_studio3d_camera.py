import pytest

from artanimate.desktop.studio3d_camera import (
    CAMERA_MOTIONS,
    camera_motion,
    camera_motion_timing,
    final_fit_distance,
)


def test_camera_catalog_only_exposes_artwork_first_movements() -> None:
    assert tuple(preset.key for preset in CAMERA_MOTIONS) == (
        "flyover",
        "top_drift",
        "top_fixed",
    )
    assert all(preset.pitch >= 68.0 for preset in CAMERA_MOTIONS)
    assert all("pièce" not in preset.label.lower() for preset in CAMERA_MOTIONS)
    assert camera_motion("flyover").label.startswith("Signature")
    with pytest.raises(ValueError, match="Mouvement caméra inconnu"):
        camera_motion("room")


def test_flyover_finishes_locked_and_top_drift_returns_to_center() -> None:
    opening = camera_motion_timing("flyover", 0.0, 1.0)
    crossing = camera_motion_timing("flyover", 0.55, 1.0)
    final = camera_motion_timing("flyover", 1.0, 1.0)

    assert opening.flyover_weight == pytest.approx(1.0)
    assert crossing.flight_progress > 0.9
    assert crossing.flyover_weight > 0.95
    assert final.settle_progress == pytest.approx(1.0)
    assert final.flyover_weight == pytest.approx(0.0)
    assert camera_motion_timing("top_drift", 0.5, 0.6).drift_envelope == pytest.approx(0.6)
    assert camera_motion_timing("top_drift", 1.0, 0.6).drift_envelope == pytest.approx(0.0)


def test_vertical_export_moves_back_enough_to_keep_the_whole_artwork() -> None:
    horizontal = final_fit_distance(360.0, 225.0, 16 / 9)
    vertical = final_fit_distance(360.0, 225.0, 9 / 16)

    assert horizontal == pytest.approx(560.0)
    assert vertical > 900.0

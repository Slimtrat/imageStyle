from __future__ import annotations

import cv2
import numpy as np
import pytest

from artanimate.studio.eyelids import EyelidGeometry, compose_eyelid_blink


def _graphic_eye() -> tuple[np.ndarray, np.ndarray]:
    height, width = 120, 180
    yy, xx = np.mgrid[0:height, 0:width]
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[..., 0] = np.clip(212 + xx * 0.08, 0, 255)
    frame[..., 1] = np.clip(48 + yy * 0.05, 0, 255)
    frame[..., 2] = np.clip(92 + xx * 0.03, 0, 255)
    mask = np.zeros((height, width), dtype=np.float32)
    cv2.ellipse(mask, (92, 64), (48, 30), 7.0, 0.0, 360.0, 1.0, -1)
    cv2.ellipse(frame, (100, 64), (19, 25), 7.0, 0.0, 360.0, (12, 13, 18), -1)
    cv2.line(frame, (50, 75), (131, 80), (18, 18, 22), 3, cv2.LINE_AA)
    return frame, mask


def test_eyelid_geometry_is_versionable_and_strict() -> None:
    geometry = EyelidGeometry.from_mapping(
        {
            "axis": [0.04, 0.69, 0.96, 0.79],
            "curvature": -0.08,
            "amplitude": 0.94,
            "protection": 0.14,
            "seam_width": 0.018,
        }
    )

    assert EyelidGeometry.from_mapping(geometry.to_dict()) == geometry
    with pytest.raises(ValueError, match="gauche à droite"):
        EyelidGeometry.from_mapping({"axis": [0.8, 0.5, 0.2, 0.5]})
    with pytest.raises(ValueError, match="inconnue"):
        EyelidGeometry.from_mapping({"skin_color": "pink"})


def test_eyelid_blink_covers_the_iris_without_compressing_the_eye() -> None:
    frame, mask = _graphic_eye()
    geometry = EyelidGeometry(
        axis=(0.04, 0.68, 0.96, 0.78),
        curvature=-0.08,
        protection=0.12,
        seam_width=0.014,
    )

    opened = compose_eyelid_blink(frame, mask, 0.0, geometry)
    halfway = compose_eyelid_blink(frame, mask, 0.5, geometry)
    closed = compose_eyelid_blink(frame, mask, 1.0, geometry)
    reopened = compose_eyelid_blink(frame, mask, 0.0, geometry)

    assert np.array_equal(opened, frame)
    assert np.array_equal(reopened, frame)
    assert not np.array_equal(halfway, frame)
    assert not np.array_equal(closed, halfway)
    assert np.array_equal(closed[mask == 0.0], frame[mask == 0.0])
    iris = np.s_[48:78, 88:114]
    assert float(closed[iris].mean()) > float(frame[iris].mean()) + 25.0
    seam = closed[72:83, 52:132]
    assert np.count_nonzero(seam.mean(axis=2) < 55.0) > 12


def test_eyelid_blink_validates_frame_and_mask_shapes() -> None:
    frame, mask = _graphic_eye()
    with pytest.raises(TypeError, match="RGB uint8"):
        compose_eyelid_blink(frame.astype(np.float32), mask, 1.0)
    with pytest.raises(ValueError, match="correspondre"):
        compose_eyelid_blink(frame, mask[:-1], 1.0)

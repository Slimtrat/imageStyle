from __future__ import annotations

import numpy as np

from artanimate.v3_qualification import _comparison


def test_qualification_accepts_small_gpu_rasterization_variance() -> None:
    expected = np.full((64, 64, 3), 120, dtype=np.uint8)
    actual = expected.copy()
    actual[::4, ::4] = 124

    comparison = _comparison(expected, actual)

    assert comparison["passed"]
    assert comparison["mae"] > 0.0


def test_qualification_rejects_a_visually_different_frame() -> None:
    expected = np.zeros((64, 64, 3), dtype=np.uint8)
    actual = np.full((64, 64, 3), 96, dtype=np.uint8)

    comparison = _comparison(expected, actual)

    assert not comparison["passed"]
    assert comparison["mae"] == 96.0

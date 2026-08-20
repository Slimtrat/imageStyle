import numpy as np

from artanimate.colors import family_for_color, kmeans_lab, rgb_to_lab


def test_rgb_to_lab_reference_extremes() -> None:
    lab = rgb_to_lab(np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8))
    assert np.allclose(lab[0], [0, 0, 0], atol=0.03)
    assert np.allclose(lab[1], [100, 0, 0], atol=0.03)


def test_color_families_cover_chromatic_circle() -> None:
    assert family_for_color((240, 25, 30), 60)[0] == "red"
    assert family_for_color((245, 150, 20), 60)[0] == "orange"
    assert family_for_color((20, 95, 225), 60)[0] == "blue"
    assert family_for_color((140, 140, 140), 2)[0] == "neutral"


def test_kmeans_is_deterministic_and_separates_colors() -> None:
    samples = np.concatenate(
        [
            np.repeat([[45.0, 65.0, 40.0]], 20, axis=0),
            np.repeat([[70.0, -50.0, 45.0]], 20, axis=0),
        ],
        axis=0,
    ).astype(np.float32)
    first = kmeans_lab(samples, 4, seed=9)
    second = kmeans_lab(samples, 4, seed=9)
    assert len(first) == 2
    assert np.allclose(first, second)

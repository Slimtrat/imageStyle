import numpy as np
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core.masks import complete_family_labels


def test_shape_completion_closes_isolated_family_hole() -> None:
    labels = np.full((9, 9), -1, dtype=np.int16)
    labels[1:8, 1:8] = 0
    labels[4, 4] = 1

    completed = complete_family_labels(labels, strength=1)

    assert completed[4, 4] == 0
    assert np.all(completed[labels < 0] == -1)


def test_shape_completion_can_be_disabled_exactly() -> None:
    labels = np.array([[0, 1], [-1, 1]], dtype=np.int16)
    assert np.array_equal(complete_family_labels(labels, strength=0), labels)


def test_shape_completion_configuration_is_bounded() -> None:
    assert RenderConfig(shape_completion=4).validate().shape_completion == 4
    with pytest.raises(ValueError, match="shape_completion"):
        RenderConfig(shape_completion=5).validate()

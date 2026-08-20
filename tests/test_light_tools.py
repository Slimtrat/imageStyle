import numpy as np

from artanimate.core.effects.light_tools import blend_ink_edges, feather_mask


def test_feather_mask_softens_edges_without_wrapping() -> None:
    mask = np.zeros((9, 11), dtype=bool)
    mask[0, 0] = True
    feathered = feather_mask(mask, radius=2)

    assert feathered[0, 0] == 1.0
    assert 0.0 < feathered[0, 1] < 1.0
    assert 0.0 < feathered[1, 0] < 1.0
    assert feathered[-1, -1] == 0.0


def test_wet_ink_bridges_only_the_revealed_mask_boundary() -> None:
    frame = np.full((12, 16, 3), 245, dtype=np.uint8)
    mask = np.zeros((12, 16), dtype=bool)
    mask[3:9, 4:12] = True
    field = np.broadcast_to(
        np.linspace(0.0, 1.0, 16, dtype=np.float32), (12, 16)
    )
    result = blend_ink_edges(
        frame,
        mask,
        field,
        progress=0.5,
        soft_edge=0.01,
        color=(220, 35, 55),
        radius=2,
    )

    assert not np.array_equal(result[4, 3], frame[4, 3])
    assert np.array_equal(result[4, 14], frame[4, 14])
    assert np.array_equal(result[1, 1], frame[1, 1])


def test_underprint_fills_only_the_future_outline_mask() -> None:
    frame = np.full((16, 24, 3), 245, dtype=np.uint8)
    mask = np.zeros((16, 24), dtype=bool)
    mask[5:11, 5:10] = True
    future_outline = np.zeros((16, 24), dtype=bool)
    future_outline[5:11, 10:14] = True
    field = np.broadcast_to(
        np.linspace(0.0, 1.0, 24, dtype=np.float32), (16, 24)
    )
    result = blend_ink_edges(
        frame,
        mask,
        field,
        progress=1.0,
        soft_edge=0.01,
        color=(220, 35, 55),
        radius=5,
        bridge_mask=future_outline,
    )

    assert not np.array_equal(result[7, 12], frame[7, 12])
    assert np.array_equal(result[7, 16], frame[7, 16])

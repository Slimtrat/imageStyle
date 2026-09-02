from __future__ import annotations

import numpy as np
import pytest

from artanimate.studio.color_fidelity import (
    ArtworkColorMode,
    ArtworkColorPolicy,
    delta_e_ciede2000,
    measure_color_fidelity,
)


def test_faithful_policy_is_default_versioned_and_round_trips() -> None:
    policy = ArtworkColorPolicy.from_mapping(None)

    assert policy.mode == ArtworkColorMode.FAITHFUL
    assert policy.to_dict() == {
        "schema_version": 1,
        "mode": "faithful",
        "texture_color_space": "srgb",
        "exposure": 1.0,
        "tone_mapping": "linear",
    }
    assert ArtworkColorPolicy.from_mapping(policy.to_dict()) == policy
    assert policy.qml_properties()["artworkColorMode"] == "faithful"


def test_integrated_mode_is_explicit_and_invalid_corrections_are_rejected() -> None:
    assert ArtworkColorPolicy.from_mapping("scene_integrated").mode == (
        ArtworkColorMode.SCENE_INTEGRATED
    )
    with pytest.raises(ValueError, match="Mode colorimétrique inconnu"):
        ArtworkColorPolicy.from_mapping({"mode": "blue_filter"})
    with pytest.raises(ValueError, match="exposition"):
        ArtworkColorPolicy.from_mapping({"exposure": 0.8})
    with pytest.raises(ValueError, match="inconnus"):
        ArtworkColorPolicy.from_mapping({"temperature": 4300})


def test_ciede2000_matches_the_published_reference_pair() -> None:
    first = np.array([[50.0, 2.6772, -79.7751]])
    second = np.array([[50.0, 0.0, -82.7485]])

    result = delta_e_ciede2000(first, second)

    assert float(result[0]) == pytest.approx(2.0425, abs=0.0001)


def test_reference_chart_passes_unchanged_and_rejects_a_warm_cast() -> None:
    chart = np.array(
        [
            [[230, 45, 35], [35, 190, 75], [30, 80, 225], [242, 208, 35]],
            [[215, 70, 175], [35, 205, 210], [245, 245, 242], [25, 26, 30]],
        ],
        dtype=np.uint8,
    )
    unchanged = measure_color_fidelity(chart, chart)
    warm = chart.astype(np.int16)
    warm[..., 0] += 24
    warm[..., 1] += 13
    warm[..., 2] -= 16
    warm = np.clip(warm, 0, 255).astype(np.uint8)
    shifted = measure_color_fidelity(chart, warm)

    assert unchanged.passes
    assert unchanged.median_delta_e00 == pytest.approx(0.0)
    assert shifted.passes is False
    assert shifted.median_delta_e00 > unchanged.median_limit


def test_measurement_excludes_filtered_edges_and_masked_pixels() -> None:
    reference = np.full((8, 8, 3), (80, 120, 180), dtype=np.uint8)
    rendered = reference.copy()
    rendered[[0, -1], :, :] = (255, 0, 0)
    rendered[:, [0, -1], :] = (255, 0, 0)
    mask = np.ones((8, 8), dtype=bool)

    report = measure_color_fidelity(reference, rendered, mask=mask, edge_filter=1)

    assert report.passes
    assert report.sample_count == 36

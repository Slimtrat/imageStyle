from __future__ import annotations

import cv2
import numpy as np
import pytest

from artanimate.studio.semantic_detection import (
    InterestRegionDetectorConfig,
    LocalInterestRegionDetector,
    SemanticDetectionCancelled,
)


def _detailed_artwork() -> np.ndarray:
    image = np.full((180, 260, 3), (235, 224, 198), dtype=np.uint8)
    cv2.rectangle(image, (12, 18), (102, 92), (15, 60, 175), -1)
    cv2.circle(image, (190, 52), 37, (230, 35, 80), -1)
    cv2.line(image, (25, 145), (232, 112), (10, 10, 10), 8, cv2.LINE_AA)
    for offset in range(0, 70, 10):
        cv2.line(
            image,
            (120 + offset, 95),
            (105 + offset, 172),
            (35, 155, 75),
            3,
            cv2.LINE_AA,
        )
    return image


def _iou(left, right) -> float:
    x1 = max(left.x, right.x)
    y1 = max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union


def _center_distance(left, right) -> float:
    left_center = (left.x + left.width / 2, left.y + left.height / 2)
    right_center = (right.x + right.width / 2, right.y + right.height / 2)
    return float(
        np.hypot(
            left_center[0] - right_center[0],
            left_center[1] - right_center[1],
        )
    )


def test_local_interest_regions_are_deterministic_explainable_and_diverse() -> None:
    artwork = _detailed_artwork()
    detector = LocalInterestRegionDetector(
        InterestRegionDetectorConfig(max_candidates=6, working_size=180)
    )

    first = detector.detect(artwork)
    second = detector.detect(artwork.copy())

    assert 3 <= len(first.candidates) <= 6
    assert first.metadata["network_used"] is False
    assert first.metadata["fallback"] is False
    assert [item.bounds for item in first.candidates] == [
        item.bounds for item in second.candidates
    ]
    assert [item.metadata.to_dict() for item in first.candidates] == [
        item.metadata.to_dict() for item in second.candidates
    ]
    assert {
        item.metadata["reason"] for item in first.candidates
    } >= {"contrast", "edges", "color"}
    for index, candidate in enumerate(first.candidates):
        assert candidate.mask.shape == artwork.shape[:2]
        assert np.count_nonzero(candidate.mask) > 0
        assert candidate.metadata["generated"] is False
        assert 0.0 <= candidate.bounds.x < 1.0
        assert 0.0 < candidate.bounds.width <= 1.0
        for previous in first.candidates[:index]:
            assert _iou(candidate.bounds, previous.bounds) <= 0.48 + 1e-9
            assert _center_distance(candidate.bounds, previous.bounds) >= 0.18 - 1e-9


def test_uniform_artwork_uses_composition_fallback() -> None:
    artwork = np.full((100, 160, 3), (90, 50, 170), dtype=np.uint8)

    detection = LocalInterestRegionDetector().detect(artwork)

    assert len(detection.candidates) == 1
    candidate = detection.candidates[0]
    assert candidate.region_type == "artwork.region.composition"
    assert candidate.metadata["reason"] == "composition"
    assert candidate.metadata["fallback"] is True
    assert detection.metadata["fallback"] is True


def test_interest_detection_honors_cancellation() -> None:
    with pytest.raises(SemanticDetectionCancelled, match="annulée"):
        LocalInterestRegionDetector().detect(
            _detailed_artwork(),
            should_cancel=lambda: True,
        )

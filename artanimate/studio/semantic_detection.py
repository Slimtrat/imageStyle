from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .semantic import Bounds, FrozenJsonObject


class SemanticDetectionCancelled(RuntimeError):
    """Raised when a local detector reaches a cancellation boundary."""


@dataclass(frozen=True, slots=True)
class SemanticRegionCandidate:
    """A detector-neutral region proposal expressed in canonical artwork space."""

    region_type: str
    label: str
    bounds: Bounds
    confidence: float
    mask: np.ndarray
    metadata: FrozenJsonObject = FrozenJsonObject()

    def validate(self) -> SemanticRegionCandidate:
        Bounds(self.bounds.x, self.bounds.y, self.bounds.width, self.bounds.height)
        if not self.region_type.strip() or not self.label.strip():
            raise ValueError("Une région doit déclarer son type et son libellé")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("La confiance d’une région doit être comprise entre 0 et 1")
        if self.mask.ndim != 2 or self.mask.size == 0:
            raise ValueError("Le masque d’une région doit être une image 2D non vide")
        if not np.issubdtype(self.mask.dtype, np.number):
            raise TypeError("Le masque d’une région doit contenir des valeurs numériques")
        return self


@dataclass(frozen=True, slots=True)
class SemanticRegionDetection:
    analyzer_id: str
    analyzer_version: str
    candidates: tuple[SemanticRegionCandidate, ...]
    metadata: FrozenJsonObject = FrozenJsonObject()

    def validate(self) -> SemanticRegionDetection:
        if not self.analyzer_id or not self.analyzer_version:
            raise ValueError("Un détecteur doit déclarer son identité et sa version")
        shapes: set[tuple[int, int]] = set()
        for candidate in self.candidates:
            candidate.validate()
            shapes.add(candidate.mask.shape)
        if len(shapes) > 1:
            raise ValueError("Les masques d’une détection doivent partager le même repère")
        return self


class SemanticRegionDetector(Protocol):
    """Port for local CV, segmentation models, or user-assisted analyzers."""

    analyzer_id: str
    analyzer_version: str

    def detect(
        self,
        artwork_rgb: np.ndarray,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SemanticRegionDetection: ...


@dataclass(frozen=True, slots=True)
class InterestRegionDetectorConfig:
    max_candidates: int = 6
    working_size: int = 320
    overlap_limit: float = 0.48
    minimum_center_distance: float = 0.18
    minimum_information: float = 0.055

    def __post_init__(self) -> None:
        if not 1 <= self.max_candidates <= 12:
            raise ValueError("Le détecteur doit proposer entre 1 et 12 régions")
        if self.working_size < 96:
            raise ValueError("La taille de travail du détecteur est trop petite")
        if not 0.0 < self.overlap_limit < 1.0:
            raise ValueError("La limite de recouvrement doit être normalisée")
        if not 0.0 <= self.minimum_center_distance < 1.0:
            raise ValueError("La distance minimale entre centres doit être normalisée")
        if not 0.0 <= self.minimum_information <= 1.0:
            raise ValueError("Le seuil d’information doit être normalisé")


@dataclass(frozen=True, slots=True)
class _WindowProposal:
    reason: str
    region_type: str
    label: str
    x: int
    y: int
    width: int
    height: int
    score: float
    contrast: float
    edge_density: float
    color_saliency: float
    centrality: float
    fallback: bool = False


def _cancel_if_requested(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise SemanticDetectionCancelled("Détection sémantique locale annulée")


def _robust_normalize(values: np.ndarray) -> np.ndarray:
    source = np.asarray(values, dtype=np.float32)
    low, high = np.quantile(source, (0.08, 0.94))
    if float(high - low) <= 1e-6:
        return np.zeros_like(source, dtype=np.float32)
    return np.clip((source - low) / (high - low), 0.0, 1.0).astype(np.float32)


def _window_mean(integral: np.ndarray, x: int, y: int, width: int, height: int) -> float:
    x2 = x + width
    y2 = y + height
    total = integral[y2, x2] - integral[y, x2] - integral[y2, x] + integral[y, x]
    return float(total / max(1, width * height))


def _iou(left: _WindowProposal, right: _WindowProposal) -> float:
    x1 = max(left.x, right.x)
    y1 = max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union else 0.0


class LocalInterestRegionDetector:
    """Deterministic local proposals based on visual evidence, never generation."""

    analyzer_id = "detector.local-interest-regions"
    analyzer_version = "1"

    _REASONS = (
        ("contrast", "artwork.region.contrast", "Contraste local"),
        ("edges", "artwork.region.lines", "Détail graphique"),
        ("color", "artwork.region.color", "Couleur distinctive"),
    )

    def __init__(self, config: InterestRegionDetectorConfig | None = None) -> None:
        self.config = config or InterestRegionDetectorConfig()

    def detect(
        self,
        artwork_rgb: np.ndarray,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SemanticRegionDetection:
        image = np.asarray(artwork_rgb)
        if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
            raise ValueError("L’œuvre à analyser doit être une image RGB non vide")
        if not np.issubdtype(image.dtype, np.number):
            raise TypeError("Les pixels de l’œuvre doivent être numériques")
        image = np.clip(image, 0, 255).astype(np.uint8, copy=False)
        source_height, source_width = image.shape[:2]
        _cancel_if_requested(should_cancel)

        scale = min(1.0, self.config.working_size / max(source_width, source_height))
        work_width = max(1, int(round(source_width * scale)))
        work_height = max(1, int(round(source_height * scale)))
        working = (
            cv2.resize(image, (work_width, work_height), interpolation=cv2.INTER_AREA)
            if (work_width, work_height) != (source_width, source_height)
            else image.copy()
        )
        gray = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        lab = cv2.cvtColor(working, cv2.COLOR_RGB2LAB).astype(np.float32)
        _cancel_if_requested(should_cancel)

        local_mean = cv2.GaussianBlur(
            gray,
            (0, 0),
            sigmaX=max(1.2, min(work_width, work_height) / 45),
        )
        contrast = _robust_normalize(np.abs(gray - local_mean))
        gradient_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        edges = _robust_normalize(cv2.magnitude(gradient_x, gradient_y))
        median_lab = np.median(lab.reshape(-1, 3), axis=0)
        color_distance = np.linalg.norm(lab - median_lab, axis=2)
        color_saliency = _robust_normalize(
            cv2.GaussianBlur(color_distance, (0, 0), sigmaX=1.1)
        )
        yy, xx = np.mgrid[0:work_height, 0:work_width]
        nx = (xx + 0.5) / work_width
        ny = (yy + 0.5) / work_height
        centrality = np.clip(
            1.0
            - np.sqrt(
                ((nx - 0.5) / 0.72) ** 2
                + ((ny - 0.5) / 0.72) ** 2
            ),
            0.0,
            1.0,
        ).astype(np.float32)
        maps = {
            "contrast": contrast,
            "edges": edges,
            "color": color_saliency,
            "centrality": centrality,
        }
        integrals = {
            name: cv2.integral(values, sdepth=cv2.CV_64F)
            for name, values in maps.items()
        }
        information = float(
            0.45 * np.mean(contrast)
            + 0.35 * np.mean(edges)
            + 0.20 * np.mean(color_saliency)
        )
        _cancel_if_requested(should_cancel)

        proposals = self._face_proposals(working)
        proposals.extend(self._grid_proposals(integrals, work_width, work_height))
        selected = self._select_diverse(proposals, work_width, work_height)
        fallback_used = information < self.config.minimum_information or not selected
        if fallback_used:
            selected = [self._composition_fallback(work_width, work_height)]
        candidates = tuple(
            self._candidate(
                proposal,
                maps,
                source_width,
                source_height,
                rank,
            )
            for rank, proposal in enumerate(selected, start=1)
        )
        _cancel_if_requested(should_cancel)
        return SemanticRegionDetection(
            self.analyzer_id,
            self.analyzer_version,
            candidates,
            FrozenJsonObject(
                {
                    "engine": "opencv-local-evidence",
                    "working_width": work_width,
                    "working_height": work_height,
                    "information": round(information, 6),
                    "fallback": fallback_used,
                    "candidate_count": len(candidates),
                    "network_used": False,
                }
            ),
        ).validate()

    def _grid_proposals(
        self,
        integrals: dict[str, np.ndarray],
        width: int,
        height: int,
    ) -> list[_WindowProposal]:
        proposals: list[_WindowProposal] = []
        scales = ((0.24, 0.28), (0.32, 0.34), (0.42, 0.40))
        for reason, region_type, label in self._REASONS:
            reason_proposals: list[_WindowProposal] = []
            for scale_x, scale_y in scales:
                window_width = min(width, max(18, int(round(width * scale_x))))
                window_height = min(height, max(18, int(round(height * scale_y))))
                step_x = max(6, window_width // 3)
                step_y = max(6, window_height // 3)
                x_positions = list(
                    range(0, max(1, width - window_width + 1), step_x)
                )
                y_positions = list(
                    range(0, max(1, height - window_height + 1), step_y)
                )
                if not x_positions or x_positions[-1] != width - window_width:
                    x_positions.append(width - window_width)
                if not y_positions or y_positions[-1] != height - window_height:
                    y_positions.append(height - window_height)
                for y in y_positions:
                    for x in x_positions:
                        values = {
                            name: _window_mean(
                                integral,
                                x,
                                y,
                                window_width,
                                window_height,
                            )
                            for name, integral in integrals.items()
                        }
                        primary = values[reason]
                        score = (
                            0.50 * primary
                            + 0.19 * values["contrast"]
                            + 0.16 * values["edges"]
                            + 0.10 * values["color"]
                            + 0.05 * values["centrality"]
                        )
                        reason_proposals.append(
                            _WindowProposal(
                                reason,
                                region_type,
                                label,
                                x,
                                y,
                                window_width,
                                window_height,
                                score,
                                values["contrast"],
                                values["edges"],
                                values["color"],
                                values["centrality"],
                            )
                        )
            reason_proposals.sort(
                key=lambda item: (-item.score, item.y, item.x, item.width)
            )
            # Keep enough alternatives for the second diversity pass to reach
            # peripheral details instead of exhausting only the visual centre.
            proposals.extend(reason_proposals[:48])
        return proposals

    def _face_proposals(self, image: np.ndarray) -> list[_WindowProposal]:
        cascade_path = (
            Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        )
        if not cascade_path.is_file():
            return []
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        minimum = max(18, int(round(min(image.shape[:2]) * 0.10)))
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.12,
            minNeighbors=5,
            minSize=(minimum, minimum),
        )
        proposals: list[_WindowProposal] = []
        ordered_faces = sorted(
            (tuple(int(value) for value in face) for face in faces),
            key=lambda item: (item[1], item[0], -item[2] * item[3]),
        )
        for x, y, width, height in ordered_faces:
            margin_x = int(round(width * 0.16))
            margin_y = int(round(height * 0.20))
            left = max(0, x - margin_x)
            top = max(0, y - margin_y)
            right = min(image.shape[1], x + width + margin_x)
            bottom = min(image.shape[0], y + height + margin_y)
            proposals.append(
                _WindowProposal(
                    "face",
                    "artwork.region.face",
                    "Visage probable",
                    left,
                    top,
                    right - left,
                    bottom - top,
                    0.48,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                )
            )
        return proposals

    def _select_diverse(
        self,
        proposals: list[_WindowProposal],
        image_width: int,
        image_height: int,
    ) -> list[_WindowProposal]:
        ordered = sorted(
            proposals,
            key=lambda item: (
                -item.score,
                item.reason,
                item.y,
                item.x,
            ),
        )
        selected: list[_WindowProposal] = []
        used_reasons: set[str] = set()
        while ordered and len(selected) < self.config.max_candidates:
            unused = [item for item in ordered if item.reason not in used_reasons]
            pool = unused or ordered
            accepted = next(
                (
                    item
                    for item in pool
                    if all(
                        _iou(item, previous) <= self.config.overlap_limit
                        and self._center_distance(
                            item,
                            previous,
                            image_width,
                            image_height,
                        )
                        >= self.config.minimum_center_distance
                        for previous in selected
                    )
                ),
                None,
            )
            if accepted is None:
                break
            selected.append(accepted)
            used_reasons.add(accepted.reason)
            ordered.remove(accepted)
        return selected

    @staticmethod
    def _center_distance(
        left: _WindowProposal,
        right: _WindowProposal,
        image_width: int,
        image_height: int,
    ) -> float:
        left_x = (left.x + left.width / 2) / image_width
        left_y = (left.y + left.height / 2) / image_height
        right_x = (right.x + right.width / 2) / image_width
        right_y = (right.y + right.height / 2) / image_height
        return float(np.hypot(left_x - right_x, left_y - right_y))

    @staticmethod
    def _composition_fallback(width: int, height: int) -> _WindowProposal:
        window_width = max(1, int(round(width * 0.50)))
        window_height = max(1, int(round(height * 0.52)))
        return _WindowProposal(
            "composition",
            "artwork.region.composition",
            "Centre de composition",
            (width - window_width) // 2,
            (height - window_height) // 2,
            window_width,
            window_height,
            0.38,
            0.0,
            0.0,
            0.0,
            1.0,
            True,
        )

    @staticmethod
    def _candidate(
        proposal: _WindowProposal,
        maps: dict[str, np.ndarray],
        source_width: int,
        source_height: int,
        rank: int,
    ) -> SemanticRegionCandidate:
        work_height, work_width = maps["contrast"].shape
        local = (
            0.38 * maps["contrast"]
            + 0.34 * maps["edges"]
            + 0.20 * maps["color"]
            + 0.08 * maps["centrality"]
        )
        mask = np.zeros((work_height, work_width), dtype=np.uint8)
        region = local[
            proposal.y : proposal.y + proposal.height,
            proposal.x : proposal.x + proposal.width,
        ]
        if proposal.reason in {"face", "composition"}:
            local_mask = np.zeros(
                (proposal.height, proposal.width),
                dtype=np.uint8,
            )
            cv2.ellipse(
                local_mask,
                (proposal.width // 2, proposal.height // 2),
                (
                    max(1, proposal.width // 2 - 1),
                    max(1, proposal.height // 2 - 1),
                ),
                0.0,
                0.0,
                360.0,
                255,
                -1,
                cv2.LINE_AA,
            )
        else:
            threshold = float(np.quantile(region, 0.52))
            local_mask = np.where(region >= threshold, 255, 0).astype(np.uint8)
            kernel_size = max(
                3,
                int(round(min(proposal.width, proposal.height) * 0.045)) | 1,
            )
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (kernel_size, kernel_size),
            )
            local_mask = cv2.morphologyEx(
                local_mask,
                cv2.MORPH_CLOSE,
                kernel,
            )
        mask[
            proposal.y : proposal.y + proposal.height,
            proposal.x : proposal.x + proposal.width,
        ] = local_mask
        if (work_width, work_height) != (source_width, source_height):
            mask = cv2.resize(
                mask,
                (source_width, source_height),
                interpolation=cv2.INTER_NEAREST,
            )
        confidence = float(np.clip(0.30 + 0.62 * proposal.score, 0.30, 0.94))
        return SemanticRegionCandidate(
            proposal.region_type,
            proposal.label,
            Bounds(
                proposal.x / work_width,
                proposal.y / work_height,
                proposal.width / work_width,
                proposal.height / work_height,
            ),
            round(confidence, 6),
            mask,
            FrozenJsonObject(
                {
                    "rank": rank,
                    "reason": proposal.reason,
                    "reason_label": proposal.label,
                    "fallback": proposal.fallback,
                    "scores": {
                        "global": round(proposal.score, 6),
                        "contrast": round(proposal.contrast, 6),
                        "edge_density": round(proposal.edge_density, 6),
                        "color_saliency": round(proposal.color_saliency, 6),
                        "centrality": round(proposal.centrality, 6),
                    },
                    "editable": True,
                    "generated": False,
                }
            ),
        ).validate()

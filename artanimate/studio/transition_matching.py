from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Protocol

import cv2
import numpy as np
from PIL import Image


AKAZE_ALGORITHM = "akaze-homography-v1"


def _rgb_array(image: Image.Image | np.ndarray, where: str) -> np.ndarray:
    value = np.asarray(image.convert("RGB") if isinstance(image, Image.Image) else image)
    if value.ndim != 3 or value.shape[2] != 3 or value.dtype != np.uint8:
        raise TypeError(f"{where} doit être une image RGB uint8")
    return np.ascontiguousarray(value)


def _quad_area(points: tuple[tuple[float, float], ...]) -> float:
    return abs(
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(
                points,
                (*points[1:], points[0]),
                strict=True,
            )
        )
    ) * 0.5


def _convex(points: tuple[tuple[float, float], ...]) -> bool:
    signs = []
    for first, second, third in zip(
        points,
        (*points[1:], points[0]),
        (*points[2:], points[0], points[1]),
        strict=True,
    ):
        cross = (
            (second[0] - first[0]) * (third[1] - second[1])
            - (second[1] - first[1]) * (third[0] - second[0])
        )
        if abs(cross) > 1.0e-8:
            signs.append(math.copysign(1.0, cross))
    return bool(signs) and all(sign == signs[0] for sign in signs)


@dataclass(frozen=True, slots=True)
class SpatialMatchSolution:
    target_quad: tuple[tuple[float, float], ...]
    homography: tuple[tuple[float, float, float], ...]
    reference_keypoints: int
    target_keypoints: int
    candidate_matches: int
    accepted_matches: int
    inliers: int
    inlier_ratio: float
    reprojection_error: float
    confidence: float
    algorithm: str = AKAZE_ALGORITHM

    def validate(self) -> SpatialMatchSolution:
        if len(self.target_quad) != 4 or not _convex(self.target_quad):
            raise ValueError("Le raccord spatial exige un quadrilatère cible convexe")
        if len(self.homography) != 3 or any(len(row) != 3 for row in self.homography):
            raise ValueError("L’homographie du raccord spatial doit être une matrice 3×3")
        values = [value for point in self.target_quad for value in point]
        values.extend(value for row in self.homography for value in row)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("La géométrie du raccord spatial doit être finie")
        if any(not -5.0 <= value <= 6.0 for value in values[:8]):
            raise ValueError("Le quadrilatère du raccord spatial est trop loin du cadre")
        if _quad_area(self.target_quad) < 0.0025:
            raise ValueError("L’œuvre détectée est trop petite pour un raccord spatial")
        for name, value in (
            ("reference_keypoints", self.reference_keypoints),
            ("target_keypoints", self.target_keypoints),
            ("candidate_matches", self.candidate_matches),
            ("accepted_matches", self.accepted_matches),
            ("inliers", self.inliers),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} doit être un entier positif")
        if self.inliers > self.accepted_matches:
            raise ValueError("Le nombre d’inliers dépasse le nombre de correspondances")
        if not 0.0 <= self.inlier_ratio <= 1.0:
            raise ValueError("Le ratio d’inliers doit être compris entre 0 et 1")
        if not math.isfinite(self.reprojection_error) or self.reprojection_error < 0.0:
            raise ValueError("L’erreur de reprojection doit être positive et finie")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("La confiance du raccord doit être comprise entre 0 et 1")
        if self.algorithm != AKAZE_ALGORITHM:
            raise ValueError(f"Solveur de raccord inconnu : {self.algorithm}")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "algorithm": self.algorithm,
            "target_quad": [[round(x, 8), round(y, 8)] for x, y in self.target_quad],
            "homography": [
                [round(float(value), 10) for value in row]
                for row in self.homography
            ],
            "reference_keypoints": self.reference_keypoints,
            "target_keypoints": self.target_keypoints,
            "candidate_matches": self.candidate_matches,
            "accepted_matches": self.accepted_matches,
            "inliers": self.inliers,
            "inlier_ratio": round(self.inlier_ratio, 6),
            "reprojection_error": round(self.reprojection_error, 6),
            "confidence": round(self.confidence, 6),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> SpatialMatchSolution:
        if not isinstance(payload, dict):
            raise TypeError("spatial_match.solution doit être un objet JSON")
        allowed = {
            "algorithm",
            "target_quad",
            "homography",
            "reference_keypoints",
            "target_keypoints",
            "candidate_matches",
            "accepted_matches",
            "inliers",
            "inlier_ratio",
            "reprojection_error",
            "confidence",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans spatial_match.solution : " + ", ".join(unknown)
            )
        try:
            quad = tuple(
                (float(point[0]), float(point[1]))
                for point in payload["target_quad"]
            )
            homography = tuple(
                tuple(float(value) for value in row)
                for row in payload["homography"]
            )
            result = cls(
                quad,
                homography,
                int(payload["reference_keypoints"]),
                int(payload["target_keypoints"]),
                int(payload["candidate_matches"]),
                int(payload["accepted_matches"]),
                int(payload["inliers"]),
                float(payload["inlier_ratio"]),
                float(payload["reprojection_error"]),
                float(payload["confidence"]),
                str(payload.get("algorithm", AKAZE_ALGORITHM)),
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError("Solution de raccord spatial invalide") from exc
        return result.validate()


class ArtworkMatchSolver(Protocol):
    def solve(
        self,
        reference: Image.Image | np.ndarray,
        target: Image.Image | np.ndarray,
    ) -> SpatialMatchSolution: ...


@dataclass(frozen=True, slots=True)
class AkazeMatchSettings:
    ratio_test: float = 0.78
    ransac_threshold: float = 3.0
    minimum_matches: int = 12
    minimum_inliers: int = 10
    minimum_inlier_ratio: float = 0.35
    maximum_reprojection_error: float = 4.5
    maximum_analysis_edge: int = 1600

    def validate(self) -> AkazeMatchSettings:
        if not 0.5 <= self.ratio_test <= 0.95:
            raise ValueError("Le ratio test AKAZE doit être compris entre 0,5 et 0,95")
        if not 0.5 <= self.ransac_threshold <= 12.0:
            raise ValueError("Le seuil RANSAC doit être compris entre 0,5 et 12 px")
        if self.minimum_matches < 8 or self.minimum_inliers < 6:
            raise ValueError("AKAZE exige au moins 8 matches et 6 inliers")
        if not 0.1 <= self.minimum_inlier_ratio <= 1.0:
            raise ValueError("Le ratio minimum d’inliers doit être compris entre 0,1 et 1")
        if not 0.5 <= self.maximum_reprojection_error <= 20.0:
            raise ValueError("L’erreur de reprojection maximale doit être comprise entre 0,5 et 20")
        if self.maximum_analysis_edge < 320:
            raise ValueError("L’analyse AKAZE doit conserver au moins 320 px")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "ratio_test": self.ratio_test,
            "ransac_threshold": self.ransac_threshold,
            "minimum_matches": self.minimum_matches,
            "minimum_inliers": self.minimum_inliers,
            "minimum_inlier_ratio": self.minimum_inlier_ratio,
            "maximum_reprojection_error": self.maximum_reprojection_error,
            "maximum_analysis_edge": self.maximum_analysis_edge,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> AkazeMatchSettings:
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise TypeError("spatial_match.solver doit être un objet JSON")
        unknown = sorted(set(payload) - set(cls().to_dict()))
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans spatial_match.solver : " + ", ".join(unknown)
            )
        return cls(
            ratio_test=float(payload.get("ratio_test", 0.78)),
            ransac_threshold=float(payload.get("ransac_threshold", 3.0)),
            minimum_matches=int(payload.get("minimum_matches", 12)),
            minimum_inliers=int(payload.get("minimum_inliers", 10)),
            minimum_inlier_ratio=float(payload.get("minimum_inlier_ratio", 0.35)),
            maximum_reprojection_error=float(
                payload.get("maximum_reprojection_error", 4.5)
            ),
            maximum_analysis_edge=int(payload.get("maximum_analysis_edge", 1600)),
        ).validate()


def _analysis_image(image: np.ndarray, maximum_edge: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = min(1.0, maximum_edge / max(width, height))
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(32, round(width * scale)), max(32, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return gray, scale


@dataclass(frozen=True, slots=True)
class AkazeArtworkMatchSolver:
    settings: AkazeMatchSettings = AkazeMatchSettings()

    def solve(
        self,
        reference: Image.Image | np.ndarray,
        target: Image.Image | np.ndarray,
    ) -> SpatialMatchSolution:
        settings = self.settings.validate()
        reference_rgb = _rgb_array(reference, "L’œuvre de référence")
        target_rgb = _rgb_array(target, "La photo cible")
        reference_gray, reference_scale = _analysis_image(
            reference_rgb,
            settings.maximum_analysis_edge,
        )
        target_gray, target_scale = _analysis_image(
            target_rgb,
            settings.maximum_analysis_edge,
        )
        detector = cv2.AKAZE_create()
        reference_points, reference_descriptors = detector.detectAndCompute(
            reference_gray,
            None,
        )
        target_points, target_descriptors = detector.detectAndCompute(target_gray, None)
        if reference_descriptors is None or target_descriptors is None:
            raise ValueError("AKAZE ne trouve pas assez de détails dans les deux images")
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        candidates = matcher.knnMatch(reference_descriptors, target_descriptors, k=2)
        accepted = [
            first
            for pair in candidates
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < settings.ratio_test * second.distance
        ]
        best_by_target: dict[int, Any] = {}
        for match in accepted:
            current = best_by_target.get(match.trainIdx)
            if current is None or match.distance < current.distance:
                best_by_target[match.trainIdx] = match
        accepted = sorted(best_by_target.values(), key=lambda item: item.distance)
        if len(accepted) < settings.minimum_matches:
            raise ValueError(
                "Correspondance AKAZE insuffisante "
                f"({len(accepted)} < {settings.minimum_matches})"
            )
        reference_coordinates = np.float32(
            [reference_points[item.queryIdx].pt for item in accepted]
        ).reshape(-1, 1, 2)
        target_coordinates = np.float32(
            [target_points[item.trainIdx].pt for item in accepted]
        ).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            reference_coordinates,
            target_coordinates,
            cv2.RANSAC,
            settings.ransac_threshold,
        )
        if homography is None or mask is None:
            raise ValueError("AKAZE n’a pas pu estimer une homographie stable")
        selected = mask.ravel().astype(bool)
        inliers = int(np.count_nonzero(selected))
        inlier_ratio = inliers / len(accepted)
        if inliers < settings.minimum_inliers:
            raise ValueError(
                f"Homographie trop faible ({inliers} inliers < {settings.minimum_inliers})"
            )
        if inlier_ratio < settings.minimum_inlier_ratio:
            raise ValueError(
                "Ratio d’inliers trop faible "
                f"({inlier_ratio:.2f} < {settings.minimum_inlier_ratio:.2f})"
            )
        projected = cv2.perspectiveTransform(reference_coordinates, homography)
        residuals = np.linalg.norm(
            projected.reshape(-1, 2) - target_coordinates.reshape(-1, 2),
            axis=1,
        )
        reprojection_error = float(np.mean(residuals[selected]))
        if reprojection_error > settings.maximum_reprojection_error:
            raise ValueError(
                "Erreur de reprojection trop élevée "
                f"({reprojection_error:.2f} > {settings.maximum_reprojection_error:.2f})"
            )
        reference_height, reference_width = reference_gray.shape
        target_height, target_width = target_gray.shape
        corners = np.float32(
            [
                (0.0, 0.0),
                (reference_width - 1.0, 0.0),
                (reference_width - 1.0, reference_height - 1.0),
                (0.0, reference_height - 1.0),
            ]
        ).reshape(-1, 1, 2)
        target_corners = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        normalized_quad = tuple(
            (
                float(point[0] / max(1, target_width - 1)),
                float(point[1] / max(1, target_height - 1)),
            )
            for point in target_corners
        )
        source_normalizer = np.asarray(
            (
                (reference_width - 1.0, 0.0, 0.0),
                (0.0, reference_height - 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        target_normalizer = np.asarray(
            (
                (1.0 / max(1, target_width - 1), 0.0, 0.0),
                (0.0, 1.0 / max(1, target_height - 1), 0.0),
                (0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )
        normalized_homography = target_normalizer @ homography @ source_normalizer
        normalized_homography /= normalized_homography[2, 2]
        match_score = min(1.0, len(accepted) / max(settings.minimum_matches * 3, 1))
        error_score = max(
            0.0,
            1.0 - reprojection_error / settings.maximum_reprojection_error,
        )
        confidence = float(
            np.clip(0.5 * inlier_ratio + 0.3 * match_score + 0.2 * error_score, 0.0, 1.0)
        )
        solution = SpatialMatchSolution(
            normalized_quad,
            tuple(tuple(float(value) for value in row) for row in normalized_homography),
            len(reference_points),
            len(target_points),
            len(candidates),
            len(accepted),
            inliers,
            inlier_ratio,
            reprojection_error / max(target_scale, 1.0e-9),
            confidence,
        ).validate()
        # Ensure a meaningful part of the detected artwork intersects the target frame.
        target_polygon = np.asarray(solution.target_quad, dtype=np.float32)
        frame_polygon = np.asarray(
            ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            dtype=np.float32,
        )
        intersection, _polygon = cv2.intersectConvexConvex(target_polygon, frame_polygon)
        if float(intersection) < 0.01:
            raise ValueError("L’œuvre détectée ne recoupe pas suffisamment le cadre final")
        return solution

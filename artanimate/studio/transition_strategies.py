from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .model import Transition, TransitionKind


def _frames(
    outgoing: np.ndarray,
    incoming: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    first = np.asarray(outgoing)
    second = np.asarray(incoming)
    if first.shape != second.shape or first.ndim != 3 or first.shape[2] != 3:
        raise ValueError("Une stratégie de transition exige deux frames RGB de même taille")
    if first.dtype != np.uint8 or second.dtype != np.uint8:
        raise TypeError("Une stratégie de transition exige des frames uint8")
    return first, second


class TransitionFrameStrategy(Protocol):
    def compose(
        self,
        transition: Transition,
        outgoing: np.ndarray,
        incoming: np.ndarray,
        progress: float,
    ) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class CrossDissolveStrategy:
    def compose(
        self,
        transition: Transition,
        outgoing: np.ndarray,
        incoming: np.ndarray,
        progress: float,
    ) -> np.ndarray:
        del transition
        first, second = _frames(outgoing, incoming)
        if progress <= 0.0:
            return first.copy()
        if progress >= 1.0:
            return second.copy()
        mixed = (
            first.astype(np.float32) * (1.0 - progress)
            + second.astype(np.float32) * progress
        )
        return np.ascontiguousarray(np.rint(mixed).clip(0, 255).astype(np.uint8))


def _smoothstep(value: np.ndarray | float) -> np.ndarray | float:
    clipped = np.clip(value, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


@dataclass(frozen=True, slots=True)
class SpatialRevealStrategy:
    def compose(
        self,
        transition: Transition,
        outgoing: np.ndarray,
        incoming: np.ndarray,
        progress: float,
    ) -> np.ndarray:
        first, second = _frames(outgoing, incoming)
        from .spatial_match import SpatialMatchSettings

        settings = SpatialMatchSettings.from_transition(transition)
        if settings.comparison_overlay:
            return CrossDissolveStrategy().compose(
                transition,
                first,
                second,
                settings.overlay_opacity,
            )
        if progress <= 0.0:
            return first.copy()
        if progress >= 1.0:
            return second.copy()
        del transition
        height, width = first.shape[:2]
        reveal_start = 0.80
        if progress <= reveal_start:
            return first.copy()
        material_progress = float(
            _smoothstep((progress - reveal_start) / (1.0 - reveal_start))
        )
        y_axis, x_axis = np.mgrid[0:height, 0:width].astype(np.float32)
        x_axis /= max(1.0, width - 1.0)
        y_axis /= max(1.0, height - 1.0)
        front = (
            x_axis * 0.64
            + y_axis * 0.36
            + np.sin(y_axis * 23.0 + x_axis * 5.0) * 0.018
            + np.sin(x_axis * 41.0 - y_axis * 7.0) * 0.010
        )
        threshold = -0.06 + material_progress * 1.12
        edge_width = 0.018
        real_material = np.asarray(
            _smoothstep((threshold - front + edge_width) / (edge_width * 2.0)),
            dtype=np.float32,
        )
        alpha = 1.0 - real_material

        composed = (
            first.astype(np.float32) * alpha[..., None]
            + second.astype(np.float32) * (1.0 - alpha[..., None])
        )
        return np.ascontiguousarray(np.rint(composed).clip(0, 255).astype(np.uint8))


@dataclass(frozen=True, slots=True)
class DiscoveryRevealStrategy:
    def compose(
        self,
        transition: Transition,
        outgoing: np.ndarray,
        incoming: np.ndarray,
        progress: float,
    ) -> np.ndarray:
        first, second = _frames(outgoing, incoming)
        if progress <= 0.0:
            return first.copy()
        if progress >= 1.0:
            return second.copy()
        from .prologue import DiscoverySettings

        settings = DiscoverySettings.from_transition(transition)
        height, width = first.shape[:2]
        y_axis, x_axis = np.mgrid[0:height, 0:width].astype(np.float32)
        x_axis /= max(1.0, width - 1.0)
        y_axis /= max(1.0, height - 1.0)
        if settings.direction == "center-out":
            field = np.sqrt(
                ((x_axis - 0.5) / 0.78) ** 2
                + ((y_axis - 0.5) / 1.05) ** 2
            )
            field += np.sin(x_axis * 19.0 + y_axis * 7.0) * 0.012
            threshold = progress * 0.82
        elif settings.direction == "bottom-up":
            field = 1.0 - y_axis + np.sin(x_axis * 21.0) * 0.015
            threshold = progress * 1.04
        else:
            field = y_axis + np.sin(x_axis * 21.0) * 0.015
            threshold = progress * 1.04
        incoming_alpha = np.asarray(
            _smoothstep(
                (threshold - field + settings.softness)
                / (settings.softness * 2.0)
            ),
            dtype=np.float32,
        )
        composed = (
            first.astype(np.float32) * (1.0 - incoming_alpha[..., None])
            + second.astype(np.float32) * incoming_alpha[..., None]
        )
        return np.ascontiguousarray(np.rint(composed).clip(0, 255).astype(np.uint8))


_CROSS_DISSOLVE = CrossDissolveStrategy()
_SPATIAL_REVEAL = SpatialRevealStrategy()
_DISCOVERY_REVEAL = DiscoveryRevealStrategy()
_STRATEGIES: dict[TransitionKind, TransitionFrameStrategy] = {
    TransitionKind.DISCOVER: _DISCOVERY_REVEAL,
    TransitionKind.DISSOLVE: _CROSS_DISSOLVE,
    TransitionKind.MATCH: _CROSS_DISSOLVE,
    TransitionKind.SPATIAL_MATCH: _SPATIAL_REVEAL,
}


def strategy_for_transition(transition: Transition) -> TransitionFrameStrategy:
    try:
        return _STRATEGIES[transition.kind]
    except KeyError as exc:
        raise ValueError(
            f"Aucune stratégie de frames pour la transition {transition.kind.value}"
        ) from exc


def compose_transition_frames(
    transition: Transition,
    outgoing: np.ndarray,
    incoming: np.ndarray,
    progress: float,
) -> np.ndarray:
    if not 0.0 <= progress <= 1.0:
        raise ValueError("La progression d’une transition doit être comprise entre 0 et 1")
    return strategy_for_transition(transition).compose(
        transition,
        outgoing,
        incoming,
        progress,
    )

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

import numpy as np

from .light_tools import boundary_mask


_NEIGHBOURS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
)


@dataclass(frozen=True, slots=True)
class LaserPathPoint:
    """One timed cutter-head position; ``laser_on`` controls the physical beam."""

    x: float
    y: float
    progress: float
    laser_on: bool


@dataclass(frozen=True, slots=True)
class ContourTrace:
    """Normalized reveal field and the matching continuous cutter-head route."""

    field: np.ndarray
    points: tuple[LaserPathPoint, ...]
    component_count: int


def detected_contour_mask(
    layer_masks: list[np.ndarray] | tuple[np.ndarray, ...],
    outline_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Fuse true color-family borders with any dark outline detected by analysis."""
    if not layer_masks and outline_mask is None:
        raise ValueError("Au moins un masque est nécessaire pour détecter les contours")
    reference = outline_mask if outline_mask is not None else layer_masks[0]
    result = np.zeros_like(reference, dtype=bool)
    for mask in layer_masks:
        values = np.asarray(mask, dtype=bool)
        if values.shape != result.shape:
            raise ValueError("Tous les masques de contour doivent avoir la même taille")
        result |= boundary_mask(values)
    if outline_mask is not None:
        values = np.asarray(outline_mask, dtype=bool)
        if values.shape != result.shape:
            raise ValueError("Le masque noir doit avoir la taille des familles de couleur")
        result |= values
    return result


def thin_contours(mask: np.ndarray, max_iterations: int = 96) -> np.ndarray:
    """Reduce thick detected strokes to stable one-pixel centre lines."""
    image = np.asarray(mask, dtype=bool).copy()
    if not np.any(image):
        return image
    for _ in range(max(1, int(max_iterations))):
        changed = False
        for second_pass in (False, True):
            padded = np.pad(image, 1, mode="constant", constant_values=False)
            p2 = padded[:-2, 1:-1]
            p3 = padded[:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, :-2]
            p8 = padded[1:-1, :-2]
            p9 = padded[:-2, :-2]
            neighbours = (p2, p3, p4, p5, p6, p7, p8, p9)
            count = sum(item.astype(np.uint8) for item in neighbours)
            transitions = sum(
                ((~neighbours[index]) & neighbours[(index + 1) % 8]).astype(
                    np.uint8
                )
                for index in range(8)
            )
            if second_pass:
                preserve_a = ~(p2 & p4 & p8)
                preserve_b = ~(p2 & p6 & p8)
            else:
                preserve_a = ~(p2 & p4 & p6)
                preserve_b = ~(p4 & p6 & p8)
            remove = (
                image
                & (count >= 2)
                & (count <= 6)
                & (transitions == 1)
                & preserve_a
                & preserve_b
            )
            if np.any(remove):
                image[remove] = False
                changed = True
        if not changed:
            break
    return image


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    visited = np.zeros_like(mask, dtype=bool)
    height, width = mask.shape
    result: list[list[tuple[int, int]]] = []
    for start_y, start_x in np.argwhere(mask):
        start = (int(start_y), int(start_x))
        if visited[start]:
            continue
        queue = deque([start])
        visited[start] = True
        component: list[tuple[int, int]] = []
        while queue:
            y, x = queue.popleft()
            component.append((y, x))
            for dy, dx in _NEIGHBOURS:
                ny, nx = y + dy, x + dx
                if (
                    0 <= ny < height
                    and 0 <= nx < width
                    and mask[ny, nx]
                    and not visited[ny, nx]
                ):
                    visited[ny, nx] = True
                    queue.append((ny, nx))
        result.append(component)
    return result


def _adjacency(
    component: list[tuple[int, int]],
) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    """Build a digital-line graph without false diagonal corner branches.

    An eight-connected curve often contains a 2x2 corner. Keeping its diagonal
    in addition to both orthogonal edges creates a tiny triangle, which makes a
    perfectly continuous outline look branched and forces needless laser-off
    backtracking. The diagonal is therefore retained only when neither of its
    orthogonal bridge pixels exists.
    """
    points = set(component)
    graph: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
    for y, x in component:
        neighbours: list[tuple[int, int]] = []
        for dy, dx in _NEIGHBOURS:
            candidate = (y + dy, x + dx)
            if candidate not in points:
                continue
            if dy and dx and ((y + dy, x) in points or (y, x + dx) in points):
                continue
            neighbours.append(candidate)
        graph[(y, x)] = tuple(neighbours)
    return graph


def _direction_score(
    previous: tuple[int, int] | None,
    current: tuple[int, int],
    candidate: tuple[int, int],
) -> tuple[float, int, int]:
    if previous is None:
        return (0.0, -candidate[1], -candidate[0])
    incoming = (current[0] - previous[0], current[1] - previous[1])
    outgoing = (candidate[0] - current[0], candidate[1] - current[1])
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    return (float(dot), -candidate[1], -candidate[0])


def _walk_component(
    component: list[tuple[int, int]],
) -> list[tuple[tuple[int, int], bool]]:
    graph = _adjacency(component)
    endpoints = sorted(
        (point for point, neighbours in graph.items() if len(neighbours) <= 1),
        key=lambda point: (point[1], point[0]),
    )
    start = endpoints[0] if endpoints else min(component, key=lambda point: (point[1], point[0]))
    simple = all(len(neighbours) <= 2 for neighbours in graph.values())
    visited = {start}
    route: list[tuple[tuple[int, int], bool]] = [(start, True)]

    if simple:
        previous: tuple[int, int] | None = None
        current = start
        while len(visited) < len(component):
            candidates = [item for item in graph[current] if item not in visited]
            if not candidates:
                break
            candidate = max(
                candidates,
                key=lambda item: _direction_score(previous, current, item),
            )
            route.append((candidate, True))
            visited.add(candidate)
            previous, current = current, candidate
        return route

    stack = [start]
    while stack:
        current = stack[-1]
        previous = stack[-2] if len(stack) > 1 else None
        candidates = [item for item in graph[current] if item not in visited]
        if candidates:
            candidate = max(
                candidates,
                key=lambda item: _direction_score(previous, current, item),
            )
            visited.add(candidate)
            stack.append(candidate)
            route.append((candidate, True))
            continue
        stack.pop()
        if stack:
            route.append((stack[-1], False))
    return route


def _route_components(
    skeleton: np.ndarray,
) -> tuple[list[tuple[tuple[int, int], bool]], int]:
    components = [component for component in _components(skeleton) if len(component) >= 2]
    if not components and np.any(skeleton):
        components = _components(skeleton)
    components.sort(
        key=lambda component: (
            min(point[1] for point in component),
            min(point[0] for point in component),
        )
    )
    route: list[tuple[tuple[int, int], bool]] = []
    travel_step = max(1.5, min(skeleton.shape) / 90.0)
    for component in components:
        walked = _walk_component(component)
        if not walked:
            continue
        if route:
            start_y, start_x = walked[0][0]
            end_y, end_x = route[-1][0]
            distance = math.hypot(start_x - end_x, start_y - end_y)
            steps = max(1, int(math.ceil(distance / travel_step)))
            for step in range(1, steps + 1):
                mix = step / steps
                route.append(
                    (
                        (
                            int(round(end_y + (start_y - end_y) * mix)),
                            int(round(end_x + (start_x - end_x) * mix)),
                        ),
                        False,
                    )
                )
        route.extend(walked)
    return route, len(components)


def _timed_route(
    route: list[tuple[tuple[int, int], bool]],
) -> tuple[LaserPathPoint, ...]:
    if not route:
        return ()
    distance = np.zeros(len(route), dtype=np.float64)
    for index in range(1, len(route)):
        (previous_y, previous_x), _ = route[index - 1]
        (current_y, current_x), laser_on = route[index]
        segment = math.hypot(current_x - previous_x, current_y - previous_y)
        distance[index] = distance[index - 1] + segment * (1.0 if laser_on else 0.20)
    total = max(float(distance[-1]), 1e-6)
    progress = 0.012 + (distance / total) * 0.976
    return tuple(
        LaserPathPoint(
            x=float(point[1]),
            y=float(point[0]),
            progress=float(progress[index]),
            laser_on=laser_on,
        )
        for index, (point, laser_on) in enumerate(route)
    )


def _field_from_route(
    mask: np.ndarray,
    points: tuple[LaserPathPoint, ...],
) -> np.ndarray:
    height, width = mask.shape
    field = np.ones((height, width), dtype=np.float32)
    seed_time = np.full((height, width), np.inf, dtype=np.float32)
    for point in points:
        if not point.laser_on:
            continue
        x = int(round(point.x))
        y = int(round(point.y))
        if 0 <= y < height and 0 <= x < width and mask[y, x]:
            seed_time[y, x] = min(seed_time[y, x], point.progress)
    seeds = np.argwhere(np.isfinite(seed_time))
    if not len(seeds):
        field[mask] = 0.5
        return field
    visited = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for y, x in seeds:
        iy, ix = int(y), int(x)
        visited[iy, ix] = True
        field[iy, ix] = seed_time[iy, ix]
        queue.append((iy, ix))
    while queue:
        y, x = queue.popleft()
        for dy, dx in _NEIGHBOURS:
            ny, nx = y + dy, x + dx
            if (
                0 <= ny < height
                and 0 <= nx < width
                and mask[ny, nx]
                and not visited[ny, nx]
            ):
                visited[ny, nx] = True
                field[ny, nx] = field[y, x]
                queue.append((ny, nx))
    field[mask & ~visited] = 1.0
    return field


def build_contour_trace(mask: np.ndarray) -> ContourTrace:
    """Build one deterministic shape-following path and its reveal-time field."""
    values = np.asarray(mask, dtype=bool)
    if values.ndim != 2:
        raise ValueError("Un masque de contour doit être une image 2D")
    if not np.any(values):
        return ContourTrace(np.ones(values.shape, dtype=np.float32), (), 0)
    skeleton = thin_contours(values)
    route, component_count = _route_components(skeleton)
    points = _timed_route(route)
    return ContourTrace(
        field=_field_from_route(values, points),
        points=points,
        component_count=component_count,
    )


def contour_path_field(mask: np.ndarray) -> np.ndarray:
    """Return normalized drawing times that follow detected shapes, not image axes."""
    return build_contour_trace(mask).field


def sample_laser_path(mask: np.ndarray, max_points: int = 720) -> tuple[LaserPathPoint, ...]:
    """Resample the exact route at uniform timeline intervals for the 3D cutter."""
    points = build_contour_trace(mask).points
    if len(points) <= 1:
        return points
    count = max(2, min(int(max_points), len(points)))
    source_progress = np.asarray([point.progress for point in points], dtype=np.float64)
    targets = np.linspace(0.0, 1.0, count)
    result: list[LaserPathPoint] = []
    for target in targets:
        upper = int(np.searchsorted(source_progress, target, side="left"))
        if upper <= 0:
            point = points[0]
            result.append(LaserPathPoint(point.x, point.y, float(target), point.laser_on))
            continue
        if upper >= len(points):
            point = points[-1]
            result.append(LaserPathPoint(point.x, point.y, float(target), point.laser_on))
            continue
        before = points[upper - 1]
        after = points[upper]
        span = max(after.progress - before.progress, 1e-9)
        mix = float(np.clip((target - before.progress) / span, 0.0, 1.0))
        result.append(
            LaserPathPoint(
                x=before.x + (after.x - before.x) * mix,
                y=before.y + (after.y - before.y) * mix,
                progress=float(target),
                laser_on=after.laser_on,
            )
        )
    return tuple(result)

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .model import StudioProject
from .semantic import (
    CapabilityInvocation,
    CapabilityRegistry,
    TimelineTrigger,
    validate_trigger_graph,
)


@dataclass(frozen=True, slots=True)
class CompiledTrigger:
    trigger_id: str
    source_invocation_id: str
    event_id: str
    event_frame: int
    action_invocation_id: str
    action_start_frame: int
    offset_frames: int


@dataclass(frozen=True, slots=True)
class TriggerCompilation:
    invocations: tuple[CapabilityInvocation, ...]
    triggers: tuple[CompiledTrigger, ...]

    def invocation(self, invocation_id: str) -> CapabilityInvocation:
        try:
            return next(
                item for item in self.invocations
                if item.invocation_id == invocation_id
            )
        except StopIteration as exc:
            raise KeyError(f"Invocation compilée introuvable : {invocation_id}") from exc

    def trigger(self, trigger_id: str) -> CompiledTrigger:
        try:
            return next(item for item in self.triggers if item.trigger_id == trigger_id)
        except StopIteration as exc:
            raise KeyError(f"Déclencheur compilé introuvable : {trigger_id}") from exc


def _timed_parameter(values: dict[str, Any], key: str, selector: str | None) -> int:
    raw = values.get(key)
    if not isinstance(raw, list) or not raw:
        noun = "marqueur" if key == "markers" else "beat"
        raise ValueError(f"La source ne contient aucun {noun} exploitable")
    if key == "markers":
        candidates = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or "frame" not in item:
                raise ValueError("Un marqueur doit contenir id et frame")
            candidates.append((str(item.get("id", index)), item["frame"]))
        if selector is None:
            frame = candidates[0][1]
        else:
            try:
                frame = next(frame for marker_id, frame in candidates if marker_id == selector)
            except StopIteration as exc:
                raise ValueError(f"Marqueur audio introuvable : {selector}") from exc
    else:
        try:
            index = 0 if selector is None else int(selector)
            item = raw[index]
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Beat audio introuvable : {selector}") from exc
        frame = item.get("frame") if isinstance(item, dict) else item
    if isinstance(frame, bool) or not isinstance(frame, int) or frame < 0:
        raise ValueError(f"{key} doit contenir des frames locales positives")
    return frame


def event_local_frame(
    invocation: CapabilityInvocation,
    event_id: str,
    capabilities: CapabilityRegistry | None = None,
) -> int:
    if capabilities is not None:
        try:
            descriptor = capabilities.get(invocation.capability_id)
        except KeyError as exc:
            raise ValueError(
                f"Capability inconnue pour la source {invocation.invocation_id}"
            ) from exc
        prefix = event_id.split(":", 1)[0]
        if prefix not in {"marker", "beat"} and event_id not in descriptor.emitted_events:
            raise ValueError(
                f"{invocation.capability_id} n’émet pas l’événement {event_id}"
            )
    if event_id == "started":
        return 0
    if event_id == "completed":
        return invocation.duration_frames
    if event_id == "object-exited":
        if invocation.capability_id != "object.exit_frame":
            raise ValueError("object-exited exige une source object.exit_frame")
        return invocation.duration_frames - 1
    prefix, separator, selector = event_id.partition(":")
    values = invocation.parameters.to_dict()
    if prefix == "marker":
        local = _timed_parameter(values, "markers", selector if separator else None)
    elif prefix == "beat":
        local = _timed_parameter(values, "beats", selector if separator else None)
    else:
        raise ValueError(f"Événement de timeline inconnu : {event_id}")
    if local >= invocation.duration_frames:
        raise ValueError(
            f"L’événement {event_id} dépasse la durée de {invocation.invocation_id}"
        )
    return local


def _topological_invocations(
    invocation_ids: tuple[str, ...],
    triggers: tuple[TimelineTrigger, ...],
) -> tuple[str, ...]:
    adjacency: dict[str, list[str]] = {item: [] for item in invocation_ids}
    indegree = {item: 0 for item in invocation_ids}
    for trigger in triggers:
        adjacency[trigger.source_invocation_id].append(trigger.action_invocation_id)
        indegree[trigger.action_invocation_id] += 1
    ready = sorted(item for item, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for target in sorted(adjacency[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(ordered) != len(invocation_ids):
        raise ValueError("Le graphe de déclencheurs ne peut pas être ordonné")
    return tuple(ordered)


def compile_timeline_triggers(
    project: StudioProject,
    capabilities: CapabilityRegistry | None = None,
) -> TriggerCompilation:
    """Resolve every trigger into the one project frame consumed by preview/export."""

    project.validate()
    validate_trigger_graph(project.triggers)
    incoming: dict[str, TimelineTrigger] = {}
    for trigger in sorted(project.triggers, key=lambda item: item.trigger_id):
        previous = incoming.get(trigger.action_invocation_id)
        if previous is not None:
            raise ValueError(
                "Une action ne peut avoir qu’un déclencheur entrant : "
                f"{previous.trigger_id}, {trigger.trigger_id}"
            )
        incoming[trigger.action_invocation_id] = trigger

    original = {item.invocation_id: item for item in project.invocations}
    order = _topological_invocations(tuple(original), project.triggers)
    compiled: dict[str, CapabilityInvocation] = {}
    resolutions: list[CompiledTrigger] = []
    for invocation_id in order:
        invocation = original[invocation_id]
        trigger = incoming.get(invocation_id)
        if trigger is None:
            compiled[invocation_id] = invocation
            continue
        source = compiled[trigger.source_invocation_id]
        event_frame = source.start_frame + event_local_frame(
            source,
            trigger.event_id,
            capabilities,
        )
        action_start = event_frame + trigger.offset_frames
        if action_start < 0:
            raise ValueError(
                f"Le déclencheur {trigger.trigger_id} place l’action avant la frame 0"
            )
        if action_start + invocation.duration_frames > project.settings.duration_frames:
            raise ValueError(
                f"Le déclencheur {trigger.trigger_id} fait dépasser la durée du projet"
            )
        effective = replace(invocation, start_frame=action_start)
        compiled[invocation_id] = effective
        resolutions.append(
            CompiledTrigger(
                trigger.trigger_id,
                trigger.source_invocation_id,
                trigger.event_id,
                event_frame,
                trigger.action_invocation_id,
                action_start,
                trigger.offset_frames,
            )
        )
    return TriggerCompilation(
        tuple(compiled[item.invocation_id] for item in project.invocations),
        tuple(sorted(resolutions, key=lambda item: item.trigger_id)),
    )

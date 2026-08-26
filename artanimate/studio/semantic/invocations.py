from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .common import FrozenJsonObject, identifier


class RendererPolicyMode(StrEnum):
    AUTOMATIC = "automatic"
    PINNED = "pinned"
    FALLBACK_CHAIN = "fallback-chain"


@dataclass(frozen=True, slots=True)
class RendererPolicy:
    mode: RendererPolicyMode = RendererPolicyMode.AUTOMATIC
    renderer_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RendererPolicyMode):
            raise TypeError("renderer_policy.mode doit être un RendererPolicyMode")
        if len(self.renderer_ids) != len(set(self.renderer_ids)):
            raise ValueError("Une politique renderer contient un candidat dupliqué")
        for renderer_id in self.renderer_ids:
            identifier(renderer_id, "renderer_policy.renderer_ids")
        if self.mode == RendererPolicyMode.AUTOMATIC and self.renderer_ids:
            raise ValueError("La politique automatic ne doit pas épingler de renderer")
        if self.mode == RendererPolicyMode.PINNED and len(self.renderer_ids) != 1:
            raise ValueError("La politique pinned exige exactement un renderer")
        if self.mode == RendererPolicyMode.FALLBACK_CHAIN and not self.renderer_ids:
            raise ValueError("Une fallback-chain doit contenir au moins un renderer")

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "renderer_ids": list(self.renderer_ids)}

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "RendererPolicy":
        if not isinstance(values, Mapping):
            raise TypeError("Une politique renderer doit être un objet JSON")
        unknown = set(values) - {"mode", "renderer_ids"}
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans RendererPolicy : " + ", ".join(sorted(unknown)))
        return cls(RendererPolicyMode(values.get("mode", RendererPolicyMode.AUTOMATIC.value)), tuple(values.get("renderer_ids", ())))


@dataclass(frozen=True, slots=True)
class CapabilityInvocation:
    invocation_id: str
    capability_id: str
    start_frame: int
    duration_frames: int
    target_id: str | None = None
    parameters: FrozenJsonObject = field(default_factory=FrozenJsonObject)
    renderer_policy: RendererPolicy = RendererPolicy()
    enabled: bool = True

    def __post_init__(self) -> None:
        identifier(self.invocation_id, "invocation.invocation_id")
        identifier(self.capability_id, "invocation.capability_id")
        if self.target_id is not None:
            identifier(self.target_id, "invocation.target_id")
        if isinstance(self.start_frame, bool) or not isinstance(self.start_frame, int) or self.start_frame < 0:
            raise ValueError("invocation.start_frame doit être un entier positif")
        if isinstance(self.duration_frames, bool) or not isinstance(self.duration_frames, int) or self.duration_frames <= 0:
            raise ValueError("invocation.duration_frames doit être un entier strictement positif")
        if not isinstance(self.parameters, FrozenJsonObject):
            object.__setattr__(self, "parameters", FrozenJsonObject(self.parameters, where="invocation.parameters"))
        if not isinstance(self.renderer_policy, RendererPolicy):
            raise TypeError("invocation.renderer_policy doit être un RendererPolicy")
        if not isinstance(self.enabled, bool):
            raise TypeError("invocation.enabled doit être booléen")

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames

    @classmethod
    def create(cls, capability_id: str, *, start_frame: int, duration_frames: int, target_id: str | None = None,
               parameters: Mapping[str, Any] | None = None, renderer_policy: RendererPolicy = RendererPolicy()) -> "CapabilityInvocation":
        return cls(f"inv-{uuid4().hex}", capability_id, start_frame, duration_frames, target_id=target_id,
                   parameters=FrozenJsonObject(parameters or {}, where="invocation.parameters"), renderer_policy=renderer_policy)

    def to_dict(self) -> dict[str, Any]:
        return {"invocation_id": self.invocation_id, "capability_id": self.capability_id, "target_id": self.target_id,
                "start_frame": self.start_frame, "duration_frames": self.duration_frames, "parameters": self.parameters.to_dict(),
                "renderer_policy": self.renderer_policy.to_dict(), "enabled": self.enabled}

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CapabilityInvocation":
        if not isinstance(values, Mapping):
            raise TypeError("Une invocation doit être un objet JSON")
        allowed = {"invocation_id", "capability_id", "target_id", "start_frame", "duration_frames", "parameters", "renderer_policy", "enabled"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Clé(s) inconnue(s) dans CapabilityInvocation : " + ", ".join(sorted(unknown)))
        return cls(values["invocation_id"], values["capability_id"], values["start_frame"], values["duration_frames"],
                   target_id=values.get("target_id"), parameters=FrozenJsonObject(values.get("parameters", {}), where="invocation.parameters"),
                   renderer_policy=RendererPolicy.from_dict(values.get("renderer_policy", {})), enabled=values.get("enabled", True))


@dataclass(frozen=True, slots=True)
class TimelineTrigger:
    trigger_id: str
    source_invocation_id: str
    event_id: str
    action_invocation_id: str
    offset_frames: int = 0

    def __post_init__(self) -> None:
        identifier(self.trigger_id, "trigger.trigger_id")
        identifier(self.source_invocation_id, "trigger.source_invocation_id")
        identifier(self.event_id, "trigger.event_id")
        identifier(self.action_invocation_id, "trigger.action_invocation_id")
        if self.source_invocation_id == self.action_invocation_id:
            raise ValueError("Un trigger ne peut pas déclencher sa propre invocation")
        if isinstance(self.offset_frames, bool) or not isinstance(self.offset_frames, int):
            raise TypeError("trigger.offset_frames doit être un entier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "source_invocation_id": self.source_invocation_id,
            "event_id": self.event_id,
            "action_invocation_id": self.action_invocation_id,
            "offset_frames": self.offset_frames,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "TimelineTrigger":
        if not isinstance(values, Mapping):
            raise TypeError("Un trigger doit être un objet JSON")
        allowed = {
            "trigger_id",
            "source_invocation_id",
            "event_id",
            "action_invocation_id",
            "offset_frames",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(
                "Clé(s) inconnue(s) dans TimelineTrigger : "
                + ", ".join(sorted(unknown))
            )
        return cls(
            values["trigger_id"],
            values["source_invocation_id"],
            values["event_id"],
            values["action_invocation_id"],
            values.get("offset_frames", 0),
        )

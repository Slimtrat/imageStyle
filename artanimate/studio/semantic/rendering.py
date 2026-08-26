from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .common import FrozenJsonObject, identifier
from .invocations import CapabilityInvocation
from .scene import SemanticScene, SceneObject


@dataclass(frozen=True, slots=True)
class RenderConstraints:
    width: int
    height: int
    fps: int
    quality: str = "studio"
    require_alpha: bool = False
    require_deterministic: bool = True
    offline_only: bool = True
    proxy: bool = False

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (self.width, self.height, self.fps)):
            raise ValueError("Les dimensions et le FPS de rendu doivent être positifs")
        identifier(self.quality, "render_constraints.quality")
        if not all(isinstance(value, bool) for value in (self.require_alpha, self.require_deterministic, self.offline_only, self.proxy)):
            raise TypeError("Les options de contraintes de rendu doivent être booléennes")


@dataclass(frozen=True, slots=True)
class RendererDescriptor:
    renderer_id: str
    label: str
    capability_ids: tuple[str, ...]
    version: str = "1"
    deterministic: bool = True
    offline: bool = True
    supports_alpha: bool = False
    quality_tiers: tuple[str, ...] = ("fast", "studio")
    priority: int = 0
    max_width: int | None = None
    max_height: int | None = None

    def __post_init__(self) -> None:
        identifier(self.renderer_id, "renderer.renderer_id")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("Un renderer doit avoir un label")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Un renderer doit avoir une version")
        if not self.capability_ids:
            raise ValueError("Un renderer doit annoncer au moins une capability")
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError("Un renderer annonce une capability en double")
        for capability_id in self.capability_ids:
            identifier(capability_id, "renderer.capability_ids")
        for quality in self.quality_tiers:
            identifier(quality, "renderer.quality_tiers")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("renderer.priority doit être un entier")
        for where, value in (("max_width", self.max_width), ("max_height", self.max_height)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                raise ValueError(f"renderer.{where} doit être positif")


@dataclass(frozen=True, slots=True)
class RendererEvaluation:
    compatible: bool
    score: int = 0
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.compatible, bool):
            raise TypeError("renderer_evaluation.compatible doit être booléen")
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise TypeError("renderer_evaluation.score doit être entier")
        if not self.compatible and not self.reasons:
            raise ValueError("Un renderer incompatible doit expliquer pourquoi")


@dataclass(frozen=True, slots=True)
class RenderRequest:
    project_id: str
    scene: SemanticScene
    invocation: CapabilityInvocation
    target: SceneObject | None
    constraints: RenderConstraints
    seed: int

    def __post_init__(self) -> None:
        identifier(self.project_id, "render_request.project_id")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("render_request.seed doit être un entier positif")
        if self.invocation.target_id is None and self.target is not None:
            raise ValueError("Une requête sans target_id ne doit pas injecter de cible")
        if self.invocation.target_id is not None and (self.target is None or self.target.object_id != self.invocation.target_id):
            raise ValueError("La cible résolue ne correspond pas à l'invocation")


@dataclass(frozen=True, slots=True)
class RenderFrame:
    """Engine-neutral envelope; adapters own concrete pixel and audio types."""

    image: Any
    alpha: Any | None = None
    reference: Any | None = None
    blend_mode: str = "normal"
    metadata: FrozenJsonObject = field(default_factory=FrozenJsonObject)


@runtime_checkable
class PreparedRender(Protocol):
    width: int
    height: int
    fps: int
    frame_count: int

    def frame_at(self, frame_index: int) -> RenderFrame: ...

    def close(self) -> None: ...


@runtime_checkable
class CapabilityRenderer(Protocol):
    descriptor: RendererDescriptor

    def evaluate(self, request: RenderRequest) -> RendererEvaluation: ...

    def prepare(self, request: RenderRequest) -> PreparedRender: ...


@dataclass(frozen=True, slots=True)
class RenderPlanEntry:
    request: RenderRequest
    renderer_id: str
    renderer_version: str
    evaluation: RendererEvaluation

    def __post_init__(self) -> None:
        identifier(self.renderer_id, "render_plan_entry.renderer_id")


@dataclass(frozen=True, slots=True)
class RenderPlan:
    project_id: str
    scene_id: str
    constraints: RenderConstraints
    entries: tuple[RenderPlanEntry, ...]

    def __post_init__(self) -> None:
        identifier(self.project_id, "render_plan.project_id")
        identifier(self.scene_id, "render_plan.scene_id")
        invocation_ids = tuple(item.request.invocation.invocation_id for item in self.entries)
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("Un plan de rendu contient une invocation dupliquée")

from __future__ import annotations

from dataclasses import dataclass

import pytest

from artanimate.studio.semantic import (
    Affordance,
    AvailabilityStatus,
    Bounds,
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityParameter,
    CapabilityRegistry,
    CapabilityRequirement,
    RendererDescriptor,
    RendererEvaluation,
    RendererPolicy,
    RendererPolicyMode,
    RendererRegistry,
    RenderConstraints,
    RenderFrame,
    RenderPlanner,
    ResourceRef,
    SceneObject,
    SemanticScene,
)


def _scene(*, with_mask: bool = True, movable: bool = True) -> SemanticScene:
    resources = (
        (ResourceRef("object-mask", "mask", "mask-asset"),)
        if with_mask
        else ()
    )
    affordances = (
        (Affordance("movable", 0.95, source="manual"),)
        if movable
        else ()
    )
    return SemanticScene(
        "scene-1",
        "artwork",
        (
            SceneObject("artwork", "artwork", "Œuvre", bounds=Bounds(0, 0, 1, 1)),
            SceneObject(
                "object-1",
                "private.unknown-object",
                "Objet",
                bounds=Bounds(0.2, 0.2, 0.3, 0.4),
                resource_refs=resources,
                affordances=affordances,
            ),
        ),
    )


def _move_capability() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        "object.move",
        "Déplacer l'objet",
        "object",
        requirements=(
            CapabilityRequirement(
                "movable-mask",
                "L'objet doit être mobile et détouré",
                affordance_ids=("movable",),
                resource_kinds=("mask",),
            ),
        ),
        parameters=(
            CapabilityParameter("destination", "Destination", "point", required=True),
            CapabilityParameter(
                "easing",
                "Accélération",
                "choice",
                default="ease-in-out",
                has_default=True,
                choices=("linear", "ease-in-out"),
            ),
        ),
        renderer_candidates=("classic.trajectory", "fallback.trajectory"),
        emitted_events=("completed", "object-exited"),
    )


@dataclass
class _Prepared:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    frame_count: int = 30
    closed: bool = False

    def frame_at(self, frame_index: int) -> RenderFrame:
        if self.closed:
            raise RuntimeError("closed")
        return RenderFrame((self.width, self.height, frame_index))

    def close(self) -> None:
        self.closed = True


class _Renderer:
    def __init__(self, renderer_id: str, *, score: int, priority: int = 0):
        self.descriptor = RendererDescriptor(
            renderer_id,
            renderer_id,
            ("object.move",),
            priority=priority,
            supports_alpha=True,
        )
        self.score = score

    def evaluate(self, request):
        return RendererEvaluation(True, self.score)

    def prepare(self, request):
        return _Prepared(
            request.constraints.width,
            request.constraints.height,
            request.constraints.fps,
            request.invocation.duration_frames,
        )


def _registries() -> tuple[CapabilityRegistry, RendererRegistry]:
    capabilities = CapabilityRegistry()
    capabilities.register(_move_capability())
    renderers = RendererRegistry()
    renderers.register(_Renderer("classic.trajectory", score=40))
    renderers.register(_Renderer("fallback.trajectory", score=10))
    return capabilities.freeze(), renderers.freeze()


def test_registry_explains_when_an_analysis_is_missing() -> None:
    registry = CapabilityRegistry()
    registry.register(_move_capability())
    registry.freeze()

    decision = registry.evaluate("object.move", _scene(with_mask=False), "object-1")

    assert decision.status == AvailabilityStatus.ANALYSIS_REQUIRED
    assert "mask" in decision.reasons[0]


def test_registry_stays_extensible_and_freezes_per_session() -> None:
    registry = CapabilityRegistry()
    registry.register(_move_capability())
    registry.freeze()

    assert registry.evaluate("object.move", _scene(), "object-1").available
    with pytest.raises(RuntimeError, match="figé"):
        registry.register(
            CapabilityDescriptor("private.new-motion", "Nouveau", "private")
        )


def test_planner_normalizes_parameters_and_selects_renderer_deterministically() -> None:
    capabilities, renderers = _registries()
    planner = RenderPlanner(capabilities, renderers)
    invocation = CapabilityInvocation(
        "move-1",
        "object.move",
        12,
        30,
        target_id="object-1",
        parameters={"destination": [0.8, 0.3]},
    )
    constraints = RenderConstraints(1080, 1920, 30, require_alpha=True)

    first = planner.plan("project-1", _scene(), (invocation,), constraints)
    second = planner.plan("project-1", _scene(), (invocation,), constraints)

    assert first == second
    assert first.entries[0].renderer_id == "classic.trajectory"
    assert first.entries[0].request.invocation.parameters.to_dict() == {
        "destination": [0.8, 0.3],
        "easing": "ease-in-out",
    }
    assert first.entries[0].request.seed == second.entries[0].request.seed


def test_pinned_renderer_is_an_intent_preserved_by_the_plan() -> None:
    capabilities, renderers = _registries()
    invocation = CapabilityInvocation(
        "move-1",
        "object.move",
        0,
        30,
        target_id="object-1",
        parameters={"destination": [0.5, 0.5]},
        renderer_policy=RendererPolicy(
            RendererPolicyMode.PINNED,
            ("fallback.trajectory",),
        ),
    )

    plan = RenderPlanner(capabilities, renderers).plan(
        "project-1",
        _scene(),
        (invocation,),
        RenderConstraints(540, 960, 30, proxy=True),
    )

    assert plan.entries[0].renderer_id == "fallback.trajectory"


def test_planner_rejects_unknown_parameters_before_preparing_a_renderer() -> None:
    capabilities, renderers = _registries()
    invocation = CapabilityInvocation(
        "move-1",
        "object.move",
        0,
        30,
        target_id="object-1",
        parameters={"destination": [0.5, 0.5], "model_name": "forbidden"},
    )

    with pytest.raises(ValueError, match="model_name"):
        RenderPlanner(capabilities, renderers).plan(
            "project-1",
            _scene(),
            (invocation,),
            RenderConstraints(1080, 1920, 30),
        )


def test_semantic_domain_does_not_import_qt_or_numpy() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "artanimate" / "studio" / "semantic"
    imports: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    assert not any(name.startswith(("PySide6", "numpy")) for name in imports)

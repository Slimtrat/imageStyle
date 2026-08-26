from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib

from .capabilities import CapabilityDescriptor
from .invocations import CapabilityInvocation, RendererPolicyMode
from .rendering import CapabilityRenderer, RenderConstraints, RendererEvaluation, RenderPlan, RenderPlanEntry, RenderRequest
from .scene import SemanticScene


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    ANALYSIS_REQUIRED = "analysis-required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    capability_id: str
    target_id: str | None
    status: AvailabilityStatus
    reasons: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == AvailabilityStatus.AVAILABLE


class CapabilityRegistry:
    """Mutable while bootstrapping, immutable for one Studio session."""

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityDescriptor] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, descriptor: CapabilityDescriptor) -> None:
        if self._frozen:
            raise RuntimeError("Le registre de capabilities est figé pour cette session")
        if descriptor.capability_id in self._capabilities:
            raise ValueError(f"Capability déjà enregistrée : {descriptor.capability_id}")
        self._capabilities[descriptor.capability_id] = descriptor

    def freeze(self) -> "CapabilityRegistry":
        self._frozen = True
        return self

    def get(self, capability_id: str) -> CapabilityDescriptor:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"Capability inconnue : {capability_id}") from exc

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self._capabilities[key] for key in sorted(self._capabilities))

    def evaluate(self, capability_id: str, scene: SemanticScene, target_id: str | None) -> CapabilityDecision:
        descriptor = self.get(capability_id)
        target = scene.object_by_id(target_id) if target_id is not None else None
        if target_id is not None and target is None:
            return CapabilityDecision(capability_id, target_id, AvailabilityStatus.UNAVAILABLE, (f"La cible {target_id!r} n'existe pas dans la scène",))
        unavailable: list[str] = []
        analysis: list[str] = []
        for requirement in descriptor.requirements:
            if requirement.target_required and target is None:
                unavailable.append(requirement.description + " : aucune cible sélectionnée")
                continue
            if target is None:
                continue
            if requirement.semantic_types and target.semantic_type not in requirement.semantic_types:
                unavailable.append(requirement.description + f" : type {target.semantic_type!r} non compatible")
                continue
            if target.confidence < requirement.minimum_confidence:
                analysis.append(requirement.description + f" : confiance {target.confidence:.2f} insuffisante")
            missing_affordances = sorted(set(requirement.affordance_ids) - target.affordance_ids)
            if missing_affordances:
                analysis.append(requirement.description + " : affordance(s) manquante(s) " + ", ".join(missing_affordances))
            missing_resources = sorted(set(requirement.resource_kinds) - target.resource_kinds)
            if missing_resources:
                analysis.append(requirement.description + " : analyse(s) manquante(s) " + ", ".join(missing_resources))
        if unavailable:
            return CapabilityDecision(capability_id, target_id, AvailabilityStatus.UNAVAILABLE, tuple(unavailable))
        if analysis:
            return CapabilityDecision(capability_id, target_id, AvailabilityStatus.ANALYSIS_REQUIRED, tuple(analysis))
        return CapabilityDecision(capability_id, target_id, AvailabilityStatus.AVAILABLE)

    def for_target(self, scene: SemanticScene, target_id: str | None) -> tuple[CapabilityDecision, ...]:
        return tuple(self.evaluate(descriptor.capability_id, scene, target_id) for descriptor in self.descriptors())


class RendererRegistry:
    def __init__(self) -> None:
        self._renderers: dict[str, CapabilityRenderer] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, renderer: CapabilityRenderer) -> None:
        if self._frozen:
            raise RuntimeError("Le registre de renderers est figé pour cette session")
        renderer_id = renderer.descriptor.renderer_id
        if renderer_id in self._renderers:
            raise ValueError(f"Renderer déjà enregistré : {renderer_id}")
        self._renderers[renderer_id] = renderer

    def freeze(self) -> "RendererRegistry":
        self._frozen = True
        return self

    def get(self, renderer_id: str) -> CapabilityRenderer:
        try:
            return self._renderers[renderer_id]
        except KeyError as exc:
            raise KeyError(f"Renderer inconnu : {renderer_id}") from exc

    def candidates_for(self, capability_id: str) -> tuple[CapabilityRenderer, ...]:
        return tuple(renderer for renderer_id, renderer in sorted(self._renderers.items()) if capability_id in renderer.descriptor.capability_ids)


def _seed_for(project_id: str, invocation_id: str) -> int:
    digest = hashlib.sha256(f"{project_id}:{invocation_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _static_renderer_evaluation(renderer: CapabilityRenderer, request: RenderRequest) -> RendererEvaluation | None:
    descriptor = renderer.descriptor
    constraints = request.constraints
    reasons: list[str] = []
    if request.invocation.capability_id not in descriptor.capability_ids:
        reasons.append("capability non prise en charge")
    if constraints.require_deterministic and not descriptor.deterministic:
        reasons.append("renderer non déterministe")
    if constraints.offline_only and not descriptor.offline:
        reasons.append("renderer non local")
    if constraints.require_alpha and not descriptor.supports_alpha:
        reasons.append("canal alpha non pris en charge")
    if constraints.quality not in descriptor.quality_tiers:
        reasons.append(f"qualité {constraints.quality!r} non prise en charge")
    if descriptor.max_width is not None and constraints.width > descriptor.max_width:
        reasons.append("largeur demandée trop élevée")
    if descriptor.max_height is not None and constraints.height > descriptor.max_height:
        reasons.append("hauteur demandée trop élevée")
    if reasons:
        return RendererEvaluation(False, reasons=tuple(reasons))
    return None


class RenderPlanner:
    def __init__(self, capabilities: CapabilityRegistry, renderers: RendererRegistry) -> None:
        if not capabilities.frozen or not renderers.frozen:
            raise ValueError("Les registries doivent être figés avant de planifier un rendu")
        self.capabilities = capabilities
        self.renderers = renderers

    def plan(self, project_id: str, scene: SemanticScene, invocations: tuple[CapabilityInvocation, ...], constraints: RenderConstraints) -> RenderPlan:
        entries: list[RenderPlanEntry] = []
        for invocation in invocations:
            if not invocation.enabled:
                continue
            descriptor = self.capabilities.get(invocation.capability_id)
            decision = self.capabilities.evaluate(invocation.capability_id, scene, invocation.target_id)
            if not decision.available:
                raise ValueError(f"Capability {invocation.capability_id} indisponible : " + "; ".join(decision.reasons))
            normalized = CapabilityInvocation(
                invocation.invocation_id, invocation.capability_id, invocation.start_frame, invocation.duration_frames,
                target_id=invocation.target_id, parameters=descriptor.normalize_parameters(invocation.parameters),
                renderer_policy=invocation.renderer_policy, enabled=True,
            )
            target = scene.object_by_id(normalized.target_id) if normalized.target_id is not None else None
            request = RenderRequest(project_id, scene, normalized, target, constraints, _seed_for(project_id, normalized.invocation_id))
            renderer, evaluation = self._select_renderer(descriptor, request)
            entries.append(RenderPlanEntry(request, renderer.descriptor.renderer_id, renderer.descriptor.version, evaluation))
        return RenderPlan(project_id, scene.scene_id, constraints, tuple(entries))

    def _select_renderer(self, capability: CapabilityDescriptor, request: RenderRequest) -> tuple[CapabilityRenderer, RendererEvaluation]:
        policy = request.invocation.renderer_policy
        if policy.mode == RendererPolicyMode.AUTOMATIC:
            candidate_ids = capability.renderer_candidates or tuple(item.descriptor.renderer_id for item in self.renderers.candidates_for(capability.capability_id))
        else:
            candidate_ids = policy.renderer_ids
        evaluations: list[tuple[int, int, int, str, CapabilityRenderer, RendererEvaluation]] = []
        failures: list[str] = []
        for index, renderer_id in enumerate(candidate_ids):
            try:
                renderer = self.renderers.get(renderer_id)
            except KeyError:
                failures.append(f"{renderer_id}: non installé")
                continue
            evaluation = _static_renderer_evaluation(renderer, request) or renderer.evaluate(request)
            if not evaluation.compatible:
                failures.append(renderer_id + ": " + ", ".join(evaluation.reasons))
                continue
            if policy.mode in {RendererPolicyMode.PINNED, RendererPolicyMode.FALLBACK_CHAIN}:
                return renderer, evaluation
            evaluations.append((evaluation.score, renderer.descriptor.priority, -index, renderer_id, renderer, evaluation))
        if evaluations:
            _score, _priority, _order, _renderer_id, renderer, evaluation = max(evaluations, key=lambda item: (item[0], item[1], item[2], item[3]))
            return renderer, evaluation
        detail = "; ".join(failures) if failures else "aucun candidat enregistré"
        raise ValueError(f"Aucun renderer disponible pour {capability.capability_id} : {detail}")

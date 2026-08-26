"""Stable domain contracts for Artanimate's artwork-first semantic Studio."""

from .affordances import Affordance, AffordanceSet
from .capabilities import CapabilityDescriptor, CapabilityParameter, CapabilityRequirement
from .common import FrozenJsonObject
from .invocations import (
    CapabilityInvocation, RendererPolicy, RendererPolicyMode, TimelineTrigger,
    trigger_cycle_path, validate_trigger_graph,
)
from .registry import AvailabilityStatus, CapabilityDecision, CapabilityRegistry, RendererRegistry, RenderPlanner
from .rendering import CapabilityRenderer, PreparedRender, RenderConstraints, RendererDescriptor, RendererEvaluation, RenderFrame, RenderPlan, RenderPlanEntry, RenderRequest
from .scene import AnalyzerRun, Bounds, ResourceRef, SceneObject, SceneRelation, SemanticScene

__all__ = [
    "Affordance", "AffordanceSet", "AnalyzerRun", "AvailabilityStatus", "Bounds", "CapabilityDecision",
    "CapabilityDescriptor", "CapabilityInvocation", "CapabilityParameter", "CapabilityRegistry", "CapabilityRenderer",
    "CapabilityRequirement", "FrozenJsonObject", "PreparedRender", "RendererDescriptor", "RendererEvaluation",
    "RendererPolicy", "RendererPolicyMode", "RendererRegistry", "RenderConstraints", "RenderFrame", "RenderPlan",
    "RenderPlanEntry", "RenderPlanner", "RenderRequest", "ResourceRef", "SceneObject", "SceneRelation",
    "SemanticScene", "TimelineTrigger", "trigger_cycle_path", "validate_trigger_graph",
]

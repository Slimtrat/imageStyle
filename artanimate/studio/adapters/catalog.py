from __future__ import annotations

from ..semantic import CapabilityDescriptor, CapabilityParameter, CapabilityRequirement
from ...core.effects import effect_keys


def effect_capability_id(effect_key: str) -> str:
    return "reveal.chromatic" if effect_key == "rgb_fade" else f"reveal.{effect_key}"


def _build_legacy_capability_catalog() -> tuple[CapabilityDescriptor, ...]:
    """Capabilities currently backed by native V1 renderers, without rewriting them."""
    artwork_requirement = CapabilityRequirement(
        "artwork-presentable",
        "L'œuvre doit pouvoir être présentée",
        semantic_types=("artwork",),
        affordance_ids=("presentable",),
    )
    effect_requirement = CapabilityRequirement(
        "artwork-effect-applicable",
        "L'œuvre doit accepter un effet",
        semantic_types=("artwork",),
        affordance_ids=("effect-applicable",),
    )
    camera_requirement = CapabilityRequirement(
        "camera-animatable",
        "La caméra doit pouvoir être animée",
        semantic_types=("scene.camera",),
        affordance_ids=("animatable",),
    )
    source_in = CapabilityParameter(
        "source_in_frame", "Entrée source", "integer", default=0, has_default=True, minimum=0
    )
    opacity = CapabilityParameter(
        "opacity", "Opacité", "number", default=1.0, has_default=True, minimum=0.0, maximum=1.0
    )
    fit = CapabilityParameter(
        "fit", "Ajustement", "choice", default="contain", has_default=True,
        choices=("contain", "cover", "stretch"),
    )
    capabilities = [
        CapabilityDescriptor(
            "artwork.present", "Présenter l'œuvre", "artwork",
            requirements=(artwork_requirement,), parameters=(source_in, opacity, fit),
            renderer_candidates=("classic.artwork.static",),
        ),
        CapabilityDescriptor(
            "scene.depth_present", "Mettre l'œuvre en profondeur", "scene",
            requirements=(artwork_requirement,),
            parameters=(
                source_in, opacity, fit,
                CapabilityParameter("settings", "Réglages 3D", "any", default={}, has_default=True),
            ),
            renderer_candidates=("classic.studio-3d",),
        ),
        CapabilityDescriptor(
            "camera.animate", "Animer la caméra", "camera",
            requirements=(camera_requirement,),
            parameters=(
                CapabilityParameter("keyframes", "Keyframes", "any", required=True),
                CapabilityParameter("target_invocation_id", "Plan ciblé", "string", required=True),
            ),
            renderer_candidates=("classic.camera-2d",),
        ),
        CapabilityDescriptor(
            "media.present", "Présenter un média réel", "media",
            parameters=(
                CapabilityParameter("asset_id", "Média", "resource", required=True),
                source_in, opacity, fit,
                CapabilityParameter(
                    "settings", "Réglages média", "any", default={}, has_default=True
                ),
            ),
            renderer_candidates=("local.media",),
        ),
        CapabilityDescriptor(
            "audio.play", "Lire une piste audio", "audio",
            parameters=(
                CapabilityParameter("asset_id", "Audio", "resource", required=True),
                source_in,
            ),
            renderer_candidates=("local.audio",),
        ),
    ]
    for effect_key in effect_keys():
        capabilities.append(
            CapabilityDescriptor(
                effect_capability_id(effect_key),
                "Révéler l'œuvre · " + effect_key.replace("_", " "),
                "reveal",
                requirements=(effect_requirement,),
                parameters=(
                    CapabilityParameter("render_config", "Réglages figés", "any", required=True),
                    CapabilityParameter("intensity", "Intensité", "number", default=1.0, has_default=True, minimum=0.0, maximum=1.0),
                    CapabilityParameter("target_clip_id", "Plan d'œuvre ciblé", "string", required=True),
                    opacity,
                ),
                renderer_candidates=(f"classic.effect.{effect_key}",),
            )
        )
    return tuple(capabilities)


_LEGACY_CAPABILITY_CATALOG = _build_legacy_capability_catalog()


def legacy_capability_catalog() -> tuple[CapabilityDescriptor, ...]:
    return _LEGACY_CAPABILITY_CATALOG

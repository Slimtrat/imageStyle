from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .model import Clip, ClipKind, StudioProject, TrackKind
from .semantic import (
    CapabilityDescriptor,
    CapabilityInvocation,
    CapabilityParameter,
    CapabilityRequirement,
)


SEMANTIC_ACTION_RENDERER_ID = "local.semantic-actions"
SEMANTIC_ACTION_IDS = frozenset(
    {
        "object.move",
        "object.exit_frame",
        "region.blink",
        "scene.parallax",
        "camera.inspect",
        "camera.zoom_out",
        "environment.particles",
    }
)


def _easing_parameter() -> CapabilityParameter:
    return CapabilityParameter(
        "easing",
        "Accélération",
        "choice",
        default="ease-in-out",
        has_default=True,
        choices=("linear", "ease-in", "ease-out", "ease-in-out"),
        description="Courbe temporelle déterministe appliquée au mouvement.",
    )


def _seed_parameter() -> CapabilityParameter:
    return CapabilityParameter(
        "seed",
        "Seed",
        "integer",
        default=0,
        has_default=True,
        minimum=0,
        maximum=2_147_483_647,
        description="Une même seed produit exactement le même résultat.",
    )


def semantic_action_capability_catalog() -> tuple[CapabilityDescriptor, ...]:
    movable_mask = CapabilityRequirement(
        "movable-mask",
        "L’objet doit être détouré et déclaré mobile",
        affordance_ids=("movable",),
        resource_kinds=("mask",),
    )
    exitable_mask = CapabilityRequirement(
        "exitable-mask",
        "L’objet doit être détouré et autorisé à quitter le cadre",
        affordance_ids=("frame-exitable",),
        resource_kinds=("mask",),
    )
    blinkable_eye = CapabilityRequirement(
        "blinkable-eye-mask",
        "L’œil doit posséder un masque canonique et être déclaré clignable",
        semantic_types=("artwork.region.eye",),
        affordance_ids=("blinkable",),
        resource_kinds=("mask",),
    )
    depth = CapabilityRequirement(
        "artwork-depth",
        "L’œuvre doit disposer d’une carte de profondeur locale",
        semantic_types=("artwork",),
        affordance_ids=("depth-aware",),
        resource_kinds=("depth",),
    )
    inspectable = CapabilityRequirement(
        "inspectable-target",
        "La cible doit pouvoir être inspectée par la caméra",
        affordance_ids=("camera-inspectable",),
    )
    camera = CapabilityRequirement(
        "camera-animatable",
        "La caméra de scène doit pouvoir être animée",
        semantic_types=("scene.camera",),
        affordance_ids=("animatable",),
    )
    fill = CapabilityParameter(
        "fill_mode",
        "Zones libérées",
        "choice",
        default="edge-fill",
        has_default=True,
        choices=("edge-fill", "hold"),
        description=(
            "edge-fill reconstruit localement la zone désoccluse ; hold conserve "
            "l’image sous l’objet comme fallback explicite."
        ),
    )
    return (
        CapabilityDescriptor(
            "object.move",
            "Déplacer cet élément",
            "object",
            requirements=(movable_mask,),
            parameters=(
                CapabilityParameter(
                    "destination",
                    "Destination",
                    "point",
                    default=[0.75, 0.5],
                    has_default=True,
                    description="Centre final normalisé [x, y] dans le cadre.",
                ),
                _easing_parameter(),
                fill,
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            emitted_events=("started", "completed"),
            description=(
                "Déplace uniquement les pixels du masque sélectionné. Le reste de "
                "l’œuvre demeure la source maîtresse."
            ),
        ),
        CapabilityDescriptor(
            "object.exit_frame",
            "Faire sortir cet élément du cadre",
            "object",
            requirements=(exitable_mask,),
            parameters=(
                CapabilityParameter(
                    "direction",
                    "Bord de sortie",
                    "direction",
                    default="right",
                    has_default=True,
                    choices=("left", "right", "top", "bottom"),
                ),
                CapabilityParameter(
                    "margin",
                    "Marge hors cadre",
                    "number",
                    default=0.04,
                    has_default=True,
                    minimum=0.0,
                    maximum=0.5,
                ),
                _easing_parameter(),
                fill,
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            emitted_events=("started", "object-exited", "completed"),
            description=(
                "Anime le masque jusqu’à ce qu’il franchisse entièrement le bord "
                "choisi ; la dernière frame émet object-exited."
            ),
        ),
        CapabilityDescriptor(
            "region.blink",
            "Faire cligner cet œil",
            "region",
            requirements=(blinkable_eye,),
            parameters=(
                CapabilityParameter(
                    "close_frames",
                    "Fermeture",
                    "integer",
                    default=6,
                    has_default=True,
                    minimum=2,
                    maximum=60,
                ),
                CapabilityParameter(
                    "hold_frames",
                    "Maintien",
                    "integer",
                    default=2,
                    has_default=True,
                    minimum=0,
                    maximum=60,
                ),
                CapabilityParameter(
                    "open_frames",
                    "Ouverture",
                    "integer",
                    default=8,
                    has_default=True,
                    minimum=2,
                    maximum=60,
                ),
                CapabilityParameter(
                    "intensity",
                    "Intensité",
                    "number",
                    default=1.0,
                    has_default=True,
                    minimum=0.0,
                    maximum=1.0,
                ),
                _easing_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            emitted_events=("started", "blink-closed", "completed"),
            description=(
                "Ferme puis rouvre uniquement la région de l’œil. Le même masque "
                "canonique est reprojeté sur le plan réel par le raccord spatial."
            ),
        ),
        CapabilityDescriptor(
            "scene.parallax",
            "Créer un mouvement de profondeur",
            "scene",
            requirements=(depth,),
            parameters=(
                CapabilityParameter(
                    "travel",
                    "Déplacement",
                    "point",
                    default=[0.04, 0.015],
                    has_default=True,
                    description="Amplitude normalisée horizontale et verticale.",
                ),
                CapabilityParameter(
                    "strength",
                    "Profondeur",
                    "number",
                    default=1.0,
                    has_default=True,
                    minimum=0.0,
                    maximum=3.0,
                ),
                _easing_parameter(),
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            description=(
                "Déforme localement l’image selon la depth map, avec extension des "
                "bords pour éviter les trous noirs et fallback déterministe."
            ),
        ),
        CapabilityDescriptor(
            "camera.inspect",
            "Inspecter cette zone",
            "camera",
            requirements=(inspectable,),
            parameters=(
                CapabilityParameter(
                    "zoom",
                    "Zoom final",
                    "number",
                    default=1.8,
                    has_default=True,
                    minimum=1.0,
                    maximum=8.0,
                ),
                _easing_parameter(),
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            description="Cadre progressivement la zone choisie sans altérer l’œuvre source.",
        ),
        CapabilityDescriptor(
            "camera.zoom_out",
            "Revenir au cadrage de l’œuvre",
            "camera",
            requirements=(camera,),
            parameters=(
                CapabilityParameter(
                    "start_zoom",
                    "Zoom de départ",
                    "number",
                    default=1.6,
                    has_default=True,
                    minimum=1.0,
                    maximum=8.0,
                ),
                _easing_parameter(),
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            description=(
                "Part d’un détail et termine exactement sur le cadrage fidèle de l’œuvre."
            ),
        ),
        CapabilityDescriptor(
            "environment.particles",
            "Ajouter des particules ciblées",
            "environment",
            parameters=(
                CapabilityParameter(
                    "count",
                    "Quantité",
                    "integer",
                    default=120,
                    has_default=True,
                    minimum=1,
                    maximum=1_000,
                ),
                CapabilityParameter(
                    "color",
                    "Couleur",
                    "color",
                    default="#ffffff",
                    has_default=True,
                ),
                CapabilityParameter(
                    "size",
                    "Taille",
                    "number",
                    default=2.5,
                    has_default=True,
                    minimum=0.5,
                    maximum=20.0,
                ),
                CapabilityParameter(
                    "speed",
                    "Vitesse",
                    "number",
                    default=0.35,
                    has_default=True,
                    minimum=0.0,
                    maximum=3.0,
                ),
                _seed_parameter(),
            ),
            renderer_candidates=(SEMANTIC_ACTION_RENDERER_ID,),
            description=(
                "Échantillonne le masque de la cible ; sans masque, le renderer "
                "annonce et utilise le fallback scène entière."
            ),
        ),
    )


_SEMANTIC_ACTION_CATALOG = semantic_action_capability_catalog()


def semantic_action_catalog() -> tuple[CapabilityDescriptor, ...]:
    return _SEMANTIC_ACTION_CATALOG


def is_semantic_action_capability(capability_id: str) -> bool:
    return capability_id in SEMANTIC_ACTION_IDS


def is_semantic_action_clip(clip: Clip) -> bool:
    if clip.invocation_id is None or clip.legacy_kind is not None:
        return False
    parameters = clip.parameters or {}
    return parameters.get("semantic_action") in SEMANTIC_ACTION_IDS


def add_semantic_action_clip(
    project: StudioProject,
    invocation: CapabilityInvocation,
) -> tuple[StudioProject, Clip]:
    """Persist a native semantic action and expose it as an editable timeline clip."""

    if invocation.capability_id not in SEMANTIC_ACTION_IDS:
        raise ValueError(f"Capability non gérée comme action native : {invocation.capability_id}")
    if invocation.invocation_id in {item.invocation_id for item in project.invocations}:
        raise ValueError("Cette invocation existe déjà dans le projet")
    track_index = next(
        (
            index
            for index, track in enumerate(project.tracks)
            if track.kind == TrackKind.EFFECT and not track.locked
        ),
        None,
    )
    if track_index is None:
        raise PermissionError("Ajoutez ou déverrouillez une piste d’actions")
    clip = Clip(
        clip_id=f"semantic-action-{uuid4().hex[:12]}",
        kind=ClipKind.EFFECT_2D,
        start_frame=invocation.start_frame,
        duration_frames=invocation.duration_frames,
        enabled=invocation.enabled,
        parameters={"semantic_action": invocation.capability_id},
        invocation_id=invocation.invocation_id,
    ).validate()
    tracks = list(project.tracks)
    track = tracks[track_index]
    clips = sorted(
        (*track.clips, clip),
        key=lambda item: (item.start_frame, item.clip_id),
    )
    tracks[track_index] = replace(track, clips=tuple(clips))
    updated = replace(
        project,
        tracks=tuple(tracks),
        invocations=(*project.invocations, invocation),
    ).validate()
    return updated, clip

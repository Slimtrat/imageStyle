from __future__ import annotations

import json

import pytest

from artanimate.studio.semantic import (
    Affordance,
    AffordanceSet,
    Bounds,
    FrozenJsonObject,
    ResourceRef,
    SceneObject,
    SemanticScene,
)


def test_minimal_scene_keeps_every_artwork_usable_without_a_model() -> None:
    scene = SemanticScene.minimal("artwork", scene_id="scene-minimal")

    assert tuple(item.object_id for item in scene.objects) == (
        "artwork",
        "background",
        "camera",
    )
    assert "camera-inspectable" in scene.object_by_id("artwork").affordance_ids
    assert scene.object_by_id("camera").semantic_type == "scene.camera"


def test_scene_graph_accepts_arbitrary_semantic_types_and_round_trips_json() -> None:
    scene = SemanticScene(
        "scene-custom",
        "artwork",
        (
            SceneObject("artwork", "artwork", "Œuvre", bounds=Bounds(0, 0, 1, 1)),
            SceneObject(
                "constellation-7",
                "collector.private.constellation-creature",
                "Créature constellation",
                confidence=0.87,
                bounds=Bounds(0.12, 0.18, 0.44, 0.52),
                resource_refs=(
                    ResourceRef(
                        "mask-constellation",
                        "mask",
                        "mask-asset",
                        FrozenJsonObject({"format": "png", "channel": 0}),
                    ),
                ),
                attributes=FrozenJsonObject(
                    {"palette": ["#123456", "#abcdef"], "count": 3}
                ),
                affordances=(
                    Affordance("movable", 0.91, source="analyzer.local.v1"),
                    Affordance("frame-exitable", 0.84, source="manual"),
                ),
            ),
        ),
    )

    payload = json.loads(json.dumps(scene.to_dict(), ensure_ascii=False))
    restored = SemanticScene.from_dict(payload)

    assert restored == scene
    assert restored.object_by_id("constellation-7").resource_kinds == {"mask"}
    assert hash(restored.object_by_id("constellation-7").attributes)


def test_frozen_json_deeply_detaches_from_mutable_input() -> None:
    source = {"nested": {"values": [1, 2]}}
    frozen = FrozenJsonObject(source)
    source["nested"]["values"].append(3)

    assert frozen.to_dict() == {"nested": {"values": [1, 2]}}
    with pytest.raises(TypeError):
        frozen["new"] = 4


def test_affordance_merge_keeps_strongest_evidence_deterministically() -> None:
    merged = AffordanceSet.merge(
        (Affordance("movable", 0.4, source="analyzer.a"),),
        (
            Affordance("frame-exitable", 0.7, source="manual"),
            Affordance("movable", 0.9, source="analyzer.b"),
        ),
    )

    assert tuple(item.affordance_id for item in merged.values) == (
        "frame-exitable",
        "movable",
    )
    assert merged.get("movable").source == "analyzer.b"


def test_scene_rejects_relations_to_unknown_objects() -> None:
    from artanimate.studio.semantic import SceneRelation

    with pytest.raises(ValueError, match="objet absent"):
        SemanticScene(
            "scene-invalid",
            "artwork",
            (SceneObject("artwork", "artwork", "Œuvre"),),
            (SceneRelation("rel-1", "attached-to", "artwork", "missing"),),
        )

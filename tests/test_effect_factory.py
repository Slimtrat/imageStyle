from dataclasses import fields

import numpy as np
import pytest

from artanimate.core.config import EFFECTS, RenderConfig
from artanimate.core.effects import (
    AnimationEffect,
    EffectCapability,
    EffectContext,
    create_effect,
    effect_descriptors,
    effect_keys,
)


def test_factory_is_the_single_source_of_registered_effects() -> None:
    assert effect_keys() == EFFECTS == (
        "sand",
        "pigment_sweep",
        "wave",
        "paint_drop",
        "rgb_fade",
        "vertical_halo",
        "screenprint",
        "contour_laser",
        "screenprint_laser",
    )
    assert [descriptor.key for descriptor in effect_descriptors()] == list(EFFECTS)


@pytest.mark.parametrize("key", EFFECTS)
def test_every_registered_effect_fulfils_the_contract(key: str) -> None:
    effect = create_effect(key)
    config = RenderConfig(effect=key, width=64)
    context = EffectContext(width=64, height=40, seed=7, config=config)
    first = effect.create_field(context)
    second = create_effect(key).create_field(context)

    assert isinstance(effect, AnimationEffect)
    assert first.shape == (40, 64)
    assert first.dtype == np.float32
    assert 0.0 <= float(first.min()) <= float(first.max()) <= 1.0
    assert np.array_equal(first, second)


def test_effect_metadata_is_documented_and_references_real_config_fields() -> None:
    config_fields = {field.name for field in fields(RenderConfig)}
    for descriptor in effect_descriptors():
        assert descriptor.selector_label
        assert descriptor.description
        documented = tuple(parameter.key for parameter in descriptor.parameters)
        assert documented == descriptor.config_fields
        assert set(descriptor.config_fields) <= config_fields


def test_effect_capabilities_match_their_composition_model() -> None:
    descriptors = {item.key: item for item in effect_descriptors()}
    for key in (
        "sand",
        "wave",
        "paint_drop",
        "screenprint",
        "screenprint_laser",
    ):
        assert descriptors[key].supports(EffectCapability.CHROMATIC_SEQUENCE)
        assert not descriptors[key].supports(EffectCapability.FRAME_COMPOSITOR)
    for key in ("paint_drop", "screenprint", "contour_laser", "screenprint_laser"):
        assert descriptors[key].supports(EffectCapability.FRAME_DECORATOR)
    assert descriptors["contour_laser"].supports(EffectCapability.DETECTED_CONTOURS)
    assert descriptors["pigment_sweep"].supports(EffectCapability.GLOBAL_REVEAL)
    assert descriptors["pigment_sweep"].supports(EffectCapability.TARGETED_PARTICLES)
    assert not descriptors["pigment_sweep"].supports(
        EffectCapability.CHROMATIC_SEQUENCE
    )
    assert descriptors["vertical_halo"].supports(EffectCapability.FRAME_COMPOSITOR)
    assert descriptors["rgb_fade"].supports(EffectCapability.FRAME_COMPOSITOR)
    assert not descriptors["contour_laser"].supports(EffectCapability.CHROMATIC_SEQUENCE)
    assert not descriptors["rgb_fade"].supports(EffectCapability.CHROMATIC_SEQUENCE)


def test_factory_rejects_unknown_effect() -> None:
    with pytest.raises(ValueError, match="Effet inconnu"):
        create_effect("missing")


def test_contract_rejects_a_malformed_field() -> None:
    class BrokenEffect(AnimationEffect):
        key = "broken"

        def build_field(self, context: EffectContext) -> np.ndarray:
            return np.zeros((2, 2), dtype=np.float32)

    context = EffectContext(8, 6, 1, RenderConfig())
    with pytest.raises(ValueError, match="attendu"):
        BrokenEffect().create_field(context)

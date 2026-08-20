"""Extensible animation-effect subsystem.

Adding an effect intentionally has a short, explicit path:

1. create one module next to :mod:`sand` and :mod:`wave`;
2. subclass :class:`AnimationEffect` and implement ``build_field``;
3. decorate the class with :func:`register_effect`;
4. import that module here so registration happens at application startup.

The renderer and configuration consume only this public contract. Compatibility
exports for ``sand_field``, ``wave_field`` and ``reveal_opacity`` are retained for
callers that use the low-level numerical functions directly.
"""

from .base import (
    AnimationEffect,
    EffectCapability,
    EffectContext,
    EffectDescriptor,
    FrameCompositionContext,
)
from .documentation import (
    ChoiceDocumentation,
    EffectDocumentation,
    ParameterDocumentation,
    documentation_for,
    load_effect_documentation,
)
from .factory import create_effect, effect_descriptors, effect_keys, register_effect
from .reveal import reveal_opacity
from .sand import SandEffect, sand_field
from .wave import WaveEffect, wave_field
from .rgb_fade import RgbFadeEffect, rgb_channel_weights


__all__ = [
    "AnimationEffect",
    "ChoiceDocumentation",
    "EffectCapability",
    "EffectContext",
    "EffectDescriptor",
    "EffectDocumentation",
    "FrameCompositionContext",
    "ParameterDocumentation",
    "RgbFadeEffect",
    "SandEffect",
    "WaveEffect",
    "create_effect",
    "documentation_for",
    "effect_descriptors",
    "effect_keys",
    "load_effect_documentation",
    "register_effect",
    "reveal_opacity",
    "rgb_channel_weights",
    "sand_field",
    "wave_field",
]

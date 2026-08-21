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
    FrameDecorationContext,
    LayerFrameState,
    TargetedParticleBank,
    TargetedParticleContext,
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
from .pigment_sweep import (
    PIGMENT_SWEEP_DIRECTIONS,
    PigmentSweepEffect,
    pigment_sweep_field,
    targeted_particle_position,
)
from .wave import WaveEffect, wave_field
from .paint_drop import PaintDropEffect, paint_drop_field, paint_drop_target
from .rgb_fade import RgbFadeEffect, rgb_channel_weights
from .vertical_halo import VerticalHaloEffect
from .screenprint import ScreenPrintEffect
from .contour_laser import ContourLaserEffect
from .contour_paths import (
    ContourTrace,
    LaserPathPoint,
    build_contour_trace,
    contour_path_field,
    detected_contour_mask,
    sample_laser_path,
    thin_contours,
)
from .screenprint_laser import ScreenPrintLaserEffect


__all__ = [
    "AnimationEffect",
    "ChoiceDocumentation",
    "EffectCapability",
    "EffectContext",
    "EffectDescriptor",
    "EffectDocumentation",
    "FrameCompositionContext",
    "FrameDecorationContext",
    "LayerFrameState",
    "LaserPathPoint",
    "ParameterDocumentation",
    "PaintDropEffect",
    "PIGMENT_SWEEP_DIRECTIONS",
    "PigmentSweepEffect",
    "RgbFadeEffect",
    "TargetedParticleBank",
    "TargetedParticleContext",
    "SandEffect",
    "ScreenPrintEffect",
    "ScreenPrintLaserEffect",
    "ContourLaserEffect",
    "ContourTrace",
    "VerticalHaloEffect",
    "WaveEffect",
    "build_contour_trace",
    "contour_path_field",
    "create_effect",
    "detected_contour_mask",
    "documentation_for",
    "effect_descriptors",
    "effect_keys",
    "load_effect_documentation",
    "paint_drop_field",
    "paint_drop_target",
    "pigment_sweep_field",
    "register_effect",
    "reveal_opacity",
    "rgb_channel_weights",
    "sample_laser_path",
    "thin_contours",
    "targeted_particle_position",
    "sand_field",
    "wave_field",
]

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from .analysis import ArtworkAnalysis, ColorLayer, analyze_artwork
from .config import RenderConfig
from .effects import (
    EffectCapability,
    EffectContext,
    FrameCompositionContext,
    FrameDecorationContext,
    LayerFrameState,
    create_effect,
    reveal_opacity,
)
from .quality import ease_in_out, exposure_average, srgb_to_linear


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FallingParticles:
    target_x: np.ndarray
    target_y: np.ndarray
    settle: np.ndarray
    flight: np.ndarray
    sway: np.ndarray
    phase: np.ndarray
    colors: np.ndarray


class ArtworkRenderer:
    """Prepared, reusable renderer. Frame generation is streaming and deterministic."""

    def __init__(self, analysis: ArtworkAnalysis, config: RenderConfig):
        self.analysis = analysis
        self.config = config.validate()
        self.effect = create_effect(config.effect)
        self.width, self.height = analysis.size
        self.color_layers = analysis.ordered_layers(
            config.order,
            config.start_hue,
            config.neutral_position,
        )
        self.stages = self._stage_layers()
        self.blank = np.empty_like(analysis.source)
        self.blank[:] = analysis.background_color
        self.blank[analysis.background_mask] = analysis.source[analysis.background_mask]
        direct_compositor = self.effect.supports(EffectCapability.FRAME_COMPOSITOR)
        self.frame_context = FrameCompositionContext(
            source=analysis.source,
            canvas=self.blank,
            config=config,
            linear_source=srgb_to_linear(analysis.source) if direct_compositor else None,
        )
        all_layers = list(self.color_layers)
        if analysis.outline:
            all_layers.append(analysis.outline)
        self.fields: dict[str, np.ndarray] = {}
        self.particles: dict[str, FallingParticles] = {}
        if direct_compositor:
            all_layers = []
        for index, layer in enumerate(all_layers):
            layer_seed = config.seed + (index + 1) * 7919
            context = EffectContext(
                width=self.width,
                height=self.height,
                seed=layer_seed,
                config=config,
                layer_mask=layer.mask,
                layer_color=layer.color,
                is_outline=layer.is_outline,
            )
            field = self.effect.create_field(context)
            self.fields[layer.key] = field
            if (
                self.effect.supports(EffectCapability.FALLING_PARTICLES)
                and config.grain_density > 0
            ):
                particles = self._prepare_particles(layer, field, layer_seed)
                if particles is not None:
                    self.particles[layer.key] = particles

        logger.info(
            "Moteur prêt : effet=%s, ordre=%s, couches=%d, images=%d",
            config.effect,
            config.order,
            len(self.stages),
            self.frame_count,
        )

    def _stage_layers(self) -> list[ColorLayer]:
        outline = self.analysis.outline
        if outline is not None and self.effect.supports(EffectCapability.OUTLINE_FINALE):
            return [*self.color_layers, outline]
        if outline is None or self.config.outline == "together":
            return list(self.color_layers)
        if self.config.outline == "first":
            return [outline, *self.color_layers]
        return [*self.color_layers, outline]

    def _prepare_particles(
        self,
        layer: ColorLayer,
        field: np.ndarray,
        seed: int,
    ) -> FallingParticles | None:
        coordinates = np.argwhere(layer.mask)
        if len(coordinates) == 0:
            return None
        desired = int(round(len(coordinates) * self.config.grain_density))
        desired = min(len(coordinates), max(180, min(6800, desired)))
        rng = np.random.default_rng(seed)
        chosen = rng.choice(len(coordinates), size=desired, replace=False)
        targets = coordinates[chosen]
        target_y = targets[:, 0].astype(np.float32)
        target_x = targets[:, 1].astype(np.float32)
        settle = field[targets[:, 0], targets[:, 1]].astype(np.float32)
        return FallingParticles(
            target_x=target_x,
            target_y=target_y,
            settle=settle,
            flight=rng.uniform(0.20, 0.40, desired).astype(np.float32),
            sway=np.clip(rng.normal(0.0, 9.0, desired), -20.0, 20.0).astype(np.float32),
            phase=rng.uniform(0.0, np.pi * 2.0, desired).astype(np.float32),
            colors=self.analysis.source[targets[:, 0], targets[:, 1]],
        )

    def global_progress_at(self, seconds: float) -> float:
        """Return animation progress with configured opening and closing holds removed."""
        start = self.config.hold_start
        end = self.config.duration - self.config.hold_end
        if seconds <= start:
            return 0.0
        if seconds >= end:
            return 1.0
        return (seconds - start) / (end - start)

    def stage_stride(self) -> float:
        """Return the public spacing between layer starts for this effect."""
        if self.effect.supports(EffectCapability.STRICT_SEQUENCE):
            return 1.0
        return 1.0 - self.config.overlap

    def _stage_progress(self, global_progress: float, index: int) -> float:
        count = max(1, len(self.stages))
        stride = self.stage_stride()
        timeline = 1.0 + (count - 1) * stride
        linear = float(np.clip(global_progress * timeline - index * stride, 0.0, 1.0))
        return ease_in_out(linear)

    def _layer_progresses(self, global_progress: float) -> list[tuple[ColorLayer, float]]:
        result = [
            (layer, self._stage_progress(global_progress, index))
            for index, layer in enumerate(self.stages)
        ]
        if (
            self.analysis.outline
            and self.config.outline == "together"
            and not self.effect.supports(EffectCapability.OUTLINE_FINALE)
        ):
            result.append((self.analysis.outline, global_progress))
        return result

    def _draw_particles(
        self,
        frame: np.ndarray,
        particles: FallingParticles,
        progress: float,
    ) -> None:
        """Blend airborne pigment with a soft anti-aliased brush.

        Particles are deliberately translucent and vertically elongated. This
        avoids the isolated opaque pixels produced by point drawing while keeping
        their trajectories readable. The completed layer remains the exact source.
        """
        spawn = np.maximum(0.0, particles.settle - particles.flight)
        alive = (progress >= spawn) & (progress < particles.settle)
        if not np.any(alive):
            return
        denominator = np.maximum(particles.settle - spawn, 1e-5)
        phase_progress = np.clip((progress - spawn) / denominator, 0.0, 1.0)
        fall = phase_progress * phase_progress
        margin = self.height * 0.20
        current_y = -margin + (particles.target_y + margin) * fall
        stream_envelope = np.sin(np.pi * phase_progress)
        current_x = (
            particles.target_x
            + particles.sway * (1.0 - fall)
            + np.sin(particles.phase + phase_progress * np.pi * 2.0)
            * (2.0 + np.abs(particles.sway) * 0.08)
            * stream_envelope
        )
        indices = np.flatnonzero(alive)
        x = np.rint(current_x[indices]).astype(np.int32)
        y = np.rint(current_y[indices]).astype(np.int32)
        visible = (x >= 0) & (x < self.width) & (y >= 0) & (y < self.height)
        x, y, indices = x[visible], y[visible], indices[visible]
        if not len(indices):
            return

        grain_size = max(0.5, float(self.config.grain_size))
        sigma_x = max(0.58, grain_size * 0.48)
        sigma_y = max(1.05, grain_size * 1.05)
        radius_x = max(1, min(4, int(np.ceil(grain_size * 0.68))))
        radius_y = max(2, min(8, int(np.ceil(grain_size * 1.65))))
        colors = particles.colors[indices].astype(np.float32)
        life = phase_progress[indices]
        fade_in = np.clip(life / 0.16, 0.0, 1.0)
        fade_out = np.clip((1.0 - life) / 0.12, 0.0, 1.0)
        fade_in = fade_in * fade_in * (3.0 - 2.0 * fade_in)
        fade_out = fade_out * fade_out * (3.0 - 2.0 * fade_out)
        visibility = (fade_in * fade_out).astype(np.float32)

        for dy in range(-radius_y, radius_y + 1):
            for dx in range(-radius_x, radius_x + 1):
                distance = (dx / sigma_x) ** 2 + (dy / sigma_y) ** 2
                kernel_alpha = 0.74 * float(np.exp(-0.5 * distance))
                if kernel_alpha < 0.035:
                    continue
                nx, ny = x + dx, y + dy
                inside = (nx >= 0) & (nx < self.width) & (ny >= 0) & (ny < self.height)
                if not np.any(inside):
                    continue
                background = frame[ny[inside], nx[inside]].astype(np.float32)
                foreground = colors[inside]
                alpha = (kernel_alpha * visibility[inside])[:, None]
                frame[ny[inside], nx[inside]] = np.rint(
                    background * (1.0 - alpha) + foreground * alpha
                ).astype(np.uint8)

    def frame_at(self, seconds: float, presentation: str = "2d") -> np.ndarray:
        seconds = float(np.clip(seconds, 0.0, self.config.duration))
        global_progress = self.global_progress_at(seconds)
        if global_progress >= 1.0:
            return self.analysis.source.copy()
        composed = self.effect.create_frame(self.frame_context, global_progress)
        if composed is not None:
            return composed
        frame = self.blank.copy()
        layer_progresses = self._layer_progresses(global_progress)
        for layer, progress in layer_progresses:
            if progress <= 0.0:
                continue
            if progress >= 1.0:
                frame[layer.mask] = self.analysis.source[layer.mask]
                continue
            opacity = reveal_opacity(
                layer.mask,
                self.fields[layer.key],
                progress,
                self.config.soft_edge,
            )
            active = opacity > 0.0
            if np.any(active):
                alpha = opacity[active, None]
                foreground = self.analysis.source[active].astype(np.float32)
                background = frame[active].astype(np.float32)
                frame[active] = np.rint(background * (1.0 - alpha) + foreground * alpha).astype(
                    np.uint8
                )
            particles = self.particles.get(layer.key)
            if particles is not None:
                self._draw_particles(frame, particles, progress)
        if self.effect.supports(EffectCapability.FRAME_DECORATOR):
            states = tuple(
                LayerFrameState(
                    mask=layer.mask,
                    field=self.fields[layer.key],
                    progress=progress,
                    color=layer.color,
                    is_outline=layer.is_outline,
                )
                for layer, progress in layer_progresses
            )
            return self.effect.create_decoration(
                frame,
                FrameDecorationContext(
                    source=self.analysis.source,
                    config=self.config,
                    progress=global_progress,
                    layers=states,
                    presentation=presentation,
                ),
            )
        return frame

    @property
    def frame_count(self) -> int:
        return max(2, int(round(self.config.duration * self.config.fps)))

    def _studio_frame_at(self, seconds: float, presentation: str = "2d") -> np.ndarray:
        """Integrate three subframes over a cinematic 270° shutter."""
        shutter = 0.75 / self.config.fps
        offsets = np.linspace(-0.5, 0.5, 3, dtype=np.float32) * shutter
        return exposure_average(
            self.frame_at(
                float(np.clip(seconds + offset, 0.0, self.config.duration)),
                presentation=presentation,
            )
            for offset in offsets
        )

    def frames(self, presentation: str = "2d") -> Iterator[np.ndarray]:
        count = self.frame_count
        for index in range(count):
            seconds = self.config.duration * index / (count - 1)
            if self.config.quality == "studio" and 0 < index < count - 1:
                yield self._studio_frame_at(seconds, presentation=presentation)
            else:
                yield self.frame_at(seconds, presentation=presentation)


def render_video(
    input_path: str | Path,
    output_path: str | Path,
    config: RenderConfig | None = None,
    manifest_path: str | Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ArtworkAnalysis:
    selected_config = (config or RenderConfig()).validate()
    logger.info("Rendu demandé : %s -> %s", Path(input_path).resolve(), Path(output_path).resolve())
    analysis = analyze_artwork(input_path, selected_config)
    renderer = ArtworkRenderer(analysis, selected_config)
    from .video import encode_video

    encode_video(renderer, output_path, progress)
    if manifest_path:
        analysis.save_manifest(manifest_path, selected_config)
    logger.info("Rendu terminé : %s", Path(output_path).resolve())
    return analysis

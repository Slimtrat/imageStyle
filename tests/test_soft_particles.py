from __future__ import annotations

import numpy as np

from artanimate.core.config import RenderConfig
from artanimate.core.renderer import ArtworkRenderer, FallingParticles


def test_airborne_grain_is_soft_and_never_an_opaque_pixel_cross() -> None:
    renderer = ArtworkRenderer.__new__(ArtworkRenderer)
    renderer.width = 32
    renderer.height = 32
    renderer.config = RenderConfig(grain_size=0.5)
    particles = FallingParticles(
        target_x=np.array([16.0], dtype=np.float32),
        target_y=np.array([24.0], dtype=np.float32),
        settle=np.array([0.8], dtype=np.float32),
        flight=np.array([0.4], dtype=np.float32),
        sway=np.array([0.0], dtype=np.float32),
        phase=np.array([0.0], dtype=np.float32),
        colors=np.array([[220, 40, 20]], dtype=np.uint8),
    )
    frame = np.full((32, 32, 3), 255, dtype=np.uint8)

    renderer._draw_particles(frame, particles, progress=0.7)

    changed = np.any(frame != 255, axis=2)
    assert changed.sum() >= 5
    assert not np.any(np.all(frame == particles.colors[0], axis=2))
    assert len(np.unique(frame[changed], axis=0)) >= 2

from __future__ import annotations

import numpy as np

from types import SimpleNamespace

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


def test_sand_particles_form_dense_but_controlled_streams() -> None:
    renderer = ArtworkRenderer.__new__(ArtworkRenderer)
    renderer.config = RenderConfig(grain_density=0.004)
    renderer.analysis = SimpleNamespace(
        source=np.full((40, 60, 3), (180, 105, 55), dtype=np.uint8)
    )
    layer = SimpleNamespace(mask=np.ones((40, 60), dtype=bool))
    field = np.linspace(0.0, 1.0, 2400, dtype=np.float32).reshape(40, 60)

    particles = renderer._prepare_particles(layer, field, seed=17)

    assert particles is not None
    assert len(particles.target_x) == 180
    assert float(particles.flight.min()) >= 0.20
    assert float(particles.flight.max()) <= 0.40
    assert float(np.abs(particles.sway).max()) <= 20.0

import numpy as np
import pytest

from PySide6.QtGui import QColor, QImage

from artanimate.core.config import RenderConfig
from artanimate.desktop.studio3d_wave import (
    OrganicWaveGeometry,
    OrganicWaveSettings,
    pigment_density,
)


def test_organic_wave_settings_share_the_validated_render_configuration() -> None:
    config = RenderConfig(
        effect="wave",
        wave_amplitude=0.12,
        wave_frequency=4.2,
        turbulence=0.19,
        soft_edge=0.035,
        wave_density_contrast=0.82,
    )

    settings = OrganicWaveSettings.from_config(config)

    assert settings == OrganicWaveSettings(
        amplitude=pytest.approx(0.12),
        frequency=pytest.approx(4.2),
        turbulence=pytest.approx(0.19),
        soft_edge=pytest.approx(0.035),
        density_contrast=pytest.approx(0.82),
    )


def test_dark_and_cool_pigments_are_physically_denser() -> None:
    samples = np.array(
        [[0.95, 0.72, 0.28], [0.08, 0.12, 0.48]],
        dtype=np.float32,
    )
    densities = pigment_density(samples)
    assert densities[1] > densities[0]


def test_native_wave_geometry_rises_then_returns_to_an_exact_plane() -> None:
    geometry = OrganicWaveGeometry()
    source = QImage(96, 64, QImage.Format.Format_RGBA8888)
    source.fill(QColor("#2857d8"))
    geometry.set_source(source)
    geometry.configure(
        OrganicWaveSettings(amplitude=0.08, density_contrast=0.9),
        "left",
    )

    geometry.set_progress(0.5)
    assert geometry.maximum_height > 15.0
    geometry.set_progress(1.0)
    assert geometry.maximum_height == pytest.approx(0.0)


def test_wave_deposits_color_only_after_its_physical_crest() -> None:
    geometry = OrganicWaveGeometry()
    source = QImage(192, 96, QImage.Format.Format_ARGB32)
    source.fill(QColor("#e64232"))
    base = QImage(192, 96, QImage.Format.Format_ARGB32)
    base.fill(QColor("#101318"))
    geometry.set_source(source)
    geometry.configure(
        OrganicWaveSettings(amplitude=0.0, turbulence=0.0, soft_edge=0.012),
        "left",
    )
    geometry.set_progress(0.5)

    mask = geometry.deposit_mask()
    assert mask[:, :24].mean() > 245
    assert mask[:, 46:50].max() == 0
    assert mask[:, 66:].max() == 0

    deposited = geometry.composite_deposit(base, source)
    assert deposited.pixelColor(8, 48).red() > 200
    assert deposited.pixelColor(104, 48) == QColor("#101318")
    geometry.set_progress(1.0)
    final = geometry.composite_deposit(base, source)
    assert final.pixelColor(104, 48) == QColor("#e64232")


@pytest.mark.parametrize("contrast", [-0.01, 1.01])
def test_wave_density_contrast_rejects_values_outside_the_ui_contract(
    contrast: float,
) -> None:
    with pytest.raises(ValueError, match="wave_density_contrast"):
        RenderConfig(wave_density_contrast=contrast).validate()

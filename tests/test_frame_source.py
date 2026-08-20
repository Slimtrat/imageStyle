from pathlib import Path

from PIL import Image, ImageDraw

from artanimate.core.analysis import analyze_artwork
from artanimate.core.config import RenderConfig
from artanimate.core.frame_source import FrameSource
from artanimate.core.renderer import ArtworkRenderer


def test_artwork_renderer_implements_presentation_frame_source(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    image = Image.new("RGB", (64, 48), "white")
    ImageDraw.Draw(image).rectangle((8, 8, 55, 39), fill=(220, 80, 40))
    image.save(source)
    config = RenderConfig(
        width=64, fps=12, duration=1.0, hold_start=0.1, hold_end=0.1
    )
    analysis = analyze_artwork(source, config)
    renderer = ArtworkRenderer(analysis, config)

    assert isinstance(renderer, FrameSource)
    assert renderer.frame_count == 12
    assert (renderer.width, renderer.height) == (64, 48)

"""ArtAnimate public package."""

from .config import RenderConfig
from .renderer import ArtworkRenderer, render_video

__all__ = ["ArtworkRenderer", "RenderConfig", "render_video"]
__version__ = "1.0.0"

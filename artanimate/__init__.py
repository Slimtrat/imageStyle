"""ArtAnimate public package."""

from .core.config import RenderConfig
from .core.renderer import ArtworkRenderer, render_video

__all__ = ["ArtworkRenderer", "RenderConfig", "render_video"]
__version__ = "2.1.0"

from pathlib import Path

import numpy as np
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core.video import encode_video


class TinyRenderer:
    config = RenderConfig(width=64, duration=1.0, fps=2, hold_start=0.1, hold_end=0.1)
    width = 64
    height = 48
    frame_count = 2

    def frames(self):
        yield np.zeros((48, 64, 3), dtype=np.uint8)
        yield np.zeros((48, 64, 3), dtype=np.uint8)


def test_encoder_does_not_silently_recreate_missing_destination(tmp_path: Path) -> None:
    missing = tmp_path / "deleted" / "movie.mp4"

    with pytest.raises(FileNotFoundError, match="Dossier de destination introuvable"):
        encode_video(TinyRenderer(), missing)

    assert not missing.parent.exists()

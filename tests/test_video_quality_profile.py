from __future__ import annotations

from pathlib import Path

import numpy as np

from artanimate.core.config import RenderConfig
from artanimate.core import video


class _Renderer:
    width = 16
    height = 12
    frame_count = 1
    config = RenderConfig(width=64, duration=1, fps=12, quality="studio")

    def frames(self):
        yield np.zeros((self.height, self.width, 3), dtype=np.uint8)


class _Writer:
    def __init__(self, path: str):
        Path(path).write_bytes(b"encoded")

    def send(self, _frame) -> None:
        pass

    def close(self) -> None:
        pass


def test_studio_encoding_uses_animation_tuning(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def writer(path, *_args, **kwargs):
        captured.update(kwargs)
        return _Writer(path)

    monkeypatch.setattr(video.imageio_ffmpeg, "write_frames", writer)

    video.encode_video(_Renderer(), tmp_path / "studio.mp4")

    parameters = captured["output_params"]
    assert isinstance(parameters, list)
    assert parameters[parameters.index("-preset") + 1] == "slow"
    assert parameters[parameters.index("-tune") + 1] == "animation"
    assert parameters[parameters.index("-colorspace") + 1] == "bt709"

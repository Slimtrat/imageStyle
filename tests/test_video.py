from pathlib import Path

import numpy as np
import pytest

from artanimate.core.config import RenderConfig
from artanimate.core import video


class FakeRenderer:
    width = 16
    height = 12
    frame_count = 3
    config = RenderConfig(width=64, duration=3, fps=12)

    def frames(self):
        for value in (0, 80, 160):
            yield np.full((self.height, self.width, 3), value, dtype=np.uint8)


class FakeWriter:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.write_bytes(b"partial")
        self.frames = []
        self.closed = False

    def send(self, frame) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


def test_encoder_reports_frames_and_progress(tmp_path: Path, monkeypatch) -> None:
    writers = []

    def make_writer(path, *_args, **_kwargs):
        writer = FakeWriter(path)
        writers.append(writer)
        return writer

    monkeypatch.setattr(video.imageio_ffmpeg, "write_frames", make_writer)
    progress = []
    previews = []
    destination = tmp_path / "movie.mp4"
    result = video.encode_video(
        FakeRenderer(),
        destination,
        lambda done, total: progress.append((done, total)),
        frame_callback=lambda frame, done, total: previews.append((int(frame[0, 0, 0]), done, total)),
    )
    assert result == destination
    assert destination.read_bytes() == b"partial"
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert previews == [(0, 1, 3), (80, 2, 3), (160, 3, 3)]
    assert writers[0].closed


def test_encoder_cancellation_removes_partial_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        video.imageio_ffmpeg,
        "write_frames",
        lambda path, *_args, **_kwargs: FakeWriter(path),
    )
    destination = tmp_path / "cancelled.mp4"
    with pytest.raises(video.RenderCancelled):
        video.encode_video(FakeRenderer(), destination, should_cancel=lambda: True)
    assert not destination.exists()
    assert not (tmp_path / "cancelled.part.mp4").exists()

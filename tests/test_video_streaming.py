from pathlib import Path

import numpy as np
import pytest

from artanimate.core import video


class FakeStreamingWriter:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.write_bytes(b"encoded")
        self.frames: list[object] = []
        self.closed = False

    def send(self, frame: object) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


def test_streaming_encoder_accepts_external_3d_frames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writers: list[FakeStreamingWriter] = []

    def make_writer(path: str, *_args, **_kwargs) -> FakeStreamingWriter:
        writer = FakeStreamingWriter(path)
        writers.append(writer)
        return writer

    monkeypatch.setattr(video.imageio_ffmpeg, "write_frames", make_writer)
    destination = tmp_path / "studio3d.mp4"
    encoder = video.VideoFrameEncoder(
        destination,
        128,
        72,
        24,
        total_frames=2,
    )

    encoder.open()
    encoder.write(np.zeros((72, 128, 3), dtype=np.uint8))
    encoder.write(np.full((72, 128, 3), 180, dtype=np.uint8))
    result = encoder.finish()

    assert result == destination
    assert destination.read_bytes() == b"encoded"
    assert encoder.written_frames == 2
    assert writers[0].closed
    assert len(writers[0].frames) == 3  # handshake plus two RGB frames


def test_streaming_encoder_rejects_bad_frame_and_cleans_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        video.imageio_ffmpeg,
        "write_frames",
        lambda path, *_args, **_kwargs: FakeStreamingWriter(path),
    )
    destination = tmp_path / "broken.mp4"
    encoder = video.VideoFrameEncoder(destination, 128, 72, 24)
    encoder.open()

    with pytest.raises(ValueError, match="attendu"):
        encoder.write(np.zeros((70, 128, 3), dtype=np.uint8))
    encoder.abort()

    assert not destination.exists()
    assert not (tmp_path / "broken.part.mp4").exists()


def test_streaming_encoder_requires_even_dimensions(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="paires"):
        video.VideoFrameEncoder(tmp_path / "odd.mp4", 127, 72, 24)

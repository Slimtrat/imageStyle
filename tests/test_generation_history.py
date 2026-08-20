from pathlib import Path

from artanimate.core.config import RenderConfig
from artanimate.desktop.history import GenerationHistory


def test_history_persists_deduplicates_and_never_deletes_video(tmp_path: Path) -> None:
    output = tmp_path / "exports" / "artwork-sand.mp4"
    output.parent.mkdir()
    output.write_bytes(b"video")
    source = tmp_path / "artwork.png"
    source.write_bytes(b"image")
    history = GenerationHistory(tmp_path / "history", limit=4)

    first = history.add(output, source, RenderConfig(), "Sable")
    second = history.add(output, source, RenderConfig(seed=9), "Sable")
    records = history.load()

    assert first.id != second.id
    assert len(records) == 1
    assert records[0].config["seed"] == 9
    assert records[0].available
    assert history.remove(output)
    assert history.load() == ()
    assert output.read_bytes() == b"video"


def test_history_ignores_a_corrupt_manifest(tmp_path: Path) -> None:
    history = GenerationHistory(tmp_path / "history")
    history.root.mkdir()
    history.manifest_path.write_text("not json", encoding="utf-8")

    assert history.load() == ()

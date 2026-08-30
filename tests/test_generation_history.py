import json
from pathlib import Path

import pytest
from artanimate.core.config import RenderConfig
from artanimate.desktop.history import GenerationHistory, GenerationType


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


def test_history_ignores_a_non_object_manifest(tmp_path: Path) -> None:
    history = GenerationHistory(tmp_path / "history")
    history.root.mkdir()
    history.manifest_path.write_text("[]", encoding="utf-8")

    assert history.load() == ()


def test_history_cleans_new_thumbnail_when_manifest_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Thumbnail:
        def isNull(self) -> bool:
            return False

        def save(self, path: str, *_args) -> bool:
            Path(path).write_bytes(b"thumbnail")
            return True

    history = GenerationHistory(tmp_path / "history")
    monkeypatch.setattr(
        history,
        "_write",
        lambda _records: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        history.add_studio(
            tmp_path / "reel.mp4",
            tmp_path / "artwork.png",
            project_id="project",
            export_config={},
            thumbnail=Thumbnail(),
        )

    assert list(history.thumbnail_root.glob("*")) == []


def test_legacy_manifest_remains_readable_and_is_upgraded_on_studio_add(
    tmp_path: Path,
) -> None:
    root = tmp_path / "history"
    root.mkdir()
    old_output = tmp_path / "old.mp4"
    old_source = tmp_path / "old.png"
    old_output.write_bytes(b"video")
    old_source.write_bytes(b"image")
    (root / "history.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generations": [
                    {
                        "id": "legacy",
                        "created_at": "2026-01-02T03:04:05+01:00",
                        "output": str(old_output),
                        "source": str(old_source),
                        "effect": "sand",
                        "effect_label": "Sable",
                        "config": {"fps": 30},
                        "thumbnail": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    history = GenerationHistory(root)

    legacy = history.load()[0]

    assert legacy.generation_type == GenerationType.ATELIER_2D.value
    assert legacy.project_path is None
    studio_output = tmp_path / "reel.mp4"
    studio_output.write_bytes(b"studio-video")
    project = tmp_path / "reel.artanimate"
    project.write_text("{}", encoding="utf-8")
    added = history.add_studio(
        studio_output,
        old_source,
        project_id="project-123",
        export_config={"fps": 60, "audio_mode": "embedded"},
        project_path=project,
    )
    records = history.load()
    manifest = json.loads(history.manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert len(records) == 2
    assert records[0] == added
    assert added.is_studio_project
    assert added.project_available
    assert added.project_id == "project-123"
    assert added.config["audio_mode"] == "embedded"


def test_studio_history_deduplicates_without_owning_project_or_media(tmp_path: Path) -> None:
    output = tmp_path / "reel.mp4"
    source = tmp_path / "artwork.png"
    project = tmp_path / "reel.artanimate"
    media = tmp_path / "music.wav"
    for path in (output, source, project, media):
        path.write_bytes(path.name.encode())
    history = GenerationHistory(tmp_path / "history")

    history.add_studio(
        output, source, project_id="p", export_config={}, project_path=project
    )
    history.add_studio(
        output,
        source,
        project_id="p",
        export_config={"fps": 30},
        project_path=project,
    )

    assert len(history.load()) == 1
    assert history.remove(output)
    assert output.is_file()
    assert project.is_file()
    assert source.is_file()
    assert media.is_file()

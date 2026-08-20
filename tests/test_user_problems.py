import errno
from pathlib import Path

import pytest
from PIL import Image

from artanimate.desktop import problems
from artanimate.desktop.problems import (
    UserInputError,
    destination_reference_problem,
    source_reference_problem,
    translate_exception,
    validate_destination_path,
    validate_output_name,
    validate_source_path,
)


def test_missing_source_and_destination_explain_what_to_do(tmp_path: Path) -> None:
    source = source_reference_problem(tmp_path / "moved-artwork.png")
    destination = destination_reference_problem(tmp_path / "deleted-folder")

    assert source is not None and source.code == "source_not_found"
    assert "déplacée" in source.action
    assert destination is not None and destination.code == "destination_not_found"
    assert "choisissez" in destination.action.lower()
    assert "Que faire" in source.display_text


def test_corrupt_image_is_reported_as_an_image_problem(tmp_path: Path) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(b"this is not a png")

    with pytest.raises(UserInputError) as captured:
        validate_source_path(source)

    assert captured.value.problem.code == "source_unreadable"
    assert "PNG ou JPEG" in captured.value.problem.action


def test_destination_is_writable_and_probe_is_cleaned(tmp_path: Path) -> None:
    destination = tmp_path / "exports"
    destination.mkdir()

    assert validate_destination_path(destination) == destination.resolve()
    assert list(destination.iterdir()) == []


def test_low_disk_space_has_a_specific_recovery_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination = tmp_path / "exports"
    destination.mkdir()
    disk_usage = problems.shutil._ntuple_diskusage(  # type: ignore[attr-defined]
        1024 * 1024,
        1024 * 1024 - 1,
        1,
    )
    monkeypatch.setattr(problems.shutil, "disk_usage", lambda _path: disk_usage)

    with pytest.raises(UserInputError) as captured:
        validate_destination_path(destination)

    assert captured.value.problem.code == "destination_space"
    assert "autre disque" in captured.value.problem.action


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("", "output_name_missing"),
        ("../video.mp4", "output_name_path"),
        ("bad:name.mp4", "output_name_characters"),
        ("CON.mp4", "output_name_reserved"),
        ("video. ", "output_name_ending"),
    ],
)
def test_invalid_windows_names_are_explained(name: str, code: str) -> None:
    with pytest.raises(UserInputError) as captured:
        validate_output_name(name, ".mp4")

    assert captured.value.problem.code == code
    assert captured.value.problem.action


def test_technical_failures_are_translated() -> None:
    permission = translate_exception(PermissionError("locked"))
    disk_full = translate_exception(OSError(errno.ENOSPC, "full"))

    assert permission.title == "Accès refusé par Windows"
    assert disk_full.title == "Disque plein"
    assert "PermissionError" in permission.technical_details


def test_missing_destination_is_not_misattributed_to_the_source(tmp_path: Path) -> None:
    source = tmp_path / "artwork.png"
    Image.new("RGB", (8, 8), "red").save(source)
    destination = tmp_path / "deleted-output"

    problem = translate_exception(
        FileNotFoundError("gone"),
        "render",
        source=source,
        destination=destination,
    )

    assert problem.code == "destination_not_found"
    assert "dossier" in problem.message.lower()

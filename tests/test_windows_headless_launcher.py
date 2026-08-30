from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import artanimate.headless_studio as headless


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_launcher_routes_headless_studio_without_starting_the_desktop(monkeypatch) -> None:
    path = PROJECT_ROOT / "packaging" / "windows" / "launcher.py"
    spec = importlib.util.spec_from_file_location("artanimate_windows_headless_test", path)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["ArtAnimate.exe", "--headless-studio", "recipe.json", "project", "report.json"],
    )
    monkeypatch.setattr(
        headless,
        "write_headless_studio_report",
        lambda recipe, project, report: calls.append((recipe, project, report)) or 31,
    )

    assert launcher.main() == 31
    assert calls == [("recipe.json", "project", "report.json")]

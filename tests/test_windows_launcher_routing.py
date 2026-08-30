from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import artanimate.packaging_diagnostics as diagnostics
import artanimate.v3_qualification as qualification


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _launcher_module():
    path = PROJECT_ROOT / "packaging" / "windows" / "launcher.py"
    spec = importlib.util.spec_from_file_location("artanimate_windows_launcher_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_routes_self_test_without_starting_the_desktop(
    monkeypatch,
) -> None:
    launcher = _launcher_module()
    monkeypatch.setattr(sys, "argv", ["ArtAnimate.exe", "--self-test-report", "probe.json"])
    monkeypatch.setattr(diagnostics, "write_codec_self_test_report", lambda path: 17)

    assert launcher.main() == 17


def test_launcher_routes_v3_qualification_without_starting_the_desktop(
    monkeypatch,
) -> None:
    launcher = _launcher_module()
    monkeypatch.setattr(sys, "argv", ["ArtAnimate.exe", "--qualify-v3", "release"])
    monkeypatch.setattr(qualification, "write_v3_qualification_report", lambda path: 23)

    assert launcher.main() == 23

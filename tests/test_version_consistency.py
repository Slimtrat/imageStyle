from pathlib import Path
import tomllib

import artanimate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_cli_and_windows_metadata_share_the_release_version() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    cli = (PROJECT_ROOT / "artanimate" / "cli" / "main.py").read_text(encoding="utf-8")
    windows = (PROJECT_ROOT / "packaging" / "windows" / "version_info.txt").read_text(
        encoding="utf-8"
    )

    assert version == artanimate.__version__ == "2.6.0"
    assert f'ArtAnimate {version}' in cli
    assert f"'ProductVersion', '{version}'" in windows
    numeric = ", ".join(version.split(".")) + ", 0"
    assert f"filevers=({numeric})" in windows
    assert f"prodvers=({numeric})" in windows

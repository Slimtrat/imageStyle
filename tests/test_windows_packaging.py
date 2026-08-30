from pathlib import Path

from PIL import Image

from artanimate.packaging_diagnostics import REQUIRED_ENCODERS, run_codec_self_test


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = PROJECT_ROOT / "packaging" / "windows"


def test_windows_icon_contains_required_resolutions() -> None:
    with Image.open(WINDOWS_DIR / "artanimate.ico") as icon:
        sizes = icon.ico.sizes()

    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes


def test_windows_launcher_and_build_recipe_are_present() -> None:
    assert (WINDOWS_DIR / "launcher.py").is_file()
    assert (WINDOWS_DIR / "artanimate.spec").is_file()
    assert (WINDOWS_DIR / "build.ps1").is_file()
    assert (WINDOWS_DIR / "version_info.txt").is_file()


def test_windows_package_includes_studio_materials() -> None:
    material = PROJECT_ROOT / "artanimate" / "assets" / "materials" / "dark-walnut-v2.png"
    spec = (WINDOWS_DIR / "artanimate.spec").read_text(encoding="utf-8")

    assert material.is_file()
    assert "dark-walnut-v2.png" in spec
    assert "material_datas" in spec


def test_windows_package_collects_and_self_tests_bundled_codecs() -> None:
    spec = (WINDOWS_DIR / "artanimate.spec").read_text(encoding="utf-8")
    launcher = (WINDOWS_DIR / "launcher.py").read_text(encoding="utf-8")
    build = (WINDOWS_DIR / "build.ps1").read_text(encoding="utf-8")

    assert 'collect_all("imageio_ffmpeg")' in spec
    assert "--self-test-report" in launcher
    assert "ffmpeg_embedded" in build
    assert "desktop_startup.success" in build
    assert "build_seconds" in build
    assert "isolated_build_path" in build
    assert "$PythonExecutable" in build
    assert "$env:SystemRoot" in build


def test_local_codec_probe_round_trips_h264_and_lists_export_encoders() -> None:
    report = run_codec_self_test()

    assert report["success"]
    assert report["h264_round_trip"]
    assert set(report["encoders"]) == set(REQUIRED_ENCODERS)

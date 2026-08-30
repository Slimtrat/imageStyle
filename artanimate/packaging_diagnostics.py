from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any


REQUIRED_ENCODERS = ("libx264", "libvpx-vp9", "aac", "libopus")


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _bundled_in_frozen_app(executable: Path) -> bool:
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or bundle is None:
        return False
    try:
        executable.resolve().relative_to(Path(bundle).resolve())
    except ValueError:
        return False
    return True


def run_codec_self_test() -> dict[str, Any]:
    """Exercise the exact FFmpeg binary resolved by imageio inside the app."""

    import imageio_ffmpeg
    import numpy as np

    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve(strict=True)
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creation_flags(),
    )
    encoder_output = completed.stdout + completed.stderr
    missing = [name for name in REQUIRED_ENCODERS if name not in encoder_output]
    if missing:
        raise RuntimeError("Encodeurs FFmpeg absents : " + ", ".join(missing))

    with TemporaryDirectory(prefix="artanimate-codec-self-test-") as directory:
        video = Path(directory) / "probe.mp4"
        writer = imageio_ffmpeg.write_frames(
            str(video),
            (16, 16),
            fps=2,
            codec="libx264",
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            output_params=["-crf", "30", "-preset", "ultrafast", "-an"],
        )
        writer.send(None)
        try:
            for value in (32, 196):
                frame = np.full((16, 16, 3), value, dtype=np.uint8)
                writer.send(frame.tobytes())
        finally:
            writer.close()
        if not video.is_file() or video.stat().st_size <= 0:
            raise RuntimeError("La sonde H.264 n’a produit aucun fichier")
        reader = imageio_ffmpeg.read_frames(str(video), pix_fmt="rgb24")
        try:
            metadata = next(reader)
            decoded = next(reader)
        finally:
            reader.close()
        if tuple(metadata.get("size", ())) != (16, 16) or len(decoded) != 16 * 16 * 3:
            raise RuntimeError("La sonde H.264 embarquée n’est pas décodable")

    version = imageio_ffmpeg.get_ffmpeg_version()
    frozen = bool(getattr(sys, "frozen", False))
    embedded = _bundled_in_frozen_app(ffmpeg)
    if frozen and not embedded:
        raise RuntimeError("L’EXE utilise un FFmpeg extérieur au bundle")
    return {
        "success": True,
        "frozen": frozen,
        "ffmpeg_embedded": embedded,
        "ffmpeg_path": str(ffmpeg),
        "ffmpeg_version": version,
        "encoders": list(REQUIRED_ENCODERS),
        "h264_round_trip": True,
    }


def run_desktop_startup_self_test() -> dict[str, Any]:
    """Construct and close the real main window without entering its event loop."""

    from PySide6.QtWidgets import QApplication

    from artanimate.desktop.app import MainWindow

    application = QApplication.instance() or QApplication(
        ["ArtAnimate", "--packaged-self-test"]
    )
    with TemporaryDirectory(prefix="artanimate-ui-self-test-") as directory:
        window = MainWindow(history_root=Path(directory) / "history")
        application.processEvents()
        tab_count = window.workspace_tabs.count()
        studio_ready = window.studio_v3 is not None
        window.close()
        application.processEvents()
    if tab_count < 3 or not studio_ready:
        raise RuntimeError("La fenêtre principale n’a pas chargé tous ses espaces")
    return {
        "success": True,
        "main_window": True,
        "studio_workspace": True,
        "workspace_tabs": tab_count,
    }


def write_codec_self_test_report(path: str | Path) -> int:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        desktop_startup = run_desktop_startup_self_test()
        report = run_codec_self_test()
        report["desktop_startup"] = desktop_startup
        exit_code = 0
    except Exception as exc:
        report = {
            "success": False,
            "frozen": bool(getattr(sys, "frozen", False)),
            "error": f"{type(exc).__name__}: {exc}",
        }
        exit_code = 1
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return exit_code

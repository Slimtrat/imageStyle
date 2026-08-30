from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import wave
from typing import Any

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

from .core.config import RenderConfig
from .desktop.history import GenerationHistory
from .desktop.studio3d_bridge import Studio3DCaptureBridge
from .desktop.studio3d_renderer import ClassicStudio3DRenderer
from .desktop.studio_history_thumbnail import representative_video_thumbnail
from .packaging_diagnostics import run_codec_self_test
from .studio.assets import import_artwork_asset, import_media_asset
from .studio.audio import AudioClipSettings, AudioFadeCurve, add_audio_clip, update_audio_clip
from .studio.effect_2d import add_effect_clip
from .studio.export import export_studio_project, frame_digest
from .studio.manual_match import (
    ManualMatchSettings,
    add_manual_match,
    update_manual_match,
)
from .studio.model import (
    AssetKind,
    AudioExportMode,
    CameraAnimation,
    CameraKeyframe,
    CameraPose,
    Clip,
    ClipKind,
    Easing,
    ExportSettings,
    FitMode,
    MediaAsset,
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
)
from .studio.persistence import load_project, project_digest, save_project
from .studio.render_session import StudioRenderSession
from .studio.video import VideoClipSettings, VideoFrameSource, inspect_video


QUALIFICATION_REPORT = "ArtAnimate-v3-qualification.json"
CONTROL_FRAMES = (0, 72, 135, 210, 266, 285, 359)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_artwork(path: Path) -> None:
    width, height = 540, 960
    yy, xx = np.indices((height, width))
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    pixels[..., 0] = np.clip(22 + xx * 120 / width + yy * 25 / height, 0, 255)
    pixels[..., 1] = np.clip(28 + yy * 95 / height, 0, 255)
    pixels[..., 2] = np.clip(75 + (width - xx) * 100 / width, 0, 255)
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((62, 138, 478, 554), fill=(239, 86, 76, 215))
    draw.polygon(
        ((48, 770), (270, 365), (492, 770)),
        fill=(250, 205, 72, 220),
    )
    draw.rounded_rectangle(
        (130, 612, 410, 872),
        radius=42,
        fill=(40, 205, 174, 225),
        outline=(246, 245, 235, 245),
        width=8,
    )
    draw.line((70, 105, 470, 855), fill=(255, 255, 255, 185), width=12)
    image.save(path)


def _write_real_photo(path: Path) -> None:
    width, height = 540, 960
    yy, xx = np.indices((height, width))
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    pixels[..., 0] = np.clip(36 + yy * 90 / height, 0, 255)
    pixels[..., 1] = np.clip(48 + xx * 70 / width, 0, 255)
    pixels[..., 2] = np.clip(54 + yy * 55 / height, 0, 255)
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((42, 94, 498, 876), fill=(230, 218, 194, 255))
    draw.rectangle((69, 121, 471, 849), fill=(18, 22, 35, 255))
    draw.ellipse((108, 232, 432, 556), fill=(224, 82, 70, 240))
    draw.polygon(
        ((92, 735), (270, 418), (448, 735)),
        fill=(244, 192, 64, 235),
    )
    draw.rounded_rectangle(
        (155, 617, 385, 812),
        radius=34,
        fill=(42, 188, 163, 235),
        outline=(248, 242, 222, 240),
        width=7,
    )
    draw.rectangle((24, 70, 516, 900), outline=(118, 91, 55, 255), width=18)
    image.save(path)


def _write_music(path: Path, *, seconds: float = 14.0, sample_rate: int = 48_000) -> None:
    sample_count = int(round(seconds * sample_rate))
    samples = np.arange(sample_count, dtype=np.float64)
    envelope = np.minimum(1.0, samples / (sample_rate * 0.35))
    envelope *= np.minimum(1.0, (sample_count - samples) / (sample_rate * 0.5))
    tone = (
        np.sin(samples * (2.0 * math.pi * 220.0 / sample_rate)) * 0.33
        + np.sin(samples * (2.0 * math.pi * 330.0 / sample_rate)) * 0.16
        + np.sin(samples * (2.0 * math.pi * 440.0 / sample_rate)) * 0.08
    )
    pcm = np.round(np.clip(tone * envelope, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def create_qualification_media(root: str | Path) -> dict[str, Path]:
    destination = Path(root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    artwork = destination / "qualification-artwork.png"
    real_photo = destination / "qualification-real-photo.png"
    music = destination / "qualification-music.wav"
    _write_artwork(artwork)
    _write_real_photo(real_photo)
    _write_music(music)
    return {"artwork": artwork, "real_photo": real_photo, "music": music}


def build_v3_qualification_project(
    root: str | Path,
    *,
    width: int = 1080,
    height: int = 1920,
) -> tuple[StudioProject, Path, dict[str, Path]]:
    destination = Path(root).resolve()
    media = create_qualification_media(destination)
    project_path = destination / "qualification-reel.artanimate"
    base = StudioProject.new(media["artwork"], fps=30, duration_seconds=12)
    artwork = import_artwork_asset(media["artwork"], project_path)
    real_asset = import_media_asset(
        media["real_photo"],
        AssetKind.IMAGE,
        project_path,
        asset_id="qualification-real-photo",
    )
    audio_asset = import_media_asset(
        media["music"],
        AssetKind.AUDIO,
        project_path,
        asset_id="qualification-music",
    )
    establishing = Clip(
        "qualification-establishing",
        ClipKind.ARTWORK_2D,
        0,
        90,
        fit=FitMode.COVER,
        camera=CameraAnimation(
            (
                CameraKeyframe(0, CameraPose(x=0.48, y=0.50, zoom=1.0)),
                CameraKeyframe(
                    89,
                    CameraPose(x=0.52, y=0.48, zoom=1.16, rotation_degrees=-1.0),
                    Easing.EASE_IN_OUT,
                ),
            )
        ),
    )
    detail = Clip(
        "qualification-detail",
        ClipKind.ARTWORK_2D,
        90,
        90,
        fit=FitMode.COVER,
        camera=CameraAnimation(
            (
                CameraKeyframe(0, CameraPose(x=0.42, y=0.58, zoom=1.42)),
                CameraKeyframe(
                    89,
                    CameraPose(
                        x=0.59,
                        y=0.43,
                        zoom=1.78,
                        rotation_degrees=1.8,
                    ),
                    Easing.EASE_OUT,
                ),
            )
        ),
    )
    depth_config = RenderConfig(
        effect="sand",
        duration=3.3,
        fps=30,
        width=min(width, 540),
        hold_start=0.15,
        hold_end=0.25,
        quality="fast",
        seed=34,
    ).validate()
    depth = Clip(
        "qualification-depth",
        ClipKind.ARTWORK_3D,
        180,
        90,
        fit=FitMode.COVER,
        parameters={
            "schema_version": 1,
            "render_config": depth_config.to_dict(),
            "camera": {
                "yaw": 4.0,
                "pitch": -73.0,
                "distance": 610.0,
                "motion": "top_drift",
                "motion_strength": 0.68,
            },
            "lamp_brightness": 2.7,
            "lamp_motion": 0.36,
        },
    )
    real = Clip(
        "qualification-real",
        ClipKind.STILL,
        270,
        90,
        asset_id=real_asset.asset_id,
        fit=FitMode.COVER,
        parameters={
            "still": {
                "crop_x": 0.02,
                "crop_y": 0.01,
                "crop_width": 0.96,
                "crop_height": 0.98,
                "rotation_degrees": -0.35,
            }
        },
    )
    project = replace(
        base,
        project_id="artanimate-v3-packaged-qualification",
        artwork=artwork,
        settings=ProjectSettings(
            width=width,
            height=height,
            fps=30,
            duration_frames=360,
            background=(12, 13, 19),
        ),
        assets=(real_asset, audio_asset),
        tracks=(
            Track(
                "video-main",
                TrackKind.VIDEO,
                "Œuvre vers réel",
                (establishing, detail, depth, real),
            ),
            Track("effects-main", TrackKind.EFFECT, "Effets 2D"),
            Track("audio-main", TrackKind.AUDIO, "Musique"),
        ),
        transitions=(),
        export=ExportSettings(
            container="mp4",
            crf=18,
            quality="fast",
            audio_mode=AudioExportMode.REFERENCE,
        ),
    ).validate()
    effect_config = RenderConfig(
        effect="wave",
        duration=1.5,
        fps=30,
        width=min(width, 540),
        hold_start=0.1,
        hold_end=0.1,
        quality="fast",
        seed=33,
    ).validate()
    project, _effect = add_effect_clip(
        project,
        effect_config,
        start_frame=112,
        duration_seconds=1.5,
        intensity=0.82,
        opacity=0.9,
        target_clip_id=detail.clip_id,
    )
    project, match = add_manual_match(
        project,
        depth.clip_id,
        real.clip_id,
        duration_frames=18,
        easing=Easing.EASE_IN_OUT,
    )
    match_settings = ManualMatchSettings.from_transition(match)
    project = update_manual_match(
        project,
        match.transition_id,
        overlay_opacity=0.58,
        transform=replace(
            match_settings.transform,
            position_x=0.505,
            position_y=0.495,
            scale=0.965,
            rotation_degrees=0.8,
        ),
    )
    project, audio_clip = add_audio_clip(
        project,
        audio_asset.asset_id,
        start_frame=15,
        source_in_frame=30,
        duration_frames=315,
    )
    project, _audio_clip = update_audio_clip(
        project,
        audio_clip.clip_id,
        settings=AudioClipSettings(
            gain_db=-2.0,
            fade_in_frames=24,
            fade_out_frames=36,
            fade_in_curve=AudioFadeCurve.EQUAL_POWER,
            fade_out_curve=AudioFadeCurve.EQUAL_POWER,
        ),
    )
    return project.validate(), project_path, media


def qualification_scenario(project: StudioProject) -> dict[str, Any]:
    clips = tuple(clip for track in project.tracks for clip in track.clips)
    return {
        "resolution": [project.settings.width, project.settings.height],
        "fps": project.settings.fps,
        "duration_frames": project.settings.duration_frames,
        "duration_seconds": project.settings.duration_frames / project.settings.fps,
        "camera_shots": sum(
            1
            for clip in clips
            if clip.kind in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}
        ),
        "camera_keyframes": sum(
            len(clip.camera.keyframes) if clip.camera is not None else 0
            for clip in clips
        ),
        "effect_2d_clips": sum(clip.kind == ClipKind.EFFECT_2D for clip in clips),
        "artwork_3d_clips": sum(clip.kind == ClipKind.ARTWORK_3D for clip in clips),
        "real_image_clips": sum(clip.kind == ClipKind.STILL for clip in clips),
        "manual_matches": sum(item.kind.value == "match" for item in project.transitions),
        "audio_clips": sum(clip.kind == ClipKind.AUDIO for clip in clips),
        "audio_trimmed": any(
            clip.kind == ClipKind.AUDIO and clip.source_in_frame > 0 for clip in clips
        ),
    }


def _renderer(
    artwork_path: Path,
    project: StudioProject,
    bridge: Studio3DCaptureBridge,
) -> ClassicStudio3DRenderer:
    return ClassicStudio3DRenderer(
        artwork_path,
        fingerprint=project.artwork.fingerprint,
        capture_port=bridge,
    )


def _render_controls(
    project: StudioProject,
    artwork_path: Path,
    project_path: Path,
    bridge: Studio3DCaptureBridge,
) -> tuple[dict[int, np.ndarray], str]:
    with StudioRenderSession(
        project,
        artwork_path,
        resource_base=project_path.parent,
        extra_renderers=(_renderer(artwork_path, project, bridge),),
    ) as session:
        frames = {
            index: np.ascontiguousarray(session.frame_at(index)).copy()
            for index in CONTROL_FRAMES
        }
        return frames, session.execution_mode


def _video_source(path: Path, fps: int) -> VideoFrameSource:
    inspection = inspect_video(path, count_frames=True)
    asset = MediaAsset(
        "qualification-export",
        AssetKind.VIDEO,
        str(path),
        width=inspection.width,
        height=inspection.height,
        metadata={
            "native_frame_count": inspection.native_frame_count,
            "native_fps": inspection.native_fps,
        },
    )
    return VideoFrameSource(
        asset,
        path,
        fps,
        VideoClipSettings(),
        max_cache_frames=2,
    )


def _decode_controls(path: Path, fps: int) -> dict[int, np.ndarray]:
    source = _video_source(path, fps)
    try:
        return {
            index: np.ascontiguousarray(source.frame_at(index)).copy()
            for index in CONTROL_FRAMES
        }
    finally:
        source.close()


def _comparison(expected: np.ndarray, actual: np.ndarray) -> dict[str, Any]:
    if expected.shape != actual.shape:
        return {
            "shape_equal": False,
            "expected_shape": list(expected.shape),
            "actual_shape": list(actual.shape),
            "passed": False,
        }
    delta = np.abs(expected.astype(np.int16) - actual.astype(np.int16))
    mae = float(np.mean(delta))
    percentile_99 = float(np.percentile(delta, 99))
    return {
        "shape_equal": True,
        "mae": round(mae, 4),
        "p99": round(percentile_99, 4),
        "max": int(np.max(delta)),
        "passed": mae <= 12.0 and percentile_99 <= 48.0,
    }


def _audio_probe(path: Path) -> dict[str, Any]:
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "2",
        "-ar",
        "48000",
        "pipe:1",
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        check=False,
    )
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    finite = samples[np.isfinite(samples)]
    return {
        "stream_present": completed.returncode == 0 and finite.size > 0,
        "decoder_exit_code": completed.returncode,
        "sample_values": int(finite.size),
        "peak": round(float(np.max(np.abs(finite))), 6) if finite.size else 0.0,
    }


def _export_record(path: Path, result: Any, audio: dict[str, Any]) -> dict[str, Any]:
    inspection = inspect_video(path, count_frames=True)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "width": inspection.width,
        "height": inspection.height,
        "native_fps": inspection.native_fps,
        "native_frame_count": inspection.native_frame_count,
        "rendered_frame_count": result.frame_count,
        "first_frame_digest": result.first_frame_digest,
        "last_frame_digest": result.last_frame_digest,
        "audio_mode": result.audio_mode.value,
        "audio_sample_count": result.audio_sample_count,
        "audio_probe": audio,
    }


def _thumbnail(frame: np.ndarray, width: int = 180) -> Image.Image:
    image = Image.fromarray(frame)
    height = max(1, int(round(image.height * width / image.width)))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _contact_sheet(
    path: Path,
    preview: dict[int, np.ndarray],
    reopened: dict[int, np.ndarray],
    reference: dict[int, np.ndarray],
    embedded: dict[int, np.ndarray],
) -> None:
    columns = (
        ("Aperçu", preview),
        ("Réouvert", reopened),
        ("Référence", reference),
        ("Audio intégré", embedded),
    )
    cell_width = 180
    first = _thumbnail(preview[CONTROL_FRAMES[0]], cell_width)
    cell_height = first.height
    label_height = 28
    sheet = Image.new(
        "RGB",
        (cell_width * len(columns), (cell_height + label_height) * len(CONTROL_FRAMES)),
        (16, 17, 22),
    )
    draw = ImageDraw.Draw(sheet)
    for row, frame_index in enumerate(CONTROL_FRAMES):
        top = row * (cell_height + label_height)
        for column, (name, frames) in enumerate(columns):
            left = column * cell_width
            thumb = _thumbnail(frames[frame_index], cell_width)
            sheet.paste(thumb, (left, top + label_height))
            draw.text(
                (left + 7, top + 8),
                f"{name} · f{frame_index}",
                fill=(239, 239, 243),
            )
    sheet.save(path, quality=94)


def _history_check(
    root: Path,
    project: StudioProject,
    project_path: Path,
    artwork_path: Path,
    reference_path: Path,
    embedded_path: Path,
) -> dict[str, Any]:
    history = GenerationHistory(root)
    reference_thumbnail = representative_video_thumbnail(reference_path, 360)
    embedded_thumbnail = representative_video_thumbnail(embedded_path, 360)
    if reference_thumbnail is None or embedded_thumbnail is None:
        raise RuntimeError("Les exports ne peuvent pas être relus pour l’historique")
    history.add_studio(
        reference_path,
        artwork_path,
        project_id=project.project_id,
        project_path=project_path,
        export_config={"audio_mode": AudioExportMode.REFERENCE.value},
        thumbnail=reference_thumbnail,
    )
    history.add_studio(
        embedded_path,
        artwork_path,
        project_id=project.project_id,
        project_path=project_path,
        export_config={"audio_mode": AudioExportMode.EMBEDDED.value},
        thumbnail=embedded_thumbnail,
    )
    records = history.load()
    return {
        "record_count": len(records),
        "outputs_available": all(item.available for item in records),
        "projects_available": all(item.project_available for item in records),
        "thumbnails_available": all(
            item.thumbnail_path is not None and item.thumbnail_path.is_file()
            for item in records
        ),
        "output_paths": [str(item.output_path) for item in records],
    }


def run_v3_qualification(
    output_dir: str | Path,
    *,
    require_frozen: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication(
        ["ArtAnimate", "--qualify-v3"]
    )
    codec = run_codec_self_test()
    if require_frozen and not codec["frozen"]:
        raise RuntimeError("La qualification finale doit être exécutée depuis ArtAnimate.exe")
    if require_frozen and not codec["ffmpeg_embedded"]:
        raise RuntimeError("La qualification utilise un FFmpeg extérieur à l’EXE")

    project, project_path, media = build_v3_qualification_project(root)
    scenario = qualification_scenario(project)
    expected_scenario = {
        "resolution": [1080, 1920],
        "fps": 30,
        "duration_frames": 360,
        "duration_seconds": 12.0,
        "camera_shots": 3,
        "camera_keyframes": 4,
        "effect_2d_clips": 1,
        "artwork_3d_clips": 1,
        "real_image_clips": 1,
        "manual_matches": 1,
        "audio_clips": 1,
        "audio_trimmed": True,
    }
    if scenario != expected_scenario:
        raise AssertionError(f"Scénario V3 incomplet : {scenario}")

    bridge = Studio3DCaptureBridge(max_surfaces=1)
    try:
        before_frames, before_mode = _render_controls(
            project, media["artwork"], project_path, bridge
        )
        if before_mode != "semantic":
            raise AssertionError("L’aperçu de qualification n’utilise pas le pipeline sémantique")
        before_digest = project_digest(project)
        save_project(project, project_path)
        reopened = load_project(project_path)
        reopened_digest = project_digest(reopened)
        reopened_frames, reopened_mode = _render_controls(
            reopened, media["artwork"], project_path, bridge
        )
        reopened_comparisons = [
            {
                "frame": index,
                "exact": np.array_equal(before_frames[index], reopened_frames[index]),
                **_comparison(before_frames[index], reopened_frames[index]),
            }
            for index in CONTROL_FRAMES
        ]
        persistence_checks = {
            "before_digest": before_digest,
            "reopened_digest": reopened_digest,
            "project_equal": reopened == project,
            "digest_equal": reopened_digest == before_digest,
            "preview_execution_mode": before_mode,
            "reopened_execution_mode": reopened_mode,
            "control_frames_exact": all(
                item["exact"] for item in reopened_comparisons
            ),
            "control_frames_within_tolerance": all(
                item["passed"] for item in reopened_comparisons
            ),
            "control_frame_comparisons": reopened_comparisons,
        }
        if not all(
            (
                persistence_checks["project_equal"],
                persistence_checks["digest_equal"],
                persistence_checks["control_frames_within_tolerance"],
                reopened_mode == "semantic",
            )
        ):
            raise AssertionError(f"Réouverture visuellement divergente : {persistence_checks}")

        reference_project = replace(
            reopened,
            export=replace(reopened.export, audio_mode=AudioExportMode.REFERENCE),
        ).validate()
        embedded_project = replace(
            reopened,
            export=replace(reopened.export, audio_mode=AudioExportMode.EMBEDDED),
        ).validate()
        reference_path = root / "qualification-reference.mp4"
        embedded_path = root / "qualification-audio-integre.mp4"
        reference_result = export_studio_project(
            reference_project,
            media["artwork"],
            reference_path,
            resource_base=project_path.parent,
            extra_renderers=(_renderer(media["artwork"], reference_project, bridge),),
        )
        embedded_result = export_studio_project(
            embedded_project,
            media["artwork"],
            embedded_path,
            resource_base=project_path.parent,
            extra_renderers=(_renderer(media["artwork"], embedded_project, bridge),),
        )
        reference_frames = _decode_controls(reference_path, reopened.settings.fps)
        embedded_frames = _decode_controls(embedded_path, reopened.settings.fps)
        controls: list[dict[str, Any]] = []
        for index in CONTROL_FRAMES:
            reference_comparison = _comparison(reopened_frames[index], reference_frames[index])
            embedded_comparison = _comparison(reopened_frames[index], embedded_frames[index])
            modes_comparison = _comparison(reference_frames[index], embedded_frames[index])
            controls.append(
                {
                    "frame": index,
                    "preview_digest": frame_digest(before_frames[index]),
                    "reopened_digest": frame_digest(reopened_frames[index]),
                    "preview_reopened_exact": np.array_equal(
                        before_frames[index], reopened_frames[index]
                    ),
                    "reference": reference_comparison,
                    "embedded": embedded_comparison,
                    "export_modes": modes_comparison,
                }
            )
        if not all(
            item[mode]["passed"]
            for item in controls
            for mode in ("reference", "embedded", "export_modes")
        ):
            raise AssertionError("Un export diffère excessivement de l’aperçu")
        if len({item["preview_digest"] for item in controls}) < 5:
            raise AssertionError("Les frames de contrôle ne couvrent pas assez d’états visuels")

        reference_audio = _audio_probe(reference_path)
        embedded_audio = _audio_probe(embedded_path)
        if reference_audio["stream_present"]:
            raise AssertionError("Le mode référence contient une piste audio inattendue")
        if not embedded_audio["stream_present"] or embedded_audio["peak"] <= 0.01:
            raise AssertionError("Le mode audio intégré ne contient pas de musique audible")

        sheet_path = root / "qualification-controles-visuels.jpg"
        _contact_sheet(
            sheet_path,
            before_frames,
            reopened_frames,
            reference_frames,
            embedded_frames,
        )
        history = _history_check(
            root / "history",
            reopened,
            project_path,
            media["artwork"],
            reference_path,
            embedded_path,
        )
        if not all(
            (
                history["record_count"] == 2,
                history["outputs_available"],
                history["projects_available"],
                history["thumbnails_available"],
            )
        ):
            raise AssertionError(f"Historique Studio incomplet : {history}")

        report = {
            "success": True,
            "qualification": "ArtAnimate V3 · Reel complet packagé",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "runtime": {
                "frozen": bool(getattr(sys, "frozen", False)),
                "executable": str(Path(sys.executable).resolve()),
                "python_process_spawned": False,
                "network_required": False,
                "codec": codec,
            },
            "scenario": scenario,
            "persistence": persistence_checks,
            "control_frames": controls,
            "exports": {
                "reference": _export_record(
                    reference_path, reference_result, reference_audio
                ),
                "embedded": _export_record(
                    embedded_path, embedded_result, embedded_audio
                ),
            },
            "history": history,
            "artifacts": {
                "project": str(project_path),
                "artwork": str(media["artwork"]),
                "real_photo": str(media["real_photo"]),
                "music": str(media["music"]),
                "visual_contact_sheet": str(sheet_path),
            },
            "visual_qa": {
                "automated_pixel_comparison": "passed",
                "contact_sheet_generated": True,
                "human_review": "documented in docs/studio-v3-qualification.md",
            },
        }
        application.processEvents()
        return report
    finally:
        bridge.close()
        application.processEvents()


def write_v3_qualification_report(output_dir: str | Path) -> int:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / QUALIFICATION_REPORT
    started = time.perf_counter()
    try:
        report = run_v3_qualification(root, require_frozen=True)
        exit_code = 0
    except BaseException as exc:
        report = {
            "success": False,
            "qualification": "ArtAnimate V3 · Reel complet packagé",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "runtime": {
                "frozen": bool(getattr(sys, "frozen", False)),
                "executable": str(Path(sys.executable).resolve()),
            },
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    _atomic_json(report_path, report)
    return exit_code

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .studio.assets import resolve_asset_path
from .studio.export import StudioExportResult, export_studio_project, frame_digest
from .studio.model import ClipKind, StudioProject, TrackKind
from .studio.persistence import project_digest
from .studio.recipe import RecipeBuildResult, StudioRecipe, build_portable_project
from .studio.render_session import StudioRenderSession


HEADLESS_REPORT_SCHEMA_VERSION = 1


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_output_path(output: Path, value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} doit rester relatif au dossier de projet")
    resolved = (output / candidate).resolve(strict=False)
    try:
        resolved.relative_to(output.resolve(strict=False))
    except ValueError as exc:
        raise ValueError(f"{label} sort du dossier de projet") from exc
    return resolved


def _requested_output(
    output: Path,
    override: str | Path | None,
    recipe_value: str | None,
    label: str,
) -> Path | None:
    if override is not None:
        candidate = Path(override)
        return (
            candidate.resolve(strict=False)
            if candidate.is_absolute()
            else (Path.cwd() / candidate).resolve(strict=False)
        )
    if recipe_value is None:
        return None
    return _portable_output_path(output, recipe_value, label)


def representative_frames(project: StudioProject, maximum: int = 9) -> tuple[int, ...]:
    candidates = {0, project.settings.duration_frames - 1}
    for track in project.tracks:
        if track.kind != TrackKind.VIDEO:
            continue
        for clip in track.clips:
            candidates.add(clip.start_frame)
            candidates.add(min(clip.end_frame - 1, clip.start_frame + clip.duration_frames // 2))
    for transition in project.transitions:
        candidates.add(transition.start_frame)
        candidates.add(
            min(
                project.settings.duration_frames - 1,
                transition.start_frame + transition.duration_frames // 2,
            )
        )
        candidates.add(
            min(
                project.settings.duration_frames - 1,
                transition.start_frame + transition.duration_frames - 1,
            )
        )
    ordered = sorted(index for index in candidates if 0 <= index < project.settings.duration_frames)
    if len(ordered) <= maximum:
        return tuple(ordered)
    selected = {
        ordered[round(index * (len(ordered) - 1) / (maximum - 1))]
        for index in range(maximum)
    }
    return tuple(sorted(selected))


def _proxy_size(project: StudioProject, width: int) -> tuple[int, int]:
    width = max(64, int(width))
    if width % 2:
        width += 1
    height = max(64, int(round(width * project.settings.height / project.settings.width)))
    if height % 2:
        height += 1
    return width, height


def _has_3d(project: StudioProject) -> bool:
    return any(
        clip.kind == ClipKind.ARTWORK_3D
        for track in project.tracks
        for clip in track.clips
    )


class _RenderEnvironment:
    def __init__(self, project: StudioProject, artwork_path: Path) -> None:
        self.project = project
        self.artwork_path = artwork_path
        self.application: Any = None
        self.bridge: Any = None
        self.renderers: tuple[Any, ...] = ()

    def __enter__(self) -> _RenderEnvironment:
        if not _has_3d(self.project):
            return self
        from PySide6.QtWidgets import QApplication

        from .desktop.studio3d_bridge import Studio3DCaptureBridge
        from .desktop.studio3d_renderer import ClassicStudio3DRenderer

        self.application = QApplication.instance() or QApplication(
            ["ArtAnimate", "--headless-studio"]
        )
        self.bridge = Studio3DCaptureBridge(max_surfaces=1)
        self.renderers = (
            ClassicStudio3DRenderer(
                self.artwork_path,
                fingerprint=self.project.artwork.fingerprint,
                capture_port=self.bridge,
            ),
        )
        return self

    def __exit__(self, *_args: object) -> None:
        if self.bridge is not None:
            self.bridge.close()


def _contact_sheet(path: Path, frames: dict[int, np.ndarray], fps: int) -> None:
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("La planche de contrôle doit être .jpg, .png ou .webp")
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(frames.items())
    if not ordered:
        raise ValueError("Aucune frame disponible pour la planche de contrôle")
    columns = min(3, len(ordered))
    rows = (len(ordered) + columns - 1) // columns
    first = Image.fromarray(ordered[0][1])
    label_height = 28
    sheet = Image.new(
        "RGB",
        (first.width * columns, (first.height + label_height) * rows),
        (15, 16, 21),
    )
    draw = ImageDraw.Draw(sheet)
    for position, (frame_index, frame) in enumerate(ordered):
        row, column = divmod(position, columns)
        left = column * first.width
        top = row * (first.height + label_height)
        image = Image.fromarray(frame)
        sheet.paste(image, (left, top + label_height))
        seconds = frame_index / fps
        draw.text(
            (left + 8, top + 8),
            f"f{frame_index:04d}  {seconds:05.2f}s",
            fill=(240, 240, 244),
        )
    save_options = {"quality": 92} if path.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
    sheet.save(path, **save_options)


def render_control_sheet(
    result: RecipeBuildResult,
    destination: str | Path,
    *,
    width: int,
    environment: _RenderEnvironment,
) -> dict[str, Any]:
    path = Path(destination).resolve(strict=False)
    proxy_width, proxy_height = _proxy_size(result.project, width)
    indexes = representative_frames(result.project)
    with StudioRenderSession(
        result.project,
        environment.artwork_path,
        output_width=proxy_width,
        output_height=proxy_height,
        resource_base=result.project_path.parent,
        extra_renderers=environment.renderers,
    ) as session:
        frames = {
            index: np.ascontiguousarray(session.frame_at(index)).copy()
            for index in indexes
        }
        execution_mode = session.execution_mode
    _contact_sheet(path, frames, result.project.settings.fps)
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "proxy_resolution": [proxy_width, proxy_height],
        "frames": [
            {"index": index, "digest": frame_digest(frames[index])}
            for index in indexes
        ],
        "execution_mode": execution_mode,
    }


def _export(
    result: RecipeBuildResult,
    destination: Path,
    environment: _RenderEnvironment,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    exported: StudioExportResult = export_studio_project(
        result.project,
        environment.artwork_path,
        destination,
        resource_base=result.project_path.parent,
        extra_renderers=environment.renderers,
    )
    return {
        **asdict(exported),
        "path": str(exported.path),
        "audio_mode": exported.audio_mode.value,
        "sha256": _sha256_file(exported.path),
        "size_bytes": exported.path.stat().st_size,
    }


def run_headless_studio(
    recipe_path: str | Path,
    output_directory: str | Path,
    report_path: str | Path,
    *,
    control_sheet: str | Path | None = None,
    export: str | Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    source = Path(recipe_path).resolve(strict=False)
    output = Path(output_directory).resolve(strict=False)
    result = build_portable_project(source, output)
    portable_recipe = StudioRecipe.from_path(result.recipe_path)
    control_path = _requested_output(
        output,
        control_sheet,
        portable_recipe.outputs.control_sheet,
        "recipe.outputs.control_sheet",
    )
    export_path = _requested_output(
        output,
        export,
        portable_recipe.outputs.export,
        "recipe.outputs.export",
    )
    artwork_path = resolve_asset_path(result.project.artwork.path, result.project_path)
    controls_record: dict[str, Any] | None = None
    export_record: dict[str, Any] | None = None
    with ExitStack() as stack:
        environment = stack.enter_context(_RenderEnvironment(result.project, artwork_path))
        if control_path is not None:
            controls_record = render_control_sheet(
                result,
                control_path,
                width=portable_recipe.outputs.control_width,
                environment=environment,
            )
        if export_path is not None:
            export_record = _export(result, export_path, environment)
    assets = sorted(
        path.relative_to(output).as_posix()
        for path in result.assets_directory.rglob("*")
        if path.is_file()
    )
    report = {
        "schema_version": HEADLESS_REPORT_SCHEMA_VERSION,
        "success": True,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "source_recipe": str(source),
        "output_directory": str(output),
        "project": {
            "path": str(result.project_path),
            "digest": project_digest(result.project),
            "id": result.project.project_id,
            "changed": result.changed,
            "snapshot": str(result.snapshot_path) if result.snapshot_path is not None else None,
            "assets": assets,
            "artwork_preparation": result.artwork_preparation,
            "duration_frames": result.project.settings.duration_frames,
            "fps": result.project.settings.fps,
            "resolution": [result.project.settings.width, result.project.settings.height],
        },
        "controls": controls_record,
        "export": export_record,
    }
    _atomic_json(Path(report_path).resolve(strict=False), report)
    return report


def write_headless_studio_report(
    recipe_path: str | Path,
    output_directory: str | Path,
    report_path: str | Path,
    *,
    control_sheet: str | Path | None = None,
    export: str | Path | None = None,
) -> int:
    destination = Path(report_path).resolve(strict=False)
    started = time.perf_counter()
    try:
        report = run_headless_studio(
            recipe_path,
            output_directory,
            destination,
            control_sheet=control_sheet,
            export=export,
        )
    except Exception as exc:
        report = {
            "schema_version": HEADLESS_REPORT_SCHEMA_VERSION,
            "success": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "source_recipe": str(Path(recipe_path).resolve(strict=False)),
            "output_directory": str(Path(output_directory).resolve(strict=False)),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        _atomic_json(destination, report)
        print(f"Studio headless en échec : {exc}")
        print(f"Rapport : {destination}")
        return 2
    project = report["project"]
    state = "mis à jour" if project["changed"] else "inchangé"
    print(f"Projet Studio {state} : {project['path']}")
    if report["controls"] is not None:
        print(f"Contrôles visuels : {report['controls']['path']}")
    if report["export"] is not None:
        print(f"Export : {report['export']['path']}")
    print(f"Rapport : {destination}")
    return 0

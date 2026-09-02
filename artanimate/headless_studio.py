from __future__ import annotations

from contextlib import ExitStack
from collections.abc import Mapping
from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .studio.assets import resolve_asset_path
from .studio.color_fidelity import (
    ArtworkColorPolicy,
    FAITHFUL_MEDIAN_DELTA_E00,
    FAITHFUL_P95_DELTA_E00,
)
from .studio.eyelids import EyelidGeometry
from .studio.export import StudioExportResult, export_studio_project, frame_digest
from .studio.model import ClipKind, StudioProject, TrackKind
from .studio.persistence import project_digest
from .studio.recipe import RecipeBuildResult, StudioRecipe, build_portable_project
from .studio.render_session import StudioRenderSession
from .studio.semantic_projection import (
    blink_amount,
    compose_blink,
    project_canonical_mask,
)
from .studio.spatial_match import SpatialMatchSettings


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


def representative_frames(project: StudioProject, maximum: int = 12) -> tuple[int, ...]:
    candidates = {0, project.settings.duration_frames - 1}
    semantic_moments: set[int] = set()
    for invocation in project.invocations:
        if invocation.capability_id != "region.blink":
            continue
        close_frames = int(invocation.parameters.get("close_frames", 6))
        moments = {
            invocation.start_frame,
            invocation.start_frame + max(0, close_frames - 1),
            invocation.end_frame - 1,
        }
        semantic_moments.update(moments)
        candidates.update(moments)
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
    selected = {0, project.settings.duration_frames - 1}
    for index in sorted(semantic_moments):
        if len(selected) >= maximum:
            break
        if 0 <= index < project.settings.duration_frames:
            selected.add(index)
    remaining = maximum - len(selected)
    available = [index for index in ordered if index not in selected]
    if remaining > 0 and available:
        selected.update(
            available[round(index * (len(available) - 1) / max(1, remaining - 1))]
            for index in range(remaining)
        )
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


def _project_with_color_mode(
    project: StudioProject,
    mode: str,
) -> tuple[StudioProject, int] | None:
    tracks = list(project.tracks)
    for track_index, track in enumerate(tracks):
        for clip_index, clip in enumerate(track.clips):
            if clip.kind != ClipKind.ARTWORK_3D:
                continue
            parameters = dict(clip.parameters or {})
            parameters["color_policy"] = ArtworkColorPolicy.from_mapping(mode).to_dict()
            clips = list(track.clips)
            clips[clip_index] = replace(clip, parameters=parameters)
            tracks[track_index] = replace(track, clips=tuple(clips))
            return (
                replace(project, tracks=tuple(tracks)).validate(),
                clip.end_frame - 1,
            )
    return None


def _project_color_policies(project: StudioProject) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for track in project.tracks:
        for clip in track.clips:
            if clip.kind != ClipKind.ARTWORK_3D:
                continue
            parameters = clip.parameters or {}
            policy = ArtworkColorPolicy.from_mapping(parameters.get("color_policy"))
            records.append({"clip_id": clip.clip_id, "policy": policy.to_dict()})
    return records


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


def _color_comparison_sheet(
    path: Path,
    integrated: np.ndarray,
    faithful: np.ndarray,
    frame_index: int,
    fps: int,
) -> None:
    label_height = 48
    height, width = faithful.shape[:2]
    sheet = Image.new("RGB", (width * 2, height + label_height), (15, 16, 21))
    sheet.paste(Image.fromarray(integrated), (0, label_height))
    sheet.paste(Image.fromarray(faithful), (width, label_height))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), "AVANT · LUMIÈRE 3D", fill=(240, 208, 176))
    draw.text((width + 10, 8), "APRÈS · COULEURS FIDÈLES", fill=(202, 246, 224))
    draw.text(
        (10, 28),
        f"même œuvre · même caméra · f{frame_index:04d} · {frame_index / fps:05.2f}s",
        fill=(176, 181, 193),
    )
    options = (
        {"quality": 94}
        if path.suffix.lower() in {".jpg", ".jpeg", ".webp"}
        else {}
    )
    sheet.save(path, **options)


def _render_color_comparison(
    result: RecipeBuildResult,
    path: Path,
    *,
    width: int,
    height: int,
    environment: _RenderEnvironment,
) -> dict[str, Any] | None:
    faithful = _project_with_color_mode(result.project, "faithful")
    integrated = _project_with_color_mode(result.project, "scene_integrated")
    if faithful is None or integrated is None:
        return None
    faithful_project, frame_index = faithful
    integrated_project, _ = integrated
    rendered: dict[str, np.ndarray] = {}
    for mode, project in (
        ("scene_integrated", integrated_project),
        ("faithful", faithful_project),
    ):
        with StudioRenderSession(
            project,
            environment.artwork_path,
            output_width=width,
            output_height=height,
            resource_base=result.project_path.parent,
            extra_renderers=environment.renderers,
        ) as session:
            rendered[mode] = np.ascontiguousarray(session.frame_at(frame_index)).copy()
    _color_comparison_sheet(
        path,
        rendered["scene_integrated"],
        rendered["faithful"],
        frame_index,
        result.project.settings.fps,
    )
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "frame_index": frame_index,
        "modes": ["scene_integrated", "faithful"],
        "acceptance": {
            "median_delta_e00_max": FAITHFUL_MEDIAN_DELTA_E00,
            "percentile_95_delta_e00_max": FAITHFUL_P95_DELTA_E00,
            "artist_review": "pending",
        },
    }


def _eye_crop(
    image: np.ndarray,
    alpha: np.ndarray,
    *,
    width: int = 300,
    height: int = 220,
) -> Image.Image:
    selected = np.argwhere(alpha > 0.04)
    if not len(selected):
        raise ValueError("Le masque de la région blink est vide")
    ys, xs = selected[:, 0], selected[:, 1]
    center_x = (float(xs.min()) + float(xs.max())) * 0.5
    center_y = (float(ys.min()) + float(ys.max())) * 0.5
    region_width = max(2.0, float(xs.max() - xs.min() + 1))
    region_height = max(2.0, float(ys.max() - ys.min() + 1))
    crop_width = max(region_width * 2.1, region_height * 2.1 * width / height)
    crop_height = crop_width * height / width
    source = Image.fromarray(image)
    crop = source.crop(
        (
            round(center_x - crop_width * 0.5),
            round(center_y - crop_height * 0.5),
            round(center_x + crop_width * 0.5),
            round(center_y + crop_height * 0.5),
        )
    )
    return crop.resize((width, height), Image.Resampling.LANCZOS)


def _project_blink_mask(
    project: StudioProject,
    target: Any,
    mask: np.ndarray,
    project_frame: int,
    *,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    projection = target.attributes.get("projection")
    if not isinstance(projection, Mapping):
        raise ValueError("La preview réelle du blink exige une projection spatiale")
    transition_id = str(projection.get("transition_id", ""))
    target_clip_id = str(projection.get("target_clip_id", ""))
    transition = next(
        item for item in project.transitions if item.transition_id == transition_id
    )
    target_clip = next(
        clip
        for track in project.tracks
        for clip in track.clips
        if clip.clip_id == target_clip_id
    )
    asset = next(
        item for item in project.assets if item.asset_id == target_clip.asset_id
    )
    if asset.width is None or asset.height is None:
        raise ValueError("Le média réel du blink ne possède pas de dimensions")
    settings = SpatialMatchSettings.from_transition(transition)
    return project_canonical_mask(
        mask,
        settings.solution.homography,
        output_width=output_width,
        output_height=output_height,
        camera=target_clip.camera,
        reference_camera_frame=int(projection.get("reference_camera_frame", 0)),
        current_camera_frame=project_frame - target_clip.start_frame,
        camera_source_width=asset.width,
        camera_source_height=asset.height,
    )


def _blink_comparison_sheet(
    path: Path,
    canonical: list[Image.Image],
    projected: list[Image.Image],
    labels: list[str],
) -> None:
    label_height = 36
    row_label_width = 112
    cell_width, cell_height = canonical[0].size
    sheet = Image.new(
        "RGB",
        (
            row_label_width + cell_width * len(labels),
            label_height + cell_height * 2,
        ),
        (15, 16, 21),
    )
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(labels):
        draw.text(
            (row_label_width + index * cell_width + 10, 11),
            label,
            fill=(238, 239, 244),
        )
        sheet.paste(canonical[index], (row_label_width + index * cell_width, label_height))
        sheet.paste(
            projected[index],
            (row_label_width + index * cell_width, label_height + cell_height),
        )
    draw.text((10, label_height + cell_height // 2), "CANONIQUE", fill=(225, 177, 106))
    draw.text(
        (10, label_height + cell_height + cell_height // 2),
        "PHOTO RÉELLE",
        fill=(143, 214, 203),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    options = (
        {"quality": 95}
        if path.suffix.lower() in {".jpg", ".jpeg", ".webp"}
        else {}
    )
    sheet.save(path, **options)


def _render_blink_comparisons(
    result: RecipeBuildResult,
    control_path: Path,
    *,
    width: int,
    height: int,
    environment: _RenderEnvironment,
) -> list[dict[str, Any]]:
    scene = result.project.scene
    invocations = [
        item
        for item in result.project.invocations
        if item.capability_id == "region.blink"
    ]
    if scene is None or not invocations:
        return []
    with Image.open(environment.artwork_path) as source:
        artwork = np.asarray(source.convert("RGB"), dtype=np.uint8)
    records: list[dict[str, Any]] = []
    with StudioRenderSession(
        result.project,
        environment.artwork_path,
        output_width=width,
        output_height=height,
        resource_base=result.project_path.parent,
        extra_renderers=environment.renderers,
    ) as session:
        for invocation in invocations:
            target = scene.object_by_id(invocation.target_id or "")
            if target is None:
                raise ValueError("La preview blink ne trouve pas sa région")
            reference = next(
                item for item in target.resource_refs if item.kind == "mask"
            )
            asset = next(
                item for item in result.project.assets
                if item.asset_id == reference.asset_id
            )
            mask_path = resolve_asset_path(asset.path, result.project_path)
            with Image.open(mask_path) as source:
                mask = np.asarray(source.convert("L"), dtype=np.float32) / 255.0
            if mask.shape != artwork.shape[:2]:
                mask = cv2.resize(
                    mask,
                    (artwork.shape[1], artwork.shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )
            geometry = EyelidGeometry.from_mapping(
                target.attributes.get("blink_model")
            )
            parameters = invocation.parameters
            close_frames = int(parameters.get("close_frames", 6))
            local_frames = [
                0,
                max(1, (close_frames - 1) // 2),
                close_frames - 1,
                invocation.duration_frames - 1,
            ]
            labels = ["OUVERT", "MI-COURSE", "FERMÉ", "RÉOUVERT"]
            amounts = [
                blink_amount(
                    local,
                    close_frames=close_frames,
                    hold_frames=int(parameters.get("hold_frames", 2)),
                    open_frames=int(parameters.get("open_frames", 8)),
                    easing=str(parameters.get("easing", "ease-in-out")),
                    intensity=float(parameters.get("intensity", 1.0)),
                )
                for local in local_frames
            ]
            canonical_panels = [
                _eye_crop(
                    compose_blink(artwork, mask, amount, geometry),
                    mask,
                )
                for amount in amounts
            ]
            projected_panels: list[Image.Image] = []
            project_frames: list[int] = []
            for local in local_frames:
                project_frame = invocation.start_frame + local
                project_frames.append(project_frame)
                rendered = np.ascontiguousarray(session.frame_at(project_frame)).copy()
                projected_mask = _project_blink_mask(
                    result.project,
                    target,
                    mask,
                    project_frame,
                    output_width=width,
                    output_height=height,
                )
                projected_panels.append(_eye_crop(rendered, projected_mask))
            safe_target = (invocation.target_id or invocation.invocation_id).replace(":", "-")
            path = control_path.with_name(
                f"{control_path.stem}-blink-{safe_target}{control_path.suffix}"
            )
            _blink_comparison_sheet(
                path,
                canonical_panels,
                projected_panels,
                labels,
            )
            records.append(
                {
                    "path": str(path),
                    "sha256": _sha256_file(path),
                    "size_bytes": path.stat().st_size,
                    "invocation_id": invocation.invocation_id,
                    "target_id": invocation.target_id,
                    "geometry": geometry.to_dict(),
                    "states": [
                        {
                            "label": label.lower(),
                            "local_frame": local,
                            "project_frame": project_frame,
                            "amount": round(amount, 6),
                        }
                        for label, local, project_frame, amount in zip(
                            labels,
                            local_frames,
                            project_frames,
                            amounts,
                            strict=True,
                        )
                    ],
                    "artist_review": "pending",
                }
            )
    return records


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
    color_comparison = _render_color_comparison(
        result,
        path.with_name(f"{path.stem}-color-fidelity{path.suffix}"),
        width=proxy_width,
        height=proxy_height,
        environment=environment,
    )
    blink_comparisons = _render_blink_comparisons(
        result,
        path,
        width=proxy_width,
        height=proxy_height,
        environment=environment,
    )
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
        "color_fidelity": color_comparison,
        "blink_previews": blink_comparisons,
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
            "color_policies": _project_color_policies(result.project),
            "duration_frames": result.project.settings.duration_frames,
            "fps": result.project.settings.fps,
            "transitions": [
                {
                    "id": transition.transition_id,
                    "kind": transition.kind.value,
                    "start_frame": transition.start_frame,
                    "duration_frames": transition.duration_frames,
                    "parameters": transition.parameters,
                }
                for transition in result.project.transitions
            ],
            "semantic_regions": [
                item.to_dict()
                for item in (result.project.scene.objects if result.project.scene is not None else ())
                if item.semantic_type.startswith("artwork.region.")
            ],
            "semantic_actions": [
                invocation.to_dict()
                for invocation in result.project.invocations
                if invocation.capability_id.startswith("region.")
            ],
            "semantic_triggers": [
                trigger.to_dict()
                for trigger in result.project.triggers
                if any(
                    invocation.invocation_id == trigger.action_invocation_id
                    and invocation.capability_id.startswith("region.")
                    for invocation in result.project.invocations
                )
            ],
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

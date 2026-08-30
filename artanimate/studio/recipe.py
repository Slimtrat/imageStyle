from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping
from uuid import uuid4
import zipfile

from ..core.config import RenderConfig
from .assets import (
    asset_kind_for_path,
    import_artwork_asset,
    import_media_asset,
)
from .audio import AudioClipSettings
from .manual_match import ManualMatchTransform, add_manual_match, update_manual_match
from .media import StillClipSettings
from .model import (
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
    ProjectSettings,
    StudioProject,
    Track,
    TrackKind,
)
from .persistence import load_project, project_digest, save_project
from .transitions import add_dissolve
from .video import VideoClipSettings


RECIPE_SCHEMA_VERSION = 1
PROJECT_FILENAME = "project.artanimate"
RECIPE_FILENAME = "recipe.json"
ASSETS_DIRECTORY = "assets"
SNAPSHOTS_DIRECTORY = "snapshots"


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{where} doit être un objet JSON")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{where} contient une clé non textuelle")
    return dict(value)


def _known(values: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"Clé(s) inconnue(s) dans {where} : {', '.join(unknown)}")


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{where} doit être un identifiant textuel non vide")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(
            f"{where} accepte uniquement lettres ASCII, chiffres, point, tiret et underscore"
        )
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} doit être un texte non vide")
    return value.strip()


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{where} doit être un entier supérieur ou égal à {minimum}")
    return value


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where} doit être numérique")
    result = float(value)
    if not (-1.0e12 < result < 1.0e12):
        raise ValueError(f"{where} doit être fini")
    return result


def _enum(enum_type: type[Any], value: Any, where: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValueError(f"{where} doit être l’une de ces valeurs : {allowed}") from exc


def _path_text(value: Any, where: str) -> str:
    result = _text(value, where)
    if "\x00" in result:
        raise ValueError(f"{where} contient un caractère interdit")
    return result


@dataclass(frozen=True, slots=True)
class RecipeProjectSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background: tuple[int, int, int] = (18, 18, 22)
    quality: str = "fast"
    crf: int = 18
    audio_mode: AudioExportMode = AudioExportMode.REFERENCE

    @classmethod
    def from_dict(cls, payload: Any) -> RecipeProjectSettings:
        values = _object(payload, "recipe.project")
        _known(
            values,
            {"width", "height", "fps", "background", "quality", "crf", "audio_mode"},
            "recipe.project",
        )
        background = values.get("background", [18, 18, 22])
        if (
            not isinstance(background, list)
            or len(background) != 3
            or any(
                isinstance(channel, bool)
                or not isinstance(channel, int)
                or not 0 <= channel <= 255
                for channel in background
            )
        ):
            raise ValueError("recipe.project.background doit contenir trois canaux RGB")
        settings = cls(
            width=_integer(values.get("width", 1080), "recipe.project.width", minimum=64),
            height=_integer(values.get("height", 1920), "recipe.project.height", minimum=64),
            fps=_integer(values.get("fps", 30), "recipe.project.fps", minimum=1),
            background=tuple(background),
            quality=_text(values.get("quality", "fast"), "recipe.project.quality"),
            crf=_integer(values.get("crf", 18), "recipe.project.crf"),
            audio_mode=_enum(
                AudioExportMode,
                values.get("audio_mode", AudioExportMode.REFERENCE.value),
                "recipe.project.audio_mode",
            ),
        )
        ProjectSettings(
            settings.width,
            settings.height,
            settings.fps,
            1,
            settings.background,
        ).validate()
        ExportSettings(
            crf=settings.crf,
            quality=settings.quality,
            audio_mode=settings.audio_mode,
        ).validate()
        return settings

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "background": list(self.background),
            "quality": self.quality,
            "crf": self.crf,
            "audio_mode": self.audio_mode.value,
        }


@dataclass(frozen=True, slots=True)
class RecipeMedia:
    media_id: str
    path: str
    kind: AssetKind

    @classmethod
    def from_pair(cls, media_id: str, payload: Any) -> RecipeMedia:
        identifier = _identifier(media_id, "recipe.media.<id>")
        values = _object(payload, f"recipe.media.{identifier}")
        _known(values, {"path", "kind"}, f"recipe.media.{identifier}")
        return cls(
            identifier,
            _path_text(values.get("path"), f"recipe.media.{identifier}.path"),
            _enum(AssetKind, values.get("kind"), f"recipe.media.{identifier}.kind"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind.value}


def _camera_animation(payload: Any, duration_frames: int, where: str) -> CameraAnimation | None:
    if payload is None:
        return None
    values = _object(payload, where)
    _known(values, {"keyframes"}, where)
    raw_keyframes = values.get("keyframes", [])
    if not isinstance(raw_keyframes, list):
        raise TypeError(f"{where}.keyframes doit être une liste")
    keyframes: list[CameraKeyframe] = []
    for index, raw in enumerate(raw_keyframes):
        key = _object(raw, f"{where}.keyframes[{index}]")
        _known(
            key,
            {"frame", "x", "y", "zoom", "rotation_degrees", "perspective", "focus", "easing"},
            f"{where}.keyframes[{index}]",
        )
        keyframes.append(
            CameraKeyframe(
                _integer(key.get("frame"), f"{where}.keyframes[{index}].frame"),
                CameraPose(
                    x=_number(key.get("x", 0.5), f"{where}.keyframes[{index}].x"),
                    y=_number(key.get("y", 0.5), f"{where}.keyframes[{index}].y"),
                    zoom=_number(key.get("zoom", 1.0), f"{where}.keyframes[{index}].zoom"),
                    rotation_degrees=_number(
                        key.get("rotation_degrees", 0.0),
                        f"{where}.keyframes[{index}].rotation_degrees",
                    ),
                    perspective=_number(
                        key.get("perspective", 0.0),
                        f"{where}.keyframes[{index}].perspective",
                    ),
                    focus=_number(key.get("focus", 1.0), f"{where}.keyframes[{index}].focus"),
                ),
                _enum(
                    Easing,
                    key.get("easing", Easing.EASE_IN_OUT.value),
                    f"{where}.keyframes[{index}].easing",
                ),
            )
        )
    return CameraAnimation(tuple(keyframes)).validate(
        clip_duration_frames=duration_frames
    )


@dataclass(frozen=True, slots=True)
class RecipeShot:
    shot_id: str
    kind: ClipKind
    duration_frames: int
    asset: str | None = None
    source_in_frame: int = 0
    fit: FitMode = FitMode.COVER
    opacity: float = 1.0
    camera_payload: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Any, index: int) -> RecipeShot:
        where = f"recipe.shots[{index}]"
        values = _object(payload, where)
        _known(
            values,
            {
                "id",
                "kind",
                "duration_frames",
                "asset",
                "source_in_frame",
                "fit",
                "opacity",
                "camera",
                "settings",
            },
            where,
        )
        duration = _integer(
            values.get("duration_frames"), f"{where}.duration_frames", minimum=1
        )
        kind = _enum(ClipKind, values.get("kind"), f"{where}.kind")
        if kind not in {
            ClipKind.ARTWORK_2D,
            ClipKind.ARTWORK_3D,
            ClipKind.STILL,
            ClipKind.VIDEO,
        }:
            raise ValueError(f"{where}.kind n’est pas un type de plan visuel")
        asset = values.get("asset")
        if kind in {ClipKind.STILL, ClipKind.VIDEO}:
            asset = _identifier(asset, f"{where}.asset")
        elif asset is not None:
            raise ValueError(f"{where}.asset est réservé aux plans réels")
        camera_payload = values.get("camera")
        if camera_payload is not None:
            camera_payload = _object(camera_payload, f"{where}.camera")
            _camera_animation(camera_payload, duration, f"{where}.camera")
        settings = values.get("settings")
        if settings is not None:
            settings = _object(settings, f"{where}.settings")
        opacity = _number(values.get("opacity", 1.0), f"{where}.opacity")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError(f"{where}.opacity doit être compris entre 0 et 1")
        return cls(
            _identifier(values.get("id"), f"{where}.id"),
            kind,
            duration,
            asset,
            _integer(values.get("source_in_frame", 0), f"{where}.source_in_frame"),
            _enum(FitMode, values.get("fit", FitMode.COVER.value), f"{where}.fit"),
            opacity,
            camera_payload,
            settings,
        )

    def camera(self) -> CameraAnimation | None:
        return _camera_animation(
            self.camera_payload,
            self.duration_frames,
            f"recipe.shot.{self.shot_id}.camera",
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.shot_id,
            "kind": self.kind.value,
            "duration_frames": self.duration_frames,
            "fit": self.fit.value,
        }
        if self.asset is not None:
            payload["asset"] = self.asset
        if self.source_in_frame:
            payload["source_in_frame"] = self.source_in_frame
        if self.opacity != 1.0:
            payload["opacity"] = self.opacity
        if self.camera_payload is not None:
            payload["camera"] = deepcopy(self.camera_payload)
        if self.settings is not None:
            payload["settings"] = deepcopy(self.settings)
        return payload


@dataclass(frozen=True, slots=True)
class RecipeTransition:
    kind: str
    from_shot: str
    to_shot: str
    duration_frames: int = 1
    easing: Easing = Easing.EASE_IN_OUT
    settings: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Any, index: int) -> RecipeTransition:
        where = f"recipe.transitions[{index}]"
        values = _object(payload, where)
        _known(
            values,
            {"kind", "from", "to", "duration_frames", "easing", "settings"},
            where,
        )
        kind = _text(values.get("kind"), f"{where}.kind")
        if kind not in {"cut", "dissolve", "manual_match"}:
            raise ValueError(f"{where}.kind doit être cut, dissolve ou manual_match")
        duration = _integer(
            values.get("duration_frames", 1 if kind == "cut" else 12),
            f"{where}.duration_frames",
            minimum=1 if kind == "cut" else 2,
        )
        if kind == "cut" and duration != 1:
            raise ValueError("Une transition cut dure exactement une frame")
        settings = values.get("settings")
        if settings is not None:
            settings = _object(settings, f"{where}.settings")
        return cls(
            kind,
            _identifier(values.get("from"), f"{where}.from"),
            _identifier(values.get("to"), f"{where}.to"),
            duration,
            _enum(
                Easing,
                values.get("easing", Easing.EASE_IN_OUT.value),
                f"{where}.easing",
            ),
            settings,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "from": self.from_shot,
            "to": self.to_shot,
            "duration_frames": self.duration_frames,
            "easing": self.easing.value,
        }
        if self.settings is not None:
            payload["settings"] = deepcopy(self.settings)
        return payload


@dataclass(frozen=True, slots=True)
class RecipeAudio:
    audio_id: str
    asset: str
    start_frame: int
    source_in_frame: int
    duration_frames: int
    gain_db: float = 0.0
    fade_in_frames: int = 0
    fade_out_frames: int = 0

    @classmethod
    def from_dict(cls, payload: Any, index: int) -> RecipeAudio:
        where = f"recipe.audio[{index}]"
        values = _object(payload, where)
        _known(
            values,
            {
                "id",
                "asset",
                "start_frame",
                "source_in_frame",
                "duration_frames",
                "gain_db",
                "fade_in_frames",
                "fade_out_frames",
            },
            where,
        )
        result = cls(
            _identifier(values.get("id"), f"{where}.id"),
            _identifier(values.get("asset"), f"{where}.asset"),
            _integer(values.get("start_frame", 0), f"{where}.start_frame"),
            _integer(values.get("source_in_frame", 0), f"{where}.source_in_frame"),
            _integer(values.get("duration_frames"), f"{where}.duration_frames", minimum=1),
            _number(values.get("gain_db", 0.0), f"{where}.gain_db"),
            _integer(values.get("fade_in_frames", 0), f"{where}.fade_in_frames"),
            _integer(values.get("fade_out_frames", 0), f"{where}.fade_out_frames"),
        )
        result.settings().validate(duration_frames=result.duration_frames)
        return result

    def settings(self) -> AudioClipSettings:
        return AudioClipSettings(
            gain_db=self.gain_db,
            fade_in_frames=self.fade_in_frames,
            fade_out_frames=self.fade_out_frames,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.audio_id,
            "asset": self.asset,
            "start_frame": self.start_frame,
            "source_in_frame": self.source_in_frame,
            "duration_frames": self.duration_frames,
            "gain_db": self.gain_db,
            "fade_in_frames": self.fade_in_frames,
            "fade_out_frames": self.fade_out_frames,
        }


@dataclass(frozen=True, slots=True)
class RecipeOutputs:
    control_sheet: str | None = None
    export: str | None = None
    control_width: int = 270

    @classmethod
    def from_dict(cls, payload: Any) -> RecipeOutputs:
        values = _object(payload, "recipe.outputs")
        _known(values, {"control_sheet", "export", "control_width"}, "recipe.outputs")
        control = values.get("control_sheet")
        export = values.get("export")
        if control is not None:
            control = _path_text(control, "recipe.outputs.control_sheet")
        if export is not None:
            export = _path_text(export, "recipe.outputs.export")
        return cls(
            control,
            export,
            _integer(values.get("control_width", 270), "recipe.outputs.control_width", minimum=64),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"control_width": self.control_width}
        if self.control_sheet is not None:
            payload["control_sheet"] = self.control_sheet
        if self.export is not None:
            payload["export"] = self.export
        return payload


@dataclass(frozen=True, slots=True)
class StudioRecipe:
    name: str
    artwork: str
    project: RecipeProjectSettings
    media: tuple[RecipeMedia, ...]
    shots: tuple[RecipeShot, ...]
    transitions: tuple[RecipeTransition, ...] = ()
    audio: tuple[RecipeAudio, ...] = ()
    outputs: RecipeOutputs = RecipeOutputs()
    schema_version: int = RECIPE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Any) -> StudioRecipe:
        values = _object(payload, "recipe")
        _known(
            values,
            {
                "schema_version",
                "name",
                "artwork",
                "project",
                "media",
                "shots",
                "transitions",
                "audio",
                "outputs",
            },
            "recipe",
        )
        version = _integer(values.get("schema_version"), "recipe.schema_version", minimum=1)
        if version != RECIPE_SCHEMA_VERSION:
            raise ValueError(f"Version de recette headless inconnue : {version}")
        raw_media = _object(values.get("media", {}), "recipe.media")
        media = tuple(
            RecipeMedia.from_pair(media_id, item)
            for media_id, item in sorted(raw_media.items())
        )
        raw_shots = values.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError("recipe.shots doit contenir au moins un plan")
        shots = tuple(RecipeShot.from_dict(item, index) for index, item in enumerate(raw_shots))
        raw_transitions = values.get("transitions", [])
        raw_audio = values.get("audio", [])
        if not isinstance(raw_transitions, list) or not isinstance(raw_audio, list):
            raise TypeError("recipe.transitions et recipe.audio doivent être des listes")
        result = cls(
            _text(values.get("name"), "recipe.name"),
            _path_text(values.get("artwork"), "recipe.artwork"),
            RecipeProjectSettings.from_dict(values.get("project", {})),
            media,
            shots,
            tuple(
                RecipeTransition.from_dict(item, index)
                for index, item in enumerate(raw_transitions)
            ),
            tuple(RecipeAudio.from_dict(item, index) for index, item in enumerate(raw_audio)),
            RecipeOutputs.from_dict(values.get("outputs", {})),
            version,
        )
        result.validate()
        return result

    @classmethod
    def from_path(cls, path: str | Path) -> StudioRecipe:
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Recette JSON invalide dans {source} : {exc}") from exc
        return cls.from_dict(payload)

    def validate(self) -> StudioRecipe:
        media = {item.media_id: item for item in self.media}
        if len(media) != len(self.media):
            raise ValueError("La recette contient deux médias portant le même identifiant")
        shot_ids = [item.shot_id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("La recette contient deux plans portant le même identifiant")
        for shot in self.shots:
            if shot.asset is not None:
                asset = media.get(shot.asset)
                if asset is None:
                    raise ValueError(f"Le plan {shot.shot_id} référence le média absent {shot.asset}")
                expected = AssetKind.IMAGE if shot.kind == ClipKind.STILL else AssetKind.VIDEO
                if asset.kind != expected:
                    raise ValueError(f"Le média de {shot.shot_id} n’a pas le type {expected.value}")
        positions = {shot_id: index for index, shot_id in enumerate(shot_ids)}
        endpoints: set[tuple[str, str]] = set()
        for transition in self.transitions:
            if transition.from_shot not in positions or transition.to_shot not in positions:
                raise ValueError("Une transition référence un plan absent")
            if positions[transition.to_shot] != positions[transition.from_shot] + 1:
                raise ValueError("Une transition doit relier deux plans consécutifs")
            endpoint = (transition.from_shot, transition.to_shot)
            if endpoint in endpoints:
                raise ValueError("Deux transitions relient les mêmes plans")
            endpoints.add(endpoint)
            if transition.kind == "manual_match":
                first = self.shots[positions[transition.from_shot]]
                second = self.shots[positions[transition.to_shot]]
                if first.kind not in {ClipKind.ARTWORK_2D, ClipKind.ARTWORK_3D}:
                    raise ValueError("Le match manuel doit partir de l’œuvre")
                if second.kind not in {ClipKind.STILL, ClipKind.VIDEO}:
                    raise ValueError("Le match manuel doit arriver sur une photo ou vidéo")
        duration = self.duration_frames
        for audio in self.audio:
            asset = media.get(audio.asset)
            if asset is None or asset.kind != AssetKind.AUDIO:
                raise ValueError(f"L’audio {audio.audio_id} référence un média audio absent")
            if audio.start_frame + audio.duration_frames > duration:
                raise ValueError(f"L’audio {audio.audio_id} dépasse la durée du projet")
        return self

    @property
    def duration_frames(self) -> int:
        return sum(item.duration_frames for item in self.shots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "artwork": self.artwork,
            "project": self.project.to_dict(),
            "media": {item.media_id: item.to_dict() for item in self.media},
            "shots": [item.to_dict() for item in self.shots],
            "transitions": [item.to_dict() for item in self.transitions],
            "audio": [item.to_dict() for item in self.audio],
            "outputs": self.outputs.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RecipeBuildResult:
    project: StudioProject
    project_path: Path
    recipe_path: Path
    assets_directory: Path
    changed: bool
    snapshot_path: Path | None = None


def _resolved_media_path(stored: str, base: Path) -> Path:
    path = Path(stored)
    return (path if path.is_absolute() else base / path).resolve(strict=True)


def _safe_filename(path: Path, prefix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-.") or "media"
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", prefix).strip("-.") or "asset"
    return f"{prefix}-{stem}{path.suffix.lower()}"


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _portable_recipe(
    recipe: StudioRecipe,
    source_base: Path,
    candidate: Path,
) -> tuple[StudioRecipe, dict[str, Path]]:
    assets = candidate / ASSETS_DIRECTORY
    artwork_source = _resolved_media_path(recipe.artwork, source_base)
    if asset_kind_for_path(artwork_source) != AssetKind.IMAGE:
        raise ValueError("L’œuvre centrale de la recette doit être une image")
    artwork_relative = Path(ASSETS_DIRECTORY) / "artwork" / _safe_filename(
        artwork_source, "artwork"
    )
    artwork_destination = candidate / artwork_relative
    artwork_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artwork_source, artwork_destination)
    copied: dict[str, Path] = {"artwork": artwork_destination}
    portable_media: list[RecipeMedia] = []
    for media in recipe.media:
        source = _resolved_media_path(media.path, source_base)
        detected = asset_kind_for_path(source)
        if detected != media.kind:
            raise ValueError(
                f"Le média {media.media_id} est déclaré {media.kind.value} mais détecté {detected.value}"
            )
        relative = Path(ASSETS_DIRECTORY) / "media" / _safe_filename(
            source, media.media_id
        )
        destination = candidate / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied[media.media_id] = destination
        portable_media.append(replace(media, path=relative.as_posix()))
    portable = replace(
        recipe,
        artwork=artwork_relative.as_posix(),
        media=tuple(portable_media),
    )
    portable.validate()
    assets.mkdir(parents=True, exist_ok=True)
    return portable, copied


def _build_identity(recipe: StudioRecipe, copied: Mapping[str, Path]) -> str:
    digest = sha256(
        json.dumps(
            recipe.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    for media_id, path in sorted(copied.items()):
        digest.update(media_id.encode("utf-8"))
        digest.update(_file_digest(path).encode("ascii"))
    return digest.hexdigest()


def _three_d_parameters(
    shot: RecipeShot,
    recipe: StudioRecipe,
    outgoing_handle_frames: int,
) -> dict[str, Any]:
    values = deepcopy(shot.settings or {})
    allowed = {"render_config", "camera", "lamp_brightness", "lamp_motion"}
    _known(values, allowed, f"recipe.shot.{shot.shot_id}.settings")
    raw_config = _object(values.get("render_config", {}), "recipe.3d.render_config")
    required_duration = (shot.duration_frames + outgoing_handle_frames) / recipe.project.fps
    raw_config.setdefault("effect", "sand")
    raw_config["duration"] = max(float(raw_config.get("duration", 0.0)), required_duration)
    raw_config["fps"] = recipe.project.fps
    raw_config.setdefault("width", min(recipe.project.width, 540))
    raw_config.setdefault("quality", recipe.project.quality)
    raw_config.setdefault("hold_start", min(0.15, required_duration * 0.1))
    raw_config.setdefault("hold_end", min(0.25, required_duration * 0.1))
    config = RenderConfig.from_dict(raw_config)
    camera = _object(values.get("camera", {}), "recipe.3d.camera")
    _known(
        camera,
        {"yaw", "pitch", "distance", "motion", "motion_strength"},
        "recipe.3d.camera",
    )
    return {
        "schema_version": 1,
        "render_config": config.to_dict(),
        "camera": {
            "yaw": float(camera.get("yaw", 4.0)),
            "pitch": float(camera.get("pitch", -73.0)),
            "distance": float(camera.get("distance", 610.0)),
            "motion": str(camera.get("motion", "top_drift")),
            "motion_strength": float(camera.get("motion_strength", 0.65)),
        },
        "lamp_brightness": float(values.get("lamp_brightness", 2.7)),
        "lamp_motion": float(values.get("lamp_motion", 0.35)),
    }


def compile_studio_recipe(
    recipe: StudioRecipe,
    project_path: str | Path,
    *,
    build_identity: str,
) -> StudioProject:
    recipe.validate()
    path = Path(project_path)
    artwork_path = _resolved_media_path(recipe.artwork, path.parent)
    artwork = import_artwork_asset(artwork_path, path)
    media_assets = tuple(
        import_media_asset(
            _resolved_media_path(media.path, path.parent),
            media.kind,
            path,
            asset_id=f"media-{media.media_id}",
        )
        for media in recipe.media
    )
    media_by_id = {
        media.media_id: asset
        for media, asset in zip(recipe.media, media_assets, strict=True)
    }
    outgoing_handles: dict[str, int] = {}
    for transition in recipe.transitions:
        if transition.kind != "cut":
            outgoing_handles[transition.from_shot] = (
                transition.duration_frames - transition.duration_frames // 2
            )
    start = 0
    visual_clips: list[Clip] = []
    for shot in recipe.shots:
        parameters: dict[str, Any] | None = None
        asset_id: str | None = None
        if shot.kind == ClipKind.ARTWORK_3D:
            parameters = _three_d_parameters(
                shot,
                recipe,
                outgoing_handles.get(shot.shot_id, 0),
            )
        elif shot.kind == ClipKind.STILL:
            settings = StillClipSettings.from_mapping(shot.settings)
            parameters = {"still": settings.to_dict()}
            asset_id = media_by_id[shot.asset or ""].asset_id
        elif shot.kind == ClipKind.VIDEO:
            settings = VideoClipSettings.from_mapping(shot.settings)
            parameters = settings.to_dict()
            asset_id = media_by_id[shot.asset or ""].asset_id
        clip = Clip(
            clip_id=f"shot-{shot.shot_id}",
            kind=shot.kind,
            start_frame=start,
            duration_frames=shot.duration_frames,
            source_in_frame=shot.source_in_frame,
            asset_id=asset_id,
            opacity=shot.opacity,
            fit=shot.fit,
            camera=shot.camera(),
            parameters=parameters,
        ).validate()
        visual_clips.append(clip)
        start += shot.duration_frames
    audio_clips = tuple(
        Clip(
            clip_id=f"audio-{item.audio_id}",
            kind=ClipKind.AUDIO,
            start_frame=item.start_frame,
            duration_frames=item.duration_frames,
            source_in_frame=item.source_in_frame,
            asset_id=media_by_id[item.asset].asset_id,
            parameters=item.settings().to_dict(),
        ).validate()
        for item in recipe.audio
    )
    base = StudioProject.new(artwork_path, fps=recipe.project.fps, duration_seconds=1)
    project = replace(
        base,
        project_id=f"recipe-{build_identity[:32]}",
        artwork=artwork,
        settings=ProjectSettings(
            recipe.project.width,
            recipe.project.height,
            recipe.project.fps,
            recipe.duration_frames,
            recipe.project.background,
        ),
        assets=media_assets,
        tracks=(
            Track(
                "video-main",
                TrackKind.VIDEO,
                recipe.name,
                tuple(visual_clips),
            ),
            Track("effects-main", TrackKind.EFFECT, "Effets"),
            Track("audio-main", TrackKind.AUDIO, "Musique", audio_clips),
        ),
        transitions=(),
        export=ExportSettings(
            crf=recipe.project.crf,
            quality=recipe.project.quality,
            audio_mode=recipe.project.audio_mode,
        ),
        scene=None,
        invocations=(),
        triggers=(),
    ).validate()
    clip_ids = {shot.shot_id: f"shot-{shot.shot_id}" for shot in recipe.shots}
    for transition_recipe in recipe.transitions:
        if transition_recipe.kind == "cut":
            continue
        if transition_recipe.kind == "dissolve":
            project, transition = add_dissolve(
                project,
                clip_ids[transition_recipe.from_shot],
                clip_ids[transition_recipe.to_shot],
                duration_frames=transition_recipe.duration_frames,
                easing=transition_recipe.easing,
            )
        else:
            project, transition = add_manual_match(
                project,
                clip_ids[transition_recipe.from_shot],
                clip_ids[transition_recipe.to_shot],
                duration_frames=transition_recipe.duration_frames,
                easing=transition_recipe.easing,
            )
            settings = transition_recipe.settings or {}
            _known(
                settings,
                {"overlay_opacity", "reference_source_frame", "transform"},
                f"recipe.transition.{transition_recipe.from_shot}-{transition_recipe.to_shot}.settings",
            )
            project = update_manual_match(
                project,
                transition.transition_id,
                overlay_opacity=(
                    float(settings["overlay_opacity"])
                    if "overlay_opacity" in settings
                    else None
                ),
                reference_source_frame=(
                    int(settings["reference_source_frame"])
                    if "reference_source_frame" in settings
                    else None
                ),
                transform=(
                    ManualMatchTransform.from_dict(settings["transform"])
                    if "transform" in settings
                    else None
                ),
            )
            transition = next(
                item
                for item in project.transitions
                if item.from_clip_id == clip_ids[transition_recipe.from_shot]
                and item.to_clip_id == clip_ids[transition_recipe.to_shot]
            )
        stable_id = f"transition-{transition_recipe.from_shot}-{transition_recipe.to_shot}"
        project = replace(
            project,
            transitions=tuple(
                replace(item, transition_id=stable_id)
                if item.transition_id == transition.transition_id
                else item
                for item in project.transitions
            ),
        ).validate()
    return project.validate()


def _snapshot_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in (Path(PROJECT_FILENAME), Path(RECIPE_FILENAME)):
        candidate = root / relative
        if candidate.is_file():
            files.append(candidate)
    assets = root / ASSETS_DIRECTORY
    if assets.is_dir():
        files.extend(path for path in assets.rglob("*") if path.is_file())
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _managed_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _file_digest(path)
        for path in _snapshot_files(root)
    }


def _create_snapshot(source: Path, destination_root: Path, digest: str) -> Path:
    snapshots = destination_root / SNAPSHOTS_DIRECTORY
    snapshots.mkdir(parents=True, exist_ok=True)
    existing = tuple(snapshots.glob("[0-9][0-9][0-9][0-9]-*.zip"))
    index = len(existing) + 1
    destination = snapshots / f"{index:04d}-{digest[:12]}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _snapshot_files(source):
            archive.write(path, path.relative_to(source).as_posix())
    return destination


def _swap_directory(prepared: Path, destination: Path) -> None:
    if not destination.exists():
        prepared.replace(destination)
        return
    backup = destination.with_name(f".{destination.name}.backup-{uuid4().hex}")
    destination.replace(backup)
    try:
        prepared.replace(destination)
    except BaseException:
        if not destination.exists() and backup.exists():
            backup.replace(destination)
        raise
    shutil.rmtree(backup)


def build_portable_project(
    recipe_path: str | Path,
    output_directory: str | Path,
) -> RecipeBuildResult:
    source = Path(recipe_path).resolve(strict=True)
    recipe = StudioRecipe.from_path(source)
    output = Path(output_directory).resolve(strict=False)
    if output.parent == output:
        raise ValueError("Le dossier de projet ne peut pas être la racine du volume")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.headless-",
        dir=output.parent,
    ) as temporary_value:
        temporary = Path(temporary_value)
        candidate = temporary / "candidate"
        candidate.mkdir()
        portable, copied = _portable_recipe(recipe, source.parent, candidate)
        identity = _build_identity(portable, copied)
        project_path = candidate / PROJECT_FILENAME
        project = compile_studio_recipe(
            portable,
            project_path,
            build_identity=identity,
        )
        _atomic_text(candidate / RECIPE_FILENAME, _json_text(portable.to_dict()))
        save_project(project, project_path)
        reopened = load_project(project_path)
        if reopened != project:
            raise AssertionError("Le projet compilé diffère après sa réouverture")

        existing_project_path = output / PROJECT_FILENAME
        existing: StudioProject | None = None
        if existing_project_path.exists():
            existing = load_project(existing_project_path)
            if (
                project_digest(existing) == project_digest(project)
                and _managed_manifest(output) == _managed_manifest(candidate)
            ):
                return RecipeBuildResult(
                    existing,
                    existing_project_path,
                    output / RECIPE_FILENAME,
                    output / ASSETS_DIRECTORY,
                    changed=False,
                )

        prepared = temporary / "prepared"
        if output.exists():
            if not output.is_dir():
                raise NotADirectoryError(f"La destination existe sans être un dossier : {output}")
            shutil.copytree(output, prepared)
        else:
            prepared.mkdir()
        snapshot: Path | None = None
        if existing is not None:
            snapshot = _create_snapshot(output, prepared, project_digest(existing))
        prepared_assets = prepared / ASSETS_DIRECTORY
        if prepared_assets.exists():
            shutil.rmtree(prepared_assets)
        shutil.copytree(candidate / ASSETS_DIRECTORY, prepared_assets)
        shutil.copy2(candidate / RECIPE_FILENAME, prepared / RECIPE_FILENAME)
        shutil.copy2(candidate / PROJECT_FILENAME, prepared / PROJECT_FILENAME)
        snapshot_relative = snapshot.relative_to(prepared) if snapshot is not None else None
        _swap_directory(prepared, output)

    final_project_path = output / PROJECT_FILENAME
    final_project = load_project(final_project_path)
    return RecipeBuildResult(
        final_project,
        final_project_path,
        output / RECIPE_FILENAME,
        output / ASSETS_DIRECTORY,
        changed=True,
        snapshot_path=(output / snapshot_relative if snapshot_relative is not None else None),
    )

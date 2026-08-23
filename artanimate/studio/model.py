from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import math
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4


STUDIO_SCHEMA_VERSION = 1


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class TrackKind(StrEnum):
    VIDEO = "video"
    EFFECT = "effect"
    AUDIO = "audio"


class ClipKind(StrEnum):
    ARTWORK_2D = "artwork_2d"
    ARTWORK_3D = "artwork_3d"
    STILL = "still"
    VIDEO = "video"
    EFFECT_2D = "effect_2d"
    AUDIO = "audio"


class Easing(StrEnum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


class TransitionKind(StrEnum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    MATCH = "match"


class AudioExportMode(StrEnum):
    EMBEDDED = "embedded"
    REFERENCE = "reference"


class FitMode(StrEnum):
    CONTAIN = "contain"
    COVER = "cover"
    STRETCH = "stretch"


def _identifier(value: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} doit être un identifiant non vide")
    if value != value.strip():
        raise ValueError(f"{where} ne peut pas commencer ou finir par un espace")
    return value


def _positive_int(value: int | None, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{where} doit être un entier strictement positif")
    return value


def _finite(value: float, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where} doit être numérique")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{where} doit être fini")
    return result


def _json_value(value: Any, where: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} contient une valeur flottante non finie")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _json_value(item, f"{where}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{where} contient une clé non textuelle")
            _json_value(item, f"{where}.{key}")
        return
    raise TypeError(f"{where} contient un type non sérialisable : {type(value).__name__}")


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{where} doit être un objet JSON")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{where} contient une clé non textuelle")
    return dict(value)


def _known_keys(values: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"Clé(s) inconnue(s) dans {where} : {', '.join(unknown)}")


EnumT = TypeVar("EnumT", bound=StrEnum)


def _enum(enum_type: type[EnumT], value: Any, where: str) -> EnumT:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{where} doit être l’une de ces valeurs : {allowed}") from exc


@dataclass(frozen=True, slots=True)
class ArtworkAsset:
    path: str
    asset_id: str = "artwork"
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None

    def validate(self) -> ArtworkAsset:
        _identifier(self.asset_id, "artwork.asset_id")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("Le chemin de l’œuvre doit être renseigné")
        _positive_int(self.width, "artwork.width")
        _positive_int(self.height, "artwork.height")
        if self.fingerprint is not None and not self.fingerprint.strip():
            raise ValueError("Le fingerprint de l’œuvre ne peut pas être vide")
        return self


@dataclass(frozen=True, slots=True)
class MediaAsset:
    asset_id: str
    kind: AssetKind
    path: str
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] | None = None

    def validate(self) -> MediaAsset:
        _identifier(self.asset_id, "asset.asset_id")
        if not isinstance(self.kind, AssetKind):
            raise TypeError("asset.kind doit être un AssetKind")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("Le chemin d’un média doit être renseigné")
        _positive_int(self.width, f"asset {self.asset_id}.width")
        _positive_int(self.height, f"asset {self.asset_id}.height")
        if self.kind == AssetKind.AUDIO and (self.width is not None or self.height is not None):
            raise ValueError("Un asset audio ne possède pas de dimensions visuelles")
        if self.fingerprint is not None and not self.fingerprint.strip():
            raise ValueError("Le fingerprint d’un média ne peut pas être vide")
        if self.metadata is not None:
            _json_value(self.metadata, f"asset {self.asset_id}.metadata")
        return self


@dataclass(frozen=True, slots=True)
class CameraPose:
    x: float = 0.5
    y: float = 0.5
    zoom: float = 1.0
    rotation_degrees: float = 0.0
    perspective: float = 0.0
    focus: float = 1.0

    def validate(self) -> CameraPose:
        _finite(self.x, "camera.x")
        _finite(self.y, "camera.y")
        zoom = _finite(self.zoom, "camera.zoom")
        perspective = _finite(self.perspective, "camera.perspective")
        focus = _finite(self.focus, "camera.focus")
        _finite(self.rotation_degrees, "camera.rotation_degrees")
        if zoom <= 0:
            raise ValueError("camera.zoom doit être strictement positif")
        if not 0.0 <= perspective <= 1.0:
            raise ValueError("camera.perspective doit être compris entre 0 et 1")
        if not 0.0 <= focus <= 1.0:
            raise ValueError("camera.focus doit être compris entre 0 et 1")
        return self


@dataclass(frozen=True, slots=True)
class CameraKeyframe:
    frame: int
    pose: CameraPose
    easing: Easing = Easing.EASE_IN_OUT

    def validate(self) -> CameraKeyframe:
        if isinstance(self.frame, bool) or not isinstance(self.frame, int) or self.frame < 0:
            raise ValueError("Une keyframe caméra doit utiliser une frame entière positive")
        self.pose.validate()
        if not isinstance(self.easing, Easing):
            raise TypeError("camera.easing doit être un Easing")
        return self


@dataclass(frozen=True, slots=True)
class CameraAnimation:
    keyframes: tuple[CameraKeyframe, ...] = ()

    def validate(self, *, clip_duration_frames: int | None = None) -> CameraAnimation:
        previous = -1
        for keyframe in self.keyframes:
            keyframe.validate()
            if keyframe.frame <= previous:
                raise ValueError("Les keyframes caméra doivent être strictement ordonnées")
            if clip_duration_frames is not None and keyframe.frame >= clip_duration_frames:
                raise ValueError("Une keyframe caméra dépasse la durée locale du clip")
            previous = keyframe.frame
        return self


@dataclass(frozen=True, slots=True)
class Clip:
    clip_id: str
    kind: ClipKind
    start_frame: int
    duration_frames: int
    source_in_frame: int = 0
    asset_id: str | None = None
    opacity: float = 1.0
    enabled: bool = True
    fit: FitMode = FitMode.CONTAIN
    camera: CameraAnimation | None = None
    parameters: dict[str, Any] | None = None

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.duration_frames

    def validate(self) -> Clip:
        _identifier(self.clip_id, "clip.clip_id")
        if not isinstance(self.kind, ClipKind):
            raise TypeError("clip.kind doit être un ClipKind")
        if isinstance(self.start_frame, bool) or not isinstance(self.start_frame, int):
            raise TypeError("clip.start_frame doit être un entier")
        if self.start_frame < 0:
            raise ValueError("clip.start_frame ne peut pas être négatif")
        if (
            isinstance(self.duration_frames, bool)
            or not isinstance(self.duration_frames, int)
            or self.duration_frames <= 0
        ):
            raise ValueError("clip.duration_frames doit être strictement positif")
        if (
            isinstance(self.source_in_frame, bool)
            or not isinstance(self.source_in_frame, int)
            or self.source_in_frame < 0
        ):
            raise ValueError("clip.source_in_frame doit être un entier positif")
        opacity = _finite(self.opacity, "clip.opacity")
        if not 0.0 <= opacity <= 1.0:
            raise ValueError("clip.opacity doit être compris entre 0 et 1")
        if not isinstance(self.enabled, bool):
            raise TypeError("clip.enabled doit être un booléen")
        if not isinstance(self.fit, FitMode):
            raise TypeError("clip.fit doit être un FitMode")
        if self.asset_id is not None:
            _identifier(self.asset_id, "clip.asset_id")
        if self.camera is not None:
            self.camera.validate(clip_duration_frames=self.duration_frames)
        if self.parameters is not None:
            _json_value(self.parameters, f"clip {self.clip_id}.parameters")
        return self


@dataclass(frozen=True, slots=True)
class Track:
    track_id: str
    kind: TrackKind
    name: str
    clips: tuple[Clip, ...] = ()
    muted: bool = False
    locked: bool = False
    hidden: bool = False

    def validate(self) -> Track:
        _identifier(self.track_id, "track.track_id")
        if not isinstance(self.kind, TrackKind):
            raise TypeError("track.kind doit être un TrackKind")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Une piste doit avoir un nom")
        if not all(isinstance(value, bool) for value in (self.muted, self.locked, self.hidden)):
            raise TypeError("Les états de piste doivent être booléens")
        allowed = {
            TrackKind.VIDEO: {
                ClipKind.ARTWORK_2D,
                ClipKind.ARTWORK_3D,
                ClipKind.STILL,
                ClipKind.VIDEO,
            },
            TrackKind.EFFECT: {ClipKind.EFFECT_2D},
            TrackKind.AUDIO: {ClipKind.AUDIO},
        }[self.kind]
        for clip in self.clips:
            clip.validate()
            if clip.kind not in allowed:
                raise ValueError(
                    f"Le clip {clip.clip_id} de type {clip.kind.value} "
                    f"ne peut pas être placé sur une piste {self.kind.value}"
                )
            if self.kind != TrackKind.VIDEO and clip.camera is not None:
                raise ValueError("Seuls les clips vidéo peuvent porter une caméra")
        return self


@dataclass(frozen=True, slots=True)
class Transition:
    transition_id: str
    kind: TransitionKind
    from_clip_id: str
    to_clip_id: str
    start_frame: int
    duration_frames: int
    parameters: dict[str, Any] | None = None

    def validate(self) -> Transition:
        _identifier(self.transition_id, "transition.transition_id")
        _identifier(self.from_clip_id, "transition.from_clip_id")
        _identifier(self.to_clip_id, "transition.to_clip_id")
        if self.from_clip_id == self.to_clip_id:
            raise ValueError("Une transition doit relier deux clips différents")
        if not isinstance(self.kind, TransitionKind):
            raise TypeError("transition.kind doit être un TransitionKind")
        if isinstance(self.start_frame, bool) or not isinstance(self.start_frame, int):
            raise TypeError("transition.start_frame doit être un entier")
        if self.start_frame < 0:
            raise ValueError("transition.start_frame ne peut pas être négatif")
        if (
            isinstance(self.duration_frames, bool)
            or not isinstance(self.duration_frames, int)
            or self.duration_frames <= 0
        ):
            raise ValueError("transition.duration_frames doit être strictement positif")
        if self.kind == TransitionKind.CUT and self.duration_frames != 1:
            raise ValueError("Une transition cut occupe exactement une frame")
        if self.parameters is not None:
            _json_value(self.parameters, f"transition {self.transition_id}.parameters")
        return self


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration_frames: int = 360
    background: tuple[int, int, int] = (18, 18, 22)

    def validate(self) -> ProjectSettings:
        if self.width < 64 or self.height < 64 or self.width % 2 or self.height % 2:
            raise ValueError("Les dimensions du projet doivent être paires et au moins égales à 64")
        if self.fps not in {30, 60}:
            raise ValueError("Le Studio Reel prend en charge 30 ou 60 FPS")
        if self.duration_frames <= 0:
            raise ValueError("Le projet doit contenir au moins une frame")
        if len(self.background) != 3 or any(
            isinstance(channel, bool)
            or not isinstance(channel, int)
            or not 0 <= channel <= 255
            for channel in self.background
        ):
            raise ValueError("La couleur de fond doit contenir trois canaux RGB 0–255")
        return self


@dataclass(frozen=True, slots=True)
class ExportSettings:
    container: str = "mp4"
    crf: int = 16
    quality: str = "studio"
    audio_mode: AudioExportMode = AudioExportMode.REFERENCE

    def validate(self) -> ExportSettings:
        if self.container not in {"mp4", "mov", "webm"}:
            raise ValueError("Le conteneur Studio doit être mp4, mov ou webm")
        if isinstance(self.crf, bool) or not isinstance(self.crf, int) or not 0 <= self.crf <= 51:
            raise ValueError("export.crf doit être compris entre 0 et 51")
        if self.quality not in {"fast", "studio"}:
            raise ValueError("export.quality doit être fast ou studio")
        if not isinstance(self.audio_mode, AudioExportMode):
            raise TypeError("export.audio_mode doit être un AudioExportMode")
        return self


@dataclass(frozen=True, slots=True)
class StudioProject:
    project_id: str
    artwork: ArtworkAsset
    settings: ProjectSettings = ProjectSettings()
    assets: tuple[MediaAsset, ...] = ()
    tracks: tuple[Track, ...] = ()
    transitions: tuple[Transition, ...] = ()
    export: ExportSettings = ExportSettings()
    schema_version: int = STUDIO_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        artwork_path: str | Path,
        *,
        fps: int = 30,
        duration_seconds: int = 12,
    ) -> StudioProject:
        if duration_seconds <= 0:
            raise ValueError("La durée initiale doit être strictement positive")
        settings = ProjectSettings(
            fps=fps,
            duration_frames=fps * duration_seconds,
        )
        project = cls(
            project_id=uuid4().hex,
            artwork=ArtworkAsset(path=str(artwork_path)),
            settings=settings,
            tracks=(
                Track(
                    "video-main",
                    TrackKind.VIDEO,
                    "Œuvre",
                    (
                        Clip(
                            "artwork-main",
                            ClipKind.ARTWORK_2D,
                            0,
                            settings.duration_frames,
                            camera=CameraAnimation(
                                (CameraKeyframe(0, CameraPose()),)
                            ),
                        ),
                    ),
                ),
                Track("effects-main", TrackKind.EFFECT, "Effets"),
                Track("audio-main", TrackKind.AUDIO, "Musique"),
            ),
        )
        return project.validate()

    def validate(self) -> StudioProject:
        if self.schema_version != STUDIO_SCHEMA_VERSION:
            raise ValueError(
                f"Version de projet Studio {self.schema_version} non normalisée ; "
                "chargez le projet via StudioProject.from_dict pour le migrer"
            )
        _identifier(self.project_id, "project_id")
        self.artwork.validate()
        self.settings.validate()
        self.export.validate()

        asset_ids = {self.artwork.asset_id}
        asset_by_id: dict[str, MediaAsset] = {}
        for asset in self.assets:
            asset.validate()
            if asset.asset_id in asset_ids:
                raise ValueError(f"Identifiant d’asset dupliqué : {asset.asset_id}")
            asset_ids.add(asset.asset_id)
            asset_by_id[asset.asset_id] = asset

        track_ids: set[str] = set()
        clip_ids: set[str] = set()
        clip_by_id: dict[str, Clip] = {}
        for track in self.tracks:
            track.validate()
            if track.track_id in track_ids:
                raise ValueError(f"Identifiant de piste dupliqué : {track.track_id}")
            track_ids.add(track.track_id)
            for clip in track.clips:
                if clip.clip_id in clip_ids:
                    raise ValueError(f"Identifiant de clip dupliqué : {clip.clip_id}")
                clip_ids.add(clip.clip_id)
                clip_by_id[clip.clip_id] = clip
                if clip.end_frame > self.settings.duration_frames:
                    raise ValueError(f"Le clip {clip.clip_id} dépasse la durée du projet")
                expected_asset_kind = {
                    ClipKind.STILL: AssetKind.IMAGE,
                    ClipKind.VIDEO: AssetKind.VIDEO,
                    ClipKind.AUDIO: AssetKind.AUDIO,
                }.get(clip.kind)
                if expected_asset_kind is None:
                    if clip.asset_id is not None:
                        raise ValueError(
                            f"Le clip {clip.clip_id} est lié à l’œuvre centrale et "
                            "ne doit pas référencer un média externe"
                        )
                else:
                    if clip.asset_id is None or clip.asset_id not in asset_by_id:
                        raise ValueError(f"Asset introuvable pour le clip {clip.clip_id}")
                    if asset_by_id[clip.asset_id].kind != expected_asset_kind:
                        raise ValueError(f"Type d’asset incompatible pour le clip {clip.clip_id}")

        transition_ids: set[str] = set()
        for transition in self.transitions:
            transition.validate()
            if transition.transition_id in transition_ids:
                raise ValueError(
                    f"Identifiant de transition dupliqué : {transition.transition_id}"
                )
            transition_ids.add(transition.transition_id)
            if transition.from_clip_id not in clip_by_id or transition.to_clip_id not in clip_by_id:
                raise ValueError(
                    f"La transition {transition.transition_id} référence un clip introuvable"
                )
            if transition.start_frame + transition.duration_frames > self.settings.duration_frames:
                raise ValueError(
                    f"La transition {transition.transition_id} dépasse la durée du projet"
                )
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "artwork": _encode(self.artwork),
            "settings": _encode(self.settings),
            "assets": _encode(self.assets),
            "tracks": _encode(self.tracks),
            "transitions": _encode(self.transitions),
            "export": _encode(self.export),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StudioProject:
        values = migrate_project_payload(payload)
        _known_keys(
            values,
            {
                "schema_version",
                "project_id",
                "artwork",
                "settings",
                "assets",
                "tracks",
                "transitions",
                "export",
            },
            "StudioProject",
        )
        project = cls(
            schema_version=int(values["schema_version"]),
            project_id=values["project_id"],
            artwork=_artwork_from_dict(values["artwork"]),
            settings=_settings_from_dict(values.get("settings", {})),
            assets=tuple(_asset_from_dict(item) for item in values.get("assets", [])),
            tracks=tuple(_track_from_dict(item) for item in values.get("tracks", [])),
            transitions=tuple(
                _transition_from_dict(item) for item in values.get("transitions", [])
            ),
            export=_export_from_dict(values.get("export", {})),
        )
        return project.validate()


def _encode(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    return value


Migration = Callable[[dict[str, Any]], dict[str, Any]]
PROJECT_MIGRATIONS: dict[int, Migration] = {}


def migrate_project_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    values = _mapping(payload, "StudioProject")
    version = values.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("schema_version doit être un entier")
    if version > STUDIO_SCHEMA_VERSION:
        raise ValueError(
            f"Ce projet Studio nécessite une version plus récente (schéma {version})"
        )
    if version < 1:
        raise ValueError(f"Version de projet Studio invalide : {version}")
    while version < STUDIO_SCHEMA_VERSION:
        migration = PROJECT_MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(f"Migration Studio manquante depuis le schéma {version}")
        values = migration(dict(values))
        migrated_version = values.get("schema_version")
        if migrated_version != version + 1:
            raise ValueError("Une migration Studio n’a pas avancé exactement d’une version")
        version = migrated_version
    return values


def _artwork_from_dict(value: Any) -> ArtworkAsset:
    data = _mapping(value, "artwork")
    _known_keys(data, {"path", "asset_id", "fingerprint", "width", "height"}, "artwork")
    return ArtworkAsset(
        path=data["path"],
        asset_id=data.get("asset_id", "artwork"),
        fingerprint=data.get("fingerprint"),
        width=data.get("width"),
        height=data.get("height"),
    )


def _asset_from_dict(value: Any) -> MediaAsset:
    data = _mapping(value, "asset")
    _known_keys(
        data,
        {"asset_id", "kind", "path", "fingerprint", "width", "height", "metadata"},
        "asset",
    )
    return MediaAsset(
        asset_id=data["asset_id"],
        kind=_enum(AssetKind, data["kind"], "asset.kind"),
        path=data["path"],
        fingerprint=data.get("fingerprint"),
        width=data.get("width"),
        height=data.get("height"),
        metadata=data.get("metadata"),
    )


def _pose_from_dict(value: Any) -> CameraPose:
    data = _mapping(value, "camera.pose")
    _known_keys(
        data,
        {"x", "y", "zoom", "rotation_degrees", "perspective", "focus"},
        "camera.pose",
    )
    return CameraPose(**data)


def _camera_from_dict(value: Any) -> CameraAnimation:
    data = _mapping(value, "camera")
    _known_keys(data, {"keyframes"}, "camera")
    keyframes = []
    for item in data.get("keyframes", []):
        keyframe = _mapping(item, "camera.keyframe")
        _known_keys(keyframe, {"frame", "pose", "easing"}, "camera.keyframe")
        keyframes.append(
            CameraKeyframe(
                frame=keyframe["frame"],
                pose=_pose_from_dict(keyframe["pose"]),
                easing=_enum(
                    Easing,
                    keyframe.get("easing", Easing.EASE_IN_OUT.value),
                    "camera.keyframe.easing",
                ),
            )
        )
    return CameraAnimation(tuple(keyframes))


def _clip_from_dict(value: Any) -> Clip:
    data = _mapping(value, "clip")
    _known_keys(
        data,
        {
            "clip_id",
            "kind",
            "start_frame",
            "duration_frames",
            "source_in_frame",
            "asset_id",
            "opacity",
            "enabled",
            "fit",
            "camera",
            "parameters",
        },
        "clip",
    )
    return Clip(
        clip_id=data["clip_id"],
        kind=_enum(ClipKind, data["kind"], "clip.kind"),
        start_frame=data["start_frame"],
        duration_frames=data["duration_frames"],
        source_in_frame=data.get("source_in_frame", 0),
        asset_id=data.get("asset_id"),
        opacity=data.get("opacity", 1.0),
        enabled=data.get("enabled", True),
        fit=_enum(FitMode, data.get("fit", FitMode.CONTAIN.value), "clip.fit"),
        camera=_camera_from_dict(data["camera"]) if data.get("camera") is not None else None,
        parameters=data.get("parameters"),
    )


def _track_from_dict(value: Any) -> Track:
    data = _mapping(value, "track")
    _known_keys(
        data,
        {"track_id", "kind", "name", "clips", "muted", "locked", "hidden"},
        "track",
    )
    return Track(
        track_id=data["track_id"],
        kind=_enum(TrackKind, data["kind"], "track.kind"),
        name=data["name"],
        clips=tuple(_clip_from_dict(item) for item in data.get("clips", [])),
        muted=data.get("muted", False),
        locked=data.get("locked", False),
        hidden=data.get("hidden", False),
    )


def _transition_from_dict(value: Any) -> Transition:
    data = _mapping(value, "transition")
    _known_keys(
        data,
        {
            "transition_id",
            "kind",
            "from_clip_id",
            "to_clip_id",
            "start_frame",
            "duration_frames",
            "parameters",
        },
        "transition",
    )
    return Transition(
        transition_id=data["transition_id"],
        kind=_enum(TransitionKind, data["kind"], "transition.kind"),
        from_clip_id=data["from_clip_id"],
        to_clip_id=data["to_clip_id"],
        start_frame=data["start_frame"],
        duration_frames=data["duration_frames"],
        parameters=data.get("parameters"),
    )


def _settings_from_dict(value: Any) -> ProjectSettings:
    data = _mapping(value, "settings")
    _known_keys(data, {"width", "height", "fps", "duration_frames", "background"}, "settings")
    if "background" in data:
        data["background"] = tuple(data["background"])
    return ProjectSettings(**data)


def _export_from_dict(value: Any) -> ExportSettings:
    data = _mapping(value, "export")
    _known_keys(data, {"container", "crf", "quality", "audio_mode"}, "export")
    if "audio_mode" in data:
        data["audio_mode"] = _enum(AudioExportMode, data["audio_mode"], "export.audio_mode")
    return ExportSettings(**data)


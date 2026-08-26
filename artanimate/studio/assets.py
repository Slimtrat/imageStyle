from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from uuid import uuid4
import wave

from .image_io import load_normalized_image
from .model import ArtworkAsset, AssetKind, MediaAsset, StudioProject
from .persistence import normalize_project_path
from .video import inspect_video


FINGERPRINT_SAMPLE_BYTES = 1024 * 1024
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


@dataclass(frozen=True, slots=True)
class FileIdentity:
    size: int
    modified_ns: int
    fingerprint: str


class AssetAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    REPLACED = "replaced"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AssetCheck:
    state: AssetAvailability
    resolved_path: Path
    current: FileIdentity | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class FolderRelinkResult:
    relinked: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()


def fingerprint_file(path: str | Path) -> FileIdentity:
    source = Path(path)
    stat = source.stat()
    if not source.is_file():
        raise IsADirectoryError(f"Le média n’est pas un fichier : {source}")
    digest = sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with source.open("rb") as handle:
        digest.update(handle.read(FINGERPRINT_SAMPLE_BYTES))
        if stat.st_size > FINGERPRINT_SAMPLE_BYTES * 2:
            handle.seek(max(0, stat.st_size // 2 - FINGERPRINT_SAMPLE_BYTES // 2))
            digest.update(handle.read(FINGERPRINT_SAMPLE_BYTES))
        if stat.st_size > FINGERPRINT_SAMPLE_BYTES:
            handle.seek(max(0, stat.st_size - FINGERPRINT_SAMPLE_BYTES))
            digest.update(handle.read(FINGERPRINT_SAMPLE_BYTES))
    return FileIdentity(
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        fingerprint=f"sha256-sampled:{digest.hexdigest()}",
    )


def resolve_asset_path(stored_path: str, project_path: str | Path) -> Path:
    source = Path(stored_path)
    if source.is_absolute():
        return source.resolve(strict=False)
    project = normalize_project_path(project_path)
    return (project.parent / source).resolve(strict=False)


def stored_asset_path(source: str | Path, project_path: str | Path) -> str:
    absolute = Path(source).resolve(strict=False)
    project_dir = normalize_project_path(project_path).parent.resolve(strict=False)
    try:
        return absolute.relative_to(project_dir).as_posix()
    except ValueError:
        # External and cross-drive assets stay absolute. A future explicit
        # consolidation command can copy and rewrite them.
        return str(absolute)


def _extensions(kind: AssetKind) -> set[str]:
    return {
        AssetKind.IMAGE: IMAGE_EXTENSIONS,
        AssetKind.VIDEO: VIDEO_EXTENSIONS,
        AssetKind.AUDIO: AUDIO_EXTENSIONS,
    }[kind]


def asset_kind_for_path(path: str | Path) -> AssetKind:
    suffix = Path(path).suffix.casefold()
    for kind in AssetKind:
        if suffix in _extensions(kind):
            return kind
    supported = sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS)
    raise ValueError(
        f"Extension {suffix or 'absente'} non prise en charge. "
        f"Formats acceptés : {', '.join(supported)}"
    )


def _validate_kind(path: Path, kind: AssetKind) -> tuple[int | None, int | None]:
    if path.suffix.lower() not in _extensions(kind):
        raise ValueError(
            f"Extension {path.suffix or 'absente'} incompatible avec un média {kind.value}"
        )
    if kind == AssetKind.AUDIO and path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as source:
                if source.getframerate() <= 0 or source.getnchannels() <= 0:
                    raise ValueError("WAV local sans format audio exploitable")
        except (EOFError, OSError, wave.Error) as exc:
            raise ValueError(f"Audio WAV local illisible : {path}") from exc
    if kind == AssetKind.VIDEO:
        inspection = inspect_video(path, count_frames=False)
        return inspection.width, inspection.height
    if kind != AssetKind.IMAGE:
        return None, None
    image, _inspection = load_normalized_image(path)
    return image.size


def _image_metadata(path: Path) -> dict[str, object]:
    _image, inspection = load_normalized_image(path)
    return inspection.metadata()


def _audio_metadata(path: Path) -> dict[str, int | float]:
    if path.suffix.lower() != ".wav":
        return {}
    with wave.open(str(path), "rb") as source:
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        return {
            "duration_seconds": frame_count / sample_rate,
            "sample_rate": sample_rate,
            "channels": source.getnchannels(),
            "sample_width_bytes": source.getsampwidth(),
        }


def _video_metadata(path: Path) -> dict[str, object]:
    return inspect_video(path, count_frames=True).metadata()


def import_media_asset(
    path: str | Path,
    kind: AssetKind,
    project_path: str | Path,
    *,
    asset_id: str | None = None,
) -> MediaAsset:
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise IsADirectoryError(f"Le média n’est pas un fichier : {source}")
    width, height = _validate_kind(source, kind)
    identity = fingerprint_file(source)
    return MediaAsset(
        asset_id=asset_id or uuid4().hex,
        kind=kind,
        path=stored_asset_path(source, project_path),
        fingerprint=identity.fingerprint,
        width=width,
        height=height,
        metadata={
            "file_size": identity.size,
            "modified_ns": identity.modified_ns,
            **(_audio_metadata(source) if kind == AssetKind.AUDIO else {}),
            **(_image_metadata(source) if kind == AssetKind.IMAGE else {}),
            **(_video_metadata(source) if kind == AssetKind.VIDEO else {}),
        },
    ).validate()


def import_artwork_asset(
    path: str | Path,
    project_path: str | Path,
    *,
    asset_id: str = "artwork",
) -> ArtworkAsset:
    source = Path(path).resolve(strict=True)
    width, height = _validate_kind(source, AssetKind.IMAGE)
    identity = fingerprint_file(source)
    return ArtworkAsset(
        path=stored_asset_path(source, project_path),
        asset_id=asset_id,
        fingerprint=identity.fingerprint,
        width=width,
        height=height,
    ).validate()


def register_media_asset(
    project: StudioProject,
    path: str | Path,
    project_path: str | Path,
) -> tuple[StudioProject, MediaAsset, bool]:
    """Register a reference only; identical media reuse their existing asset id."""

    kind = asset_kind_for_path(path)
    imported = import_media_asset(path, kind, project_path)
    existing = next(
        (
            asset
            for asset in project.assets
            if asset.kind == imported.kind
            and asset.fingerprint == imported.fingerprint
        ),
        None,
    )
    if existing is not None:
        return project, existing, False
    updated = replace(project, assets=(*project.assets, imported)).validate()
    return updated, imported, True


def check_media_asset(asset: MediaAsset, project_path: str | Path) -> AssetCheck:
    path = resolve_asset_path(asset.path, project_path)
    if not path.exists():
        return AssetCheck(AssetAvailability.MISSING, path, message="Média introuvable")
    if not path.is_file():
        return AssetCheck(AssetAvailability.INVALID, path, message="Le chemin est un dossier")
    try:
        _validate_kind(path, asset.kind)
        current = fingerprint_file(path)
    except (OSError, ValueError) as exc:
        return AssetCheck(AssetAvailability.INVALID, path, message=str(exc))
    if asset.fingerprint is not None and current.fingerprint != asset.fingerprint:
        return AssetCheck(
            AssetAvailability.REPLACED,
            path,
            current=current,
            message="Le contenu du média a changé depuis son import",
        )
    return AssetCheck(AssetAvailability.AVAILABLE, path, current=current)


def check_artwork_asset(asset: ArtworkAsset, project_path: str | Path) -> AssetCheck:
    path = resolve_asset_path(asset.path, project_path)
    proxy = MediaAsset(
        asset_id=asset.asset_id,
        kind=AssetKind.IMAGE,
        path=asset.path,
        fingerprint=asset.fingerprint,
        width=asset.width,
        height=asset.height,
    )
    return check_media_asset(proxy, project_path)


def relink_media_asset(
    project: StudioProject,
    asset_id: str,
    new_path: str | Path,
    project_path: str | Path,
) -> StudioProject:
    replacement_index = next(
        (index for index, asset in enumerate(project.assets) if asset.asset_id == asset_id),
        None,
    )
    if replacement_index is None:
        raise KeyError(f"Asset Studio introuvable : {asset_id}")
    previous = project.assets[replacement_index]
    replacement = import_media_asset(
        new_path,
        previous.kind,
        project_path,
        asset_id=previous.asset_id,
    )
    assets = list(project.assets)
    assets[replacement_index] = replacement
    return replace(project, assets=tuple(assets)).validate()


def relink_artwork_asset(
    project: StudioProject,
    new_path: str | Path,
    project_path: str | Path,
) -> StudioProject:
    artwork = import_artwork_asset(
        new_path,
        project_path,
        asset_id=project.artwork.asset_id,
    )
    updated = replace(project, artwork=artwork).validate()
    from .analysis import invalidate_stale_scene_analysis

    return invalidate_stale_scene_analysis(updated)


def find_relink_candidates(
    asset: MediaAsset,
    roots: Iterable[str | Path],
) -> tuple[Path, ...]:
    filename = Path(asset.path).name
    matches: list[Path] = []
    for root_value in roots:
        root = Path(root_value)
        if not root.exists() or not root.is_dir():
            continue
        for candidate in root.rglob(filename):
            try:
                if not candidate.is_file():
                    continue
                _validate_kind(candidate, asset.kind)
                identity = fingerprint_file(candidate)
            except (OSError, ValueError):
                continue
            if asset.fingerprint is None or identity.fingerprint == asset.fingerprint:
                matches.append(candidate.resolve())
    return tuple(sorted(set(matches), key=lambda path: str(path).casefold()))


def relink_project_from_folders(
    project: StudioProject,
    roots: Iterable[str | Path],
    project_path: str | Path,
) -> tuple[StudioProject, FolderRelinkResult]:
    """Relink unambiguous missing/replaced references without copying any media."""

    roots = tuple(Path(root) for root in roots)
    updated = project
    relinked: list[str] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []

    artwork_check = check_artwork_asset(updated.artwork, project_path)
    if artwork_check.state != AssetAvailability.AVAILABLE:
        artwork_proxy = MediaAsset(
            asset_id=updated.artwork.asset_id,
            kind=AssetKind.IMAGE,
            path=updated.artwork.path,
            fingerprint=updated.artwork.fingerprint,
            width=updated.artwork.width,
            height=updated.artwork.height,
        )
        candidates = find_relink_candidates(artwork_proxy, roots)
        if len(candidates) == 1:
            updated = relink_artwork_asset(updated, candidates[0], project_path)
            relinked.append(updated.artwork.asset_id)
        elif len(candidates) > 1:
            ambiguous.append(updated.artwork.asset_id)
        else:
            unresolved.append(updated.artwork.asset_id)

    for original in project.assets:
        current = next(
            asset for asset in updated.assets if asset.asset_id == original.asset_id
        )
        check = check_media_asset(current, project_path)
        if check.state == AssetAvailability.AVAILABLE:
            continue
        candidates = find_relink_candidates(current, roots)
        if len(candidates) == 1:
            updated = relink_media_asset(
                updated,
                current.asset_id,
                candidates[0],
                project_path,
            )
            relinked.append(current.asset_id)
        elif len(candidates) > 1:
            ambiguous.append(current.asset_id)
        else:
            unresolved.append(current.asset_id)

    return updated, FolderRelinkResult(
        relinked=tuple(relinked),
        unresolved=tuple(unresolved),
        ambiguous=tuple(ambiguous),
    )


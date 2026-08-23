from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .model import ArtworkAsset, AssetKind, MediaAsset, StudioProject
from .persistence import normalize_project_path


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


def _validate_kind(path: Path, kind: AssetKind) -> tuple[int | None, int | None]:
    if path.suffix.lower() not in _extensions(kind):
        raise ValueError(
            f"Extension {path.suffix or 'absente'} incompatible avec un média {kind.value}"
        )
    if kind != AssetKind.IMAGE:
        return None, None
    try:
        with Image.open(path) as image:
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            return oriented.size
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Image locale illisible : {path}") from exc


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
    return replace(project, artwork=artwork).validate()


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


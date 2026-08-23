from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from .model import StudioProject


PROJECT_SUFFIX = ".artanimate"


def normalize_project_path(path: str | Path) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != PROJECT_SUFFIX:
        destination = destination.with_suffix(PROJECT_SUFFIX)
    return destination


def autosave_path(project_path: str | Path) -> Path:
    source = normalize_project_path(project_path)
    return source.with_name(f"{source.stem}.autosave{PROJECT_SUFFIX}")


def _serialized(project: StudioProject) -> str:
    return json.dumps(
        project.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def project_digest(project: StudioProject) -> str:
    canonical = json.dumps(
        project.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _atomic_write(destination: Path, text: str) -> Path:
    parent = destination.parent
    if not parent.exists():
        raise FileNotFoundError(f"Dossier de projet introuvable : {parent}")
    if not parent.is_dir():
        raise NotADirectoryError(f"La destination du projet n’est pas un dossier : {parent}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
        return destination
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def save_project(
    project: StudioProject,
    path: str | Path,
    *,
    clear_autosave: bool = True,
) -> Path:
    destination = normalize_project_path(path)
    text = _serialized(project)
    result = _atomic_write(destination, text)
    if clear_autosave:
        autosave_path(destination).unlink(missing_ok=True)
    return result


def save_autosave(project: StudioProject, project_path: str | Path) -> Path:
    destination = autosave_path(project_path)
    return _atomic_write(destination, _serialized(project))


def load_project(path: str | Path) -> StudioProject:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Projet Studio JSON invalide dans {source} : {exc}") from exc
    return StudioProject.from_dict(payload)


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    project_path: Path
    autosave_path: Path
    project: StudioProject
    autosave_modified_ns: int


def find_recovery(project_path: str | Path) -> RecoveryCandidate | None:
    source = normalize_project_path(project_path)
    recovery = autosave_path(source)
    if not recovery.exists():
        return None
    recovery_stat = recovery.stat()
    if source.exists() and recovery_stat.st_mtime_ns <= source.stat().st_mtime_ns:
        return None
    return RecoveryCandidate(
        project_path=source,
        autosave_path=recovery,
        project=load_project(recovery),
        autosave_modified_ns=recovery_stat.st_mtime_ns,
    )


def discard_recovery(project_path: str | Path) -> None:
    autosave_path(project_path).unlink(missing_ok=True)


@dataclass(slots=True)
class ProjectSession:
    """Tracks the saved identity of an immutable StudioProject."""

    project: StudioProject
    path: Path | None = None
    _saved_digest: str | None = None

    @classmethod
    def new(cls, project: StudioProject) -> ProjectSession:
        return cls(project=project)

    @classmethod
    def loaded(cls, project: StudioProject, path: str | Path) -> ProjectSession:
        return cls(
            project=project,
            path=normalize_project_path(path),
            _saved_digest=project_digest(project),
        )

    @property
    def dirty(self) -> bool:
        return self._saved_digest != project_digest(self.project)

    def update(self, project: StudioProject) -> None:
        self.project = project.validate()

    def mark_saved(self, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = normalize_project_path(path)
        if self.path is None:
            raise ValueError("Un projet sans chemin ne peut pas être marqué comme enregistré")
        self._saved_digest = project_digest(self.project)


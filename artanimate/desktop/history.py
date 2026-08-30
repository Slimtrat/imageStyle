from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..core.config import RenderConfig


if TYPE_CHECKING:
    from PySide6.QtGui import QImage


logger = logging.getLogger(__name__)

HISTORY_SCHEMA_VERSION = 2
LEGACY_HISTORY_SCHEMA_VERSION = 1
DEFAULT_HISTORY_LIMIT = 40


class GenerationType(StrEnum):
    ATELIER_2D = "atelier_2d"
    STUDIO_3D = "studio_3d"
    STUDIO = "studio"


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """Persistent pointer to one successfully generated video and its settings."""

    id: str
    created_at: str
    output: str
    source: str
    effect: str
    effect_label: str
    config: dict[str, Any]
    thumbnail: str | None = None
    generation_type: str = GenerationType.ATELIER_2D.value
    project: str | None = None
    project_id: str | None = None

    @property
    def output_path(self) -> Path:
        return Path(self.output)

    @property
    def source_path(self) -> Path:
        return Path(self.source)

    @property
    def thumbnail_path(self) -> Path | None:
        return Path(self.thumbnail) if self.thumbnail else None

    @property
    def project_path(self) -> Path | None:
        return Path(self.project) if self.project else None

    @property
    def project_available(self) -> bool:
        path = self.project_path
        return path is not None and path.is_file()

    @property
    def is_studio_project(self) -> bool:
        return self.generation_type == GenerationType.STUDIO.value

    @property
    def available(self) -> bool:
        return self.output_path.is_file()

    @property
    def display_date(self) -> str:
        try:
            return datetime.fromisoformat(self.created_at).strftime("%d/%m/%Y · %H:%M")
        except ValueError:
            return self.created_at

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationRecord":
        required = {
            "id",
            "created_at",
            "output",
            "source",
            "effect",
            "effect_label",
            "config",
        }
        missing = required - payload.keys()
        if missing or not isinstance(payload.get("config"), dict):
            raise ValueError(f"Entrée d’historique invalide, champs manquants : {sorted(missing)}")
        generation_type = payload.get("generation_type")
        if generation_type is None:
            generation_type = (
                GenerationType.STUDIO_3D.value
                if str(payload["effect_label"]).startswith("Studio 3D")
                else GenerationType.ATELIER_2D.value
            )
        return cls(
            id=str(payload["id"]),
            created_at=str(payload["created_at"]),
            output=str(payload["output"]),
            source=str(payload["source"]),
            effect=str(payload["effect"]),
            effect_label=str(payload["effect_label"]),
            config=dict(payload["config"]),
            thumbnail=str(payload["thumbnail"]) if payload.get("thumbnail") else None,
            generation_type=str(generation_type),
            project=(
                str(payload["project"]) if payload.get("project") else None
            ),
            project_id=str(payload["project_id"]) if payload.get("project_id") else None,
        )


class GenerationHistory:
    """Atomic JSON history with lightweight cached thumbnails, never video copies."""

    def __init__(self, root: Path, limit: int = DEFAULT_HISTORY_LIMIT):
        if limit <= 0:
            raise ValueError("La limite d’historique doit être positive")
        self.root = root.resolve()
        self.limit = limit
        self.manifest_path = self.root / "history.json"
        self.thumbnail_root = self.root / "thumbnails"

    def load(self) -> tuple[GenerationRecord, ...]:
        if not self.manifest_path.is_file():
            return ()
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Historique illisible : %s", exc)
            return ()
        if not isinstance(payload, dict):
            logger.warning("Historique invalide : objet racine absent")
            return ()
        if payload.get("schema_version") not in {
            LEGACY_HISTORY_SCHEMA_VERSION,
            HISTORY_SCHEMA_VERSION,
        }:
            logger.warning(
                "Version d’historique non prise en charge : %s",
                payload.get("schema_version"),
            )
            return ()
        raw_records = payload.get("generations")
        if not isinstance(raw_records, list):
            logger.warning("Historique invalide : liste de générations absente")
            return ()
        records: list[GenerationRecord] = []
        for raw in raw_records:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("entrée non objet")
                records.append(GenerationRecord.from_dict(raw))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Entrée d’historique ignorée : %s", exc)
        logger.info("Historique chargé : %d génération(s)", len(records))
        return tuple(records[: self.limit])

    def add(
        self,
        output: Path,
        source: Path,
        config: RenderConfig,
        effect_label: str,
        thumbnail: "QImage | None" = None,
    ) -> GenerationRecord:
        output = output.resolve()
        source = source.resolve()
        record_id = uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self._save_thumbnail(record_id, thumbnail)

        record = GenerationRecord(
            id=record_id,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output=str(output),
            source=str(source),
            effect=config.effect,
            effect_label=effect_label,
            config=config.to_dict(),
            thumbnail=str(thumbnail_path) if thumbnail_path else None,
            generation_type=(
                GenerationType.STUDIO_3D.value
                if effect_label.startswith("Studio 3D")
                else GenerationType.ATELIER_2D.value
            ),
        )
        return self._store(record)

    def add_studio(
        self,
        output: Path,
        source: Path,
        *,
        project_id: str,
        export_config: dict[str, Any],
        project_path: Path | None = None,
        thumbnail: "QImage | None" = None,
    ) -> GenerationRecord:
        """Add one successful Studio Reel, linked to but independent from its project."""

        output = output.resolve()
        source = source.resolve()
        saved_project = project_path.resolve() if project_path is not None else None
        record_id = uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self._save_thumbnail(record_id, thumbnail)
        record = GenerationRecord(
            id=record_id,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output=str(output),
            source=str(source),
            effect="studio.reel",
            effect_label="Studio · Reel final",
            config=dict(export_config),
            thumbnail=str(thumbnail_path) if thumbnail_path else None,
            generation_type=GenerationType.STUDIO.value,
            project=str(saved_project) if saved_project is not None else None,
            project_id=str(project_id),
        )
        return self._store(record)

    def _save_thumbnail(
        self,
        record_id: str,
        thumbnail: "QImage | None",
    ) -> Path | None:
        if thumbnail is None or thumbnail.isNull():
            return None
        self.thumbnail_root.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self.thumbnail_root / f"{record_id}.jpg"
        if not thumbnail.save(str(thumbnail_path), "JPG", 84):
            logger.warning("Vignette d’historique non enregistrée : %s", thumbnail_path)
            thumbnail_path.unlink(missing_ok=True)
            return None
        return thumbnail_path

    def _store(self, record: GenerationRecord) -> GenerationRecord:
        output = record.output_path
        previous = self.load()
        replaced = [item for item in previous if item.output_path == output]
        deduplicated = [item for item in previous if item.output_path != output]
        records = [record, *deduplicated]
        discarded = records[self.limit :]
        records = records[: self.limit]
        try:
            self._write(records)
        except (OSError, TypeError, ValueError):
            self._remove_thumbnail(record)
            raise
        for item in [*replaced, *discarded]:
            self._remove_thumbnail(item)
        logger.info("Génération ajoutée à l’historique : %s", output)
        return record

    def remove(self, output: Path) -> bool:
        """Remove one history reference and its cached thumbnail, never another file."""
        output = output.resolve()
        records = list(self.load())
        removed = [item for item in records if item.output_path == output]
        if not removed:
            return False
        remaining = [item for item in records if item.output_path != output]
        self.root.mkdir(parents=True, exist_ok=True)
        self._write(remaining)
        for item in removed:
            self._remove_thumbnail(item)
        logger.info("Génération retirée de l’historique : %s", output)
        return True

    def _write(self, records: list[GenerationRecord]) -> None:
        payload = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "generations": [asdict(record) for record in records],
        }
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.manifest_path)

    def _remove_thumbnail(self, record: GenerationRecord) -> None:
        thumbnail = record.thumbnail_path
        if thumbnail is None:
            return
        try:
            resolved = thumbnail.resolve()
            resolved.relative_to(self.thumbnail_root)
            resolved.unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.warning("Vignette historique impossible à nettoyer : %s", thumbnail)

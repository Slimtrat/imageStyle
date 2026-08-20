from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..core.config import RenderConfig


if TYPE_CHECKING:
    from PySide6.QtGui import QImage


logger = logging.getLogger(__name__)

HISTORY_SCHEMA_VERSION = 1
DEFAULT_HISTORY_LIMIT = 40


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
        return cls(
            id=str(payload["id"]),
            created_at=str(payload["created_at"]),
            output=str(payload["output"]),
            source=str(payload["source"]),
            effect=str(payload["effect"]),
            effect_label=str(payload["effect_label"]),
            config=dict(payload["config"]),
            thumbnail=str(payload["thumbnail"]) if payload.get("thumbnail") else None,
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
        if payload.get("schema_version") != HISTORY_SCHEMA_VERSION:
            logger.warning("Version d’historique non prise en charge")
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
        thumbnail_path: Path | None = None
        self.root.mkdir(parents=True, exist_ok=True)
        if thumbnail is not None and not thumbnail.isNull():
            self.thumbnail_root.mkdir(parents=True, exist_ok=True)
            thumbnail_path = self.thumbnail_root / f"{record_id}.jpg"
            if not thumbnail.save(str(thumbnail_path), "JPG", 84):
                logger.warning("Vignette d’historique non enregistrée : %s", thumbnail_path)
                thumbnail_path = None

        record = GenerationRecord(
            id=record_id,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output=str(output),
            source=str(source),
            effect=config.effect,
            effect_label=effect_label,
            config=config.to_dict(),
            thumbnail=str(thumbnail_path) if thumbnail_path else None,
        )
        previous = self.load()
        replaced = [item for item in previous if item.output_path == output]
        deduplicated = [item for item in previous if item.output_path != output]
        records = [record, *deduplicated]
        discarded = records[self.limit :]
        records = records[: self.limit]
        self._write(records)
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

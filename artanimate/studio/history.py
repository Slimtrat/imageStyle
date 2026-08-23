from __future__ import annotations

from dataclasses import dataclass

from .model import StudioProject
from .persistence import project_digest


@dataclass(frozen=True, slots=True)
class StudioCommand:
    """One reversible replacement of the immutable Studio project."""

    before: StudioProject
    after: StudioProject
    label: str
    merge_key: str | None = None


class StudioHistory:
    """Bounded, in-memory command history for an artwork-first project."""

    def __init__(self, max_entries: int = 200):
        if max_entries < 1:
            raise ValueError("L’historique doit conserver au moins une commande")
        self.max_entries = int(max_entries)
        self._current: StudioProject | None = None
        self._undo: list[StudioCommand] = []
        self._redo: list[StudioCommand] = []

    @property
    def current(self) -> StudioProject | None:
        return self._current

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def reset(self, project: StudioProject | None) -> None:
        self._current = project.validate() if project is not None else None
        self._undo.clear()
        self._redo.clear()

    def commit(
        self,
        project: StudioProject,
        label: str,
        *,
        merge_key: str | None = None,
    ) -> bool:
        after = project.validate()
        before = self._current
        if before is None or before.project_id != after.project_id:
            self.reset(after)
            return False
        if project_digest(before) == project_digest(after):
            self._current = after
            return False

        normalized_label = " ".join(str(label).split())
        if not normalized_label:
            raise ValueError("Une commande Studio doit avoir un libellé")
        command = StudioCommand(before, after, normalized_label, merge_key)
        if (
            merge_key is not None
            and self._undo
            and self._undo[-1].merge_key == merge_key
            and project_digest(self._undo[-1].after) == project_digest(before)
        ):
            previous = self._undo[-1]
            self._undo[-1] = StudioCommand(
                previous.before,
                after,
                normalized_label,
                merge_key,
            )
        else:
            self._undo.append(command)
            if len(self._undo) > self.max_entries:
                del self._undo[: len(self._undo) - self.max_entries]
        self._redo.clear()
        self._current = after
        return True

    def undo(self) -> StudioProject:
        if not self._undo:
            raise IndexError("Aucune commande Studio à annuler")
        command = self._undo.pop()
        self._redo.append(command)
        self._current = command.before
        return command.before

    def redo(self) -> StudioProject:
        if not self._redo:
            raise IndexError("Aucune commande Studio à rétablir")
        command = self._redo.pop()
        self._undo.append(command)
        self._current = command.after
        return command.after

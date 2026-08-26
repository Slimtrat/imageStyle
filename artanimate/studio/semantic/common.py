from __future__ import annotations

from collections.abc import Iterator, Mapping
import math
import re
from typing import Any, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = Any

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


def identifier(value: str, where: str = "identifiant") -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{where} doit contenir 1 à 200 caractères alphanumériques, ".strip()
            + "avec '.', '_', ':', '/', ou '-' comme séparateurs"
        )
    return value


def finite_number(value: int | float, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where} doit être numérique")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{where} doit être fini")
    return result


def confidence(value: int | float, where: str = "confidence") -> float:
    result = finite_number(value, where)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{where} doit être compris entre 0 et 1")
    return result


def _freeze_json(value: Any, where: str) -> JsonValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} contient une valeur flottante non finie")
        return value
    if isinstance(value, Mapping):
        return FrozenJsonObject(value, where=where)
    if isinstance(value, list | tuple):
        return tuple(
            _freeze_json(item, f"{where}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(
        f"{where} contient un type non sérialisable : {type(value).__name__}"
    )


def thaw_json(value: JsonValue) -> Any:
    if isinstance(value, FrozenJsonObject):
        return value.to_dict()
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


class FrozenJsonObject(Mapping[str, JsonValue]):
    """Deeply immutable, hashable and JSON-safe mapping used by domain contracts."""

    __slots__ = ("_items", "_lookup", "_hash")

    def __init__(
        self,
        values: Mapping[str, Any] | None = None,
        *,
        where: str = "objet JSON",
    ) -> None:
        source = values or {}
        if not isinstance(source, Mapping):
            raise TypeError(f"{where} doit être un objet JSON")
        frozen: list[tuple[str, JsonValue]] = []
        for key in sorted(source):
            if not isinstance(key, str):
                raise TypeError(f"{where} contient une clé non textuelle")
            frozen.append((key, _freeze_json(source[key], f"{where}.{key}")))
        self._items = tuple(frozen)
        self._lookup = dict(frozen)
        self._hash = hash(self._items)

    def __getitem__(self, key: str) -> JsonValue:
        return self._lookup[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"FrozenJsonObject({self.to_dict()!r})"

    def to_dict(self) -> dict[str, Any]:
        return {key: thaw_json(value) for key, value in self._items}


EMPTY_JSON = FrozenJsonObject()

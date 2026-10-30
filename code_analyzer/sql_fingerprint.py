"""The Fingerprint of one Database (ADR-0045, amendment of 2026-10-30).

A Fingerprint is a small summary that Impact reads from the system catalog of
SQL Server. It holds, for each kind group, the object count and the latest
`modify_date`. The kind groups are the four object lists of a SQL cache:
procedures (`P`), views (`V`), functions (`FN`, `IF`, `TF`), and tables (`U`).

Impact compares two Fingerprints only for equality. It never orders them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

# (kind group, the `sys.objects.type` values of the group). The kind values are
# the keys of the SQL cache payload, in the order the dump reports them, and the
# field names of a Fingerprint.
KIND_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("procedures", ("P",)),
    ("views", ("V",)),
    ("functions", ("FN", "IF", "TF")),
    ("tables", ("U",)),
)

_KIND_OF_TYPE: Dict[str, str] = {
    object_type: kind for kind, object_types in KIND_GROUPS for object_type in object_types
}

# One catalog row: (`sys.objects.type`, object count, latest `modify_date`).
CatalogRow = Tuple[str, int, datetime]


def object_types() -> Tuple[str, ...]:
    """Every `sys.objects.type` value of the kind groups, in group order."""
    return tuple(object_type for _, group_types in KIND_GROUPS for object_type in group_types)


def object_types_of(kind: str) -> Tuple[str, ...]:
    """The `sys.objects.type` values of one kind group."""
    return dict(KIND_GROUPS)[kind]


@dataclass(frozen=True)
class FingerprintEntry:
    """One kind group: the object count and the latest `modify_date` (None when the group is empty)."""

    count: int = 0
    latest_modified: Optional[datetime] = None

    def with_row(self, count: int, latest_modified: datetime) -> "FingerprintEntry":
        latest = latest_modified if self.latest_modified is None else max(self.latest_modified, latest_modified)
        return FingerprintEntry(count=self.count + count, latest_modified=latest)

    def to_dict(self) -> Dict[str, object]:
        latest = "" if self.latest_modified is None else self.latest_modified.isoformat(timespec="microseconds")
        return {"count": self.count, "latest_modified": latest}

    @classmethod
    def from_dict(cls, entry: Dict[str, Any]) -> "FingerprintEntry":
        """The reverse of `to_dict()`. A malformed entry raises."""
        latest = str(entry["latest_modified"] or "")
        return cls(count=int(entry["count"]), latest_modified=datetime.fromisoformat(latest) if latest else None)


@dataclass(frozen=True)
class Fingerprint:
    """One entry for each kind group. Two Fingerprints are equal only when every entry is equal."""

    procedures: FingerprintEntry = field(default_factory=FingerprintEntry)
    views: FingerprintEntry = field(default_factory=FingerprintEntry)
    functions: FingerprintEntry = field(default_factory=FingerprintEntry)
    tables: FingerprintEntry = field(default_factory=FingerprintEntry)

    @classmethod
    def from_rows(cls, rows: Iterable[CatalogRow]) -> "Fingerprint":
        """Put each catalog row in its kind group. A type outside the groups counts nowhere.

        SQL Server returns `type` as char(2), so a one-letter type ends with a space.
        """
        entries = {kind: FingerprintEntry() for kind, _ in KIND_GROUPS}
        for object_type, count, latest_modified in rows:
            kind = _KIND_OF_TYPE.get(str(object_type or "").strip())
            if kind is not None:
                entries[kind] = entries[kind].with_row(int(count), latest_modified)
        return cls(**entries)

    def to_dict(self) -> Dict[str, Dict[str, object]]:
        """The form the Scan Record holds beside `saved_at`."""
        return {entry.name: getattr(self, entry.name).to_dict() for entry in fields(self)}

    @classmethod
    def from_dict(cls, recorded: Dict[str, Dict[str, Any]]) -> "Fingerprint":
        """The reverse of `to_dict()`: the Fingerprint that a Scan Record holds. A malformed form raises."""
        return cls(**{entry.name: FingerprintEntry.from_dict(recorded[entry.name]) for entry in fields(cls)})


# The kind groups and the fields of a Fingerprint are one list: a rename of one
# without the other fails at import, not in a scan. An `if`, not an `assert`, so
# that `python -O` keeps the check.
if [kind for kind, _ in KIND_GROUPS] != [entry.name for entry in fields(Fingerprint)]:
    raise RuntimeError("KIND_GROUPS and the fields of Fingerprint differ")

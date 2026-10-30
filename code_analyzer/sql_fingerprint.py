"""The Fingerprint of one Database (`.scratch/sql-cache-behind-source/`).

A Fingerprint is a small summary that Impact reads from the system catalog of
SQL Server. It holds, for each kind group, the object count and the latest
`modify_date`. The kind groups are the four object lists of a SQL cache:
procedures (`P`), views (`V`), functions (`FN`, `IF`, `TF`), and tables (`U`).

Impact compares two Fingerprints only for equality. It never orders them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Dict, Optional, Tuple

# (kind group, the `sys.objects.type` values of the group). The kind values are
# the keys of the SQL cache payload, in the order the dump reports them.
KIND_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("procedures", ("P",)),
    ("views", ("V",)),
    ("functions", ("FN", "IF", "TF")),
    ("tables", ("U",)),
)

_KIND_OF_TYPE: Dict[str, str] = {
    object_type: kind for kind, object_types in KIND_GROUPS for object_type in object_types
}


def kind_of(object_type: str) -> Optional[str]:
    """The kind group of one `sys.objects.type` value, or None for a type outside the groups.

    SQL Server returns `type` as char(2), so a one-letter type ends with a space.
    """
    return _KIND_OF_TYPE.get(str(object_type or "").strip())


@dataclass(frozen=True)
class FingerprintEntry:
    """One kind group: the object count and the latest `modify_date` (None when the group is empty)."""

    count: int = 0
    latest_modified: Optional[datetime] = None

    def to_json(self) -> Dict[str, object]:
        latest = "" if self.latest_modified is None else self.latest_modified.isoformat(timespec="microseconds")
        return {"count": self.count, "latest_modified": latest}


@dataclass(frozen=True)
class Fingerprint:
    """One entry for each kind group. Two Fingerprints are equal only when every entry is equal."""

    procedures: FingerprintEntry = field(default_factory=FingerprintEntry)
    views: FingerprintEntry = field(default_factory=FingerprintEntry)
    functions: FingerprintEntry = field(default_factory=FingerprintEntry)
    tables: FingerprintEntry = field(default_factory=FingerprintEntry)

    def to_json(self) -> Dict[str, Dict[str, object]]:
        """The form the Scan Record holds beside `saved_at`."""
        return {entry.name: getattr(self, entry.name).to_json() for entry in fields(self)}

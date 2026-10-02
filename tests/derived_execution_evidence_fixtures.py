"""Snapshot/restore helper for the retained Derived Execution Evidence (ticket 04/06).

Mirrors tests/sql_cache_fixtures.py's CacheRoot: the evidence retention is
process-global state, so a test that populates it must not leak into the next
one, the same way the SQL cache's in-memory retention already does not. Since
ticket 06, that retention has a disk-backed second tier
(`derived_execution_evidence_store`, see ADR-0017) which is just as much
process-global state -- pointed by default at the real
`settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT` -- so this fixture isolates
both tiers together: a test using it never reads a file a previous test (or a
real run of the service) left behind, and never leaves one behind for the
next test or for the real store to trip over.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from service import derived_execution_evidence


class RatedInvocationsRetention:
    """Clear the in-memory retention and point the disk store at a temp dir,
    on entry; restore both on exit."""

    def __enter__(self) -> "RatedInvocationsRetention":
        self._previous = dict(derived_execution_evidence._retention)
        derived_execution_evidence._retention.clear()
        self._previous_store_root = settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT = self._tmp.name
        return self

    def __exit__(self, *exc: object) -> None:
        derived_execution_evidence._retention.clear()
        derived_execution_evidence._retention.update(self._previous)
        settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT = self._previous_store_root
        self._tmp.cleanup()

    def simulate_restart(self) -> None:
        """Drop the in-memory retention only. The disk store stays, as a real
        process restart leaves it."""
        derived_execution_evidence._retention.clear()

    @property
    def store_root(self) -> Path:
        """The temp dir the disk store is currently pointed at."""
        return Path(self._tmp.name)

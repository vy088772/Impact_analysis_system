"""Snapshot/restore helper for the retained Derived Execution Evidence (ticket 04).

Mirrors tests/sql_cache_fixtures.py's CacheRoot: the rating step's retention is
process-global state, so a test that populates it must not leak into the next
one, the same way the SQL cache's in-memory retention already does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import analyze_service


class RatedInvocationsRetention:
    """Clear `_rated_invocations_retention` on entry, restore it on exit."""

    def __enter__(self) -> dict:
        self._previous = dict(analyze_service._rated_invocations_retention)
        analyze_service._rated_invocations_retention.clear()
        return analyze_service._rated_invocations_retention

    def __exit__(self, *exc: object) -> None:
        analyze_service._rated_invocations_retention.clear()
        analyze_service._rated_invocations_retention.update(self._previous)

"""Shared temp-cache-root helpers for the SQL cache tests.

tests/test_sql_cache_store.py and tests/test_sql_execution_graph.py both need a
throwaway SQL cache directory and a cache file pair inside it; they share these
rather than each hand-rolling the save-and-restore boilerplate.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from service import sql_cache_store


class CacheRoot:
    """Point settings.SQL_CACHE_ROOT at a temp dir and clear the in-process cache."""

    def __enter__(self) -> Path:
        self._previous_root = settings.SQL_CACHE_ROOT
        self._previous_mem = dict(sql_cache_store._mem_cache)
        self._tmp = tempfile.TemporaryDirectory()
        settings.SQL_CACHE_ROOT = self._tmp.name
        sql_cache_store._mem_cache.clear()
        return Path(self._tmp.name)

    def __exit__(self, *exc: object) -> None:
        settings.SQL_CACHE_ROOT = self._previous_root
        sql_cache_store._mem_cache.clear()
        sql_cache_store._mem_cache.update(self._previous_mem)
        self._tmp.cleanup()


def assert_relationships_resolve_to_known_nodes(graph: dict) -> None:
    """Every relationship target in ``graph`` must name a node the same graph holds.

    A relationship target with no matching node silently unresolves the whole
    Execution Path it belongs to (reverse-lookup-drops-proven-writes, ticket
    01) -- this is the structural invariant that repair restores. Call it over
    every graph a test builds, not only a graph built to reproduce the defect.
    """
    node_ids = {node["id"] for node in graph["nodes"] if node.get("id")}
    dangling = sorted(
        {
            (relationship.get("type"), relationship.get("target"))
            for relationship in graph["relationships"]
            if relationship.get("target") not in node_ids
        }
    )
    assert not dangling, f"relationship targets with no matching node: {dangling}"


def write_cache(
    cache_root: Path,
    key: str,
    payload: dict,
    cache_version: int | None = None,
) -> None:
    """Write one cache file pair under ``key`` — a legacy key or a new one.

    The meta file carries no ``server``: a cache written before ticket 02 has
    none, and the reader must accept that rather than reject the file.
    """
    (cache_root / f"{key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_root / f"{key}.meta.json").write_text(
        json.dumps(
            {
                "cache_version": (
                    sql_cache_store._SQL_CACHE_VERSION
                    if cache_version is None
                    else cache_version
                ),
                "database": payload["database"],
                "schema": payload["schema"],
                "saved_at": "2026-08-04 13:29:13",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

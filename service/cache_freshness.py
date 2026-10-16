"""Cache Freshness: the state of each SQL cache and each C# Scan Result (Impact ADR-0045).

The states are `current`, `outdated`, `refreshing` and `behind_source`. This module computes
`current`, `outdated` and `refreshing`; `behind_source` comes with the update page's check
(ticket 08).

- `outdated`: the cache is missing, invalid, or has an old format version.
- `refreshing`: a Refresh Job for the cache runs now. A waiting job changes nothing.
- A failed job changes nothing either: the state is the state of the cache on disk.

The module only reads. It never scans, clones, pulls or connects to a database.
A cache that several systems share is computed once per listing and shows the same state
under each system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional

from . import refresh_queue, repo_manager, scan_store, sql_cache_store

CURRENT = "current"
OUTDATED = "outdated"
REFRESHING = "refreshing"


def _state(has_usable_cache: bool, last_job: Optional[dict]) -> str:
    if last_job is not None and last_job["status"] == refresh_queue.RUNNING:
        return REFRESHING
    return CURRENT if has_usable_cache else OUTDATED


def _row(
    *,
    kind: str,
    key: str,
    label: str,
    has_usable_cache: bool,
    last_scanned_at: Optional[str],
    **identity: Any,
) -> dict[str, Any]:
    last_job = refresh_queue.shared_queue.latest_for_key(key)
    return {
        "kind": kind,
        "key": key,
        "label": label,
        "freshness": _state(has_usable_cache, last_job),
        "last_scanned_at": last_scanned_at,
        "last_job": last_job,
        **identity,
    }


def sql_row(server: str, database: str) -> Optional[dict[str, Any]]:
    """The row of one SQL cache, or None when the catalog names no usable (server, database)."""
    try:
        identity = sql_cache_store.CacheIdentity.of(server, database)
    except ValueError:
        return None
    usable = sql_cache_store.load_cached(identity) is not None
    return _row(
        kind="sql",
        key=refresh_queue.sql_key(identity.key),
        label=identity.database,
        has_usable_cache=usable,
        last_scanned_at=sql_cache_store.cached_saved_at(identity),
        server=identity.server,
        database=identity.database,
    )


def csharp_row(system_id: str, scan_roots: Iterable[Path]) -> dict[str, Any]:
    """The row of one C# Scan Result. It is `current` only when every scan root is.

    The scan time is the oldest one on disk, so an `outdated` cache still shows when it was last scanned."""
    roots = list(scan_roots)
    usable = all(scan_store.load_cached(root) is not None for root in roots)
    saved = [scan_store.cached_saved_at(root) for root in roots]
    return _row(
        kind="csharp",
        key=refresh_queue.csharp_key(str(root) for root in roots),
        label=system_id,
        has_usable_cache=usable,
        last_scanned_at=min((stamp for stamp in saved if stamp), default=None),
        system_id=system_id,
    )


def list_by_system(catalog_systems: Iterable[dict]) -> List[dict[str, Any]]:
    """Every cache of every catalog system, grouped by system, in catalog order."""
    shared_sql: dict[tuple[str, str], Optional[dict[str, Any]]] = {}
    grouped: List[dict[str, Any]] = []
    for system in catalog_systems:
        system_id = str(system.get("system_id") or "").strip()
        if not system_id:
            continue
        caches: List[dict[str, Any]] = []
        azure = system.get("azure") or {}
        if isinstance(azure, dict) and str(azure.get("repo") or "").strip():
            caches.append(csharp_row(system_id, repo_manager.peek_scan_roots(azure)))
        for declared in system.get("databases") or []:
            if not isinstance(declared, dict):
                continue
            pair = (str(declared.get("server") or ""), str(declared.get("name") or ""))
            if pair not in shared_sql:
                shared_sql[pair] = sql_row(*pair)
            row = shared_sql[pair]
            if row is not None and all(row["key"] != seen["key"] for seen in caches):
                caches.append(row)
        grouped.append({"system_id": system_id, "caches": caches})
    return grouped

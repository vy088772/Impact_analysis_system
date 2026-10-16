"""Cache Freshness: the state of each SQL cache and each C# Scan Result (Impact ADR-0045).

The states are `current`, `outdated`, `refreshing` and `behind_source`. This module computes
`current`, `outdated` and `refreshing` from the caches and the queue, and `behind_source`
from the last remote check (`source_check`).

- `outdated`: the cache is missing, invalid, or has an old format version.
- `refreshing`: a Refresh Job for the cache runs now. A waiting job changes nothing.
- A failed job changes nothing either: the state is the state of the cache on disk.
- `behind_source`: a usable C# Scan Result whose recorded commit differs from the remote head
  that the last check found. SQL caches never get it. `outdated` and `refreshing` win.

The module only reads. It never scans, clones, pulls or connects to a database.
A cache that several systems share is computed once per listing and shows the same state
under each system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional

from . import refresh_queue, repo_manager, scan_store, source_check, sql_cache_store
from .schemas import RefreshRequest, RefreshSqlRequest, UpdateAllRequest

CURRENT = "current"
OUTDATED = "outdated"
REFRESHING = "refreshing"
BEHIND_SOURCE = "behind_source"


def _job_is_running(last_job: Optional[dict]) -> bool:
    return last_job is not None and last_job["status"] == refresh_queue.RUNNING


def _state(has_usable_cache: bool, last_job: Optional[dict], behind_source: bool = False) -> str:
    if _job_is_running(last_job):
        return REFRESHING
    if not has_usable_cache:
        return OUTDATED
    return BEHIND_SOURCE if behind_source else CURRENT


def _row(
    *,
    kind: str,
    key: str,
    label: str,
    has_usable_cache: bool,
    last_scanned_at: Optional[str],
    behind_source: bool = False,
    **identity: Any,
) -> dict[str, Any]:
    last_job = refresh_queue.shared_queue.latest_for_key(key)
    return {
        "kind": kind,
        "key": key,
        "label": label,
        "freshness": _state(has_usable_cache, last_job, behind_source),
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


def _is_behind_source(source: dict, scan_roots: Iterable[Path]) -> bool:
    """True when the last check found a remote head that differs from a recorded commit."""
    head = source_check.remote_head(source)
    if head is None:
        return False
    recorded = [scan_store.cached_commit(root) for root in scan_roots]
    return any(commit and commit != head for commit in recorded)


def csharp_row(
    system_id: str, scan_roots: Iterable[Path], source: Optional[dict] = None
) -> dict[str, Any]:
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
        behind_source=usable and source is not None and _is_behind_source(source, roots),
        system_id=system_id,
    )


def _unusable(kind: str, key: str, state: str, **identity: str) -> dict[str, Any]:
    return {"kind": kind, "key": key, "state": state, **identity}


def _is_running(key: str) -> bool:
    return _job_is_running(refresh_queue.shared_queue.latest_for_key(key))


def csharp_refreshing(scan_roots: Iterable[Path]) -> Optional[dict[str, Any]]:
    """The report of a C# Scan Result whose Refresh Job runs, or None. It reads no cache file."""
    key = refresh_queue.csharp_key(str(root) for root in scan_roots)
    return _unusable("csharp", key, REFRESHING) if _is_running(key) else None


def csharp_outdated(scan_roots: Iterable[Path]) -> dict[str, Any]:
    """The report of a C# Scan Result that a question could not read."""
    return _unusable("csharp", refresh_queue.csharp_key(str(root) for root in scan_roots), OUTDATED)


def sql_unusable(identity: sql_cache_store.CacheIdentity) -> Optional[dict[str, Any]]:
    """The report of a SQL cache that a question must not read, or None.

    A running Refresh Job gives `refreshing`. A cache with a file on disk that is not usable
    gives `outdated`. A cache that was never scanned gives None: that is the normal "not scanned"
    state of a lookup, with its own reason. A usable cache gives None.
    """
    key = refresh_queue.sql_key(identity.key)
    fields = {"server": identity.server, "database": identity.database}
    if _is_running(key):
        return _unusable("sql", key, REFRESHING, **fields)
    if sql_cache_store.has_cache_files(identity) and sql_cache_store.load_cached(identity) is None:
        return _unusable("sql", key, OUTDATED, **fields)
    return None


def azure_source_of(system: dict) -> Optional[dict]:
    """The Azure source of a catalog system, or None when the system has no repository."""
    azure = system.get("azure") or {}
    if isinstance(azure, dict) and str(azure.get("repo") or "").strip():
        return azure
    return None


def sources_of(catalog_systems: Iterable[dict]) -> List[dict]:
    """The Azure source of each catalog system that has a repository."""
    return [azure for azure in map(azure_source_of, catalog_systems) if azure is not None]


def list_by_system(catalog_systems: Iterable[dict]) -> List[dict[str, Any]]:
    """Every cache of every catalog system, grouped by system, in catalog order."""
    shared_sql: dict[tuple[str, str], Optional[dict[str, Any]]] = {}
    grouped: List[dict[str, Any]] = []
    for system in catalog_systems:
        system_id = str(system.get("system_id") or "").strip()
        if not system_id:
            continue
        caches: List[dict[str, Any]] = []
        azure = azure_source_of(system)
        if azure is not None:
            caches.append(csharp_row(system_id, repo_manager.peek_scan_roots(azure), azure))
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


def update_all_requests(
    catalog_systems: Iterable[dict], req: UpdateAllRequest
) -> List[RefreshSqlRequest | RefreshRequest]:
    """The refresh request of each `outdated` cache, in catalog order, one per shared cache."""
    catalog = list(catalog_systems)
    azure_of = {str(system.get("system_id") or "").strip(): azure_source_of(system) or {} for system in catalog}
    requests: List[RefreshSqlRequest | RefreshRequest] = []
    seen: set[str] = set()
    for system in list_by_system(catalog):
        for row in system["caches"]:
            if row["freshness"] != OUTDATED or row["key"] in seen:
                continue
            seen.add(row["key"])
            if row["kind"] == "sql":
                override = req.sql_credentials.get(row["server"])
                requests.append(
                    RefreshSqlRequest(
                        database=sql_cache_store.CacheIdentity.of(row["server"], row["database"]).key,
                        server=row["server"],
                        db_name=row["database"],
                        db_user_id=override.db_user_id if override else "",
                        db_password=override.db_password if override else "",
                    )
                )
                continue
            azure = azure_of[row["system_id"]]
            requests.append(
                RefreshRequest(
                    system=row["system_id"],
                    source={field: str(azure.get(field) or "") for field in ("project", "repo", "branch", "path")},
                    wrapper_contract=req.wrapper_contracts.get(row["system_id"]) or "",
                )
            )
    return requests

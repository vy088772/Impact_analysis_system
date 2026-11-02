"""Cache Freshness: the state of each SQL cache and each C# Scan Result (Impact ADR-0045).

The states are `current`, `outdated`, `refreshing` and `behind_source`. This module computes
`current`, `outdated` and `refreshing` from the caches and the queue, and `behind_source`
from the last remote check (`source_check`).

- `outdated`: the cache is missing, invalid, or has an old format version.
- `refreshing`: a Refresh Job for the cache runs now. A waiting job changes nothing.
- A failed job changes nothing either: the state is the state of the cache on disk.
- `behind_source`: a usable C# Scan Result whose recorded commit differs from the remote head
  that the last check found, or a usable SQL cache whose recorded Fingerprint differs from the
  current Fingerprint that the last check read. `outdated` and `refreshing` win.

The module only reads. It never scans, clones, pulls or connects to a database. It names the
repositories (`csharp_check_targets`) and the SQL caches (`sql_check_targets`) that the check
reads, because it knows which rows are usable and not locked. The check itself runs in `source_check`.
A cache that several systems share is computed once per listing and shows the same state
under each system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from . import environment_check, refresh_queue, repo_manager, scan_store, source_check, sql_cache_store
from .system_targets import azure_source_of, declared_databases, sources_of
from .schemas import RefreshRequest, RefreshSqlRequest, SqlCredentialOverride, UpdateAllRequest

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
    locked_reason: str,
    behind_source: bool = False,
    source_check_failure: str = "",
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
        "locked_reason": locked_reason,
        "source_check_failure": source_check_failure,
        **identity,
    }


def sql_row(server: str, database: str) -> Optional[dict[str, Any]]:
    """The row of one SQL cache, or None when the catalog names no usable (server, database)."""
    try:
        identity = sql_cache_store.CacheIdentity.of(server, database)
    except ValueError:
        return None
    usable = sql_cache_store.load_cached(identity) is not None
    locked_reason = environment_check.sql_lock_reason(identity.server)
    # A lock that arrives after the check hides what the check read: the Fingerprint and the failure.
    checked = usable and not locked_reason
    return _row(
        kind="sql",
        key=refresh_queue.sql_key(identity.key),
        label=identity.database,
        has_usable_cache=usable,
        last_scanned_at=sql_cache_store.cached_saved_at(identity),
        locked_reason=locked_reason,
        behind_source=checked and _sql_is_behind_source(identity),
        source_check_failure=source_check.fingerprint_failure(identity) if checked else "",
        server=identity.server,
        database=identity.database,
    )


def _sql_is_behind_source(identity: sql_cache_store.CacheIdentity) -> bool:
    """True when the last check read a current Fingerprint that differs from the recorded one.

    No current Fingerprint (no check, a read failure, a locked row) and no recorded
    Fingerprint (a scan that could not read one) both give False."""
    current = source_check.current_fingerprint(identity)
    if current is None:
        return False
    recorded = sql_cache_store.cached_fingerprint(identity)
    return recorded is not None and recorded != current


def sql_check_targets(
    catalog_systems: Iterable[dict],
    sql_credentials: Optional[Mapping[str, SqlCredentialOverride]] = None,
) -> Dict[sql_cache_store.CacheIdentity, sql_cache_store.ScanConnection]:
    """The SQL caches that the `behind_source` check reads, each with its Scan Connection: each
    declared cache that is usable and not locked, one time each (a shared cache too).

    The Scan Connection holds the server of the catalog, as a refresh of the cache does, so a
    named instance (`host\\instance`) connects. It holds the scan account override of the server
    from `sql_credentials`, keyed by the `server` of a listing row, as in "update all" (ADR-0010).
    A server with no key gets the global scan account."""
    scan_accounts = sql_credentials or {}
    targets: dict[sql_cache_store.CacheIdentity, sql_cache_store.ScanConnection] = {}
    for system in catalog_systems:
        for server, database in declared_databases(system):
            try:
                identity = sql_cache_store.CacheIdentity.of(server, database)
            except ValueError:
                continue
            if identity in targets or environment_check.sql_lock_reason(identity.server):
                continue
            if sql_cache_store.load_cached(identity) is not None:
                account = scan_accounts.get(identity.server) or SqlCredentialOverride()
                targets[identity] = sql_cache_store.ScanConnection(server, account.db_user_id, account.db_password)
    return targets


def csharp_check_targets(catalog_systems: Iterable[dict]) -> List[dict]:
    """The Azure sources that the `behind_source` check asks the remote for: each source that
    is not locked. A locked row stays out, because its Lock Reason already explains it."""
    return [source for source in sources_of(catalog_systems) if not environment_check.csharp_lock_reason(source)]


def _is_behind_source(source: dict, scan_roots: Iterable[Path]) -> bool:
    """True when the last check found a remote head that differs from a recorded commit."""
    head = source_check.remote_head(source)
    if head is None:
        return False
    recorded = [scan_store.cached_commit(root) for root in scan_roots]
    return any(commit and commit != head for commit in recorded)


def _source_paths(source: Optional[dict]) -> List[str]:
    """The catalog folders of a source: one name, a list, or none (the whole repository)."""
    declared = (source or {}).get("path") or []
    names = [declared] if isinstance(declared, str) else declared
    return [str(name).strip() for name in names if str(name).strip()]


def csharp_row(
    system_id: str, scan_roots: Iterable[Path], source: Optional[dict] = None
) -> dict[str, Any]:
    """The row of one C# Scan Result. It is `current` only when every scan root is.

    The scan time is the oldest one on disk, so an `outdated` cache still shows when it was last scanned.
    `repo` and `paths` tell the page what the scan covers: an empty `paths` is the whole repository."""
    roots = list(scan_roots)
    usable = all(scan_store.load_cached(root) is not None for root in roots)
    saved = [scan_store.cached_saved_at(root) for root in roots]
    locked_reason = environment_check.csharp_lock_reason(source)
    # A lock that arrives after the check hides what the check read, as for SQL. A locked row gets
    # no failure either: its Lock Reason already explains it.
    checked = usable and not locked_reason and source is not None
    return _row(
        kind="csharp",
        key=refresh_queue.csharp_key(str(root) for root in roots),
        label=system_id,
        has_usable_cache=usable,
        last_scanned_at=min((stamp for stamp in saved if stamp), default=None),
        locked_reason=locked_reason,
        behind_source=checked and _is_behind_source(source, roots),
        source_check_failure=source_check.remote_failure(source) if checked else "",
        system_id=system_id,
        repo=str((source or {}).get("repo") or "").strip(),
        paths=_source_paths(source),
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


def list_by_system(catalog_systems: Iterable[dict]) -> List[dict[str, Any]]:
    """Every cache of every catalog system, grouped by system, in catalog order, each system with
    the time of its last `behind_source` check."""
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
        for pair in declared_databases(system):
            if pair not in shared_sql:
                shared_sql[pair] = sql_row(*pair)
            row = shared_sql[pair]
            if row is not None and all(row["key"] != seen["key"] for seen in caches):
                caches.append(row)
        grouped.append(
            {"system_id": system_id, "caches": caches, "source_checked_at": source_check.checked_at(system_id)}
        )
    return grouped


def update_all_requests(
    catalog_systems: Iterable[dict], req: UpdateAllRequest
) -> List[RefreshSqlRequest | RefreshRequest]:
    """The refresh request of each `outdated` cache, in catalog order, one per shared cache.

    A row that the last Environment Check locks gets no request."""
    catalog = list(catalog_systems)
    azure_of = {str(system.get("system_id") or "").strip(): azure_source_of(system) or {} for system in catalog}
    requests: List[RefreshSqlRequest | RefreshRequest] = []
    seen: set[str] = set()
    for system in list_by_system(catalog):
        for row in system["caches"]:
            if row["freshness"] != OUTDATED or row["locked_reason"] or row["key"] in seen:
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

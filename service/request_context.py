"""Prepare source scans and an evidence scope without building an API response."""

import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from code_analyzer.project_scanner import ProjectScanResult
from .derived_execution_evidence import DerivedExecutionEvidenceScope
from . import cache_freshness
from .request_context_adapters import CacheIdentityResult, CacheStore, ScanStore
from .scan_store import ScanOutdated
from .sql_cache_store import CacheIdentity


@dataclass(frozen=True)
class Skipped:
    pass


@dataclass(frozen=True)
class Unusable:
    """A cache that the question needs is `outdated` or `refreshing` (ADR-0045).

    ``caches`` are the typed reports of those caches. The handler answers with them
    and reads nothing.
    """

    caches: list[dict]


@dataclass(frozen=True)
class NoRepository:
    """The request's source names no repository, so it has no scan root.

    Such a system has no C# Scan Result, so there is no cache to report. The handler answers
    with an empty result, never `skipped` and never `outdated`.
    """


@dataclass(frozen=True)
class RequestContext:
    roots: list[Path]
    scans: list[ProjectScanResult]
    scan: ProjectScanResult
    root: Path
    sql_cache_identity: CacheIdentityResult
    scope: DerivedExecutionEvidenceScope


def cache_identity_of(request: object, cache_store: CacheStore) -> CacheIdentityResult:
    """The SQL Cache Identity that a request routes to: its host and Database, or a lookup by name."""
    database = getattr(request, "database", "")
    server = getattr(request, "db_server", "")
    return (
        CacheIdentity.of(server, database)
        if server.strip() and database.strip()
        else cache_store.find_cache_identity(database)
    )


def evidence_root(roots: list[Path], source: dict, scan_store: ScanStore) -> Path:
    """The root that rating reads relative paths against: the one scan root, or the repository root."""
    return (
        roots[0] if len(roots) == 1
        else scan_store.repo_dir(str(source["project"]), str(source["repo"]))
    )


def build_request_context(
    request: object,
    *,
    scan_store: ScanStore,
    cache_store: CacheStore,
    check_identity: Callable[[CacheIdentityResult], None] | None = None,
    check_roots: Callable[[list[Path]], None] | None = None,
) -> RequestContext | Skipped | Unusable | NoRepository:
    """Look up the identity, apply the handler's refusal, then read the scans.

    A question never rebuilds a cache (ADR-0045): ``request.refresh`` neither scans nor pulls here.
    A source without a repository returns NoRepository, or Unusable for its SQL cache.
    A cache-only miss returns Skipped before root resolution or reading.
    A C# Scan Result or a SQL cache that is `outdated` or `refreshing` returns Unusable.
    The context retains the raw identity result; an ambiguous result has no scope identity.
    """
    identity = cache_identity_of(request, cache_store)
    if check_identity is not None:
        check_identity(identity)
    source = scan_store.resolve_source(request)
    # Paths only: a question never clones, pulls or scans (ADR-0045).
    roots = scan_store.peek_scan_roots(source)
    if roots and getattr(request, "cache_only", False):
        gate = _unusable_candidates(scan_store, roots)
        if gate is not None:
            return gate
    if check_roots is not None:
        check_roots(roots)
    sql_report = _sql_report(getattr(request, "database", ""), identity)
    if not roots:
        return Unusable([sql_report]) if sql_report is not None else NoRepository()
    refreshing = cache_freshness.csharp_refreshing(roots)
    if refreshing is not None or sql_report is not None:
        return Unusable([report for report in (refreshing, sql_report) if report is not None])
    scans: list[ProjectScanResult] = []
    for root in roots:
        try:
            scans.append(scan_store.read_scan(root))
        except ScanOutdated:
            return Unusable([cache_freshness.csharp_outdated(roots)])
    scan = scans[0] if len(scans) == 1 else merge_scans(scans)
    root = evidence_root(roots, source, scan_store)
    scope = DerivedExecutionEvidenceScope.of(
        request, roots, identity if isinstance(identity, CacheIdentity) else None
    )
    return RequestContext(roots, scans, scan, root, identity, scope)


def _sql_report(database: str, identity: CacheIdentityResult) -> dict | None:
    """The `outdated` or `refreshing` report of the request's SQL cache, or None.

    A request that names no Database reads no SQL cache, so it has no SQL cache to report.
    """
    if database.strip() and isinstance(identity, CacheIdentity):
        return cache_freshness.sql_unusable(identity)
    return None


def _unusable_candidates(scan_store: ScanStore, candidates: list[Path]) -> Unusable | Skipped | None:
    """The cache-only gate: what a lookup answers before it reads any scan.

    None when every candidate root has a usable cache. A root with no cache file at all is
    "not scanned" (Skipped), the normal daily state. A root whose cache exists but is not
    usable is `outdated`, and a root whose Refresh Job runs is `refreshing`.
    """
    refreshing = cache_freshness.csharp_refreshing(candidates)
    if refreshing is not None:
        return Unusable([refreshing])
    without_cache = [root for root in candidates if not scan_store.has_cache(root)]
    if not without_cache:
        return None
    if any(scan_store.cache_status(root) != "missing" for root in without_cache):
        return Unusable([cache_freshness.csharp_outdated(candidates)])
    return Skipped()


def merge_scans(scans: list[ProjectScanResult]) -> ProjectScanResult:
    """Merge scans while preserving their source locations and recorded facts."""
    merged = ProjectScanResult(
        project_root=" + ".join(scan.project_root for scan in scans),
        project_name=scans[0].project_name if scans else "",
        scan_time=max((scan.scan_time for scan in scans), default=datetime.now()),
    )
    scan_roots = [str(Path(scan.project_root).resolve()) for scan in scans if scan.project_root]
    try:
        canonical_root = Path(os.path.commonpath(scan_roots)).resolve()
    except (ValueError, IndexError):
        canonical_root = None
    for scan in scans:
        merged.total_files += scan.total_files
        merged.scanned_files += scan.scanned_files
        merged.failed_files += scan.failed_files
        merged.csharp_results.extend(scan.csharp_results)
        for key, snapshot in getattr(scan, "source_snapshots", {}).items():
            relative_path = str(snapshot.relative_path or key).replace("\\", "/")
            if canonical_root is not None:
                source_path = Path(scan.project_root) / relative_path
                try:
                    relative_path = source_path.resolve().relative_to(canonical_root).as_posix()
                except ValueError:
                    pass
            merged.source_snapshots[relative_path] = replace(snapshot, relative_path=relative_path)
        merged.db_invocations.update(getattr(scan, "db_invocations", {}))
        merged.connection_sources.update(getattr(scan, "connection_sources", {}))
        merged.contract_preflight_proposals.extend(getattr(scan, "contract_preflight_proposals", []) or [])
        merged.contract_proposals.extend(getattr(scan, "contract_proposals", []) or [])
        merged.verified_implementation_snapshots.extend(getattr(scan, "verified_implementation_snapshots", []) or [])
        merged.semantic_binding_availability.extend(getattr(scan, "semantic_binding_availability", []) or [])
        merged.framework_reports.extend(getattr(scan, "framework_reports", []) or [])
        merged.unresolved_connections.update(getattr(scan, "unresolved_connections", {}) or {})
        merged.connection_observations.extend(getattr(scan, "connection_observations", []) or [])
        merged.aspx_results.extend(scan.aspx_results)
        merged.razor_results.extend(scan.razor_results)
        merged.vue_results.extend(scan.vue_results)
        merged.sp_relations.extend(scan.sp_relations)
        merged.legacy_sp_relations.extend(getattr(scan, "legacy_sp_relations", []) or [])
        merged.table_relations.extend(scan.table_relations)
    merged.calculate_statistics()
    return merged
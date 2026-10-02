"""Prepare source scans and an evidence scope without building an API response."""

import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from code_analyzer.project_scanner import ProjectScanResult
from .derived_execution_evidence import DerivedExecutionEvidenceScope
from .request_context_adapters import CacheIdentityResult, CacheStore, ScanStore
from .sql_cache_store import CacheIdentity


@dataclass(frozen=True)
class Skipped:
    pass


@dataclass(frozen=True)
class RequestContext:
    roots: list[Path]
    scans: list[ProjectScanResult]
    scan: ProjectScanResult
    root: Path
    sql_cache_identity: CacheIdentityResult
    scope: DerivedExecutionEvidenceScope


def build_request_context(
    request: object,
    *,
    scan_store: ScanStore,
    cache_store: CacheStore,
    check_identity: Callable[[CacheIdentityResult], None] | None = None,
) -> RequestContext | Skipped:
    """Look up the identity, apply the handler's refusal, then prepare the scans.

    A cache-only miss returns Skipped before root resolution or scanning.
    The context retains the raw identity result; an ambiguous result has no scope identity.
    """
    database = getattr(request, "database", "")
    server = getattr(request, "db_server", "")
    identity = (
        CacheIdentity.of(server, database)
        if server.strip() and database.strip()
        else cache_store.find_cache_identity(database)
    )
    if check_identity is not None:
        check_identity(identity)
    refresh = getattr(request, "refresh", False)
    source = scan_store.resolve_source(request)
    if getattr(request, "cache_only", False) and not refresh:
        candidates = scan_store.peek_scan_roots(source)
        if not all(scan_store.has_cache(root) for root in candidates):
            return Skipped()
    roots = scan_store.resolve_scan_roots(source, refresh=refresh)
    scans = [scan_store.get_scan(root, refresh=refresh) for root in roots]
    scan = scans[0] if len(scans) == 1 else merge_scans(scans)
    root = (
        roots[0] if len(roots) == 1
        else scan_store.repo_dir(str(source["project"]), str(source["repo"]))
    )
    scope = DerivedExecutionEvidenceScope.of(
        request, roots, identity if isinstance(identity, CacheIdentity) else None
    )
    return RequestContext(roots, scans, scan, root, identity, scope)


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
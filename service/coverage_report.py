"""The Coverage Report: per System, how far the analysis actually got.

Two ratios are reported, never one. The measured repositories have opposite
bottlenecks -- one resolves almost no Executed Procedure Name, another resolves
almost no Resolved Connection Source -- and a combined number would hide which
one is stuck.

Every Database Invocation below either line names its reason. A ratio alone
cannot tell a resolution that improved from one that merely became confident,
so the reason codes are what make the number actionable.

This module builds and renders the report. It never scans and never reads
configuration: the caller hands it a scan result and the SP Catalog, so the same
measurement runs against a cached scan and against a fresh one without knowing
which it was given.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    DbInvocation,
    SpCatalog,
)
from code_analyzer.project_scanner import ProjectScanResult

# The two ratios. They are two keys, never one, so no caller can add them up.
PROCEDURE_NAME_RATIO = "executed_procedure_name"
CONNECTION_SOURCE_RATIO = "resolved_connection_source"

# Reason codes this report names itself. Every other code it reports comes from
# the analysis that produced the invocation -- `command_text_method_parameter`,
# `root_configuration_namespace_not_connection_strings`,
# `no_project_connection_scope` and the rest keep the names their own rule gave
# them, so a number here and a log line there read as the same fact.
NO_SEMANTIC_MODEL = "no_semantic_model"
PROCEDURE_NAME_UNRESOLVED = "procedure_name_unresolved"
CONNECTION_SOURCE_UNRESOLVED = "connection_source_unresolved"
AMBIGUOUS_CONNECTION_SOURCE = "ambiguous_connection_source"
NO_CONNECTION_EXPRESSION = "no_connection_expression"

SEMANTIC_BINDING_AVAILABLE = "available"

# The procedure-name absences a missing semantic model actually produces: a value
# the tracer could not follow, and a receiver type Roslyn could not bind. A named
# contract gap or a command text that arrives as a method parameter is a fact
# about the call, not about the model, so it keeps its own name either way.
_MODEL_SHAPED_PROCEDURE_REASONS = frozenset(
    {
        "dynamic_command_text",
        "receiver_type_missing",
        "declaring_type_unresolved",
    }
)


def rate_scan_invocations(
    root: Path,
    scan: ProjectScanResult,
    *,
    catalog: SpCatalog,
    external_wrapper_contract: Optional[Mapping[str, Any]] = None,
    contract_registry: Optional[Mapping[str, Any]] = None,
    wrapper_review_exclusions: Iterable[Mapping[str, Any]] = (),
    explicit_contract: Optional[Mapping[str, Any] | str] = None,
) -> Dict[str, List[DbInvocation]]:
    """Rate every raw C# fact one scan holds, keyed by the source file that holds it.

    The connection lookup table is the one the scan itself resolved, not the one
    an `/analyze` request would remap onto its selected SQL cache scope. This
    report measures what the analysis reached, so a connection that names a
    database nobody has scanned still counts as resolved.
    """
    connection_sources_by_file = getattr(scan, "connection_sources", {}) or {}
    rated: Dict[str, List[DbInvocation]] = {}
    for file_key, raw_invocations in (getattr(scan, "db_invocations", {}) or {}).items():
        if not raw_invocations:
            continue
        gateway = CSharpAnalysisGateway(
            catalog,
            connection_sources=dict(connection_sources_by_file.get(file_key) or {}),
            external_wrapper_contract=external_wrapper_contract,
            external_wrapper_contracts=contract_registry,
            wrapper_review_exclusions=wrapper_review_exclusions,
        )
        rated[file_key] = gateway.resolve_direct_invocations(
            _relative_path(file_key, root),
            list(raw_invocations),
            scan_root=str(root),
            explicit_contract=explicit_contract,
        )
    return rated


def semantic_binding_state(scan: ProjectScanResult, source_file: str) -> str:
    """The Semantic Binding Availability of the project that holds one source file.

    A source file belongs to the nearest project file above it, so the longest
    reported project directory that the source path runs through wins. Paths are
    matched by whole path segments on either side, because the C# host may report
    a project relative to the clone root while the scan reports the file
    absolutely. Returns `""` when no reported project covers the file -- an
    unknown state is not an unavailable one.
    """
    source = _normalized_path(source_file)
    best_directory = ""
    best_state = ""
    for entry in getattr(scan, "semantic_binding_availability", []) or []:
        if not isinstance(entry, Mapping):
            continue
        located = entry.get("project_file") or entry.get("scan_root") or ""
        directory = _normalized_path(Path(str(located)).parent) if entry.get(
            "project_file"
        ) else _normalized_path(located)
        if not _runs_through(source, directory):
            continue
        if len(directory) >= len(best_directory):
            best_directory = directory
            best_state = str(entry.get("availability") or "")
    return best_state


def procedure_name_reason(invocation: DbInvocation, *, semantic_state: str = "") -> str:
    """Why one Database Invocation resolves no Executed Procedure Name, or `""`.

    The invocation's own reason wins whenever it names a specific cause, because
    that is the cause a maintainer can act on. A missing semantic model answers
    only for the absences it actually produces.
    """
    if invocation.executed_procedure_name:
        return ""
    reason = str(invocation.reason or "").strip()
    if reason and reason not in _MODEL_SHAPED_PROCEDURE_REASONS:
        return reason
    if _no_semantic_model(semantic_state):
        return NO_SEMANTIC_MODEL
    return reason or PROCEDURE_NAME_UNRESOLVED


def connection_source_reason(
    invocation: DbInvocation,
    *,
    unresolved_connections: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Why one Database Invocation resolves no Resolved Connection Source, or `""`.

    The connection tracker already named every lookup it refused, per source file
    and per connection variable, so that reason is read rather than guessed at
    again here.

    A missing semantic model is never the answer on this side. Connection
    resolution is a lookup-table rule over `Web.config` or the Application
    Settings File; the one shape that does need the model -- a receiver's
    declared context type -- already reports `context_type_not_registered`
    through the tracker.
    """
    if invocation.connection_source:
        return ""
    named = _tracked_connection_reason(invocation, unresolved_connections)
    if named:
        return named
    if len(invocation.connection_expression_candidates) > 1:
        return AMBIGUOUS_CONNECTION_SOURCE
    if not str(invocation.connection_expression or "").strip():
        # An external wrapper opens its own connection inside an assembly this
        # analysis cannot see, so the call site names no connection at all. That
        # is a different absence from a lookup key that resolved to nothing.
        return NO_CONNECTION_EXPRESSION
    return CONNECTION_SOURCE_UNRESOLVED


def build_scan_coverage(
    root: Path,
    scan: ProjectScanResult,
    invocations_by_file: Mapping[str, Sequence[DbInvocation]],
) -> Dict[str, Any]:
    """Measure one scan root: both shares, each with its own reason counts."""
    unresolved_by_file = getattr(scan, "unresolved_connections", {}) or {}
    total = 0
    procedure_reasons: Counter[str] = Counter()
    connection_reasons: Counter[str] = Counter()
    for file_key, invocations in invocations_by_file.items():
        state = semantic_binding_state(scan, file_key)
        tracked = unresolved_by_file.get(file_key) or []
        for invocation in invocations:
            total += 1
            reason = procedure_name_reason(invocation, semantic_state=state)
            if reason:
                procedure_reasons[reason] += 1
            reason = connection_source_reason(invocation, unresolved_connections=tracked)
            if reason:
                connection_reasons[reason] += 1
    return {
        "root": str(root),
        "database_invocations": total,
        PROCEDURE_NAME_RATIO: _measured(total, procedure_reasons),
        CONNECTION_SOURCE_RATIO: _measured(total, connection_reasons),
        "reason": "",
    }


def unmeasured_scan_coverage(root: Path, reason: str) -> Dict[str, Any]:
    """One scan root the command could not measure, and why.

    It still occupies a row. A root that was skipped and a root that resolved
    nothing are two different facts, and a report that dropped the first would
    make the System's shares read as if they covered everything.
    """
    return {
        "root": str(root),
        "database_invocations": 0,
        PROCEDURE_NAME_RATIO: _measured(0, {}),
        CONNECTION_SOURCE_RATIO: _measured(0, {}),
        "reason": reason,
    }


def build_system_coverage(
    system_id: str,
    scan_coverages: Sequence[Mapping[str, Any]],
    *,
    reason: str = "",
) -> Dict[str, Any]:
    """Roll one System's scan roots into its two shares, keeping each root visible.

    `reason` names why a System was not measured at all -- an unresolved source
    root, a scan cache that is not current. A System that reported nothing and a
    System that resolved nothing must never read the same.
    """
    total = sum(int(item.get("database_invocations") or 0) for item in scan_coverages)
    return {
        "system_id": system_id,
        "database_invocations": total,
        PROCEDURE_NAME_RATIO: _merged(total, scan_coverages, PROCEDURE_NAME_RATIO),
        CONNECTION_SOURCE_RATIO: _merged(total, scan_coverages, CONNECTION_SOURCE_RATIO),
        "scans": [dict(item) for item in scan_coverages],
        "reason": reason,
    }


def build_coverage_report(
    system_coverages: Sequence[Mapping[str, Any]],
    missing_systems: Iterable[str] = (),
) -> Dict[str, Any]:
    """One report over the Systems measured in this run."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "systems": [dict(item) for item in system_coverages],
        "missing_systems": sorted({str(item) for item in missing_systems if str(item)}),
    }


def render_coverage_report_text(report: Mapping[str, Any]) -> str:
    """Print the two shares per System, then every reason under each one."""
    lines: List[str] = []
    for system in report.get("systems") or []:
        lines.append(
            f"{system.get('system_id')}  "
            f"database_invocations={system.get('database_invocations', 0)}"
        )
        if system.get("reason"):
            lines.append(f"  not measured: {system['reason']}")
        for ratio_name in (PROCEDURE_NAME_RATIO, CONNECTION_SOURCE_RATIO):
            measured = system.get(ratio_name) or {}
            lines.append(
                f"  {ratio_name}: {_share_text(measured)} "
                f"({measured.get('resolved', 0)}/{system.get('database_invocations', 0)})"
            )
            for code, count in sorted(
                (measured.get("reasons") or {}).items(),
                key=lambda item: (-item[1], item[0]),
            ):
                lines.append(f"    {code}: {count}")
        for scan in system.get("scans") or []:
            if scan.get("reason"):
                lines.append(f"  not measured: {scan['root']}: {scan['reason']}")
    for system_id in report.get("missing_systems") or []:
        lines.append(f"unknown system: {system_id}")
    return "\n".join(lines)


def _measured(total: int, reasons: Mapping[str, int]) -> Dict[str, Any]:
    unresolved = sum(reasons.values())
    resolved = total - unresolved
    return {
        "resolved": resolved,
        "unresolved": unresolved,
        # No invocation measured is not the same as none resolved, so the share
        # is absent rather than zero.
        "ratio": round(resolved / total, 4) if total else None,
        "reasons": dict(sorted(reasons.items())),
    }


def _merged(
    total: int,
    scan_coverages: Sequence[Mapping[str, Any]],
    ratio_name: str,
) -> Dict[str, Any]:
    reasons: Counter[str] = Counter()
    for item in scan_coverages:
        reasons.update((item.get(ratio_name) or {}).get("reasons") or {})
    return _measured(total, reasons)


def _share_text(measured: Mapping[str, Any]) -> str:
    ratio = measured.get("ratio")
    return "n/a" if ratio is None else f"{ratio:.1%}"


def _no_semantic_model(semantic_state: str) -> bool:
    state = str(semantic_state or "").strip()
    return bool(state) and state != SEMANTIC_BINDING_AVAILABLE


def _tracked_connection_reason(
    invocation: DbInvocation,
    unresolved_connections: Iterable[Mapping[str, Any]],
) -> str:
    expression = str(invocation.connection_expression or "").strip().casefold()
    if not expression:
        return ""
    for entry in unresolved_connections:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("variable_name") or "").strip().casefold() != expression:
            continue
        reason = str(entry.get("reason") or "").strip()
        if reason:
            return reason
    return ""


def _relative_path(source_file: str, root: Path) -> str:
    path = Path(source_file)
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _normalized_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _runs_through(source: str, directory: str) -> bool:
    """Whether a source path runs through a directory, by whole path segments."""
    if not source or not directory:
        return False
    return source == directory or f"/{source}/".find(f"/{directory}/") >= 0

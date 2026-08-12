"""Deterministic legacy-versus-Gateway invocation migration reports."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    normalize_procedure_name,
    normalize_procedure_schema,
)
from code_analyzer.models import StoredProcedureCall
from code_analyzer.project_scanner import CSharpSPRelation, ProjectScanResult


def build_scan_migration_report(
    scan: ProjectScanResult,
    gateway_records: Iterable[DbInvocation],
    *,
    legacy_records: Optional[Iterable[object]] = None,
) -> dict[str, Any]:
    """Compare one scan's transient legacy facts with Gateway output."""
    source_kinds: dict[tuple[str, int, int], str] = {}
    root = Path(scan.project_root)
    for file_path, raw_records in (getattr(scan, "db_invocations", {}) or {}).items():
        relative_path = _normalize_path(file_path, source_root=root)
        for raw in raw_records or []:
            start_offset = int(raw.get("start_offset") or 0)
            end_offset = int(raw.get("end_offset") or 0)
            source_kinds[(relative_path, start_offset, end_offset)] = _raw_source_kind(raw)
    return compare_legacy_gateway(
        (
            legacy_records
            if legacy_records is not None
            else getattr(scan, "legacy_sp_relations", []) or []
        ),
        gateway_records,
        source_root=root,
        source_kinds=source_kinds,
    )


def compare_legacy_gateway(
    legacy_records: Iterable[object],
    gateway_records: Iterable[DbInvocation],
    *,
    source_root: Optional[str | Path] = None,
    source_kinds: Optional[Mapping[tuple[str, int, int], str]] = None,
) -> dict[str, Any]:
    """Compare legacy SP detections with evidence-rated Gateway invocations.

    The report is intentionally data-only so callers can persist JSON, render
    Markdown, or feed only the differences into a migration review workflow.
    """
    legacy = [
        _legacy_record(record, source_root=source_root)
        for record in legacy_records
    ]
    gateway = [
        _gateway_record(record, source_kinds=source_kinds)
        for record in gateway_records
    ]

    legacy_groups = _group_by_identity(legacy)
    gateway_groups = _group_by_identity(gateway)
    categories: dict[str, list[dict[str, Any]]] = {
        "dropped": [],
        "new": [],
        "confidence_changed": [],
        "unresolved": [],
    }
    matched = 0

    for identity in sorted(set(legacy_groups) | set(gateway_groups)):
        legacy_items = list(legacy_groups.get(identity, []))
        gateway_items = list(gateway_groups.get(identity, []))
        pair_count = min(len(legacy_items), len(gateway_items))
        for index in range(pair_count):
            legacy_item = legacy_items[index]
            gateway_item = gateway_items[index]
            evidence = gateway_item["evidence"]
            if evidence == InvocationEvidence.UNRESOLVED.value:
                categories["unresolved"].append(
                    _difference("unresolved", legacy_item, gateway_item)
                )
            elif evidence != InvocationEvidence.PROVEN.value:
                categories["confidence_changed"].append(
                    _difference("confidence_changed", legacy_item, gateway_item)
                )
            else:
                matched += 1

        for legacy_item in legacy_items[pair_count:]:
            categories["dropped"].append(
                _difference(
                    "dropped",
                    legacy_item,
                    None,
                    reason="legacy_detection_missing_from_gateway",
                )
            )
        for gateway_item in gateway_items[pair_count:]:
            category = (
                "unresolved"
                if gateway_item["evidence"] == InvocationEvidence.UNRESOLVED.value
                else "new"
            )
            categories[category].append(
                _difference(
                    category,
                    None,
                    gateway_item,
                    reason=(
                        gateway_item["reason"]
                        if category == "unresolved"
                        else "gateway_detection_missing_from_legacy"
                    ),
                )
            )

    for values in categories.values():
        values.sort(key=_difference_sort_key)

    summary = {
        "legacy_count": len(legacy),
        "gateway_count": len(gateway),
        "matched_count": matched,
        "dropped_count": len(categories["dropped"]),
        "new_count": len(categories["new"]),
        "confidence_changed_count": len(categories["confidence_changed"]),
        "unresolved_count": len(categories["unresolved"]),
    }
    differences = [
        item
        for category in ("dropped", "new", "confidence_changed", "unresolved")
        for item in categories[category]
    ]
    return {
        "report_version": 1,
        "summary": summary,
        "differences": differences,
        **categories,
    }


def build_cutover_report(
    gateway_records: Iterable[DbInvocation],
    *,
    legacy_records: Iterable[object] = (),
    source_root: Optional[str | Path] = None,
    source_kinds: Optional[Mapping[tuple[str, int, int], str]] = None,
) -> dict[str, Any]:
    """Summarize evidence, review candidates, contract lifecycle, and legacy
    difference for one scan so maintainers can decide on legacy retirement.

    ``evidence_summary`` always reports all three ``InvocationEvidence``
    statuses (even at zero) so a maintainer can tell "zero unresolved" apart
    from "not measured". ``contract_lifecycle_summary`` only lists statuses
    that were actually observed, since lifecycle status is an open-ended
    string, not a fixed enum.
    """
    records = list(gateway_records)
    legacy_migration = compare_legacy_gateway(
        legacy_records,
        records,
        source_root=source_root,
        source_kinds=source_kinds,
    )

    evidence_summary: dict[str, int] = {status.value: 0 for status in InvocationEvidence}
    review_candidate_count = 0
    contract_lifecycle_summary: dict[str, int] = defaultdict(int)
    for record in records:
        evidence_summary[_evidence_value(record.evidence)] += 1
        if record.wrapper_review_candidate:
            review_candidate_count += 1
        if record.contract_lifecycle_status:
            contract_lifecycle_summary[record.contract_lifecycle_status] += 1

    return {
        "report_version": 1,
        "evidence_summary": evidence_summary,
        "review_candidate_count": review_candidate_count,
        "contract_lifecycle_summary": dict(contract_lifecycle_summary),
        "legacy_only_detections": legacy_migration["summary"]["dropped_count"],
        "legacy_migration": legacy_migration,
    }


def render_cutover_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a maintainer-facing Markdown summary from a cutover report."""
    lines = [
        "# Migration Cutover Report",
        "",
        *_count_table("Evidence", report.get("evidence_summary", {})),
        "",
        *_count_table("Contract lifecycle", report.get("contract_lifecycle_summary", {})),
        "",
        *_count_table(
            "Metric",
            {
                "review_candidate_count": report.get("review_candidate_count", 0),
                "legacy_only_detections": report.get("legacy_only_detections", 0),
            },
        ),
        "",
    ]
    lines.append(render_migration_report_markdown(report.get("legacy_migration", {})))
    return "\n".join(lines)


def _count_table(label: str, counts: Mapping[str, int]) -> list[str]:
    lines = [f"| {label} | Count |", "|---|---:|"]
    for key, count in sorted(counts.items()):
        lines.append(f"| {key} | {count} |")
    return lines


def render_migration_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact reviewable Markdown report from comparator output."""
    summary = report.get("summary", {})
    lines = [
        "# Legacy vs Gateway Invocation Report",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for label, key in (
        ("Legacy detections", "legacy_count"),
        ("Gateway detections", "gateway_count"),
        ("Matched", "matched_count"),
        ("Dropped", "dropped_count"),
        ("New", "new_count"),
        ("Confidence changed", "confidence_changed_count"),
        ("Unresolved", "unresolved_count"),
    ):
        lines.append(f"| {label} | {summary.get(key, 0)} |")

    lines.extend(
        [
            "",
            "| Category | Caller | Source | Source kind | Evidence | Database | Procedure | Reason |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for difference in report.get("differences", []) or []:
        record = difference.get("gateway") or difference.get("legacy") or {}
        caller = record.get("caller", {})
        lines.append(
            "| {category} | {file}::{class_name}.{method} | {source} | {source_kind} | {evidence} | {database} | {procedure} | {reason} |".format(
                category=difference.get("category", ""),
                file=caller.get("file", ""),
                class_name=caller.get("class", ""),
                method=caller.get("method", ""),
                source=_markdown_source(record.get("source", {})),
                source_kind=record.get("source_kind", ""),
                evidence=record.get("evidence", ""),
                database=record.get("database", ""),
                procedure=record.get("procedure", ""),
                reason=difference.get("reason", ""),
            )
        )
    return "\n".join(lines) + "\n"


def save_migration_report(
    report: Mapping[str, Any],
    path: str | Path,
    *,
    format: Optional[str] = None,
) -> Path:
    """Save a comparison report as a review-only JSON or Markdown artifact."""
    destination = Path(path)
    selected_format = (format or destination.suffix.lstrip(".") or "json").casefold()
    if selected_format == "md":
        selected_format = "markdown"
    if selected_format == "json":
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    elif selected_format == "markdown":
        content = (
            render_cutover_report_markdown(report)
            if "legacy_migration" in report
            else render_migration_report_markdown(report)
        )
    else:
        raise ValueError("migration report format must be json or markdown")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination


def _legacy_record(record: object, *, source_root: Optional[str | Path]) -> dict[str, Any]:
    if isinstance(record, CSharpSPRelation):
        file_path = record.csharp_file
        class_name = record.class_name
        method_name = record.method_name
        database = record.sp_database
        procedure = record.sp_name
        line_number = record.line_number
        source_kind = "legacy_regex"
    elif isinstance(record, StoredProcedureCall):
        location = record.location
        file_path = location.file_path if location else ""
        class_name = ""
        method_name = ""
        database = record.database_source or ""
        procedure = record.procedure_name
        line_number = location.line_number if location else 0
        source_kind = "legacy_regex"
    elif isinstance(record, Mapping):
        file_path = str(record.get("file") or record.get("csharp_file") or "")
        class_name = str(record.get("class") or record.get("class_name") or "")
        method_name = str(record.get("method") or record.get("method_name") or "")
        database = str(record.get("database") or record.get("sp_database") or "")
        procedure = str(record.get("procedure") or record.get("sp_name") or "")
        line_number = int(record.get("line") or record.get("line_number") or 0)
        source_kind = str(record.get("source_kind") or "legacy_regex")
    else:
        raise TypeError(f"unsupported legacy invocation record: {type(record)!r}")

    return _record(
        file_path=file_path,
        class_name=class_name,
        method_name=method_name,
        database=database,
        procedure=procedure,
        evidence="legacy",
        reason="",
        source_kind=source_kind,
        source={"line": line_number},
        source_root=source_root,
    )


def _gateway_record(
    record: DbInvocation,
    *,
    source_kinds: Optional[Mapping[tuple[str, int, int], str]],
) -> dict[str, Any]:
    source = record.source
    source_key = (_normalize_path(source.relative_path), source.start_offset, source.end_offset)
    return _record(
        file_path=source.relative_path,
        class_name=record.class_name,
        method_name=record.method_name,
        database=record.database or "",
        procedure=record.procedure_name or "<unresolved>",
        evidence=_evidence_value(record.evidence),
        reason=record.reason,
        source_kind=(source_kinds or {}).get(source_key, "gateway"),
        source={
            "start_offset": source.start_offset,
            "end_offset": source.end_offset,
            "branch_context": list(record.branch_context),
            "method_chain": list(record.method_chain),
            "method_class_chain": list(record.method_class_chain),
            "source_snapshot_hash": record.source_snapshot_hash,
        },
        database_candidates=record.database_candidates,
        database_attribution=(
            "resolved"
            if record.database
            else "candidate"
            if record.database_candidates
            else "unresolved"
        ),
    )


def _record(
    *,
    file_path: str,
    class_name: str,
    method_name: str,
    database: str,
    procedure: str,
    evidence: str,
    reason: str,
    source_kind: str,
    source: Mapping[str, Any],
    source_root: Optional[str | Path] = None,
    database_candidates: Iterable[str] = (),
    database_attribution: str = "",
) -> dict[str, Any]:
    normalized_file = _normalize_path(file_path, source_root=source_root)
    normalized_procedure = _normalize_procedure(procedure)
    normalized_database = _normalize_database(database)
    identity = (
        normalized_file,
        class_name.strip().casefold(),
        method_name.strip().casefold(),
        normalized_database,
        normalized_procedure,
    )
    return {
        "identity": identity,
        "caller": {
            "file": normalized_file,
            "class": class_name,
            "method": method_name,
        },
        "database": normalized_database,
        "database_candidates": [str(value) for value in database_candidates if str(value)],
        "database_attribution": database_attribution or (
            "resolved" if normalized_database != "<unknown>" else "unresolved"
        ),
        "procedure": normalized_procedure,
        "evidence": evidence,
        "reason": reason,
        "source_kind": source_kind,
        "source": dict(source),
    }


def _group_by_identity(records: Iterable[dict[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["identity"]].append(record)
    for values in groups.values():
        values.sort(key=_record_sort_key)
    return groups


def _difference(
    category: str,
    legacy: Optional[Mapping[str, Any]],
    gateway: Optional[Mapping[str, Any]],
    *,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "reason": reason or str((gateway or {}).get("reason") or ""),
        **({"legacy": dict(legacy)} if legacy else {}),
        **({"gateway": dict(gateway)} if gateway else {}),
    }


def _record_sort_key(
    record: Mapping[str, Any],
) -> tuple[str, str, str, str, int, int, int, str, str, str, tuple[str, ...]]:
    caller = record.get("caller", {})
    source = record.get("source", {})
    return (
        str(caller.get("file", "")),
        str(caller.get("class", "")),
        str(caller.get("method", "")),
        str(record.get("procedure", "")),
        _source_position(source, "line"),
        _source_position(source, "start_offset"),
        _source_position(source, "end_offset"),
        str(record.get("source_kind", "")),
        str(record.get("evidence", "")),
        str(record.get("reason", "")),
        tuple(str(value) for value in record.get("database_candidates", []) or []),
    )


def _difference_sort_key(
    difference: Mapping[str, Any],
) -> tuple[str, str, str, str, int, int, int, str, str, str, tuple[str, ...]]:
    return _record_sort_key(
        difference.get("gateway") or difference.get("legacy") or {}
    )


def _source_position(source: Mapping[str, Any], key: str) -> int:
    try:
        return int(source.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _markdown_source(source: Mapping[str, Any]) -> str:
    if source.get("line"):
        return f"line {source['line']}"
    start = source.get("start_offset", "")
    end = source.get("end_offset", "")
    return f"offset {start}-{end}" if start != "" or end != "" else ""


def _normalize_path(path: str, *, source_root: Optional[str | Path] = None) -> str:
    candidate = Path(path)
    if source_root and candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(Path(source_root).resolve())
        except ValueError:
            pass
    return str(candidate).replace("\\", "/").casefold()


def _normalize_database(database: str) -> str:
    normalized = str(database or "").strip().casefold()
    return normalized if normalized and normalized not in {"unknown", "unresolved"} else "<unknown>"


def _normalize_procedure(procedure: str) -> str:
    if not procedure or procedure == "<unresolved>":
        return "<unresolved>"
    name = normalize_procedure_name(procedure)
    schema = normalize_procedure_schema(procedure) or "dbo"
    return f"{schema}.{name}"


def _evidence_value(evidence: object) -> str:
    return str(getattr(evidence, "value", evidence or "")).casefold()


def _raw_source_kind(raw: Mapping[str, Any]) -> str:
    invocation_kind = str(raw.get("invocation_kind") or "").casefold()
    if invocation_kind == "source_wrapper":
        return "source_wrapper"
    if invocation_kind in {"dapper", "entity_framework", "entityframework", "ef"}:
        return invocation_kind
    if raw.get("branch_context") or raw.get("branch_path"):
        return "branch_invocation"
    return "direct_sqlclient"
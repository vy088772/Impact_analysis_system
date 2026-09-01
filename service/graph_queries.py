"""Deterministic queries over the SQL Execution Graph."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from code_analyzer.csharp_analysis_gateway import DbInvocation, WRAPPER_EVIDENCE_FIELDS

from .execution_path_builder import build_execution_paths


_ACCESS_MODES = {"all", "read", "write"}
def query_table_accesses(
    graph: Mapping[str, Any],
    invocations: Iterable[DbInvocation],
    table_name: str,
    *,
    access: str = "all",
    max_call_depth: int = 5,
) -> list[dict[str, Any]]:
    """Return C#-to-table facts proven by execution paths in ``graph``.

    Each result is one terminal path/table pair. ``write`` only returns confirmed
    DML paths; View, Function, and unresolved dynamic-SQL paths therefore cannot
    become confirmed writers by accident.

    Builds Execution Paths itself, once, from ``invocations``. A caller that
    already holds Execution Paths for the same invocations and graph -- for
    example one asking about more than one table in the same scope -- should call
    `filter_table_accesses` directly instead, so paths are not rebuilt per table.
    """
    paths = build_execution_paths(invocations, graph, max_call_depth=max_call_depth)
    return filter_table_accesses(paths, graph, table_name, access=access)


def filter_table_accesses(
    paths: Iterable[Mapping[str, Any]],
    graph: Mapping[str, Any],
    table_name: str,
    *,
    access: str = "all",
) -> list[dict[str, Any]]:
    """Return C#-to-table facts proven by already-built Execution Paths.

    Split out of `query_table_accesses` so a caller holding one scope's Execution
    Paths (see `service.analyze_service._execution_paths_for_scope`) can query
    more than one table without rebuilding them -- the paths themselves do not
    depend on which table is being asked about.
    """
    if access not in _ACCESS_MODES:
        raise ValueError(f"unsupported table access mode: {access}")

    target_name = _normalize_table(table_name)
    if not target_name:
        return []

    accesses: list[dict[str, Any]] = []
    for path in paths:
        writes = _matching_names(path.get("writes", []), target_name)
        reads = _matching_names(path.get("reads", []), target_name)
        is_dynamic = "dynamic_sql" in set(path.get("risk_flags", []) or [])
        is_confirmed = path.get("evidence") == "proven" and not is_dynamic

        if writes and access in {"all", "write"} and is_confirmed:
            accesses.append(_access_record(path, writes[0], is_write=True))
            continue

        if access in {"all", "read"} and is_confirmed:
            if reads:
                accesses.append(_access_record(path, reads[0], is_write=False))
                continue
            lineage_reads = _matching_graph_read_lineage(graph, path, target_name)
            for table in lineage_reads:
                accesses.append(
                    _access_record(
                        path,
                        table,
                        is_write=False,
                        is_indirect_override=True,
                    )
                )

    return sorted(accesses, key=_access_sort_key)


def _access_record(
    path: Mapping[str, Any],
    table_name: str,
    *,
    is_write: bool,
    is_indirect_override: bool | None = None,
) -> dict[str, Any]:
    sp_chain = list(path.get("sp_chain", []) or [])
    operation = str(path.get("terminal_operation") or "")
    record = {
        "table": table_name,
        "access_type": operation if is_write else "READ",
        "is_write": is_write,
        "is_indirect": (
            is_indirect_override
            if is_indirect_override is not None
            else len(sp_chain) > 1
        ),
        "via": "stored_procedure",
        "path_id": path.get("path_id", ""),
        "source_span": dict(path.get("source_span", {}) or {}),
        "database": path.get("database", ""),
        "database_candidates": list(path.get("database_candidates", []) or []),
        "database_attribution": path.get("database_attribution", "unresolved"),
        "caller": path.get("caller", ""),
        "caller_class": path.get("caller_class", ""),
        "caller_method": path.get("caller_method", ""),
        "procedure_name": path.get("procedure_name", ""),
        "procedure_schema": path.get("procedure_schema", ""),
        "branch_context": list(path.get("branch_context", []) or []),
        "entry_method": path.get("entry_method", ""),
        "method_chain": list(path.get("method_chain", []) or []),
        "sp_chain": sp_chain,
        "terminal_operation": operation,
        "operation_type": operation,
        "terminal_operation_id": path.get("terminal_operation_id", ""),
        "written_columns": list(path.get("written_columns", []) or []),
        "conditions": list(path.get("conditions", []) or []),
        "reads": list(path.get("reads", []) or []),
        "writes": list(path.get("writes", []) or []),
        "evidence": path.get("evidence", "unresolved"),
        "reason": path.get("reason", ""),
        "confirmed": path.get("confirmed", False),
        "risk_flags": list(path.get("risk_flags", []) or []),
        "unresolved_reason": path.get("unresolved_reason", ""),
        "unresolved_targets": list(path.get("unresolved_targets", []) or []),
    }
    for key in WRAPPER_EVIDENCE_FIELDS:
        if key not in path:
            continue
        value = path[key]
        record[key] = list(value) if isinstance(value, tuple) else value
    return record


def _matching_graph_read_lineage(
    graph: Mapping[str, Any],
    path: Mapping[str, Any],
    target_name: str,
) -> list[str]:
    """Resolve a path's View/UDF reads to base tables without inferring writes."""
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    relationships = [
        relationship
        for relationship in graph.get("relationships", []) or []
        if relationship.get("source") and relationship.get("target")
    ]
    reads_by_source: dict[str, list[str]] = {}
    contains_by_source: dict[str, list[str]] = {}
    for relationship in relationships:
        source = str(relationship["source"])
        target = str(relationship["target"])
        if relationship.get("type") == "reads":
            reads_by_source.setdefault(source, []).append(target)
        elif relationship.get("type") == "contains":
            contains_by_source.setdefault(source, []).append(target)

    operation_id = str(path.get("terminal_operation_id") or "")
    if not operation_id:
        return []

    matched: list[str] = []
    visited: set[str] = set()
    frontier = list(reads_by_source.get(operation_id, []))
    while frontier:
        object_id = frontier.pop(0)
        if object_id in visited:
            continue
        visited.add(object_id)
        node = nodes.get(object_id)
        if not node:
            continue
        if node.get("type") == "table":
            name = str(node.get("name") or "")
            if _normalize_table(name) == target_name:
                matched.append(name)
            continue
        if node.get("type") not in {"view", "function"}:
            continue
        for child_operation_id in contains_by_source.get(object_id, []):
            frontier.extend(reads_by_source.get(child_operation_id, []))

    return _ordered_unique(matched)


def _matching_names(names: Iterable[object], target_name: str) -> list[str]:
    return [
        str(name)
        for name in names
        if _normalize_table(str(name)) == target_name
    ]


def _normalize_table(name: str) -> str:
    cleaned = str(name or "").replace("[", "").replace("]", "").strip()
    return cleaned.rsplit(".", 1)[-1].casefold()


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _access_sort_key(access: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(access.get("entry_method", "")),
        str(access.get("path_id", "")),
        str(access.get("access_type", "")),
    )
"""Build deterministic Execution Paths from C# invocations and the SQL graph."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any, Iterable, Mapping, Optional

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    DbInvocation,
    InvocationEvidence,
    SpCatalog,
)

MAX_COMPACT_PATHS = 20


def build_execution_paths(
    invocations: Iterable[DbInvocation],
    graph: Mapping[str, Any],
    *,
    max_call_depth: int = 5,
) -> list[dict[str, Any]]:
    """Join evidence-rated C# invocations to terminal SQL operations.

    The returned records are deliberately compact. Source spans remain an identity
    input for ``path_id`` but complete source and SQL definitions are not copied
    into an Execution Path.
    """
    nodes = {
        str(node.get("id")): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    relationships = [
        relationship
        for relationship in graph.get("relationships", []) or []
        if relationship.get("type") and relationship.get("source")
    ]
    module_nodes = _stored_procedure_nodes(nodes)
    module_nodes_by_id = {
        str(node["id"]): node
        for node in module_nodes
        if node.get("id")
    }
    paths: list[dict[str, Any]] = []
    max_call_depth = max(0, max_call_depth)
    graph_database = _normalize_database(graph.get("database"))

    for invocation in sorted(invocations, key=_invocation_sort_key):
        evidence = _evidence_value(invocation.evidence)
        if evidence == InvocationEvidence.UNRESOLVED.value:
            paths.append(_unresolved_path(invocation, invocation.reason or "unresolved_invocation"))
            continue
        if not invocation.procedure_name:
            paths.append(_unresolved_path(invocation, "missing_procedure_name"))
            continue
        if graph_database and _normalize_database(invocation.database) != graph_database:
            paths.append(
                _unresolved_path(
                    invocation,
                    "graph_database_mismatch",
                    unresolved_targets=[f"database:{graph.get('database')}"],
                )
            )
            continue

        matches = [
            node
            for node in module_nodes
            if _normalize_name(node.get("name")) == _normalize_name(invocation.procedure_name)
            and (
                not invocation.procedure_schema
                or _normalize_schema(node.get("schema"))
                == _normalize_schema(invocation.procedure_schema)
            )
        ]
        if len(matches) != 1:
            reason = "stored_procedure_not_in_graph" if not matches else "ambiguous_stored_procedure_graph_target"
            unresolved_targets = (
                [str(node.get("id")) for node in matches]
                if matches
                else [_qualified_invocation_name(invocation)]
            )
            paths.append(
                _unresolved_path(
                    invocation,
                    reason,
                    unresolved_targets=unresolved_targets,
                )
            )
            continue

        module = matches[0]
        paths.extend(
            _paths_from_module(
                invocation,
                module,
                module_nodes_by_id,
                relationships,
                nodes,
                graph,
                max_call_depth=max_call_depth,
            )
        )

    return sorted(paths, key=lambda path: (path["path_id"], path["entry_method"]))


def _paths_from_module(
    invocation: DbInvocation,
    module: Mapping[str, Any],
    module_nodes_by_id: Mapping[str, Mapping[str, Any]],
    relationships: list[Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Any],
    sp_chain: tuple[str, ...] = (),
    module_chain_ids: tuple[str, ...] = (),
    call_conditions: tuple[str, ...] = (),
    max_call_depth: int = 5,
) -> list[dict[str, Any]]:
    module_id = str(module.get("id", ""))
    qualified_module = _qualified_name(module)
    current_sp_chain = (*sp_chain, qualified_module)
    current_module_chain = (*module_chain_ids, module_id)
    if module_id in module_chain_ids:
        return [
            _unresolved_path(
                invocation,
                "stored_procedure_call_cycle",
                sp_chain_override=list(current_sp_chain),
                path_identity="|".join(current_module_chain),
                path_conditions=call_conditions,
            )
        ]
    if len(module_chain_ids) > max_call_depth:
        return [
            _unresolved_path(
                invocation,
                "call_expansion_truncated",
                sp_chain_override=list(current_sp_chain),
                path_identity="|".join(current_module_chain),
                path_conditions=call_conditions,
            )
        ]

    paths: list[dict[str, Any]] = []
    operation_ids: set[str] = set()
    dangling_contains = False
    for relationship in relationships:
        if relationship.get("type") != "contains" or relationship.get("source") != module_id:
            continue
        target_id = relationship.get("target")
        if not target_id:
            dangling_contains = True
            continue
        operation_ids.add(str(target_id))

    if dangling_contains:
        paths.append(
            _unresolved_path(
                invocation,
                "operation_not_in_graph",
                sp_chain_override=list(current_sp_chain),
                operation_id="missing_contains_target",
                path_identity="|".join(current_module_chain),
                path_conditions=call_conditions,
                unresolved_targets=["<missing-target>"],
            )
        )

    for operation_id in sorted(
        operation_ids,
        key=lambda candidate: _operation_sort_key(candidate, nodes),
    ):
        operation = nodes.get(operation_id)
        if not operation or operation.get("type") not in {
            "dml_operation",
            "unresolved_dynamic_sql",
        }:
            paths.append(
                _unresolved_path(
                    invocation,
                    "operation_not_in_graph",
                    sp_chain_override=list(current_sp_chain),
                    operation_id=operation_id,
                    path_identity="|".join(current_module_chain),
                    path_conditions=call_conditions,
                    unresolved_targets=[operation_id],
                )
            )
            continue
        paths.append(
            _path_for_operation(
                invocation,
                module,
                operation,
                relationships,
                nodes,
                graph,
                sp_chain=list(current_sp_chain),
                module_chain_ids=current_module_chain,
                call_conditions=call_conditions,
            )
        )

    call_relationships = [
        relationship
        for relationship in relationships
        if relationship.get("type") == "calls" and relationship.get("source") == module_id
    ]
    for relationship in sorted(call_relationships, key=lambda item: str(item.get("target", ""))):
        target_id = relationship.get("target")
        if not target_id or str(target_id) not in module_nodes_by_id:
            paths.append(
                _unresolved_path(
                    invocation,
                    "called_procedure_not_in_graph",
                    sp_chain_override=list(current_sp_chain),
                    operation_id=f"missing_call_target:{target_id or 'unknown'}",
                    path_identity="|".join(current_module_chain),
                    path_conditions=call_conditions,
                    unresolved_targets=[str(target_id or "<missing-target>")],
                )
            )
            continue
        child_conditions = _ordered_unique(
            (*call_conditions, *list(relationship.get("conditions", []) or []), *list(relationship.get("branch_path", []) or []))
        )
        paths.extend(
            _paths_from_module(
                invocation,
                module_nodes_by_id[str(target_id)],
                module_nodes_by_id,
                relationships,
                nodes,
                graph,
                sp_chain=current_sp_chain,
                module_chain_ids=current_module_chain,
                call_conditions=tuple(child_conditions),
                max_call_depth=max_call_depth,
            )
        )

    if not paths and not dangling_contains and not call_relationships:
        paths.append(
            _unresolved_path(
                invocation,
                "stored_procedure_has_no_terminal_dml",
                sp_chain_override=list(current_sp_chain),
                path_identity="|".join(current_module_chain),
                path_conditions=call_conditions,
            )
        )
    return paths


def build_execution_paths_from_raw_invocations(
    relative_path: str,
    raw_invocations: Iterable[Mapping[str, Any]],
    catalog: SpCatalog,
    graph: Mapping[str, Any],
    connection_sources: Optional[Mapping[str, str]] = None,
    *,
    max_call_depth: int = 5,
) -> list[dict[str, Any]]:
    """Rate raw StaticAnalyzerHost facts, then join only the rated invocations."""
    gateway = CSharpAnalysisGateway(catalog, connection_sources=dict(connection_sources or {}))
    invocations = gateway.resolve_direct_invocations(relative_path, [dict(raw) for raw in raw_invocations])
    return build_execution_paths(invocations, graph, max_call_depth=max_call_depth)


def build_compact_execution_path_summary(
    paths: Iterable[Mapping[str, Any]],
    max_paths: int = 20,
    *,
    question: str = "",
) -> list[dict[str, Any]]:
    """Return only the fields needed for first-pass path selection."""
    summaries: list[dict[str, Any]] = []
    limit = min(MAX_COMPACT_PATHS, max(0, max_paths))
    question_tokens = _question_tokens(question)
    for path in sorted(
        paths,
        key=lambda item: _compact_sort_key(item, question_tokens),
    )[:limit]:
        summary = {
            "path_id": path.get("path_id", ""),
            "entry_method": path.get("entry_method", ""),
            "method_chain": list(path.get("method_chain", []) or []),
            "sp_chain": list(path.get("sp_chain", []) or []),
            "terminal_operation": path.get("terminal_operation"),
            "target": path.get("target", ""),
            "written_columns": list(path.get("written_columns", []) or []),
            "conditions": list(path.get("conditions", []) or []),
            "reads": list(path.get("reads", []) or []),
            "writes": list(path.get("writes", []) or []),
            "risk_flags": list(path.get("risk_flags", []) or []),
            "evidence": path.get("evidence", "unresolved"),
            "unresolved_targets": list(path.get("unresolved_targets", []) or []),
        }
        if path.get("unresolved_reason"):
            summary["unresolved_reason"] = path["unresolved_reason"]
        summaries.append(summary)
    return summaries


def build_compact_execution_path_payload(
    paths: Iterable[Mapping[str, Any]],
    max_paths: int = 20,
    *,
    question: str = "",
) -> dict[str, Any]:
    """Return compact paths together with explicit truncation metadata."""
    path_list = list(paths)
    summaries = build_compact_execution_path_summary(
        path_list,
        max_paths=max_paths,
        question=question,
    )
    return {
        "paths": summaries,
        "total_paths": len(path_list),
        "returned_paths": len(summaries),
        "omitted_paths": max(0, len(path_list) - len(summaries)),
    }


def build_execution_path_summary(
    invocations: Iterable[DbInvocation],
    graph: Mapping[str, Any],
    max_paths: int = 20,
    *,
    max_call_depth: int = 5,
    question: str = "",
) -> dict[str, Any]:
    """Build full paths and the compact first-pass selector payload together."""
    paths = build_execution_paths(invocations, graph, max_call_depth=max_call_depth)
    compact_payload = build_compact_execution_path_payload(
        paths,
        max_paths=max_paths,
        question=question,
    )
    return {
        "paths": paths,
        "compact_summary": compact_payload["paths"],
        "compact_summary_meta": {
            key: compact_payload[key]
            for key in ("total_paths", "returned_paths", "omitted_paths")
        },
    }


def _path_for_operation(
    invocation: DbInvocation,
    module: Mapping[str, Any],
    operation: Mapping[str, Any],
    relationships: list[Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Any],
    sp_chain: Optional[list[str]] = None,
    module_chain_ids: tuple[str, ...] = (),
    call_conditions: tuple[str, ...] = (),
) -> dict[str, Any]:
    operation_id = str(operation["id"])
    reads, missing_reads = _relationship_targets(
        operation_id, "reads", relationships, nodes
    )
    writes, missing_writes = _relationship_targets(
        operation_id, "writes", relationships, nodes
    )
    written_columns = _ordered_unique(
        list(operation.get("written_columns", []) or [])
        + [
            column
            for relationship in relationships
            if relationship.get("type") == "writes"
            and relationship.get("source") == operation_id
            for column in relationship.get("columns", []) or []
        ]
    )
    missing_targets = missing_reads + missing_writes
    risk_flags: list[str] = []
    evidence = _evidence_value(invocation.evidence)
    is_dynamic_operation = operation.get("type") == "unresolved_dynamic_sql"
    if evidence == InvocationEvidence.LIKELY.value:
        risk_flags.append("likely_invocation")
    if is_dynamic_operation:
        risk_flags.append("dynamic_sql")
        evidence = InvocationEvidence.UNRESOLVED.value
    if missing_targets:
        risk_flags.append("missing_graph_target")
        evidence = InvocationEvidence.UNRESOLVED.value

    module_id = str(module["id"])
    module_chain = module_chain_ids or (module_id,)
    parse_error_modules = {
        str(error.get("module_id"))
        for error in graph.get("parse_errors", []) or []
        if error.get("module_id")
    }
    if any(chain_id in parse_error_modules for chain_id in module_chain):
        risk_flags.append("sql_parse_error")
    operation_conditions = list(operation.get("conditions", []) or [])
    if not operation_conditions:
        operation_conditions = list(operation.get("branch_path", []) or [])

    return {
        "path_id": _path_id(invocation, operation_id, "|".join(module_chain), call_conditions),
        "entry_method": _entry_method(invocation),
        "method_chain": _method_chain(invocation),
        "database": invocation.database or "",
        "sp_chain": list(sp_chain or [_qualified_name(module)]),
        "terminal_operation": operation.get("operation_type", ""),
        "target": writes[0] if writes else "",
        "written_columns": written_columns,
        "conditions": _ordered_unique((*call_conditions, *operation_conditions)),
        "reads": reads,
        "writes": writes,
        "risk_flags": _ordered_unique(risk_flags),
        "evidence": evidence,
        "unresolved_reason": (
            "missing_graph_target"
            if missing_targets
            else "unresolved_dynamic_sql"
            if is_dynamic_operation
            else ""
        ),
        "unresolved_targets": missing_targets,
    }


def _unresolved_path(
    invocation: DbInvocation,
    reason: str,
    module: Optional[Mapping[str, Any]] = None,
    operation_id: str = "",
    sp_chain_override: Optional[list[str]] = None,
    path_conditions: tuple[str, ...] = (),
    path_identity: str = "",
    unresolved_targets: Optional[list[str]] = None,
) -> dict[str, Any]:
    procedure_name = invocation.procedure_name or ""
    sp_chain = sp_chain_override or (
        [_qualified_name(module)] if module else ([procedure_name] if procedure_name else [])
    )
    module_id = path_identity or (str(module.get("id", "")) if module else "")
    return {
        "path_id": _path_id(
            invocation,
            operation_id or f"unresolved:{reason}",
            module_id,
            path_conditions,
        ),
        "entry_method": _entry_method(invocation),
        "method_chain": _method_chain(invocation),
        "database": invocation.database or "",
        "sp_chain": sp_chain,
        "terminal_operation": None,
        "target": "",
        "written_columns": [],
        "conditions": list(path_conditions),
        "reads": [],
        "writes": [],
        "risk_flags": [reason],
        "evidence": InvocationEvidence.UNRESOLVED.value,
        "unresolved_reason": reason,
        "unresolved_targets": list(unresolved_targets or []),
    }


def _relationship_targets(
    source_id: str,
    relationship_type: str,
    relationships: Iterable[Mapping[str, Any]],
    nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    names: list[str] = []
    missing: list[str] = []
    for relationship in relationships:
        if relationship.get("type") != relationship_type or relationship.get("source") != source_id:
            continue
        target_id = str(relationship.get("target", ""))
        target = nodes.get(target_id)
        if target is None:
            missing.append(target_id or "<missing-target>")
            continue
        names.append(_qualified_name(target))
    return _ordered_unique(names), _ordered_unique(missing)


def _stored_procedure_nodes(nodes: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        (node for node in nodes.values() if node.get("type") == "stored_procedure"),
        key=lambda node: (_normalize_name(node.get("name")), _qualified_name(node)),
    )


def _operation_sort_key(operation_id: str, nodes: Mapping[str, Mapping[str, Any]]) -> tuple[int, str]:
    operation = nodes.get(operation_id, {})
    try:
        sequence = int(operation.get("sequence", 0))
    except (TypeError, ValueError):
        sequence = 0
    return sequence, operation_id


def _invocation_sort_key(invocation: DbInvocation) -> tuple[str, int, int, str, str]:
    return (
        invocation.source.relative_path,
        invocation.source.start_offset,
        invocation.source.end_offset,
        _entry_method(invocation),
        invocation.procedure_name or "",
    )


def _compact_sort_key(
    path: Mapping[str, Any],
    question_tokens: tuple[str, ...],
) -> tuple[int, int, int, str]:
    path_text = " ".join(
        str(value)
        for field in (
            "entry_method",
            "method_chain",
            "sp_chain",
            "target",
            "conditions",
            "reads",
            "writes",
        )
        for value in (path.get(field, ""),)
    ).casefold()
    entry_method = str(path.get("entry_method", "")).casefold()
    keyword_matches = sum(token in path_text for token in question_tokens)
    entry_method_matches = sum(token in entry_method for token in question_tokens)
    has_write = bool(path.get("writes") or path.get("target"))
    return (
        0 if has_write else 1,
        -keyword_matches,
        -entry_method_matches,
        str(path.get("path_id", "")),
    )


def _question_tokens(question: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in re.findall(r"\w+", question.casefold())
        if len(token) > 1
    )


def _path_id(
    invocation: DbInvocation,
    operation_id: str,
    module_id: str,
    path_conditions: Iterable[str] = (),
) -> str:
    identity = "\x1f".join(
        (
            invocation.database or "",
            invocation.source.relative_path,
            str(invocation.source.start_offset),
            str(invocation.source.end_offset),
            _entry_method(invocation),
            invocation.procedure_schema or "",
            invocation.procedure_name or "",
            module_id,
            operation_id,
            "\x1e".join(path_conditions),
        )
    )
    return f"P-{sha256(identity.encode('utf-8')).hexdigest()[:12]}"


def _entry_method(invocation: DbInvocation) -> str:
    method_name = invocation.method_chain[0] if invocation.method_chain else invocation.method_name
    if invocation.class_name:
        return f"{invocation.class_name}.{method_name}"
    return method_name


def _method_chain(invocation: DbInvocation) -> list[str]:
    return list(invocation.method_chain) or [invocation.method_name]


def _qualified_name(node: Mapping[str, Any]) -> str:
    schema = str(node.get("schema", "") or "")
    name = str(node.get("name", "") or "")
    return f"{schema}.{name}" if schema and name else name


def _normalize_name(name: Any) -> str:
    cleaned = str(name or "").replace("[", "").replace("]", "").strip()
    return cleaned.rsplit(".", 1)[-1].casefold()


def _normalize_schema(schema: Any) -> str:
    return str(schema or "").replace("[", "").replace("]", "").strip().casefold()


def _normalize_database(database: Any) -> str:
    return str(database or "").strip().casefold()


def _qualified_invocation_name(invocation: DbInvocation) -> str:
    if invocation.procedure_schema:
        return f"{invocation.procedure_schema}.{invocation.procedure_name or ''}"
    return invocation.procedure_name or "<missing-procedure>"


def _evidence_value(evidence: Any) -> str:
    if isinstance(evidence, InvocationEvidence):
        return evidence.value
    return str(evidence or InvocationEvidence.UNRESOLVED.value).lower()


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
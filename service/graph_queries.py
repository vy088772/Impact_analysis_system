"""Deterministic queries over the SQL Execution Graph."""

from __future__ import annotations

from collections import deque
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
    lineage_index: _LineageIndex | None = None
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
            if lineage_index is None:
                lineage_index = _LineageIndex(graph)
            lineage_reads = lineage_index.read_lineage(path, target_name)
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


# A table's normalized name to the raw names actually seen for it (there is
# usually one raw name; more than one only happens if two differently-cased
# or differently-schema'd table nodes normalize to the same key).
_TableNames = dict[str, list[str]]


class _LineageIndex:
    """Table reverse index for one graph, built at most once.

    A table reverse lookup asks this once per graph, not once per Execution
    Path. Where ticket 03 cached the graph's raw `reads`/`contains`
    dictionaries and still walked forward from each path's terminal
    operation, this inverts them: one pass over the graph builds, for every
    table the graph can reach, the terminal operations that reach it. A path
    then costs one membership test against its target table's entry, not one
    graph walk.

    The inversion still respects the forward walk's own rules -- follow
    `reads` only, and stop at a table node -- so the answer does not change.
    A cycle among Views or Functions is resolved by a worklist fixed point
    over the container graph (see `_ensure_built`), not by cutting a branch
    short the first time it is visited: a container revisited while its own
    computation is still in flight would otherwise cache an incomplete
    answer, one that a *different*, non-cyclic caller reaching the same
    container later would wrongly inherit. The fixed point terminates
    because the table universe is finite and each step only adds table
    names, never removes them.

    The graph itself is kept only inside this instance, so `read_lineage`
    never re-reads it: the index and the graph it was built from stay
    paired by construction, and a caller holding a `_LineageIndex` cannot
    hand it a different graph's data.

    Built lazily, on the first call to `read_lineage` -- a lookup whose
    matches are all direct never constructs one. Once built, the index
    covers every table in the graph, so asking about a second table costs
    only the membership test, not another build.
    """

    __slots__ = ("_graph", "_operations_by_table")

    def __init__(self, graph: Mapping[str, Any]) -> None:
        self._graph = graph
        self._operations_by_table: dict[str, dict[str, list[str]]] | None = None

    def _ensure_built(self) -> dict[str, dict[str, list[str]]]:  # table -> {operation_id: names}
        if self._operations_by_table is not None:
            return self._operations_by_table

        nodes = {
            str(node.get("id")): node
            for node in self._graph.get("nodes", []) or []
            if node.get("id")
        }
        reads_by_source: dict[str, list[str]] = {}
        contains_by_source: dict[str, list[str]] = {}
        for relationship in self._graph.get("relationships", []) or []:
            source = relationship.get("source")
            target = relationship.get("target")
            if not source or not target:
                continue
            source = str(source)
            target = str(target)
            if relationship.get("type") == "reads":
                reads_by_source.setdefault(source, []).append(target)
            elif relationship.get("type") == "contains":
                contains_by_source.setdefault(source, []).append(target)

        # A View or Function's own reachable tables depend on what its child
        # operations read -- a table directly, or another container, whose
        # own reachable tables must be folded in too. Resolve that as a
        # graph problem over containers alone: `direct_tables[container]` is
        # what its children read directly; `successors[container]` /
        # `predecessors[container]` are the edges to and from the other
        # containers those children read.
        direct_tables: dict[str, _TableNames] = {}
        successors: dict[str, set[str]] = {}
        predecessors: dict[str, set[str]] = {}

        def _record_target(container_id: str, target_id: str) -> None:
            node = nodes.get(target_id)
            if not node:
                return
            node_type = node.get("type")
            if node_type == "table":
                name = str(node.get("name") or "")
                if name:
                    _add_table_name(direct_tables.setdefault(container_id, {}), name)
            elif node_type in {"view", "function"}:
                successors.setdefault(container_id, set()).add(target_id)
                predecessors.setdefault(target_id, set()).add(container_id)

        for container_id, child_operation_ids in contains_by_source.items():
            for child_operation_id in child_operation_ids:
                for target_id in reads_by_source.get(child_operation_id, []):
                    _record_target(container_id, target_id)

        # Worklist fixed point: each container starts at its own direct
        # tables and grows by folding in each successor's tables, until a
        # round adds nothing new. A container revisited through a cycle is
        # simply reprocessed once its successor's own set has grown -- so a
        # cycle changes the order tables are folded in, never the result.
        reachable: dict[str, _TableNames] = {
            container_id: {name: list(raws) for name, raws in tables.items()}
            for container_id, tables in direct_tables.items()
        }
        for container_id in successors:
            reachable.setdefault(container_id, {})

        queue: deque[str] = deque(reachable.keys())
        queued: set[str] = set(queue)
        while queue:
            container_id = queue.popleft()
            queued.discard(container_id)
            own = reachable[container_id]
            changed = False
            for successor_id in successors.get(container_id, ()):
                if _merge_reachable(own, reachable.get(successor_id, {})):
                    changed = True
            if changed:
                for predecessor_id in predecessors.get(container_id, ()):
                    if predecessor_id not in queued:
                        queue.append(predecessor_id)
                        queued.add(predecessor_id)

        # Every operation with `reads` edges (a path's own terminal operation,
        # or one nested inside a container) resolves in one hop now: a table
        # target counts directly, a container target counts via its already
        # fully-resolved `reachable` entry.
        operations_by_table: dict[str, dict[str, list[str]]] = {}
        for operation_id, target_ids in reads_by_source.items():
            reached: _TableNames = {}
            for target_id in target_ids:
                node = nodes.get(target_id)
                if not node:
                    continue
                node_type = node.get("type")
                if node_type == "table":
                    name = str(node.get("name") or "")
                    if name:
                        _add_table_name(reached, name)
                elif node_type in {"view", "function"}:
                    _merge_reachable(reached, reachable.get(target_id, {}))
            for table_name, raw_names in reached.items():
                operations_by_table.setdefault(table_name, {})[operation_id] = raw_names

        self._operations_by_table = operations_by_table
        return operations_by_table

    def read_lineage(self, path: Mapping[str, Any], target_name: str) -> list[str]:
        """Resolve a path's View/UDF reads to base tables without inferring writes."""
        operation_id = str(path.get("terminal_operation_id") or "")
        if not operation_id:
            return []

        table_entry = self._ensure_built().get(target_name)
        if not table_entry:
            return []
        return list(table_entry.get(operation_id, []))


def _add_table_name(reached: _TableNames, name: str) -> None:
    """Record one raw table name under its normalized key, without duplicates."""
    bucket = reached.setdefault(_normalize_table(name), [])
    if name not in bucket:
        bucket.append(name)


def _merge_reachable(target: _TableNames, source: Mapping[str, list[str]]) -> bool:
    """Fold `source`'s tables into `target`; report whether anything was new."""
    changed = False
    for key, names in source.items():
        bucket = target.setdefault(key, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
                changed = True
    return changed


def _matching_names(names: Iterable[object], target_name: str) -> list[str]:
    return [
        str(name)
        for name in names
        if _normalize_table(str(name)) == target_name
    ]


def _normalize_table(name: str) -> str:
    cleaned = str(name or "").replace("[", "").replace("]", "").strip()
    return cleaned.rsplit(".", 1)[-1].casefold()


def _access_sort_key(access: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(access.get("entry_method", "")),
        str(access.get("path_id", "")),
        str(access.get("access_type", "")),
    )
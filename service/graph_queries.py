"""Deterministic queries over the SQL Execution Graph."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Mapping, NamedTuple

import schema_resolution
from canonical_object_identity import ObjectName, part_key, schema_qualified
from code_analyzer.csharp_analysis_gateway import DbInvocation, WRAPPER_EVIDENCE_FIELDS

from .execution_path_builder import build_execution_paths
from .table_match import UNPROVEN_SCHEMA, TableMatch, TableQuestion


_ACCESS_MODES = {"all", "read", "write"}
def query_table_accesses(
    graph: Mapping[str, Any],
    invocations: Iterable[DbInvocation],
    table_name: str,
    *,
    access: str = "all",
    max_call_depth: int = 5,
    database: str = "",
) -> list[dict[str, Any]]:
    """Return C#-to-table facts held by execution paths in ``graph``.

    Each result is one terminal path/table pair. A path that is not `proven`
    still produces a record -- see `filter_table_accesses` -- but its
    ``is_write`` is always ``False``, so a View, a Function, or an unresolved
    path can never become a confirmed writer by accident.

    Builds Execution Paths itself, once, from ``invocations``. A caller that
    already holds Execution Paths for the same invocations and graph -- for
    example one asking about more than one table in the same scope -- should call
    `filter_table_accesses` directly instead, so paths are not rebuilt per table.
    """
    paths = build_execution_paths(invocations, graph, max_call_depth=max_call_depth)
    return filter_table_accesses(paths, graph, table_name, access=access, database=database)


def filter_table_accesses(
    paths: Iterable[Mapping[str, Any]],
    graph: Mapping[str, Any],
    table_name: str,
    *,
    access: str = "all",
    database: str = "",
) -> list[dict[str, Any]]:
    """Return every C#-to-table fact an already-built set of Execution Paths holds.

    An Execution Path that reaches ``table_name`` produces a record whether or
    not it is `proven` -- a path whose evidence is not `proven` is downgraded,
    not dropped: its record claims no mutation (``is_write`` is always
    ``False``, and ``access_type`` reads ``"UNRESOLVED"``), and carries the
    path's Evidence Status and its reason instead. A caller that wants proven
    facts only -- `write_only=True` at the `find_by_table` seam -- filters the
    returned records on Evidence Status itself; this function does not do
    that filtering, so it never has to report what it excluded. See
    ADR-0015.

    An Unresolved Dynamic SQL path names no table at all -- the dynamic text
    was never parsed, so it has no ``reads``/``writes`` to match by name. Under
    ``access="all"`` such a path is still surfaced, once per table asked
    about, because the graph genuinely cannot rule out that it touches this
    one. It is not surfaced for a directional ``access="read"``/``"write"``
    request, which has no name match to hang a direction off of.

    A path matches a table through its ``read_full_keys`` and ``write_full_keys``
    under the table match rule (see `table_match`). ``database`` is the Database
    of the request; a table name that states none takes it. A record carries
    ``unproven_schema`` in its ``risk_flags`` when the matched target states no
    schema, and ``stated_database`` when the target names another Database than
    the graph's own.

    Split out of `query_table_accesses` so a caller holding one scope's Execution
    Paths (see `service.analyze_service._execution_paths_for_scope`) can query
    more than one table without rebuilding them -- the paths themselves do not
    depend on which table is being asked about.
    """
    if access not in _ACCESS_MODES:
        raise ValueError(f"unsupported table access mode: {access}")

    question = TableQuestion.of(table_name, database)
    if not question.name:
        return []
    own_database = str(graph.get("database") or "")

    accesses: list[dict[str, Any]] = []
    lineage_index: _LineageIndex | None = None
    for path in paths:
        writes = _matching_targets(path.get("write_full_keys", []), question, own_database)
        reads = _matching_targets(path.get("read_full_keys", []), question, own_database)
        is_dynamic = "dynamic_sql" in set(path.get("risk_flags", []) or [])
        is_proven = path.get("evidence") == "proven" and not is_dynamic

        if writes and access in {"all", "write"}:
            accesses.append(_access_record(path, *writes[0], is_write=True, is_proven=is_proven))
            continue

        if reads and access in {"all", "read"}:
            accesses.append(_access_record(path, *reads[0], is_write=False, is_proven=is_proven))
            continue

        if access == "all" and is_dynamic and not writes and not reads:
            accesses.append(_access_record(path, table_name, None, is_write=False, is_proven=False))
            continue

        # A View/Function read reaches the table by lineage, not by name --
        # `is_proven` gated this before, so a path downgraded by a co-occurring
        # missing target elsewhere in the same operation (decision 3's own
        # motivating shape) vanished here exactly as it did at the direct-match
        # branches above. The lookup itself only depends on graph topology, not
        # on the path's evidence, so it runs regardless; `is_proven` still
        # decides whether the resulting record claims the read (ADR-0015).
        if access in {"all", "read"} and not writes and not reads:
            if lineage_index is None:
                lineage_index = _LineageIndex(graph)
            lineage_reads = lineage_index.read_lineage(path, question, own_database)
            for table, match in lineage_reads:
                accesses.append(
                    _access_record(
                        path,
                        table,
                        match,
                        is_write=False,
                        is_proven=is_proven,
                        is_indirect_override=True,
                    )
                )

    return sorted(accesses, key=_access_sort_key)


def _access_record(
    path: Mapping[str, Any],
    table_name: str,
    match: TableMatch | None,
    *,
    is_write: bool,
    is_proven: bool,
    is_indirect_override: bool | None = None,
) -> dict[str, Any]:
    """Build one access record; a non-`proven` path never claims a mutation.

    ``is_write`` states what the caller matched the path on (its ``writes``
    list vs. its ``reads`` list); it becomes the record's ``is_write`` only
    when the path is also `proven`. A `proven` write keeps its real operation
    as ``access_type``; anything not `proven` -- write-shaped or not -- reads
    ``"UNRESOLVED"``, per ADR-0015: the record states that the path reaches
    the table, not what it does there.

    ``table_name`` is the target as the graph stores it. ``match`` carries the
    Unproven Schema mark and ``stated_database`` of that target: the mark sits
    on this record and never on the path, because one path serves every table
    question in its scope.
    """
    sp_chain = list(path.get("sp_chain", []) or [])
    operation = str(path.get("terminal_operation") or "")
    confirmed_write = is_write and is_proven
    record = {
        "table": table_name,
        "access_type": (operation if confirmed_write else "READ") if is_proven else "UNRESOLVED",
        "is_write": confirmed_write,
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
        "schema_source": match.schema_source if match is not None else str(schema_resolution.SchemaSource.UNRESOLVED),
        "risk_flags": _record_risk_flags(path, match),
        "unresolved_reason": path.get("unresolved_reason", ""),
        "unresolved_targets": list(path.get("unresolved_targets", []) or []),
    }
    if match is not None and match.stated_database is not None:
        record["stated_database"] = match.stated_database
    for key in WRAPPER_EVIDENCE_FIELDS:
        if key not in path:
            continue
        value = path[key]
        record[key] = list(value) if isinstance(value, tuple) else value
    return record


class _Target(NamedTuple):
    """One table a View or a Function reaches, in the case the graph and the relationship state it."""

    database: str
    schema: str
    name: str
    schema_source: str = ""


_TargetKey = tuple[str, str, str]

# The tables one container reaches, keyed by full key. The Database comes from the
# relationship inside the container, because node identity holds no Database.
_Tables = dict[_TargetKey, _Target]


def _target_key(target: _Target) -> _TargetKey:
    return part_key(target.database), part_key(target.schema), target.name.casefold()


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
    A table is keyed by its full key: the Database of the relationship that
    reads it, the schema of its node, and its bare name.
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

    __slots__ = ("_graph", "_reached")

    def __init__(self, graph: Mapping[str, Any]) -> None:
        self._graph = graph
        self._reached: dict[str, dict[_TargetKey, tuple[_Target, set[str]]]] | None = None

    def _ensure_built(self) -> dict[str, dict[_TargetKey, tuple[_Target, set[str]]]]:
        """Return bare name -> full key -> (table, ids of the operations that reach it)."""
        if self._reached is not None:
            return self._reached

        graph_database = str(self._graph.get("database") or "")

        nodes = {
            str(node.get("id")): node
            for node in self._graph.get("nodes", []) or []
            if node.get("id")
        }
        reads_by_source: dict[str, list[tuple[str, str, str]]] = {}  # source -> (target id, Database, schema source)
        contains_by_source: dict[str, list[str]] = {}
        for relationship in self._graph.get("relationships", []) or []:
            source = relationship.get("source")
            target = relationship.get("target")
            if not source or not target:
                continue
            source = str(source)
            target = str(target)
            if relationship.get("type") == "reads":
                # A relationship that states no Database takes the graph's own Database.
                database = str(relationship.get("database") or "") or graph_database
                reads_by_source.setdefault(source, []).append(
                    (target, database, str(relationship.get("schema_source") or ""))
                )
            elif relationship.get("type") == "contains":
                contains_by_source.setdefault(source, []).append(target)

        # A View or Function's own reachable tables depend on what its child
        # operations read -- a table directly, or another container, whose
        # own reachable tables must be folded in too. Resolve that as a
        # graph problem over containers alone: `direct_tables[container]` is
        # what its children read directly; `successors[container]` /
        # `predecessors[container]` are the edges to and from the other
        # containers those children read.
        direct_tables: dict[str, _Tables] = {}
        successors: dict[str, set[str]] = {}
        predecessors: dict[str, set[str]] = {}

        def _record_target(container_id: str, target_id: str, database: str, schema_source: str) -> None:
            node = nodes.get(target_id)
            if not node:
                return
            node_type = node.get("type")
            if node_type == "table":
                table = _table_of(node, database, schema_source)
                if table is not None:
                    _add_table(direct_tables.setdefault(container_id, {}), table)
            elif node_type in {"view", "function"}:
                successors.setdefault(container_id, set()).add(target_id)
                predecessors.setdefault(target_id, set()).add(container_id)

        for container_id, child_operation_ids in contains_by_source.items():
            for child_operation_id in child_operation_ids:
                for target_id, database, schema_source in reads_by_source.get(child_operation_id, []):
                    _record_target(container_id, target_id, database, schema_source)

        # Worklist fixed point: each container starts at its own direct
        # tables and grows by folding in each successor's tables, until a
        # round adds nothing new. A container revisited through a cycle is
        # simply reprocessed once its successor's own set has grown -- so a
        # cycle changes the order tables are folded in, never the result.
        reachable: dict[str, _Tables] = {
            container_id: dict(tables) for container_id, tables in direct_tables.items()
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
        reached_by_name: dict[str, dict[_TargetKey, tuple[_Target, set[str]]]] = {}
        for operation_id, targets in reads_by_source.items():
            reached: _Tables = {}
            for target_id, database, schema_source in targets:
                node = nodes.get(target_id)
                if not node:
                    continue
                node_type = node.get("type")
                if node_type == "table":
                    table = _table_of(node, database, schema_source)
                    if table is not None:
                        _add_table(reached, table)
                elif node_type in {"view", "function"}:
                    _merge_reachable(reached, reachable.get(target_id, {}))
            for key, table in reached.items():
                entry = reached_by_name.setdefault(table.name.casefold(), {}).setdefault(
                    key, (table, set())
                )
                entry[1].add(operation_id)

        self._reached = reached_by_name
        return reached_by_name

    def read_lineage(
        self, path: Mapping[str, Any], question: TableQuestion, own_database: str
    ) -> list[tuple[str, TableMatch]]:
        """Resolve a path's View/UDF reads to base tables without inferring writes.

        Returns each matched table with its match. A table reached by lineage
        reports its node name, as it did before the match compared schemas.
        """
        operation_id = str(path.get("terminal_operation_id") or "")
        if not operation_id:
            return []

        matches: list[tuple[str, TableMatch]] = []
        for table, operation_ids in self._ensure_built().get(question.name, {}).values():
            if operation_id not in operation_ids:
                continue
            match = question.match(
                ObjectName("", table.database, table.schema, table.name), own_database, table.schema_source
            )
            if match is not None:
                matches.append((table.name, match))
        return matches


def _table_of(node: Mapping[str, Any], database: str, schema_source: str = "") -> _Target | None:
    """One table node; a relationship that records no schema source takes the default of `recorded_source()`."""
    name = str(node.get("name") or "")
    if not name:
        return None
    schema = str(node.get("schema") or "")
    return _Target(
        database=database,
        schema=schema,
        name=name,
        schema_source=schema_resolution.recorded_source(schema_source, schema),
    )


def _stronger(kept: _Target, other: _Target) -> _Target:
    """The first spelling stays; the schema source becomes the stronger of the two."""
    return kept._replace(
        schema_source=schema_resolution.strongest_source(kept.schema_source, other.schema_source)
    )


def _add_table(reached: _Tables, table: _Target) -> None:
    """Record one table under its full key; the first spelling seen stays."""
    key = _target_key(table)
    reached[key] = _stronger(reached[key], table) if key in reached else table


def _merge_reachable(target: _Tables, source: Mapping[_TargetKey, _Target]) -> bool:
    """Fold `source`'s tables into `target`; report whether anything was new or stronger."""
    changed = False
    for key, table in source.items():
        if key not in target:
            target[key] = table
            changed = True
        elif (stronger := _stronger(target[key], table)) != target[key]:
            target[key] = stronger
            changed = True
    return changed


def _matching_targets(
    full_keys: Iterable[Mapping[str, Any]], question: TableQuestion, own_database: str
) -> list[tuple[str, TableMatch]]:
    """Return each full key that answers the question, as (target as stored, match)."""
    matches: list[tuple[str, TableMatch]] = []
    for full_key in full_keys or []:
        schema = str(full_key.get("schema") or "")
        name = str(full_key.get("name") or "")
        match = question.match(
            ObjectName("", str(full_key.get("database") or ""), schema, name),
            own_database,
            str(full_key.get("schema_source") or ""),
        )
        if match is not None:
            matches.append((schema_qualified(ObjectName("", "", schema, name)), match))
    return matches


def _record_risk_flags(path: Mapping[str, Any], match: TableMatch | None) -> list[str]:
    flags = list(path.get("risk_flags", []) or [])
    if match is not None and match.unproven_schema and UNPROVEN_SCHEMA not in flags:
        flags.append(UNPROVEN_SCHEMA)
    return flags


def _access_sort_key(access: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(access.get("entry_method", "")),
        str(access.get("path_id", "")),
        str(access.get("access_type", "")),
    )
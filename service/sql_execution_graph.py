"""Build the persisted SQL Execution Graph from ScriptDom operation facts."""

from __future__ import annotations

import dataclasses
from collections import deque
from pathlib import Path
from typing import Any, Callable

import schema_resolution
from canonical_object_identity import ObjectName, parse, part_key
from code_analyzer.sql_text_analysis import (
    HostSqlTextAnalysis,
    SqlOperation,
    SqlTextAnalysis,
    SqlTextAnalysisError,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHostError

from .table_match import names_another_database


# v2: nested CALL branches, unresolved dynamic SQL nodes, typed View/UDF uses,
# and bounded CTE/temp-table lineage are persisted in the graph payload.
# v3: newline-safe temp-file writes keep ScriptDom offsets aligned with the
# persisted definition text (ticket 01), and every dml_operation/
# unresolved_dynamic_sql node records its module's definition length for
# staleness detection (ticket 02). Bumped so every cache built before this
# fix is rejected until tools/repair_sql_execution_graphs.py (ticket 03)
# repairs it — offsets from a v2 cache can be silently wrong.
# v4: `_ensure_referenced_node()` now returns the id of the node `_add_node()`
# actually kept, instead of the id of a same-key node it silently discarded
# (reverse-lookup-drops-proven-writes, ticket 01). A v3 graph can hold
# relationship targets that name no node in the same graph -- a dangling id
# unresolves every proven fact in its Execution Path. Bumped once for the
# whole effort, not once per ticket.
# v5: each analyzer reference on an operation node is an object with four
# parts (server, database, schema, name), and each reads, writes, and calls
# relationship records the database and server its reference stated
# (canonical-object-identity, Step 2a). This version rises whenever the graph
# payload shape changes: an operator reads this shape from disk until Step 2b.
# tools/repair_sql_execution_graphs.py rebuilds a v4 graph from the cache's
# own definitions; nothing rebuilds one on the load path.
# v6: each `#name` temp table is one node for each module that uses it. The node
# id is the plain table id plus `@` and the owning module id, and the node gains
# `scope_module_id` (temp-table-scope, ticket 03). The node lookup key holds the
# scope. A `##name` global temp table stays one node for the Database. A temp
# table read expands to the base tables behind the writers of its own node, and
# behind the writers in its callers or its callees, with a worklist fixed point
# (temp-table-scope, ticket 04). A v5 graph, which joins every `#tmp` of the
# Database into one node, is rejected until it is rebuilt.
# v7: a reference that states no schema keeps an empty schema, and a call or a
# View/Function reference with no schema names every listed node with that bare
# name (canonical-object-identity, Step 2b). A v6 graph, which filled `dbo`, reads
# its no-schema targets as proven `dbo`, so it is rejected until it is rebuilt.
# v8: a reference that states no schema resolves as SQL Server resolves it
# (`sys` for a system name, then the module's schema, then `dbo`) and records
# its schema source; a call reaches one procedure; a CTE name is no table read;
# an UPDATE or DELETE alias writes the object it names
# (unstated-schema-resolves-as-sql-server-does). A v7 graph gives a no-schema
# target an empty schema and the Unproven Schema mark, reads CTE names as
# tables, and writes aliases, so it is rejected until it is rebuilt.
GRAPH_VERSION = 8
NodeKey = tuple[str, str, str, str]


class _NodeIndex(dict):
    """Nodes by full key.

    It also holds the schema and name of each object the cache lists, of any kind,
    for the schema resolution rule. A node that only a reference adds is not listed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._listed: set[tuple[str, str]] = set()

    def list_object(self, schema: str, name: str) -> None:
        self._listed.add((schema.casefold(), name.casefold()))

    def holds(self, schema: str, name: str) -> bool:
        return (schema.casefold(), name.casefold()) in self._listed


# Each collection of listed modules in a cache payload, with the node type of its modules.
MODULE_COLLECTIONS = (
    ("procedures", "stored_procedure"),
    ("views", "view"),
    ("functions", "function"),
)


def build_sql_execution_graph(
    data: dict[str, Any],
    sql_text_analysis: SqlTextAnalysis | None = None,
    project_root: Path | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Analyze refreshed SQL modules and return a deterministic graph payload."""
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    node_by_key = _NodeIndex()
    call_edges: set[tuple[str, str]] = set()
    module_specs: list[tuple[str, str, str, str]] = []

    for collection, object_type in MODULE_COLLECTIONS:
        for item in data.get(collection, []) or []:
            written = parse(str(item.get("name") or ""))
            object_schema, name = _object_schema(item, written), written.name
            if not name:
                continue
            module_id = _node_id(object_type, object_schema, name)
            _add_node(
                nodes,
                node_by_key,
                {
                    "id": module_id,
                    "type": object_type,
                    "schema": object_schema,
                    "name": name,
                },
            )
            node_by_key.list_object(object_schema, name)
            definition = str(item.get("definition") or "")
            if definition.strip():
                module_specs.append((object_type, object_schema, name, definition))

    for item in data.get("tables", []) or []:
        written = parse(str(item.get("name") or ""))
        object_schema, name = _object_schema(item, written), written.name
        if not name:
            continue
        _add_node(
            nodes,
            node_by_key,
            {
                "id": _node_id("table", object_schema, name),
                "type": "table",
                "schema": object_schema,
                "name": name,
            },
        )
        node_by_key.list_object(object_schema, name)

    parse_errors: list[dict[str, Any]] = []
    _report_progress(progress_callback, "graph", 0, len(module_specs), "")
    if module_specs:
        analysis = sql_text_analysis or HostSqlTextAnalysis.for_project(
            project_root or Path(__file__).resolve().parent.parent
        )

        def report_batch(completed: int, total: int) -> None:
            # The operator reads the name of the last SQL module of the batch.
            _report_progress(progress_callback, "graph", completed, total, module_specs[completed - 1][2])

        try:
            results = analysis.analyze([definition for _, _, _, definition in module_specs], report_batch)
        except SqlTextAnalysisError as exc:
            # SQL Text Analysis names the failed text by index; the operator needs the module.
            raise StaticAnalyzerHostError(
                f"SQL analysis failed for module {module_specs[exc.index][2]}: {exc}"
            ) from exc
        for (object_type, object_schema, name, definition), result in zip(module_specs, results, strict=True):
            module_id = _node_id(object_type, object_schema, name)
            for error in result.parse_errors:
                parse_errors.append(
                    {
                        "module_id": module_id,
                        "line": error.line,
                        "message": error.message,
                    }
                )
            for operation in result.operations:
                _add_operation(
                    nodes,
                    relationships,
                    node_by_key,
                    call_edges,
                    operation,
                    object_type,
                    object_schema,
                    name,
                    module_id,
                    str(data.get("database") or ""),
                    len(definition),
                )

    _expand_temp_table_lineage(nodes, relationships, call_edges, progress_callback)

    return {
        "graph_version": GRAPH_VERSION,
        "database": str(data.get("database") or ""),
        "nodes": nodes,
        "relationships": relationships,
        "parse_errors": parse_errors,
    }


_NO_DIRECTION, _UP, _DOWN = "none", "up", "down"
# A state: the owning module ("" for a global temp table), the temp table name
# key, and the direction of the calls that led to it.
_State = tuple[str, tuple[str, str], str]
_Chain = tuple[str, ...]


def _expand_temp_table_lineage(
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    call_edges: set[tuple[str, str]],
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> None:
    """Add one lineage read from each temp table read to each base table behind it.

    A temp table is visible along calls in one direction. A resolution that goes
    up to callers can only go up again. A resolution that goes down to callees
    can only go down again. The expansion does not detect shadowing, so it takes
    the union of the visible writers. A worklist fixed point computes the base
    tables of each state once, so the cost grows with the graph, not with the
    number of paths through it.
    """
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    reads_by_operation: dict[str, list[dict[str, Any]]] = {}
    writers_by_table: dict[str, set[str]] = {}
    for relationship in relationships:
        relationship_type = relationship.get("type")
        source_id = str(relationship.get("source") or "")
        target_id = str(relationship.get("target") or "")
        if relationship_type == "reads":
            reads_by_operation.setdefault(source_id, []).append(relationship)
        elif relationship_type == "writes":
            writers_by_table.setdefault(target_id, set()).add(source_id)

    callers_of: dict[str, set[str]] = {}
    callees_of: dict[str, set[str]] = {}
    for caller_id, callee_id in call_edges:
        callees_of.setdefault(caller_id, set()).add(callee_id)
        callers_of.setdefault(callee_id, set()).add(caller_id)

    def is_temp_table(node_id: str) -> bool:
        return str(node_by_id.get(node_id, {}).get("name") or "").startswith("#")

    def name_key(node: dict[str, Any]) -> tuple[str, str]:
        return str(node.get("schema") or "").casefold(), str(node.get("name") or "").casefold()

    # A module that never names a temp table has no node for it, but the
    # temp table stays visible through that module.
    node_of_scope: dict[tuple[str, tuple[str, str]], str] = {}
    for node in nodes:
        if node.get("scope_module_id"):
            node_of_scope[(str(node["scope_module_id"]), name_key(node))] = str(node["id"])

    def state_of(node_id: str, direction: str) -> _State:
        node = node_by_id[node_id]
        if node.get("scope_module_id"):
            return str(node["scope_module_id"]), name_key(node), direction
        # A global temp table has no scope: its key holds the node id.
        return "", (node_id, ""), _NO_DIRECTION

    def node_id_of(state: _State) -> str:
        scope, key, _ = state
        return key[0] if not scope else node_of_scope.get((scope, key), "")

    temp_reads = [
        relationship
        for relationship in relationships
        if relationship.get("type") == "reads" and is_temp_table(str(relationship.get("target") or ""))
    ]
    _report_progress(progress_callback, "lineage", 0, len(temp_reads), "")

    # The base tables of a state are the non-temp reads of its own writers, each
    # with the server and database that read stated. A temp read of a writer is
    # an edge to another state in the same direction. A call is an edge to the
    # same temp table in a caller or a callee. Each base table keeps its chain and
    # the schema source of the read at the end of that chain.
    base_tables: dict[_State, dict[tuple[str, str, str], tuple[_Chain, str]]] = {}
    successors: dict[_State, set[_State]] = {}
    predecessors: dict[_State, set[_State]] = {}
    pending = [state_of(str(relationship.get("target") or ""), _NO_DIRECTION) for relationship in temp_reads]
    while pending:
        state = pending.pop()
        if state in base_tables:
            continue
        scope, key, direction = state
        own_node_id = node_id_of(state)
        own: dict[tuple[str, str, str], tuple[_Chain, str]] = {}
        base_tables[state] = own
        edges = successors.setdefault(state, set())
        for writer_id in writers_by_table.get(own_node_id, ()):
            for writer_read in reads_by_operation.get(writer_id, []):
                read_id = str(writer_read.get("target") or "")
                if is_temp_table(read_id):
                    edges.add(state_of(read_id, direction))
                else:
                    base = (
                        read_id,
                        str(writer_read.get("server") or ""),
                        str(writer_read.get("database") or ""),
                    )
                    # Two writers of one temp table that read one base table keep the strongest source.
                    schema_source = str(writer_read["schema_source"])
                    kept_source = own[base][1] if base in own else schema_source
                    own[base] = (
                        (own_node_id,),
                        schema_resolution.strongest_source(kept_source, schema_source),
                    )
        if scope:
            if direction != _DOWN:
                edges.update((caller, key, _UP) for caller in callers_of.get(scope, ()))
            if direction != _UP:
                edges.update((callee, key, _DOWN) for callee in callees_of.get(scope, ()))
        for successor in edges:
            predecessors.setdefault(successor, set()).add(state)
            pending.append(successor)

    # Worklist fixed point, as in graph_queries._LineageIndex: a state grows by
    # each successor's base tables until no set changes. Each base table keeps
    # its shortest chain of temp nodes, and a tie goes to the lower chain, so a
    # cycle ends and visit order does not change the result.
    queue: deque[_State] = deque(sorted(base_tables))
    queued: set[_State] = set(queue)
    while queue:
        state = queue.popleft()
        queued.discard(state)
        own = base_tables[state]
        prefix = (node_id_of(state),) if node_id_of(state) else ()
        changed = False
        for successor in successors.get(state, ()):
            for base, (chain, schema_source) in base_tables[successor].items():
                candidate = prefix + chain
                kept = own.get(base)
                if kept is None or (len(candidate), candidate) < (len(kept[0]), kept[0]):
                    own[base] = (candidate, schema_source)
                    changed = True
        if changed:
            for predecessor in predecessors.get(state, ()):
                if predecessor not in queued:
                    queue.append(predecessor)
                    queued.add(predecessor)

    # `temp_reads` is its own list, so a lineage read that joins `relationships` here is not read again.
    for index, relationship in enumerate(temp_reads, start=1):
        source_id = str(relationship.get("source") or "")
        temp_id = str(relationship.get("target") or "")
        state = state_of(temp_id, _NO_DIRECTION)
        for (base_id, server, database), (chain, schema_source) in sorted(base_tables.get(state, {}).items()):
            branch_path = list(relationship.get("branch_path") or [])
            _add_relationship(
                relationships,
                "reads",
                source_id,
                base_id,
                dict(relationship.get("source_location") or {}),
                branch_path,
                conditions=branch_path,
                identity_suffix=f"lineage:{chain[0]}",
                stated=ObjectName(server=server, database=database, schema="", name=""),
                schema_source=schema_source,
            )
            relationships[-1]["lineage"] = list(chain)
        _report_progress(progress_callback, "lineage", index, len(temp_reads), source_id)


def _report_progress(
    callback: Callable[[str, int, int, str], None] | None,
    stage: str,
    current: int,
    total: int,
    item: str,
) -> None:
    if callback is None:
        return
    try:
        callback(stage, current, total, item)
    except Exception:
        pass


def _add_operation(
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    node_by_key: _NodeIndex,
    call_edges: set[tuple[str, str]],
    operation: SqlOperation,
    module_type: str,
    module_schema: str,
    module_name: str,
    module_id: str,
    cache_database: str,
    module_definition_length: int,
) -> None:
    # The source location keeps the key order the analyzer host reports; the
    # module id stands in the place of the host's file path.
    source = {
        "source_path": module_id,
        **dataclasses.asdict(operation.source),
        "module_id": module_id,
        "module_definition_length": module_definition_length,
    }
    sequence = operation.sequence
    operation_type = operation.operation_type
    branch_path = list(operation.branch_path)
    conditions = operation.conditions or operation.branch_path

    if operation_type == "CALL":
        for target in operation.call_targets:
            if not target.name:
                continue
            call = _call_target(node_by_key, target, module_schema, cache_database)
            if call.names_module_node:
                # The temp table expansion reads calls only from these edges.
                call_edges.add((module_id, call.node_id))
            _add_relationship(
                relationships,
                "calls",
                module_id,
                call.node_id,
                source,
                branch_path,
                conditions=list(conditions),
                identity_suffix=str(sequence),
                stated=call.target,
                schema_source=call.schema_source,
            )
        return

    node_type = "unresolved_dynamic_sql" if (
        operation_type == "DYNAMIC_SQL" or operation.dynamic_sql
    ) else "dml_operation"
    operation_id = f"{node_type}:{module_id}:{sequence}"
    # The node holds every field of the operation, in the order the analyzer host
    # reports them. The cache file holds this order, so a change here changes the payload.
    operation_node = {
        "id": operation_id,
        "type": node_type,
        "operation_type": operation_type,
        "module": {
            "type": module_type,
            "schema": module_schema,
            "name": module_name,
        },
        "sequence": sequence,
        "branch_path": list(operation.branch_path),
        "conditions": list(operation.conditions),
        "where": operation.where,
        "read_tables": [dataclasses.asdict(reference) for reference in operation.read_tables],
        "write_tables": [dataclasses.asdict(reference) for reference in operation.write_tables],
        "unresolved_write_targets": list(operation.unresolved_write_targets),
        "read_columns": list(operation.read_columns),
        "written_columns": list(operation.written_columns),
        "function_references": [dataclasses.asdict(reference) for reference in operation.function_references],
        "call_targets": [dataclasses.asdict(reference) for reference in operation.call_targets],
        "dynamic_sql": operation.dynamic_sql,
        "source": source,
        "module_id": module_id,
    }
    _add_node(nodes, node_by_key, operation_node)

    _add_relationship(
        relationships,
        "contains",
        module_id,
        operation_id,
        source,
        branch_path,
    )

    if node_type == "unresolved_dynamic_sql":
        _add_relationship(
            relationships,
            "unresolved",
            module_id,
            operation_id,
            source,
            branch_path,
            conditions=list(conditions),
            confidence="unresolved",
        )
        return

    for read_table in operation.read_tables:
        reference, schema_source = _resolved_reference(node_by_key, read_table, module_schema)
        target_id = _referenced_node_id(nodes, node_by_key, reference, module_id, cache_database)
        _add_relationship(
            relationships,
            "reads",
            operation_id,
            target_id,
            source,
            branch_path,
            columns=list(operation.read_columns),
            stated=reference,
            schema_source=schema_source,
        )
        if target_id.split(":", 1)[0] in {"view", "function"}:
            _add_relationship(
                relationships,
                "uses",
                module_id,
                target_id,
                source,
                branch_path,
                conditions=list(conditions),
                schema_source=schema_source,
            )

    for write_table in operation.write_tables:
        reference, schema_source = _resolved_reference(node_by_key, write_table, module_schema)
        _add_relationship(
            relationships,
            "writes",
            operation_id,
            _referenced_node_id(nodes, node_by_key, reference, module_id, cache_database),
            source,
            branch_path,
            columns=list(operation.written_columns),
            stated=reference,
            schema_source=schema_source,
        )

    for function_reference in operation.function_references:
        reference, schema_source = _resolved_reference(node_by_key, function_reference, module_schema)
        function_id = _listed_function_id(node_by_key, reference, cache_database)
        if function_id is not None:
            _add_relationship(
                relationships,
                "uses",
                module_id,
                function_id,
                source,
                branch_path,
                conditions=list(conditions),
                schema_source=schema_source,
            )


def _resolved_reference(
    node_by_key: _NodeIndex, reference: ObjectName, module_schema: str
) -> tuple[ObjectName, str]:
    """Give one analyzer reference the schema SQL Server resolves, with its schema source."""
    return _with_resolved_schema(node_by_key, reference, module_schema, schema_resolution.resolve)


@dataclasses.dataclass(frozen=True)
class _CallTarget:
    """What one `calls` relationship names."""

    # The target with the schema that the rule gave it.
    target: ObjectName
    schema_source: str
    # The id of the module node, or the id of the resolved name when no module node answers.
    node_id: str
    names_module_node: bool


def _call_target(
    node_by_key: _NodeIndex, target: ObjectName, module_schema: str, cache_database: str
) -> _CallTarget:
    """Give a call target the schema SQL Server resolves, its schema source, and its node id.

    This is the one site that holds the call target rule (ADR-0036, ADR-0037).
    A call through a linked server or to another Database is resolved by no
    listing of this cache, so it keeps what it states and has no module node. A
    call to a module that this cache does not list has no module node either. A
    listed module with no definition is a node.
    """
    module = None
    if target.server or names_another_database(target.database, cache_database):
        schema_source = schema_resolution.recorded_source("", target.schema)
    else:
        target, schema_source = _with_resolved_schema(
            node_by_key, target, module_schema, schema_resolution.resolve_call
        )
        # An empty schema matches no listed node, because a listed node always carries a schema.
        if target.schema:
            module = node_by_key.get(_node_key("stored_procedure", target.schema, target.name))
    node_id = str(module["id"]) if module is not None else _node_id("stored_procedure", target.schema, target.name)
    return _CallTarget(target, str(schema_source), node_id, module is not None)


def _with_resolved_schema(
    node_by_key: _NodeIndex,
    reference: ObjectName,
    module_schema: str,
    rule: Callable[[ObjectName, str, Callable[[str, str], bool]], tuple[str, str]],
) -> tuple[ObjectName, str]:
    """Give ``reference`` the schema that ``rule`` resolves against the cache listing, with its schema source."""
    schema, schema_source = rule(reference, module_schema, node_by_key.holds)
    return dataclasses.replace(reference, schema=schema), schema_source


def _referenced_node_id(
    nodes: list[dict[str, Any]],
    node_by_key: _NodeIndex,
    reference: ObjectName,
    module_id: str,
    cache_database: str,
) -> str:
    """Return the id of the node that one resolved table, View, or Function reference names.

    A reference that names a listed View or Function returns its id. Any other
    reference is a table node that keeps the resolved schema, and an empty schema
    when the resolution rule left it empty. The node takes no database: node
    identity is type, schema, and name, and the relationship records the database
    its reference stated.
    """
    object_schema, name = reference.schema, reference.name
    if _is_scoped_temp_table(name):
        # A `#name` temp table belongs to the module that uses it.
        node = {
            "id": _node_id("table", object_schema, name, module_id),
            "type": "table",
            "schema": object_schema,
            "name": name,
            "scope_module_id": module_id,
        }
        return str(_add_node(nodes, node_by_key, node)["id"])
    # A reference to another Database matches no listed View or Function: this cache
    # holds no definition of that object, so a local node would be false evidence.
    # An unresolved reference names no listed object either.
    if object_schema and not names_another_database(reference.database, cache_database):
        for object_type in ("view", "function"):
            listed = node_by_key.get(_node_key(object_type, object_schema, name))
            if listed:
                return str(listed["id"])

    node = {
        "id": _node_id("table", object_schema, name),
        "type": "table",
        "schema": object_schema,
        "name": name,
    }
    kept_node = _add_node(nodes, node_by_key, node)
    return str(kept_node["id"])


def _listed_function_id(
    node_by_key: _NodeIndex,
    reference: ObjectName,
    cache_database: str,
) -> str | None:
    """Return the id of the listed Function that one resolved reference names, or None."""
    # A reference to another Database matches no node: this cache holds no
    # definition of that object, so a local node would be false evidence. An
    # unresolved reference names no listed function either.
    if not reference.schema or names_another_database(reference.database, cache_database):
        return None
    node = node_by_key.get(_node_key("function", reference.schema, reference.name))
    return str(node["id"]) if node else None


def _add_relationship(
    relationships: list[dict[str, Any]],
    relationship_type: str,
    source_id: str,
    target_id: str,
    source_location: dict[str, Any],
    branch_path: list[str],
    columns: list[str] | None = None,
    conditions: list[str] | None = None,
    confidence: str = "proven",
    identity_suffix: str = "",
    stated: ObjectName | None = None,
    schema_source: str = "",
) -> None:
    relationship_id = f"{relationship_type}:{source_id}:{target_id}"
    if identity_suffix:
        relationship_id = f"{relationship_id}:{identity_suffix}"
    # Two references that name one node from two Databases are two relationships.
    if stated is not None and (stated.server or stated.database):
        relationship_id = f"{relationship_id}@{stated.server}.{stated.database}"
    relationship = {
        "id": relationship_id,
        "type": relationship_type,
        "source": source_id,
        "target": target_id,
        "confidence": confidence,
        "branch_path": branch_path,
        "source_location": source_location,
    }
    if columns:
        relationship["columns"] = columns
    if conditions:
        relationship["conditions"] = conditions
    # The database is recorded as stated. The read side, which knows the SQL
    # Cache Identity, reads an unstated database as the cache's own Database.
    if stated is not None and stated.database:
        relationship["database"] = stated.database
    if stated is not None and stated.server:
        relationship["server"] = stated.server
    if schema_source:
        # The payload holds plain text, not the enum member.
        relationship["schema_source"] = str(schema_source)
    relationships.append(relationship)


def _object_schema(item: dict[str, Any], written: ObjectName) -> str:
    """The schema of one listed object: its own `schema` field, then the name it is written with.

    A cache written before each object carried its own schema holds none, and
    holds no other schema than `dbo`, so an object that states none reads as `dbo`.
    """
    return str(item.get("schema") or "") or written.schema or "dbo"


def _add_node(
    nodes: list[dict[str, Any]],
    node_by_key: _NodeIndex,
    node: dict[str, Any],
) -> dict[str, Any]:
    """Add ``node`` unless a node already holds its case-insensitive key.

    Returns the node that now occupies that key -- the existing node it kept,
    or ``node`` itself when none existed. A caller that builds a relationship
    target id from ``node`` must use this return value, not ``node["id"]``:
    the id it built may name a node this call decided not to add.
    """
    object_type = str(node.get("type", ""))
    schema = str(node.get("schema", ""))
    name = str(node.get("name", ""))
    key = _node_key(object_type, schema, name, str(node.get("scope_module_id", ""))) if name else (
        object_type,
        str(node.get("id", "")).casefold(),
        "",
        "",
    )
    if key in node_by_key:
        return node_by_key[key]
    node_by_key[key] = node
    nodes.append(node)
    return node


def _node_key(object_type: str, schema: str, name: str, scope_module_id: str = "") -> NodeKey:
    return object_type, schema.casefold(), name.casefold(), scope_module_id.casefold()


def _node_id(object_type: str, schema: str, name: str, scope_module_id: str = "") -> str:
    """The one node identity function: a scoped node adds `@` and its owning module id."""
    node_id = f"{object_type}:{schema}.{name}"
    return f"{node_id}@{scope_module_id}" if scope_module_id else node_id


def _is_scoped_temp_table(name: str) -> bool:
    """A `#name` temp table is scoped to its module; a `##name` global temp table is not."""
    return name.startswith("#") and not name.startswith("##")

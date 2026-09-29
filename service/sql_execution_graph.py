"""Build the persisted SQL Execution Graph from ScriptDom operation facts."""

from __future__ import annotations

import re
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Callable

from canonical_object_identity import ObjectName, parse, part_key
from code_analyzer.static_analyzer_host import StaticAnalyzerHost, StaticAnalyzerHostError

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
GRAPH_VERSION = 7
NodeKey = tuple[str, str, str, str]


class _NodeIndex(dict):
    """Nodes by full key, plus the same nodes by bare name for a reference that states no schema."""

    def __init__(self) -> None:
        super().__init__()
        self.bare: dict[tuple[str, str], list[dict[str, Any]]] = {}


_MODULE_COLLECTIONS = (
    ("procedures", "stored_procedure"),
    ("views", "view"),
    ("functions", "function"),
)


def build_sql_execution_graph(
    data: dict[str, Any],
    host: StaticAnalyzerHost | None = None,
    project_root: Path | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Analyze refreshed SQL modules and return a deterministic graph payload."""
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    node_by_key = _NodeIndex()
    call_edges: set[tuple[str, str]] = set()
    module_specs: list[tuple[str, str, str, str]] = []

    for collection, object_type in _MODULE_COLLECTIONS:
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

    parse_errors: list[dict[str, Any]] = []
    _report_progress(progress_callback, "graph", 0, len(module_specs), "")
    if module_specs:
        analyzer = host or StaticAnalyzerHost.for_project(
            project_root or Path(__file__).resolve().parent.parent
        )
        analyzer.ensure_ready()
        with tempfile.TemporaryDirectory(prefix="sql-graph-") as temp_dir:
            temp_root = Path(temp_dir)
            input_paths: list[Path] = []
            for index, (_, _, name, definition) in enumerate(module_specs, start=1):
                input_path = temp_root / f"{index:05d}_{_safe_name(name)}.sql"
                input_path.write_text(definition, encoding="utf-8", newline="")
                input_paths.append(input_path)
            name_by_path = {str(path): spec[2] for path, spec in zip(input_paths, module_specs)}

            def report_batch(completed: int, total: int, last_input: str) -> None:
                _report_progress(progress_callback, "graph", completed, total, name_by_path[last_input])

            try:
                results = analyzer.analyze_sql_files(input_paths, report_batch)
            except StaticAnalyzerHostError as exc:
                # The host names the failed input by path; the operator needs the module.
                module_name = next((name for path, name in name_by_path.items() if path in str(exc)), None)
                if module_name is None:
                    raise
                raise StaticAnalyzerHostError(f"SQL analysis failed for module {module_name}: {exc}") from exc
            if len(results) != len(module_specs):
                raise StaticAnalyzerHostError("StaticAnalyzerHost returned a SQL result count that differs from the module count")
            for (object_type, object_schema, name, definition), result in zip(module_specs, results):
                module_id = _node_id(object_type, object_schema, name)
                for error in result.get("parse_errors", []) or []:
                    parse_errors.append(
                        {
                            "module_id": module_id,
                            "line": error.get("line", 0),
                            "message": error.get("message", ""),
                        }
                    )
                for raw_operation in result.get("operations", []) or []:
                    _add_operation(
                        nodes,
                        relationships,
                        node_by_key,
                        call_edges,
                        raw_operation,
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
    # same temp table in a caller or a callee.
    base_tables: dict[_State, dict[tuple[str, str, str], _Chain]] = {}
    successors: dict[_State, set[_State]] = {}
    predecessors: dict[_State, set[_State]] = {}
    pending = [state_of(str(relationship.get("target") or ""), _NO_DIRECTION) for relationship in temp_reads]
    while pending:
        state = pending.pop()
        if state in base_tables:
            continue
        scope, key, direction = state
        own_node_id = node_id_of(state)
        own: dict[tuple[str, str, str], _Chain] = {}
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
                    own[base] = (own_node_id,)
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
            for base, chain in base_tables[successor].items():
                candidate = prefix + chain
                kept = own.get(base)
                if kept is None or (len(candidate), candidate) < (len(kept), kept):
                    own[base] = candidate
                    changed = True
        if changed:
            for predecessor in predecessors.get(state, ()):
                if predecessor not in queued:
                    queue.append(predecessor)
                    queued.add(predecessor)

    derived: list[tuple[str, str, ObjectName, dict[str, Any], list[str], list[str]]] = []
    for index, relationship in enumerate(temp_reads, start=1):
        source_id = str(relationship.get("source") or "")
        temp_id = str(relationship.get("target") or "")
        state = state_of(temp_id, _NO_DIRECTION)
        for (base_id, server, database), chain in sorted(base_tables.get(state, {}).items()):
            derived.append(
                (
                    source_id,
                    base_id,
                    ObjectName(server=server, database=database, schema="", name=""),
                    dict(relationship.get("source_location") or {}),
                    list(relationship.get("branch_path") or []),
                    list(chain),
                )
            )
        _report_progress(progress_callback, "lineage", index, len(temp_reads), source_id)

    for source_id, target_id, stated, source_location, branch_path, lineage in derived:
        _add_relationship(
            relationships,
            "reads",
            source_id,
            target_id,
            source_location,
            branch_path,
            conditions=branch_path,
            identity_suffix=f"lineage:{lineage[0]}",
            stated=stated,
        )
        relationships[-1]["lineage"] = lineage


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
    raw_operation: dict[str, Any],
    module_type: str,
    module_schema: str,
    module_name: str,
    module_id: str,
    cache_database: str,
    module_definition_length: int,
) -> None:
    module = {
        "type": module_type,
        "schema": module_schema,
        "name": module_name,
    }
    operation = dict(raw_operation)
    operation["module"] = module
    operation["module_id"] = module_id
    source = dict(operation.get("source") or {})
    source["source_path"] = module_id
    source["module_id"] = module_id
    source["module_definition_length"] = module_definition_length
    operation["source"] = source
    sequence = int(operation.get("sequence") or 0)
    operation_type = str(operation.get("operation_type") or "")
    branch_path = list(operation.get("branch_path") or [])

    if operation_type == "CALL":
        call_conditions = list(operation.get("conditions") or branch_path)
        for call_target in operation.get("call_targets", []) or []:
            target = _reference(call_target)
            if not target.name:
                continue
            for target_id, target_module in _resolve_call_target(node_by_key, target, cache_database):
                if target_module is not None:
                    # The temp table expansion reads calls only from these edges.
                    call_edges.add((module_id, str(target_module["id"])))
                _add_relationship(
                    relationships,
                    "calls",
                    module_id,
                    target_id,
                    source,
                    branch_path,
                    conditions=call_conditions,
                    identity_suffix=str(sequence),
                    stated=target,
                )
        return

    node_type = "unresolved_dynamic_sql" if (
        operation_type == "DYNAMIC_SQL" or operation.get("dynamic_sql") is True
    ) else "dml_operation"
    operation_id = f"{node_type}:{module_id}:{sequence}"
    operation_node = {
        "id": operation_id,
        "type": node_type,
        **operation,
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
            conditions=list(operation.get("conditions") or branch_path),
            confidence="unresolved",
        )
        return

    for read_table in operation.get("read_tables", []) or []:
        reference = _reference(read_table)
        for target_id in _ensure_referenced_nodes(
            nodes, node_by_key, reference, module_id, cache_database
        ):
            _add_relationship(
                relationships,
                "reads",
                operation_id,
                target_id,
                source,
                branch_path,
                columns=list(operation.get("read_columns", []) or []),
                stated=reference,
            )
            if target_id.split(":", 1)[0] in {"view", "function"}:
                _add_relationship(
                    relationships,
                    "uses",
                    module_id,
                    target_id,
                    source,
                    branch_path,
                    conditions=list(operation.get("conditions") or branch_path),
                )

    for write_table in operation.get("write_tables", []) or []:
        reference = _reference(write_table)
        for target_id in _ensure_referenced_nodes(
            nodes, node_by_key, reference, module_id, cache_database
        ):
            _add_relationship(
                relationships,
                "writes",
                operation_id,
                target_id,
                source,
                branch_path,
                columns=list(operation.get("written_columns", []) or []),
                stated=reference,
            )

    for function_reference in operation.get("function_references", []) or []:
        for target_id in _known_object_node_ids(
            node_by_key,
            "function",
            _reference(function_reference),
            cache_database,
        ):
            _add_relationship(
                relationships,
                "uses",
                module_id,
                target_id,
                source,
                branch_path,
                conditions=list(operation.get("conditions") or branch_path),
            )


def _reference(entry: dict[str, Any]) -> ObjectName:
    """Read one analyzer reference; the host always reports all four parts."""
    return ObjectName(
        server=str(entry.get("server") or ""),
        database=str(entry.get("database") or ""),
        schema=str(entry.get("schema") or ""),
        name=str(entry.get("name") or ""),
    )


def _listed_nodes(
    node_by_key: _NodeIndex, object_type: str, schema: str, name: str
) -> list[dict[str, Any]]:
    """The listed nodes one reference names, under the two-bucket rule.

    A reference that states a schema matches the node of that full key. A reference
    that states no schema matches every node of that type with the bare name. The
    lookup never fills an unstated schema with `dbo`. Listed nodes always carry a
    schema, so none of them carries the Unproven Schema mark.
    """
    if schema:
        node = node_by_key.get(_node_key(object_type, schema, name))
        return [node] if node else []
    return list(node_by_key.bare.get((object_type, name.casefold()), []))


def _ensure_referenced_nodes(
    nodes: list[dict[str, Any]],
    node_by_key: _NodeIndex,
    reference: ObjectName,
    module_id: str,
    cache_database: str,
) -> list[str]:
    """Return the ids of the nodes one table, View, or Function reference names.

    A reference that names a listed View or Function returns their ids. Any other
    reference is a table node that keeps the schema the reference states, and an
    empty schema when it states none. The node takes no database: node identity is
    type, schema, and name, and the relationship records the database its
    reference stated.
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
        return [str(_add_node(nodes, node_by_key, node)["id"])]
    # A reference to another Database matches no listed View or Function: this cache
    # holds no definition of that object, so a local node would be false evidence.
    if not names_another_database(reference.database, cache_database):
        for object_type in ("view", "function"):
            listed = _listed_nodes(node_by_key, object_type, object_schema, name)
            if listed:
                return [str(node["id"]) for node in listed]

    node = {
        "id": _node_id("table", object_schema, name),
        "type": "table",
        "schema": object_schema,
        "name": name,
    }
    kept_node = _add_node(nodes, node_by_key, node)
    return [str(kept_node["id"])]


def _resolve_call_target(
    node_by_key: _NodeIndex,
    target: ObjectName,
    cache_database: str,
) -> list[tuple[str, dict[str, Any] | None]]:
    """Return each node id a calls relationship names, with the module node the graph defines for it or None."""
    # A call through a linked server, to another Database, or to a module that this
    # cache does not list has no module node. A listed module with no definition is a node.
    # A call target that states no schema matches every listed procedure with that bare name.
    stated_id = _node_id("stored_procedure", target.schema, target.name)
    if target.server or names_another_database(target.database, cache_database):
        return [(stated_id, None)]
    modules = _listed_nodes(node_by_key, "stored_procedure", target.schema, target.name)
    if not modules:
        return [(stated_id, None)]
    return [(str(module["id"]), module) for module in modules]


def _known_object_node_ids(
    node_by_key: _NodeIndex,
    object_type: str,
    reference: ObjectName,
    cache_database: str,
) -> list[str]:
    # A reference to another Database matches no node: this cache holds no
    # definition of that object, so a local node would be false evidence.
    if names_another_database(reference.database, cache_database):
        return []
    return [
        str(node["id"])
        for node in _listed_nodes(node_by_key, object_type, reference.schema, reference.name)
    ]


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
    if name:
        node_by_key.bare.setdefault((object_type, name.casefold()), []).append(node)
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


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("_") or "module"
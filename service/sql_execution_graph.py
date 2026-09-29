"""Build the persisted SQL Execution Graph from ScriptDom operation facts."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from canonical_object_identity import ObjectName, parse, part_key
from code_analyzer.static_analyzer_host import StaticAnalyzerHost


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
GRAPH_VERSION = 5
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
    node_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
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
            for index, (object_type, object_schema, name, definition) in enumerate(module_specs, start=1):
                module_id = _node_id(object_type, object_schema, name)
                input_path = temp_root / f"{index:05d}_{_safe_name(name)}.sql"
                input_path.write_text(definition, encoding="utf-8", newline="")
                result = analyzer.analyze_sql(input_path)
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
                        raw_operation,
                        object_type,
                        object_schema,
                        name,
                        module_id,
                        str(data.get("database") or ""),
                        len(definition),
                    )
                _report_progress(progress_callback, "graph", index, len(module_specs), name)

    _expand_temp_table_lineage(nodes, relationships)

    return {
        "graph_version": GRAPH_VERSION,
        "database": str(data.get("database") or ""),
        "nodes": nodes,
        "relationships": relationships,
        "parse_errors": parse_errors,
    }


def _expand_temp_table_lineage(
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    max_depth: int = 32,
) -> None:
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    reads_by_operation: dict[str, list[dict[str, Any]]] = {}
    writers_by_table: dict[str, list[str]] = {}
    for relationship in relationships:
        relationship_type = relationship.get("type")
        source_id = str(relationship.get("source") or "")
        target_id = str(relationship.get("target") or "")
        if relationship_type == "reads":
            reads_by_operation.setdefault(source_id, []).append(relationship)
        elif relationship_type == "writes":
            writers_by_table.setdefault(target_id, []).append(source_id)

    def is_temp_table(node_id: str) -> bool:
        return str(node_by_id.get(node_id, {}).get("name") or "").startswith("#")

    def resolve_base_targets(
        read_relationship: dict[str, Any],
        visited: frozenset[str] = frozenset(),
    ) -> set[tuple[str, str, str]]:
        """Return each base table id behind one read, with the server and database that read stated."""
        table_id = str(read_relationship.get("target") or "")
        if not is_temp_table(table_id):
            return {
                (
                    table_id,
                    str(read_relationship.get("server") or ""),
                    str(read_relationship.get("database") or ""),
                )
            }
        if table_id in visited or len(visited) >= max_depth:
            return set()
        base_targets: set[tuple[str, str, str]] = set()
        next_visited = visited | {table_id}
        for writer_id in sorted(set(writers_by_table.get(table_id, []))):
            for writer_read in sorted(
                reads_by_operation.get(writer_id, []),
                key=lambda item: str(item.get("target") or ""),
            ):
                base_targets.update(resolve_base_targets(writer_read, next_visited))
        return base_targets

    derived: list[tuple[str, str, ObjectName, dict[str, Any], list[str], list[str]]] = []
    for relationship in list(relationships):
        if relationship.get("type") != "reads":
            continue
        source_id = str(relationship.get("source") or "")
        temp_id = str(relationship.get("target") or "")
        if not is_temp_table(temp_id):
            continue
        for base_id, server, database in sorted(resolve_base_targets(relationship)):
            derived.append(
                (
                    source_id,
                    base_id,
                    ObjectName(server=server, database=database, schema="", name=""),
                    dict(relationship.get("source_location") or {}),
                    list(relationship.get("branch_path") or []),
                    [temp_id],
                )
            )

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
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
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
            # A call target that states no schema reads as dbo here. Step 2b removes this default.
            target_schema, target_name = target.schema or "dbo", target.name
            if not target_name:
                continue
            _add_relationship(
                relationships,
                "calls",
                module_id,
                _node_id("stored_procedure", target_schema, target_name),
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
        target_id = _ensure_referenced_node(nodes, node_by_key, reference)
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
        target_id = _ensure_referenced_node(nodes, node_by_key, reference)
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
        target_id = _known_object_node_id(
            node_by_key,
            "function",
            _reference(function_reference),
            cache_database,
        )
        if target_id:
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


def _ensure_referenced_node(
    nodes: list[dict[str, Any]],
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
    reference: ObjectName,
) -> str:
    # A reference that states no schema reads as dbo here. Step 2b removes this default.
    # The node takes no database: node identity is type, schema, and name, and the
    # relationship records the database its reference stated.
    object_schema, name = reference.schema or "dbo", reference.name
    view_key = _node_key("view", object_schema, name)
    function_key = _node_key("function", object_schema, name)
    if view_key in node_by_key:
        return str(node_by_key[view_key]["id"])
    if function_key in node_by_key:
        return str(node_by_key[function_key]["id"])

    node = {
        "id": _node_id("table", object_schema, name),
        "type": "table",
        "schema": object_schema,
        "name": name,
    }
    kept_node = _add_node(nodes, node_by_key, node)
    return str(kept_node["id"])


def _known_object_node_id(
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
    object_type: str,
    reference: ObjectName,
    cache_database: str,
) -> str:
    # A reference to another Database matches no node: this cache holds no
    # definition of that object, so a local node would be false evidence.
    if reference.database and part_key(reference.database) != part_key(cache_database):
        return ""
    # A reference that states no schema reads as dbo here. Step 2b removes this default.
    object_schema, name = reference.schema or "dbo", reference.name
    node = node_by_key.get(_node_key(object_type, object_schema, name))
    return str(node.get("id")) if node else ""


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
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
    node: dict[str, Any],
) -> dict[str, Any]:
    """Add ``node`` unless a node already holds its case-insensitive key.

    Returns the node that now occupies that key -- the existing node it kept,
    or ``node`` itself when none existed. A caller that builds a relationship
    target id from ``node`` must use this return value, not ``node["id"]``:
    the id it built may name a node this call decided not to add.
    """
    object_type = str(node.get("type", ""))
    schema = str(node.get("schema", "dbo"))
    name = str(node.get("name", ""))
    key = _node_key(object_type, schema, name) if name else (
        object_type,
        str(node.get("id", "")).casefold(),
        "",
    )
    if key in node_by_key:
        return node_by_key[key]
    node_by_key[key] = node
    nodes.append(node)
    return node


def _node_key(object_type: str, schema: str, name: str) -> tuple[str, str, str]:
    return object_type, schema.casefold(), name.casefold()


def _node_id(object_type: str, schema: str, name: str) -> str:
    return f"{object_type}:{schema}.{name}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("_") or "module"
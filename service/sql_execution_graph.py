"""Build the persisted SQL Execution Graph from ScriptDom operation facts."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from code_analyzer.static_analyzer_host import StaticAnalyzerHost


GRAPH_VERSION = 1
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
    schema = str(data.get("schema") or "dbo")
    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    node_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    module_specs: list[tuple[str, str, str, str]] = []

    for collection, object_type in _MODULE_COLLECTIONS:
        for item in data.get(collection, []) or []:
            object_schema, name = _split_object_name(item.get("name", ""), schema)
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
        object_schema, name = _split_object_name(item.get("name", ""), schema)
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
                input_path.write_text(definition, encoding="utf-8")
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
                        schema,
                    )
                _report_progress(progress_callback, "graph", index, len(module_specs), name)

    return {
        "graph_version": GRAPH_VERSION,
        "nodes": nodes,
        "relationships": relationships,
        "parse_errors": parse_errors,
    }


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
    default_schema: str,
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
    operation["source"] = source
    sequence = int(operation.get("sequence") or 0)
    operation_id = f"dml_operation:{module_id}:{sequence}"
    operation_node = {
        "id": operation_id,
        "type": "dml_operation",
        **operation,
    }
    _add_node(nodes, node_by_key, operation_node)

    branch_path = list(operation.get("branch_path") or [])
    _add_relationship(
        relationships,
        "contains",
        module_id,
        operation_id,
        source,
        branch_path,
    )

    for table_name in operation.get("read_tables", []) or []:
        target_id = _ensure_referenced_node(
            nodes,
            node_by_key,
            table_name,
            default_schema,
        )
        _add_relationship(
            relationships,
            "reads",
            operation_id,
            target_id,
            source,
            branch_path,
            columns=list(operation.get("read_columns", []) or []),
        )

    for table_name in operation.get("write_tables", []) or []:
        target_id = _ensure_referenced_node(
            nodes,
            node_by_key,
            table_name,
            default_schema,
        )
        _add_relationship(
            relationships,
            "writes",
            operation_id,
            target_id,
            source,
            branch_path,
            columns=list(operation.get("written_columns", []) or []),
        )


def _ensure_referenced_node(
    nodes: list[dict[str, Any]],
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
    object_name: str,
    default_schema: str,
) -> str:
    object_schema, name = _split_object_name(object_name, default_schema)
    view_key = _node_key("view", object_schema, name)
    function_key = _node_key("function", object_schema, name)
    if view_key in node_by_key:
        return node_by_key[view_key]["id"]
    if function_key in node_by_key:
        return node_by_key[function_key]["id"]

    node = {
        "id": _node_id("table", object_schema, name),
        "type": "table",
        "schema": object_schema,
        "name": name,
    }
    _add_node(nodes, node_by_key, node)
    return node["id"]


def _add_relationship(
    relationships: list[dict[str, Any]],
    relationship_type: str,
    source_id: str,
    target_id: str,
    source_location: dict[str, Any],
    branch_path: list[str],
    columns: list[str] | None = None,
) -> None:
    relationship = {
        "id": f"{relationship_type}:{source_id}:{target_id}",
        "type": relationship_type,
        "source": source_id,
        "target": target_id,
        "confidence": "proven",
        "branch_path": branch_path,
        "source_location": source_location,
    }
    if columns:
        relationship["columns"] = columns
    relationships.append(relationship)


def _add_node(
    nodes: list[dict[str, Any]],
    node_by_key: dict[tuple[str, str, str], dict[str, Any]],
    node: dict[str, Any],
) -> None:
    object_type = str(node.get("type", ""))
    schema = str(node.get("schema", "dbo"))
    name = str(node.get("name", ""))
    key = _node_key(object_type, schema, name) if name else (
        object_type,
        str(node.get("id", "")).casefold(),
        "",
    )
    if key in node_by_key:
        return
    node_by_key[key] = node
    nodes.append(node)


def _node_key(object_type: str, schema: str, name: str) -> tuple[str, str, str]:
    return object_type, schema.casefold(), name.casefold()


def _node_id(object_type: str, schema: str, name: str) -> str:
    return f"{object_type}:{schema}.{name}"


def _split_object_name(value: object, default_schema: str) -> tuple[str, str]:
    cleaned = _clean_identifier(str(value or ""))
    parts = [_clean_identifier(part) for part in cleaned.split(".") if part.strip()]
    if not parts:
        return default_schema, ""
    if len(parts) == 1:
        return default_schema, parts[0]
    return parts[-2], parts[-1]


def _clean_identifier(value: str) -> str:
    return value.strip().strip("[]\"")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("_") or "module"
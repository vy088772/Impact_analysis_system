"""The one test fixture module for every hand-built SQL cache shape.

A test gets a SQL cache payload, an Execution Graph payload, a format version,
and an analyzer operation from this module only
(`.scratch/canonical-object-identity/`, ticket 02). A shape change then breaks
this file, not every test that states the shape. The check in
tests/test_fixture_shapes_have_one_source.py keeps it that way.

It also holds the throwaway cache root and the write helpers that put a payload
on disk under a SQL Cache Identity.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import canonical_object_identity
from config.settings import settings
from service import sql_cache_store
from service.sql_cache_store import CacheIdentity
from service.sql_execution_graph import GRAPH_VERSION


class CacheRoot:
    """Point settings.SQL_CACHE_ROOT at a temp dir and clear the in-process cache."""

    def __enter__(self) -> Path:
        self._previous_root = settings.SQL_CACHE_ROOT
        self._previous_mem = dict(sql_cache_store._mem_cache)
        self._tmp = tempfile.TemporaryDirectory()
        settings.SQL_CACHE_ROOT = self._tmp.name
        sql_cache_store._mem_cache.clear()
        return Path(self._tmp.name)

    def __exit__(self, *exc: object) -> None:
        settings.SQL_CACHE_ROOT = self._previous_root
        sql_cache_store._mem_cache.clear()
        sql_cache_store._mem_cache.update(self._previous_mem)
        self._tmp.cleanup()


# A written object name, alone or with the other fields of its entry
# (``definition``, ``parameters``, ``columns``, ``primary_keys``).
SqlObjects = Union[Iterable[str], Mapping[str, Mapping[str, Any]]]


def cache_payload(
    database: str,
    *,
    procedures: SqlObjects = (),
    views: SqlObjects = (),
    functions: SqlObjects = (),
    tables: SqlObjects = (),
    graph: Optional[dict] = None,
    schema: str = "dbo",
) -> dict:
    """Build one SQL cache payload: the envelope and its four object lists.

    Each object is a written name, such as ``dbo.usp_Load`` or ``Orders``. A
    mapping gives each written name the other fields of its entry. The entry
    keeps the name exactly as written, and it gains a ``schema`` field that the
    Canonical Object Identity module parses from that name.

    A name that states no schema takes ``dbo`` here. This is not a
    comparison-key default: the Canonical Object Identity rule never fills an
    unstated schema. The builder stands in for the object listing, and the
    listing always reports the schema of each object it lists.

    ``graph`` is an Execution Graph payload from ``execution_graph()``. The
    Execution Graph keeps its own helper, because its format version and the SQL
    cache format version rise in different commits. With no graph, the payload
    holds no ``sql_execution_graph`` key, as a dump holds before the graph
    builder runs. ``schema`` is the cache-wide schema field.
    """
    payload: dict[str, Any] = {
        "database": database,
        "schema": schema,
        "procedures": _sql_objects(procedures),
        "views": _sql_objects(views),
        "functions": _sql_objects(functions),
        "tables": _sql_objects(tables),
    }
    if graph is not None:
        payload["sql_execution_graph"] = graph
    return payload


def _sql_objects(objects: SqlObjects) -> list[dict[str, Any]]:
    fields_by_name = (
        objects if isinstance(objects, Mapping) else {name: {} for name in objects}
    )
    entries = []
    for written_name, fields in fields_by_name.items():
        parsed = canonical_object_identity.parse(written_name)
        entries.append({"name": written_name, "schema": parsed.schema or "dbo", **fields})
    return entries


def execution_graph(
    database: str,
    *,
    nodes: Iterable[dict] = (),
    relationships: Iterable[dict] = (),
    parse_errors: Iterable[dict] = (),
    graph_version: int = GRAPH_VERSION,
) -> dict:
    """Build one Execution Graph payload at the current graph format version.

    A test that needs another version passes one relative to ``GRAPH_VERSION``,
    for example ``GRAPH_VERSION - 1``.
    """
    return {
        "graph_version": graph_version,
        "database": database,
        "nodes": list(nodes),
        "relationships": list(relationships),
        "parse_errors": list(parse_errors),
    }


def analyzer_operation(
    operation_type: str,
    *,
    sequence: int = 1,
    reads: Iterable[str] = (),
    writes: Iterable[str] = (),
    calls: Iterable[str] = (),
    functions: Iterable[str] = (),
    read_columns: Iterable[str] = (),
    written_columns: Iterable[str] = (),
    branch_path: Iterable[str] = (),
    conditions: Iterable[str] = (),
    where: Optional[str] = None,
    dynamic_sql: bool = False,
    **fields: Any,
) -> dict:
    """Build one SQL operation in the shape the StaticAnalyzerHost reports.

    Each object reference is a written name, such as ``dbo.SOrder``, and the
    operation carries it as written. Step 2a's analyzer commit changes each
    reference to four named parts, and it changes this helper alone.

    ``fields`` adds the fields a caller places beside the operation, such as
    ``source``, ``module``, or a graph node's ``id``.
    """
    return {
        "operation_type": operation_type,
        "sequence": sequence,
        "branch_path": list(branch_path),
        "conditions": list(conditions),
        "where": where,
        "read_tables": list(reads),
        "write_tables": list(writes),
        "read_columns": list(read_columns),
        "written_columns": list(written_columns),
        "function_references": list(functions),
        "call_targets": list(calls),
        "dynamic_sql": dynamic_sql,
        **fields,
    }


def cache_with_procedures(*procedures: str) -> dict:
    """An ``OrdersDb`` cache whose graph holds one node for each named procedure, in ``dbo``."""
    return cache_payload(
        "OrdersDb",
        procedures=procedures,
        graph=execution_graph(
            "OrdersDb",
            nodes=[
                {"id": f"stored_procedure:dbo.{name}", "type": "stored_procedure", "schema": "dbo", "name": name}
                for name in procedures
            ],
        ),
    )


def assert_relationships_resolve_to_known_nodes(graph: dict) -> None:
    """Every relationship target in ``graph`` must name a node the same graph holds.

    A relationship target with no matching node silently unresolves the whole
    Execution Path it belongs to (reverse-lookup-drops-proven-writes, ticket
    01) -- this is the structural invariant that repair restores. Call it over
    every graph a test builds, not only a graph built to reproduce the defect.
    """
    node_ids = {node["id"] for node in graph["nodes"] if node.get("id")}
    dangling = sorted(
        {
            (relationship.get("type"), relationship.get("target"))
            for relationship in graph["relationships"]
            if relationship.get("target") not in node_ids
        }
    )
    assert not dangling, f"relationship targets with no matching node: {dangling}"


def case_variant_table_write_data(database: str = "OrdersDb") -> dict:
    """Graph-builder input: two stored procedures write one table in different case.

    Shared by tests/test_sql_execution_graph.py (graph-construction seam) and
    tests/test_graph_reverse_lookup.py (analyst-facing seam) so the
    reverse-lookup-drops-proven-writes ticket-01 fixture is defined once. Feed
    this to `build_sql_execution_graph()` -- a hand-written graph dict cannot
    reproduce the defect, which only exists in how the builder resolves a
    second, case-different reference to the same object.
    """
    return cache_payload(
        database,
        procedures={
            "dbo.usp_WriteUpper": {
                "definition": "CREATE PROCEDURE dbo.usp_WriteUpper AS INSERT INTO VQM (Id) VALUES (1);",
            },
            "dbo.usp_WriteLower": {
                "definition": "CREATE PROCEDURE dbo.usp_WriteLower AS UPDATE vqm SET Id = 1;",
            },
        },
    )


def case_variant_temp_table_write_data(database: str = "OrdersDb") -> dict:
    """Graph-builder input: a real write sits behind a case-variant temp-table read.

    `#TempStage` is created in one case and read back in another, inside the
    same DML operation that writes `dbo.RealTable` -- the same shape that made
    `#Order` and `#tmpPart` the two largest sources of dangling ids in the PUR
    cache (reverse-lookup-drops-proven-writes, ticket 01). Shared by
    tests/test_sql_execution_graph.py and tests/test_graph_reverse_lookup.py;
    see `case_variant_table_write_data` for why this must go through
    `build_sql_execution_graph()`.
    """
    return cache_payload(
        database,
        procedures={
            "dbo.usp_WriteWithTemp": {
                "definition": """CREATE PROCEDURE dbo.usp_WriteWithTemp
AS
BEGIN
    SELECT Id INTO #TempStage FROM dbo.SourceTable;
    INSERT INTO dbo.RealTable (Id)
        SELECT Id FROM #tempstage;
END;
""",
            },
        },
        tables=["dbo.SourceTable", "dbo.RealTable"],
    )


_SAVED_AT = "2026-08-04 13:29:13"


def write_cache(
    cache_root: Path,
    identity: CacheIdentity,
    payload: dict,
    cache_version: int | None = None,
) -> None:
    """Write one cache file pair under ``identity``, as a refresh names it.

    The cache store's own meta writer writes the meta file, so the meta format
    stays defined in one place. ``cache_version`` replaces the version in that
    file, for a test that needs a cache from another format version.
    """
    (cache_root / identity.filename).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta_path = cache_root / identity.meta_filename
    sql_cache_store.write_meta(meta_path, identity, _SAVED_AT)
    if cache_version is not None:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["cache_version"] = cache_version
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def write_legacy_cache(cache_root: Path, key: str, payload: dict) -> None:
    """Write one cache file pair under a key that no SQL Cache Identity produces.

    A cache written before the server part existed has such a key, and its meta
    file carries no ``server``. The tests of the store's rejection and of the
    key migration need that cache on purpose, so it has its own helper.
    """
    (cache_root / f"{key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_root / f"{key}.meta.json").write_text(
        json.dumps(
            {
                "cache_version": sql_cache_store._SQL_CACHE_VERSION,
                "database": payload["database"],
                "schema": payload["schema"],
                "saved_at": _SAVED_AT,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

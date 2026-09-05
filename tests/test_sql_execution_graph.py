"""Ticket 03 behavior checks for AST-backed SQL execution operations."""

from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.static_analyzer_host import StaticAnalyzerHost
from code_analyzer import sql_analyzer
from code_analyzer.sql_analyzer import SQLAnalyzer
from service import sql_cache_store
from service.sql_execution_graph import GRAPH_VERSION, build_sql_execution_graph
from tests.sql_cache_fixtures import (
    CacheRoot,
    assert_relationships_resolve_to_known_nodes,
    case_variant_table_write_data,
    case_variant_temp_table_write_data,
    write_cache,
)


TEST_SERVER = "vmsystest07"


def _write_sql_cache_fixture(
    cache_root: Path,
    database: str,
    payload: dict,
    cache_version: int | None = None,
) -> None:
    write_cache(
        cache_root,
        sql_cache_store.CacheIdentity.of(TEST_SERVER, database, "dbo").key,
        payload,
        cache_version,
    )


def test_dump_all_sql_objects_keeps_sp_helpers_on_sql_analyzer() -> None:
    """Progress reporting must not move later SQLAnalyzer methods out of the class."""
    class FakeCursor:
        def execute(self, *args: object) -> None:
            return None

        def fetchone(self) -> tuple[str, None, None]:
            return ("CREATE PROCEDURE dbo.usp_Repro AS SELECT 1", None, None)

        def fetchall(self) -> list[object]:
            return []

    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.db_config = SimpleNamespace(alias="TestDb")
    analyzer.cursor = FakeCursor()
    analyzer.get_all_procedures = lambda schema: ["usp_Repro"]
    analyzer.get_all_views = lambda schema: []
    analyzer.get_all_functions = lambda schema: []
    analyzer.get_all_tables = lambda schema: []
    analyzer.get_all_dependencies = lambda schema: {}

    data = analyzer.dump_all_sql_objects("dbo")

    assert [procedure["name"] for procedure in data["procedures"]] == ["usp_Repro"]
    assert "dependencies" not in data
    assert "write_dependencies" not in data


def test_sql_cache_rejects_graphless_payload() -> None:
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            {"database": "TestDb", "schema": "dbo", "procedures": []},
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None


def test_sql_cache_rejects_database_mismatch_from_memory_and_disk() -> None:
    mismatched_payload = {
        "database": "OtherDb",
        "schema": "dbo",
        "sql_execution_graph": {
            "graph_version": GRAPH_VERSION,
            "database": "OtherDb",
            "nodes": [],
            "relationships": [],
            "parse_errors": [],
        },
    }
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(cache_root, "TestDb", mismatched_payload)

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None

        sql_cache_store._mem_cache[
            sql_cache_store.CacheIdentity.of(TEST_SERVER, "TestDb", "dbo").key
        ] = mismatched_payload
        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None


def test_sql_cache_rejects_stale_payload_version() -> None:
    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            {
                "database": "TestDb",
                "schema": "dbo",
                "sql_execution_graph": {
                    "graph_version": GRAPH_VERSION,
                    "database": "TestDb",
                    "nodes": [],
                    "relationships": [],
                    "parse_errors": [],
                },
            },
            cache_version=sql_cache_store._SQL_CACHE_VERSION - 1,
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None


def test_sql_cache_rejects_stale_graph_version() -> None:
    """A cache built under any earlier graph version must be rejected.

    GRAPH_VERSION is bumped each time a defect can leave the persisted graph
    itself wrong -- most recently to 4, by the reverse-lookup-drops-proven-
    writes repair (ticket 01), so a graph holding dangling relationship
    targets fails this check until it is rebuilt.
    """
    assert GRAPH_VERSION == 4

    with CacheRoot() as cache_root:
        _write_sql_cache_fixture(
            cache_root,
            "TestDb",
            {
                "database": "TestDb",
                "schema": "dbo",
                "sql_execution_graph": {
                    "graph_version": GRAPH_VERSION - 1,
                    "database": "TestDb",
                    "nodes": [],
                    "relationships": [],
                    "parse_errors": [],
                },
            },
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None


def test_sql_host_emits_typed_operations_with_module_and_source_evidence() -> None:
    """A SQL module keeps ordered DML facts instead of returning an empty operation list."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    sql = """CREATE PROCEDURE [dbo].[usp_SaveOrder]
AS
BEGIN
    SELECT Id FROM dbo.SourceOrder WHERE Id = @Id;
    INSERT INTO dbo.OrderArchive (Id, OrderNo)
        SELECT Id, OrderNo FROM dbo.SourceOrder;
    IF @Mode = 1
        UPDATE dbo.SOrder SET OrderNo = @OrderNo WHERE Id = @Id;
    ELSE
        DELETE FROM dbo.SOrder WHERE Id = @Id;
    SELECT Id INTO dbo.OrderSnapshot FROM dbo.SOrder;
END;
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "usp_SaveOrder.sql"
        source_path.write_text(sql, encoding="utf-8")

        result = host.analyze_sql(source_path)

    assert result["contract_version"] == 2
    operations = result["operations"]
    assert [operation["operation_type"] for operation in operations] == [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "SELECT_INTO",
    ]

    for sequence, operation in enumerate(operations, start=1):
        assert operation["sequence"] == sequence
        assert operation["module"] == {
            "type": "stored_procedure",
            "schema": "dbo",
            "name": "usp_SaveOrder",
        }
        assert operation["source"]["start_line"] >= 1
        assert operation["source"]["start_column"] >= 1
        assert operation["source"]["length"] > 0

    insert = operations[1]
    assert insert["write_tables"] == ["dbo.OrderArchive"]
    assert insert["written_columns"] == ["Id", "OrderNo"]
    assert insert["read_tables"] == ["dbo.SourceOrder"]

    update = operations[2]
    assert update["write_tables"] == ["dbo.SOrder"]
    assert update["written_columns"] == ["OrderNo"]
    assert update["where"] == "Id = @Id"
    assert update["branch_path"] == ["IF @Mode = 1"]
    assert update["conditions"] == ["IF @Mode = 1", "Id = @Id"]

    delete = operations[3]
    assert delete["write_tables"] == ["dbo.SOrder"]
    assert delete["where"] == "Id = @Id"
    assert delete["branch_path"] == ["ELSE (NOT (@Mode = 1))"]

    select_into = operations[4]
    assert select_into["write_tables"] == ["dbo.OrderSnapshot"]
    assert select_into["read_tables"] == ["dbo.SOrder"]


def test_sql_refresh_builds_and_reloads_typed_execution_graph() -> None:
    """SQL refresh persists graph nodes and relationships alongside SQL definitions."""
    class FakeSqlAnalyzer:
        def __init__(
            self,
            alias: str,
            *,
            server: str,
            database_name: str,
            user_id: str = "",
            password: str = "",
        ) -> None:
            self.alias = alias

        def connect(self) -> bool:
            return True

        def disconnect(self) -> None:
            return None

        def dump_all_sql_objects(self, schema: str) -> dict:
            return {
                "database": self.alias,
                "schema": schema,
                "procedures": [
                    {
                        "name": "usp_SaveOrder",
                        "definition": (
                            "CREATE PROCEDURE dbo.usp_SaveOrder AS "
                            "UPDATE dbo.SOrder SET OrderNo = @OrderNo WHERE Id = @Id;"
                        ),
                        "parameters": [],
                    }
                ],
                "views": [
                    {
                        "name": "vOrder",
                        "definition": "CREATE VIEW dbo.vOrder AS SELECT Id FROM dbo.SOrder;",
                    }
                ],
                "functions": [],
                "tables": [{"name": "SOrder", "columns": []}],
                "dependencies": {
                    "legacy": {"depends_on": ["old"], "depended_by": []}
                },
                "write_dependencies": {
                    "usp_SaveOrder": {"writes_tables": ["dbo.SOrder"]}
                },
            }

    with CacheRoot():
        original_analyzer = sql_analyzer.SQLAnalyzer
        sql_analyzer.SQLAnalyzer = FakeSqlAnalyzer
        try:
            data = sql_cache_store.get_or_dump(
                "TestDb",
                schema="dbo",
                refresh=True,
                server=TEST_SERVER,
                db_name="TestDb",
            )
            assert "dependencies" not in data
            assert "write_dependencies" not in data
            graph = data["sql_execution_graph"]
            assert_relationships_resolve_to_known_nodes(graph)
            nodes_by_id = {node["id"]: node for node in graph["nodes"]}
            relationships = graph["relationships"]

            procedure = nodes_by_id["stored_procedure:dbo.usp_SaveOrder"]
            operation = nodes_by_id["dml_operation:stored_procedure:dbo.usp_SaveOrder:1"]
            view = nodes_by_id["view:dbo.vOrder"]
            view_operation = nodes_by_id["dml_operation:view:dbo.vOrder:1"]
            assert procedure["type"] == "stored_procedure"
            assert operation["operation_type"] == "UPDATE"
            assert operation["written_columns"] == ["OrderNo"]
            assert view["type"] == "view"
            assert {relationship["type"] for relationship in relationships} == {
                "contains",
                "writes",
                "reads",
            }
            assert any(
                relationship["type"] == "writes"
                and relationship["source"] == operation["id"]
                and relationship["target"] == "table:dbo.SOrder"
                for relationship in relationships
            )
            assert any(
                relationship["type"] == "reads"
                and relationship["source"] == view_operation["id"]
                and relationship["target"] == "table:dbo.SOrder"
                for relationship in relationships
            )

            sql_cache_store._mem_cache.clear()
            reloaded = sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER)
            assert reloaded is not None
            assert reloaded["sql_execution_graph"] == graph
            assert "dependencies" not in reloaded
            assert "write_dependencies" not in reloaded
        finally:
            sql_analyzer.SQLAnalyzer = original_analyzer


def _crlf_procedure_definition() -> str:
    """A stored-procedure definition long enough to expose offset drift, using \\r\\n line endings."""
    lines = ["CREATE PROCEDURE dbo.usp_PadDelete AS", "BEGIN"]
    for index in range(40):
        lines.append(f"    -- pad line {index}")
    lines.append("    DELETE FROM dbo.PadTarget;")
    lines.append("END;")
    return "\r\n".join(lines) + "\r\n"


def test_graph_offsets_stay_within_definition_length_for_crlf_source() -> None:
    """The newline-safe write path must not let ScriptDom offsets outrun the cached definition text."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    definition = _crlf_procedure_definition()
    data = {
        "database": "TestDb",
        "schema": "dbo",
        "procedures": [{"name": "usp_PadDelete", "definition": definition, "parameters": []}],
        "views": [],
        "functions": [],
        "tables": [{"name": "PadTarget", "columns": []}],
    }

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    operation_nodes = [node for node in graph["nodes"] if node["type"] == "dml_operation"]
    assert operation_nodes, "expected the DELETE statement to produce an operation node"
    for node in operation_nodes:
        source = node["source"]
        end_offset = source["start_offset"] + source["length"]
        assert end_offset <= len(definition)


def test_pre_fix_crlf_doubling_produces_out_of_bounds_offsets() -> None:
    """Reproduces the corruption the old write_text() call produced on a Windows host.

    Windows text-mode writes translate every '\\n' to '\\r\\n'. A definition that
    already used '\\r\\n' line endings became '\\r\\r\\n' on disk, so ScriptDom parsed
    a longer string than the one persisted to the JSON cache. This test recreates
    that inflated file directly (bypassing the fixed write path) and asserts the
    resulting offsets overrun the original definition's length, proving this is
    the bug the fix addresses rather than an assertion with no failing baseline.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    definition = _crlf_procedure_definition()
    corrupted = definition.replace("\r\n", "\r\r\n")
    assert len(corrupted) > len(definition)

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = Path(temp_dir) / "usp_PadDelete.sql"
        input_path.write_text(corrupted, encoding="utf-8", newline="")
        result = host.analyze_sql(input_path)

    operations = result["operations"]
    assert operations, "expected the DELETE statement to produce an operation"
    overruns = [
        operation
        for operation in operations
        if operation["source"]["start_offset"] + operation["source"]["length"] > len(definition)
    ]
    assert overruns, "expected the \\r\\n doubling to push at least one offset past the definition length"


def test_referenced_node_id_resolves_despite_a_case_variant_first_reference() -> None:
    """Ticket 01: `_ensure_referenced_node()` must return an id that names a node.

    `dbo.VQM` is referenced first in upper case, then again in lower case.
    `_add_node()` keeps the first node under a case-insensitive key, so the
    second reference must resolve back to that same node -- not to a second,
    unadded id that names nothing.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    data = case_variant_table_write_data(database="TestDb")

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    table_nodes = [
        node
        for node in graph["nodes"]
        if node["type"] == "table" and node["name"].casefold() == "vqm"
    ]
    assert len(table_nodes) == 1, "one case-insensitive key must keep exactly one node"

    writes = [
        relationship
        for relationship in graph["relationships"]
        if relationship["type"] == "writes"
    ]
    assert len(writes) == 2
    assert {relationship["target"] for relationship in writes} == {table_nodes[0]["id"]}


def test_write_to_real_table_survives_a_case_variant_read_through_a_temp_table() -> None:
    """Ticket 01: a case-variant temp-table reference must not unresolve a real write.

    `#TempStage` is created in one case and read back in another, the same
    shape that made `#Order` and `#tmpPart` the two largest sources of
    dangling ids in the PUR cache. Before the repair, the INSERT's read of
    `#tempstage` resolved to an id `_add_node()` never added, which put it in
    `missing_targets` and downgraded the whole operation -- including its
    proven write to `dbo.RealTable` -- to `unresolved`.
    """
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    data = case_variant_temp_table_write_data(database="TestDb")

    graph = build_sql_execution_graph(data, host=host, project_root=PROJECT_ROOT)
    assert_relationships_resolve_to_known_nodes(graph)

    writes = [
        relationship
        for relationship in graph["relationships"]
        if relationship["type"] == "writes"
    ]
    assert any(relationship["target"] == "table:dbo.RealTable" for relationship in writes)


if __name__ == "__main__":
    test_sql_host_emits_typed_operations_with_module_and_source_evidence()
    print("SQL execution graph tests passed")
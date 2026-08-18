"""Ticket 03 behavior checks for AST-backed SQL execution operations."""

from __future__ import annotations

import json
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
from config.settings import settings
from service import sql_cache_store


TEST_SERVER = "vmsystest07"


def _write_sql_cache_fixture(
    cache_dir: str,
    database: str,
    payload: dict,
    cache_version: int | None = None,
) -> None:
    cache_root = Path(cache_dir)
    key = sql_cache_store.cache_key(TEST_SERVER, database, "dbo")
    (cache_root / f"{key}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (cache_root / f"{key}.meta.json").write_text(
        json.dumps(
            {
                "cache_version": (
                    sql_cache_store._SQL_CACHE_VERSION
                    if cache_version is None
                    else cache_version
                ),
                "database": database,
                "schema": "dbo",
            }
        ),
        encoding="utf-8",
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
    previous_cache_root = settings.SQL_CACHE_ROOT
    previous_mem_cache = dict(sql_cache_store._mem_cache)
    with tempfile.TemporaryDirectory() as cache_dir:
        settings.SQL_CACHE_ROOT = cache_dir
        sql_cache_store._mem_cache.clear()
        _write_sql_cache_fixture(
            cache_dir,
            "TestDb",
            {"database": "TestDb", "schema": "dbo", "procedures": []},
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None
    sql_cache_store._mem_cache.clear()
    sql_cache_store._mem_cache.update(previous_mem_cache)
    settings.SQL_CACHE_ROOT = previous_cache_root


def test_sql_cache_rejects_database_mismatch_from_memory_and_disk() -> None:
    previous_cache_root = settings.SQL_CACHE_ROOT
    previous_mem_cache = dict(sql_cache_store._mem_cache)
    mismatched_payload = {
        "database": "OtherDb",
        "schema": "dbo",
        "sql_execution_graph": {
            "graph_version": 2,
            "database": "OtherDb",
            "nodes": [],
            "relationships": [],
            "parse_errors": [],
        },
    }
    with tempfile.TemporaryDirectory() as cache_dir:
        settings.SQL_CACHE_ROOT = cache_dir
        sql_cache_store._mem_cache.clear()
        _write_sql_cache_fixture(cache_dir, "TestDb", mismatched_payload)

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None

        sql_cache_store._mem_cache[
            sql_cache_store.cache_key(TEST_SERVER, "TestDb", "dbo")
        ] = mismatched_payload
        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None
    sql_cache_store._mem_cache.clear()
    sql_cache_store._mem_cache.update(previous_mem_cache)
    settings.SQL_CACHE_ROOT = previous_cache_root


def test_sql_cache_rejects_stale_payload_version() -> None:
    previous_cache_root = settings.SQL_CACHE_ROOT
    previous_mem_cache = dict(sql_cache_store._mem_cache)
    with tempfile.TemporaryDirectory() as cache_dir:
        settings.SQL_CACHE_ROOT = cache_dir
        sql_cache_store._mem_cache.clear()
        _write_sql_cache_fixture(
            cache_dir,
            "TestDb",
            {
                "database": "TestDb",
                "schema": "dbo",
                "sql_execution_graph": {
                    "graph_version": 2,
                    "database": "TestDb",
                    "nodes": [],
                    "relationships": [],
                    "parse_errors": [],
                },
            },
            cache_version=sql_cache_store._SQL_CACHE_VERSION - 1,
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None
    sql_cache_store._mem_cache.clear()
    sql_cache_store._mem_cache.update(previous_mem_cache)
    settings.SQL_CACHE_ROOT = previous_cache_root


def test_sql_cache_rejects_stale_graph_version() -> None:
    previous_cache_root = settings.SQL_CACHE_ROOT
    previous_mem_cache = dict(sql_cache_store._mem_cache)
    with tempfile.TemporaryDirectory() as cache_dir:
        settings.SQL_CACHE_ROOT = cache_dir
        sql_cache_store._mem_cache.clear()
        _write_sql_cache_fixture(
            cache_dir,
            "TestDb",
            {
                "database": "TestDb",
                "schema": "dbo",
                "sql_execution_graph": {
                    "graph_version": 1,
                    "database": "TestDb",
                    "nodes": [],
                    "relationships": [],
                    "parse_errors": [],
                },
            },
        )

        assert sql_cache_store.load_cached("TestDb", "dbo", server=TEST_SERVER) is None
    sql_cache_store._mem_cache.clear()
    sql_cache_store._mem_cache.update(previous_mem_cache)
    settings.SQL_CACHE_ROOT = previous_cache_root


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

    previous_cache_root = settings.SQL_CACHE_ROOT
    previous_mem_cache = dict(sql_cache_store._mem_cache)
    with tempfile.TemporaryDirectory() as cache_dir:
        settings.SQL_CACHE_ROOT = cache_dir
        sql_cache_store._mem_cache.clear()
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
            sql_cache_store._mem_cache.clear()
            sql_cache_store._mem_cache.update(previous_mem_cache)
            settings.SQL_CACHE_ROOT = previous_cache_root


if __name__ == "__main__":
    test_sql_host_emits_typed_operations_with_module_and_source_evidence()
    print("SQL execution graph tests passed")
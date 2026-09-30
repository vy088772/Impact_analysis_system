"""The rebuild report: what one graph holds, counted per cache, with no SQL Server.

`.scratch/unstated-schema-resolves-as-sql-server-does/` ticket 01. Every test
feeds a hand-built cache from the shared fixture module and reads the report
that the tool gives back.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import sql_cache_store
from service.sql_cache_store import CacheIdentity
from service.sql_execution_graph import build_sql_execution_graph
from tests.sql_cache_fixtures import (
    CacheRoot,
    StubAnalyzerHost,
    analyzer_operation,
    cache_payload,
    write_cache,
)
from tools.rebuild_report import report_all_caches


def _statement(definition: str, statement: str) -> dict:
    """The source location of ``statement`` inside ``definition``."""
    return {"source": {"start_offset": definition.index(statement), "length": len(statement)}}


def _built_cache(database: str, module: str, definition: str, operations: list[dict], **objects: list[str]) -> dict:
    procedures = {module: {"definition": definition}}
    graph = build_sql_execution_graph(
        cache_payload(database, procedures=procedures, **objects),
        host=StubAnalyzerHost({definition: operations}),
    )
    return cache_payload(database, procedures=procedures, graph=graph, **objects)


def _report_of(payload: dict) -> dict:
    """Write one cache to a throwaway root and report it."""
    with CacheRoot() as cache_root:
        write_cache(cache_root, CacheIdentity.of("vmsystest07", payload["database"]), payload)
        reports = report_all_caches()
    assert len(reports) == 1
    return reports[0]


def test_a_report_names_each_cache_the_store_lists() -> None:
    definition = "CREATE PROCEDURE dbo.usp_A AS SELECT 1"
    with CacheRoot() as cache_root:
        for database in ("OrdersDb", "SalesDb"):
            payload = _built_cache(database, "dbo.usp_A", definition, [])
            write_cache(cache_root, CacheIdentity.of("vmsystest07", database), payload)

        reports = report_all_caches()

    assert [(report["server"], report["database"]) for report in reports] == [
        ("vmsystest07.topmost.com.tw", "OrdersDb"),
        ("vmsystest07.topmost.com.tw", "SalesDb"),
    ]


def test_a_reference_with_no_schema_counts_as_empty_and_unproven() -> None:
    definition = "CREATE PROCEDURE dbo.usp_A AS DELETE UserProgram; SELECT 1 FROM dbo.Stated;"
    operations = [
        analyzer_operation("DELETE", sequence=1, writes=["UserProgram"], **_statement(definition, "DELETE UserProgram")),
        analyzer_operation("SELECT", sequence=2, reads=["dbo.Stated"], **_statement(definition, "SELECT 1 FROM dbo.Stated")),
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["empty_schema_references"] == 1
    assert report["unproven_schema_targets"] == 1
    assert report["references_by_schema_source"] == {"written": 1, "": 1}


def test_an_unproven_target_counts_once_however_many_references_name_it() -> None:
    definition = "CREATE PROCEDURE dbo.usp_A AS SELECT 1 FROM Loose; SELECT 2 FROM Loose;"
    operations = [
        analyzer_operation("SELECT", sequence=1, reads=["Loose"], **_statement(definition, "SELECT 1 FROM Loose")),
        analyzer_operation("SELECT", sequence=2, reads=["Loose"], **_statement(definition, "SELECT 2 FROM Loose")),
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["empty_schema_references"] == 2
    assert report["unproven_schema_targets"] == 1


def test_a_cte_name_read_as_a_table_counts_and_the_real_table_inside_does_not() -> None:
    statement = "WITH Table1 AS (SELECT Id FROM dbo.Real) SELECT Id FROM Table1"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation(
            "SELECT", reads=["dbo.Real", "Table1"], **_statement(definition, statement)
        )
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["cte_reads"] == 1


def test_a_cte_name_in_a_comma_list_and_with_columns_counts() -> None:
    statement = "WITH First AS (SELECT 1 AS Id), [Second] (Id) AS (SELECT 2) SELECT * FROM First, Second"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation("SELECT", reads=["First", "Second"], **_statement(definition, statement))
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["cte_reads"] == 2


def test_a_read_of_a_table_that_no_with_clause_names_is_not_a_cte_read() -> None:
    statement = "SELECT Id FROM Orders WHERE Note = 'x AS (y'"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [analyzer_operation("SELECT", reads=["Orders"], **_statement(definition, statement))]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["cte_reads"] == 0


def test_an_update_written_to_its_from_clause_alias_counts_as_an_alias_write() -> None:
    statement = "UPDATE B1 SET Amount = 0 FROM BSPL.BudgetBalanceSheet B1 WHERE B1.Id = 1"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation(
            "UPDATE", writes=["B1"], reads=["BSPL.BudgetBalanceSheet"], **_statement(definition, statement)
        )
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["alias_writes"] == 1


def test_a_delete_written_to_an_alias_after_as_and_a_join_counts() -> None:
    statement = (
        "DELETE d FROM dbo.Detail AS h INNER JOIN dbo.Line AS d ON d.HeaderId = h.Id"
    )
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation(
            "DELETE", writes=["d"], reads=["dbo.Detail", "dbo.Line"], **_statement(definition, statement)
        )
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["alias_writes"] == 1


def test_a_write_to_a_real_table_is_not_an_alias_write() -> None:
    update = "UPDATE dbo.Orders SET Total = 0 WHERE Id = 1"
    delete = "DELETE FROM Orders WHERE Id = 2"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {update}; {delete};"
    operations = [
        analyzer_operation("UPDATE", sequence=1, writes=["dbo.Orders"], **_statement(definition, update)),
        analyzer_operation("DELETE", sequence=2, writes=["Orders"], **_statement(definition, delete)),
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["alias_writes"] == 0


def test_an_insert_never_counts_as_an_alias_write() -> None:
    statement = "INSERT INTO Target (Id) SELECT Id FROM dbo.Source Target"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation("INSERT", writes=["Target"], **_statement(definition, statement))
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["alias_writes"] == 0


def test_a_relationship_with_no_source_location_text_counts_in_no_text_count() -> None:
    definition = "CREATE PROCEDURE dbo.usp_A AS SELECT 1 FROM Orders"
    operations = [analyzer_operation("SELECT", reads=["Orders"])]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["cte_reads"] == 0
    assert report["alias_writes"] == 0
    assert report["empty_schema_references"] == 1


def test_a_cache_the_store_does_not_trust_is_reported_and_not_read() -> None:
    definition = "CREATE PROCEDURE dbo.usp_A AS SELECT 1"
    with CacheRoot() as cache_root:
        payload = _built_cache("OrdersDb", "dbo.usp_A", definition, [])
        write_cache(cache_root, CacheIdentity.of("vmsystest07.topmost.com.tw", "OrdersDb"), payload, cache_version=0)

        reports = report_all_caches()

    assert [(report["database"], report["action"]) for report in reports] == [("OrdersDb", "invalid_cache")]
    assert "empty_schema_references" not in reports[0]


def test_the_report_asks_the_store_for_its_listing_and_opens_no_connection(monkeypatch) -> None:
    listed: list[str] = []
    real = sql_cache_store.list_caches

    def recording_listing():
        listed.append("list_caches")
        return real()

    monkeypatch.setattr(sql_cache_store, "list_caches", recording_listing)
    with CacheRoot():
        assert report_all_caches() == []

    assert listed == ["list_caches"]


def test_one_statement_reading_a_cte_name_twice_counts_one_read() -> None:
    statement = "WITH Table1 AS (SELECT 1 AS Id) SELECT a.Id FROM Table1 a JOIN Table1 b ON a.Id = b.Id"
    definition = f"CREATE PROCEDURE dbo.usp_A AS {statement};"
    operations = [
        analyzer_operation("SELECT", reads=["Table1", "Table1"], **_statement(definition, statement))
    ]

    report = _report_of(_built_cache("OrdersDb", "dbo.usp_A", definition, operations))

    assert report["cte_reads"] == 1

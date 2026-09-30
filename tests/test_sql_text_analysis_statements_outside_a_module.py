"""Seam 3: what the analyzer host says about a statement outside a SQL module.

Each case gives one SQL text to the host adapter and reads the typed answer.
The cases need `dotnet`. They run the SQL command only. The in-memory adapter
cannot show them, because it returns the answer that a test wrote.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import ObjectName
from code_analyzer.sql_text_analysis import HostSqlTextAnalysis, SqlTextResult


def _analyze(text: str) -> SqlTextResult:
    (result,) = HostSqlTextAnalysis.for_project(PROJECT_ROOT).analyze([text])
    return result


def _names(tables: Iterable[ObjectName]) -> list[str]:
    return sorted(table.name for table in tables)


def _read_names(result: SqlTextResult) -> list[str]:
    return _names(table for operation in result.operations for table in operation.read_tables)


def _write_names(result: SqlTextResult) -> list[str]:
    return _names(table for operation in result.operations for table in operation.write_tables)


def test_a_cte_query_gives_no_cte_name_and_keeps_the_tables_of_the_cte_body() -> None:
    result = _analyze(
        "WITH Recent AS (SELECT Id FROM dbo.Orders WHERE Id > 10) "
        "SELECT r.Id FROM Recent r JOIN dbo.Items i ON i.Id = r.Id"
    )

    assert result.parse_errors == ()
    assert _read_names(result) == ["Items", "Orders"]
    assert _write_names(result) == []


def test_an_update_alias_writes_the_table_behind_it_and_reads_the_joined_table() -> None:
    result = _analyze(
        "UPDATE ord SET Status = 1 FROM dbo.Orders ord JOIN dbo.Items it ON it.OrderId = ord.Id"
    )

    assert _write_names(result) == ["Orders"]
    assert _read_names(result) == ["Items"]


def test_a_table_name_in_a_comment_and_in_a_string_literal_gives_no_table() -> None:
    result = _analyze(
        "SELECT Id, 'FROM dbo.InsideString' AS Note FROM dbo.Real -- FROM dbo.InsideComment\n"
        "/* JOIN dbo.InsideBlock */"
    )

    assert _read_names(result) == ["Real"]
    assert _write_names(result) == []


def test_an_insert_with_a_column_list_writes_its_target_and_reads_its_source() -> None:
    result = _analyze("INSERT INTO dbo.Target (Id, Name) SELECT Id, Name FROM dbo.Source")

    assert _write_names(result) == ["Target"]
    assert _read_names(result) == ["Source"]


def test_a_select_into_writes_its_target_with_the_operation_type_select_into() -> None:
    result = _analyze("SELECT Id INTO dbo.Copy FROM dbo.Source")

    (operation,) = result.operations
    assert operation.operation_type == "SELECT_INTO"
    assert _names(operation.write_tables) == ["Copy"]
    assert _names(operation.read_tables) == ["Source"]


def test_a_text_that_is_not_sql_gives_a_parse_error_and_no_operation() -> None:
    result = _analyze("delete")

    assert result.parse_errors
    assert result.operations == ()

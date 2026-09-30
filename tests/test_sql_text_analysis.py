"""SQL Text Analysis: SQL texts in, one typed result for each text out.

The tests that name the real analyzer host need `dotnet`. They run the SQL
command only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import ObjectName
from code_analyzer import static_analyzer_host
from code_analyzer.sql_text_analysis import (
    HostSqlTextAnalysis,
    InMemorySqlTextAnalysis,
    SqlModuleIdentity,
    SqlOperation,
    SqlParseError,
    SqlSourceLocation,
    SqlTextAnalysisError,
    SqlTextResult,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHostError


def _host_analysis() -> HostSqlTextAnalysis:
    return HostSqlTextAnalysis.for_project(PROJECT_ROOT)


def test_a_definition_with_windows_line_ends_gives_offsets_that_agree_with_the_text() -> None:
    lines = ["CREATE PROCEDURE dbo.usp_PadDelete AS", "BEGIN"]
    lines.extend(f"    -- pad line {index}" for index in range(40))
    lines.extend(["    DELETE FROM dbo.PadTarget;", "END;"])
    definition = "\r\n".join(lines) + "\r\n"

    (result,) = _host_analysis().analyze([definition])

    (operation,) = result.operations
    source = operation.source
    assert definition[source.start_offset : source.start_offset + source.length] == "DELETE FROM dbo.PadTarget;"
    assert source.start_line == 43


def test_the_host_adapter_gives_a_typed_operation_with_every_field_the_host_reports() -> None:
    """The source location is the whole of what the host reports for it, less the path of the temporary file."""
    text = (
        "CREATE PROCEDURE [COMMON].[usp_Move] AS\n"
        "IF @Mode = 1\n"
        "    UPDATE PUR.dbo.Archive SET Qty = s.Qty FROM PUR.dbo.Archive a"
        " JOIN srv.PUR.dbo.Source s ON s.Id = a.Id WHERE a.Id = dbo.fn_Key(1);\n"
    )

    (result,) = _host_analysis().analyze([text])

    assert result == SqlTextResult(
        operations=(
            SqlOperation(
                operation_type="UPDATE",
                module=SqlModuleIdentity(type="stored_procedure", schema="COMMON", name="usp_Move"),
                sequence=1,
                branch_path=("IF @Mode = 1",),
                conditions=("IF @Mode = 1", "a.Id = dbo.fn_Key(1)"),
                where="a.Id = dbo.fn_Key(1)",
                read_tables=(ObjectName(server="srv", database="PUR", schema="dbo", name="Source"),),
                write_tables=(ObjectName(server="", database="PUR", schema="dbo", name="Archive"),),
                unresolved_write_targets=(),
                read_columns=("Id", "Qty"),
                written_columns=("Qty",),
                function_references=(ObjectName(server="", database="", schema="dbo", name="fn_Key"),),
                call_targets=(),
                dynamic_sql=False,
                source=SqlSourceLocation(
                    start_line=3, start_column=5, start_offset=57, length=130, end_line=3, end_column=135
                ),
            ),
        ),
        parse_errors=(),
    )


def test_a_text_outside_a_sql_module_gets_no_name_from_its_temporary_file() -> None:
    (result,) = _host_analysis().analyze(["SELECT Id FROM dbo.Orders;"])

    assert [operation.module for operation in result.operations] == [
        SqlModuleIdentity(type="unknown", schema="", name="")
    ]


def test_the_host_adapter_gives_one_result_for_each_text_in_input_order() -> None:
    texts = [
        "SELECT Id FROM dbo.First;",
        "SELECT Id FROM (",
        "SELECT Id FROM dbo.Third;",
        "",
        "SELECT Id FROM dbo.First;",
    ]
    reports: list[tuple[int, int]] = []

    with patch.object(static_analyzer_host, "_MAX_HOST_FILES_PER_BATCH", 2):
        results = _host_analysis().analyze(texts, lambda completed, total: reports.append((completed, total)))

    assert [
        [table.name for operation in result.operations for table in operation.read_tables]
        for result in results
    ] == [["First"], [], ["Third"], [], ["First"]]
    assert [len(result.parse_errors) for result in results] == [0, 1, 0, 0, 0]
    (parse_error,) = results[1].parse_errors
    assert isinstance(parse_error, SqlParseError)
    assert parse_error.line == 1
    assert parse_error.message
    assert reports == [(2, 5), (4, 5), (5, 5)]


class _RecordingHost:
    """A stand-in for the analyzer host that records each call and gives an empty answer."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ensure_ready(self) -> None:
        self.calls.append("ensure_ready")

    def analyze_sql_files(self, paths: list[Path], progress_callback=None) -> list[dict]:
        self.calls.append("analyze_sql_files")
        return [{"operations": [], "parse_errors": []} for _ in paths]


def test_the_host_adapter_makes_the_host_ready_before_the_first_run_only() -> None:
    host = _RecordingHost()
    analysis = HostSqlTextAnalysis(host)

    analysis.analyze(["SELECT 1;"])
    analysis.analyze(["SELECT 2;"])

    assert host.calls == ["ensure_ready", "analyze_sql_files", "analyze_sql_files"]


def test_the_host_adapter_does_not_start_the_host_for_no_text() -> None:
    host = _RecordingHost()

    assert HostSqlTextAnalysis(host).analyze([]) == []
    assert host.calls == []


def test_a_host_failure_on_one_text_raises_an_error_that_holds_the_index_of_that_text() -> None:
    class FailingHost(_RecordingHost):
        def analyze_sql_files(self, paths: list[Path], progress_callback=None) -> list[dict]:
            self.failed_path = str(paths[1])
            raise StaticAnalyzerHostError(f"sql analysis failed for input {paths[1]}: boom")

    host = FailingHost()

    with pytest.raises(SqlTextAnalysisError) as caught:
        HostSqlTextAnalysis(host).analyze(["SELECT 1;", "SELECT 2;", "SELECT 3;"])

    assert caught.value.index == 1
    assert isinstance(caught.value, StaticAnalyzerHostError)
    assert str(caught.value) == "sql analysis failed for input text 2 of 3: boom"
    assert host.failed_path not in str(caught.value)


def test_a_host_failure_that_names_no_text_passes_through_unchanged() -> None:
    class FailingHost(_RecordingHost):
        def analyze_sql_files(self, paths: list[Path], progress_callback=None) -> list[dict]:
            raise StaticAnalyzerHostError("dotnet is gone")

    with pytest.raises(StaticAnalyzerHostError) as caught:
        HostSqlTextAnalysis(FailingHost()).analyze(["SELECT 1;"])

    assert not isinstance(caught.value, SqlTextAnalysisError)
    assert str(caught.value) == "dotnet is gone"


def test_the_in_memory_adapter_gives_one_result_for_each_text_in_input_order() -> None:
    first = SqlOperation("SELECT", read_tables=(ObjectName("", "", "dbo", "First"),))
    second = SqlOperation("DELETE", write_tables=(ObjectName("", "", "dbo", "Second"),))
    analysis = InMemorySqlTextAnalysis({"first": [first], "second": [second]})
    reports: list[tuple[int, int]] = []

    results = analysis.analyze(
        ["second", "not held", "first"], lambda completed, total: reports.append((completed, total))
    )

    assert results == [
        SqlTextResult(operations=(second,)),
        SqlTextResult(),
        SqlTextResult(operations=(first,)),
    ]
    assert reports == [(3, 3)]

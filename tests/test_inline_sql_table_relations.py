"""Seam 1: the C# scan turns the host's SQL answer into table relations.

A test scans one C# file and reads the table relations. Most cases use the
in-memory adapter of SQL Text Analysis and a fake of the host's C# answer, so
they need no `dotnet`. One case uses the real host, to show that the scan sends
the text of a Database Invocation to the host.
"""

from __future__ import annotations

import hashlib
import io
import pickle
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import ObjectName
from code_analyzer.connection_lookup import ConnectionLookup
from code_analyzer.csharp_parser import CSharpParser
from code_analyzer.models import (
    CodeLocation,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    SQLQuery,
    SQLQueryType,
)
from code_analyzer.project_scanner import (
    UNRESOLVED_CONNECTION_DATABASE,
    CSharpTableRelation,
    ProjectScanner,
    ProjectScanResult,
)
from code_analyzer.sql_text_analysis import (
    InMemorySqlTextAnalysis,
    SqlOperation,
    SqlTextAnalysisError,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost, StaticAnalyzerHostError

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None,
    reason="the .NET toolchain is not available",
)

UPDATE_TEXT = "UPDATE ord SET Status = 1 FROM dbo.Orders ord JOIN dbo.Items it ON it.OrderId = ord.Id"


def _table(name: str, schema: str = "dbo") -> ObjectName:
    return ObjectName(server="", database="", schema=schema, name=name)


def _invocation(text: str | None, start: int = 100, end: int = 200, kind: str = "literal") -> dict[str, Any]:
    return {
        "class_name": "OrderPage",
        "method_name": "Save",
        "command_text_kind": kind,
        "command_text": text,
        "start_offset": start,
        "end_offset": end,
        "connection_expression": "conn",
    }


def _query(path: Path, text: str, tables: set[ObjectName], database: str | None = "Response") -> SQLQuery:
    return SQLQuery(
        query_text=text,
        query_type=SQLQueryType.UPDATE,
        tables=tables,
        location=CodeLocation(str(path), 7),
        database_source=database,
    )


class _FakeHost:
    """Answers the C# command with the invocations a test gives."""

    def __init__(self, invocations: list[dict[str, Any]]) -> None:
        self._invocations = invocations

    def ensure_ready(self) -> None:
        return None

    def semantic_binding_availability(self, scan_roots):
        return []

    def analyze_csharp_files(self, input_paths, source_roots, progress_callback=None):
        return [
            {
                "source_id": hashlib.sha256(path.read_bytes()).hexdigest(),
                "methods": [],
                "db_invocations": [dict(invocation) for invocation in self._invocations],
            }
            for path in input_paths
        ]


class _FakeParser:
    """Returns the regular expression queries that a test gives."""

    db_tracker = SimpleNamespace(connections={}, unresolved=[])

    def __init__(self, queries: list[SQLQuery]) -> None:
        self._queries = queries

    def parse_file(self, file_path: str) -> FileAnalysisResult:
        return FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.CSHARP,
            framework=FrameworkType.WEBFORMS,
            sql_queries=list(self._queries),
        )


def _scan(
    tmp_path: Path,
    analysis: Any,
    invocations: list[dict[str, Any]],
    queries: list[SQLQuery] | None = None,
) -> list[CSharpTableRelation]:
    root = tmp_path / "Orders"
    root.mkdir(exist_ok=True)
    source = root / "OrderPage.cs"
    source.write_text("class OrderPage { }", encoding="utf-8")
    scan = ProjectScanResult(project_root=str(root), project_name="Orders", scan_time=datetime.now())

    scanner = object.__new__(ProjectScanner)
    scanner.project_root = str(root)
    scanner.scan_result = None
    scanner.csharp_parser = _FakeParser([_query_for(source, query) for query in queries or []])
    scanner.static_analyzer_host = _FakeHost(invocations)
    scanner.sql_text_analysis = analysis
    scanner.connection_lookup = ConnectionLookup(root)

    scanner.refresh_csharp_files(scan, [str(source)])
    return scan.table_relations


def _query_for(source: Path, query: SQLQuery) -> SQLQuery:
    query.location = CodeLocation(str(source), query.location.line_number)
    return query


def _relations_of(relations: list[CSharpTableRelation]) -> set[tuple[str, str, str]]:
    return {(relation.table.name, relation.access_type, relation.reason) for relation in relations}


def _operation(
    operation_type: str,
    read: tuple[ObjectName, ...] = (),
    write: tuple[ObjectName, ...] = (),
    **fields: Any,
) -> SqlOperation:
    return SqlOperation(operation_type=operation_type, read_tables=read, write_tables=write, **fields)


def test_a_written_table_takes_the_operation_type_and_a_read_table_takes_select(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis(
        {UPDATE_TEXT: [_operation("UPDATE", read=(_table("Items"),), write=(_table("Orders"),))]}
    )

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)])

    assert _relations_of(relations) == {
        ("Orders", "UPDATE", "inline_sql_parsed"),
        ("Items", "SELECT", "inline_sql_parsed"),
    }


def test_a_select_into_target_takes_the_operation_type_select_into(tmp_path) -> None:
    text = "SELECT Id INTO dbo.Copy FROM dbo.Source"
    analysis = InMemorySqlTextAnalysis(
        {text: [_operation("SELECT_INTO", read=(_table("Source"),), write=(_table("Copy"),))]}
    )

    relations = _scan(tmp_path, analysis, [_invocation(text)])

    assert _relations_of(relations) == {
        ("Copy", "SELECT_INTO", "inline_sql_parsed"),
        ("Source", "SELECT", "inline_sql_parsed"),
    }


def test_a_temp_table_a_table_variable_a_function_and_an_unresolved_target_give_no_relation(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis(
        {
            UPDATE_TEXT: [
                _operation(
                    "UPDATE",
                    read=(_table("#work", ""), _table("@rows", ""), _table("Items")),
                    write=(_table("Orders"),),
                    function_references=(_table("fn_Key"),),
                    unresolved_write_targets=("ord",),
                )
            ]
        }
    )

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)])

    assert _relations_of(relations) == {
        ("Orders", "UPDATE", "inline_sql_parsed"),
        ("Items", "SELECT", "inline_sql_parsed"),
    }


def test_a_text_that_both_sources_see_gives_only_the_parsed_relations(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis(
        {UPDATE_TEXT: [_operation("UPDATE", read=(_table("Items"),), write=(_table("Orders"),))]}
    )
    regex_text = UPDATE_TEXT.replace(" FROM ", "\n    FROM ")
    regex_query = _query(Path("x"), regex_text, {_table("ord", ""), _table("Orders"), _table("Items")})

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)], [regex_query])

    assert _relations_of(relations) == {
        ("Orders", "UPDATE", "inline_sql_parsed"),
        ("Items", "SELECT", "inline_sql_parsed"),
    }


def test_a_regular_expression_relation_of_another_text_stays_and_carries_its_reason(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis(
        {UPDATE_TEXT: [_operation("UPDATE", read=(_table("Items"),), write=(_table("Orders"),))]}
    )
    other_query = _query(Path("x"), "DELETE FROM dbo.Audit WHERE Id = 1", {_table("Audit")})

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)], [other_query])

    assert {relation.reason for relation in relations if relation.table.name == "Audit"} == {"inline_sql_regex"}
    assert {relation.reason for relation in relations if relation.table.name == "Orders"} == {"inline_sql_parsed"}


def test_a_parsed_relation_carries_the_source_span_of_its_database_invocation(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis({UPDATE_TEXT: [_operation("UPDATE", write=(_table("Orders"),))]})

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT, start=154, end=310)])

    (relation,) = relations
    assert relation.invocation_span == (154, 310)
    assert relation.class_name == "OrderPage"
    assert relation.method_name == "Save"


def test_a_regular_expression_relation_carries_no_source_span(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis({})
    query = _query(Path("x"), UPDATE_TEXT, {_table("Orders")})

    relations = _scan(tmp_path, analysis, [], [query])

    assert {relation.invocation_span for relation in relations} == {()}


def test_a_parsed_relation_stores_the_database_the_parser_finds_for_the_same_text(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis({UPDATE_TEXT: [_operation("UPDATE", write=(_table("Orders"),))]})
    query = _query(Path("x"), UPDATE_TEXT, {_table("Orders")}, database="Response")

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)], [query])

    assert {relation.database for relation in relations} == {"Response"}


def test_a_parsed_relation_is_not_resolved_when_the_parser_finds_no_such_text(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis({UPDATE_TEXT: [_operation("UPDATE", write=(_table("Orders"),))]})

    relations = _scan(tmp_path, analysis, [_invocation(UPDATE_TEXT)])

    assert {relation.database for relation in relations} == {UNRESOLVED_CONNECTION_DATABASE}
    assert {relation.connection_database for relation in relations} == {""}


def test_an_error_from_sql_text_analysis_stops_the_scan_and_names_the_file_and_the_text(tmp_path) -> None:
    class FailingAnalysis:
        def analyze(self, texts, progress_callback=None):
            raise SqlTextAnalysisError(0, "text 1 of 1 failed")

    with pytest.raises(StaticAnalyzerHostError) as raised:
        _scan(tmp_path, FailingAnalysis(), [_invocation(UPDATE_TEXT)])

    assert "OrderPage.cs" in str(raised.value)
    assert UPDATE_TEXT in str(raised.value)


@requires_dotnet
def test_the_scan_sends_the_text_of_a_database_invocation_to_the_real_host(tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    source = root / "OrderPage.cs"
    source.write_text(
        "using System.Data.SqlClient;\n"
        "namespace Orders.Pages\n"
        "{\n"
        "    public class OrderPage\n"
        "    {\n"
        "        public void Save(SqlConnection conn)\n"
        "        {\n"
        f'            var cmd = new SqlCommand("{UPDATE_TEXT}", conn);\n'
        "            cmd.ExecuteNonQuery();\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    scan = ProjectScanResult(project_root=str(root), project_name="Orders", scan_time=datetime.now())

    scanner = object.__new__(ProjectScanner)
    scanner.project_root = str(root)
    scanner.scan_result = None
    scanner.csharp_parser = CSharpParser()
    scanner.static_analyzer_host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    scanner.connection_lookup = ConnectionLookup(root)

    scanner.refresh_csharp_files(scan, [str(source)])

    assert _relations_of(scan.table_relations) == {
        ("Orders", "UPDATE", "inline_sql_parsed"),
        ("Items", "SELECT", "inline_sql_parsed"),
    }
    assert "ord" not in {relation.table.name for relation in scan.table_relations}


def test_a_relation_loads_through_an_unpickler_that_admits_only_the_two_classes_it_holds() -> None:
    """The companion repository loads a C# Scan Result with a fixed list of classes.

    The new relation fields add no class to it: the reason is a string and the span is a tuple of integers.
    """
    relation = CSharpTableRelation(
        csharp_file="OrderPage.cs",
        class_name="OrderPage",
        method_name="Save",
        line_number=1,
        table=_table("Orders"),
        database="Response",
        access_type="UPDATE",
        reason="inline_sql_parsed",
        invocation_span=(154, 310),
    )
    admitted = {
        ("code_analyzer.project_scanner", "CSharpTableRelation"): CSharpTableRelation,
        ("canonical_object_identity", "ObjectName"): ObjectName,
    }

    class RestrictedUnpickler(pickle.Unpickler):
        def find_class(self, module: str, name: str):
            return admitted[(module, name)]

    loaded = RestrictedUnpickler(io.BytesIO(pickle.dumps(relation, protocol=4))).load()

    assert loaded == relation


def test_an_inline_if_exists_predicate_gives_a_select_relation_with_the_real_host(tmp_path) -> None:
    text = "IF EXISTS (SELECT 1 FROM dbo.Gate WHERE Id = @id) UPDATE dbo.Orders SET Flag = 1"
    root = tmp_path / "Orders"
    root.mkdir()
    source = root / "OrderPage.cs"
    source.write_text(
        "using System.Data.SqlClient;\n"
        "namespace Orders.Pages\n"
        "{\n"
        "    public class OrderPage\n"
        "    {\n"
        "        public void Save(SqlConnection conn)\n"
        "        {\n"
        f'            var cmd = new SqlCommand("{text}", conn);\n'
        "            cmd.ExecuteNonQuery();\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    scan = ProjectScanResult(project_root=str(root), project_name="Orders", scan_time=datetime.now())

    scanner = object.__new__(ProjectScanner)
    scanner.project_root = str(root)
    scanner.scan_result = None
    scanner.csharp_parser = CSharpParser()
    scanner.static_analyzer_host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    scanner.connection_lookup = ConnectionLookup(root)

    scanner.refresh_csharp_files(scan, [str(source)])

    assert _relations_of(scan.table_relations) == {
        ("Gate", "SELECT", "inline_sql_parsed"),
        ("Orders", "UPDATE", "inline_sql_parsed"),
    }

"""The regular expression fallback of inline SQL tables is marked and misses no table.

Seam 1 (C# Scan Result) uses the in-memory adapter of SQL Text Analysis, and
the real C# parser for the expression cases. Seam 2 (table answer) asks
`/find_by_table`. Seam 3 (SQL Text Analysis) needs `dotnet`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from canonical_object_identity import ObjectName
from code_analyzer.csharp_parser import CSharpParser
from code_analyzer.project_connection_scope import ProjectConnectionScopeIndex
from code_analyzer.project_scanner import (
    INLINE_SQL_REGEX,
    CSharpTableRelation,
    ProjectScanner,
    ProjectScanResult,
)
from code_analyzer.sql_text_analysis import (
    HostSqlTextAnalysis,
    InMemorySqlTextAnalysis,
    SqlParseError,
    SqlTextResult,
)
from code_analyzer.webconfig_connection_resolver import WebConfigConnections
from tests.test_inline_sql_table_answer import _ask
from tests.test_inline_sql_table_relations import (
    _FakeHost,
    _invocation,
    _query,
    _relations_of,
    _scan,
    _table,
)
from tests.test_table_match import _inline_scan

MERGE_TEXT = "MERGE dbo.Target t USING dbo.Source s ON t.Id = s.Id WHEN MATCHED THEN UPDATE SET t.Name = s.Name;"


class _AnswersWithParseError:
    def analyze(self, texts, progress_callback=None):
        return [SqlTextResult(parse_errors=(SqlParseError(line=1, message="bad"),)) for _ in texts]


def _fallback_tables(relations: list[CSharpTableRelation]) -> set[tuple[str, str, str]]:
    return {(relation.table.name, relation.access_type, relation.reason) for relation in relations}


# --- Seam 1, in-memory adapter: the fallback conditions ---------------------------------------


def test_a_text_with_no_read_and_no_write_gives_fallback_relations_with_its_target(tmp_path) -> None:
    analysis = InMemorySqlTextAnalysis({MERGE_TEXT: []})
    query = _query(Path("x"), MERGE_TEXT, {_table("Target"), _table("Source")})

    relations = _scan(tmp_path, analysis, [_invocation(MERGE_TEXT)], [query])

    assert _fallback_tables(relations) == {
        ("Target", "UNRESOLVED", "inline_sql_regex"),
        ("Source", "UNRESOLVED", "inline_sql_regex"),
    }


def test_a_concatenated_text_gives_fallback_relations_with_unresolved(tmp_path) -> None:
    text = "UPDATE dbo.Orders SET Id = 1"
    analysis = InMemorySqlTextAnalysis({})
    query = _query(Path("x"), text, {_table("Orders")})

    relations = _scan(tmp_path, analysis, [_invocation(None, kind="dynamic")], [query])

    assert _fallback_tables(relations) == {("Orders", "UNRESOLVED", "inline_sql_regex")}


def test_a_text_with_a_parse_error_gives_fallback_relations_with_unresolved(tmp_path) -> None:
    text = "UPDATE dbo.Orders SET"
    query = _query(Path("x"), text, {_table("Orders")})

    relations = _scan(tmp_path, _AnswersWithParseError(), [_invocation(text)], [query])

    assert _fallback_tables(relations) == {("Orders", "UNRESOLVED", "inline_sql_regex")}


# --- Seam 1, real C# parser: the fallback expressions -----------------------------------------


def _relations_of_source(tmp_path: Path, sql_literal: str) -> list[CSharpTableRelation]:
    root = tmp_path / "Orders"
    root.mkdir(exist_ok=True)
    source = root / "OrderPage.cs"
    source.write_text(
        "namespace Orders.Pages\n{\n    public class OrderPage\n    {\n"
        f"        public void Save()\n        {{\n            string sql = {sql_literal};\n        }}\n"
        "    }\n}\n",
        encoding="utf-8",
    )
    scan = ProjectScanResult(project_root=str(root), project_name="Orders", scan_time=datetime.now())
    scanner = object.__new__(ProjectScanner)
    scanner.project_root = str(root)
    scanner.scan_result = None
    scanner.csharp_parser = CSharpParser()
    scanner.static_analyzer_host = _FakeHost([])
    scanner.sql_text_analysis = InMemorySqlTextAnalysis({})
    scanner.connection_resolver = WebConfigConnections()
    scanner.connection_scopes = ProjectConnectionScopeIndex(root)
    scanner.refresh_csharp_files(scan, [str(source)])
    return scan.table_relations


def test_the_regular_expression_relations_of_the_parser_state_unresolved(tmp_path) -> None:
    relations = _relations_of_source(tmp_path, '"SELECT u.Id FROM PUR.dbo.Users u JOIN Orders o ON o.Id = u.Id"')

    assert {(relation.table.name, relation.access_type, relation.reason) for relation in relations} == {
        ("Users", "UNRESOLVED", INLINE_SQL_REGEX),
        ("Orders", "UNRESOLVED", INLINE_SQL_REGEX),
    }


def test_a_text_that_starts_with_with_gives_its_tables(tmp_path) -> None:
    relations = _relations_of_source(
        tmp_path,
        '"WITH Recent AS (SELECT Id FROM dbo.Orders) SELECT r.Id FROM Recent r JOIN dbo.Items i ON i.Id = r.Id"',
    )

    names = {relation.table.name for relation in relations}
    assert {"Orders", "Items"} <= names
    assert {relation.access_type for relation in relations} == {"UNRESOLVED"}


def test_a_text_that_starts_with_merge_gives_its_target_and_its_source(tmp_path) -> None:
    relations = _relations_of_source(tmp_path, f'"{MERGE_TEXT}"')

    assert {relation.table.name for relation in relations} == {"Target", "Source"}


def test_an_insert_with_a_column_list_gives_its_target(tmp_path) -> None:
    relations = _relations_of_source(
        tmp_path, '"insert into ManifestNew (R_ID,data) values(@RId,@Data)"'
    )

    assert _fallback_tables(relations) == {("ManifestNew", "UNRESOLVED", INLINE_SQL_REGEX)}


def test_a_table_name_in_an_sql_comment_gives_no_table(tmp_path) -> None:
    relations = _relations_of_source(
        tmp_path,
        '"SELECT Id FROM dbo.Real -- FROM dbo.InsideLine\\n /* JOIN dbo.InsideBlock */ WHERE Id = 1"',
    )

    assert {relation.table.name for relation in relations} == {"Real"}


def test_a_table_name_in_a_comment_of_a_verbatim_text_gives_no_table(tmp_path) -> None:
    relations = _relations_of_source(
        tmp_path,
        '@"SELECT Id FROM dbo.Real\n-- FROM dbo.InsideLine\n/* JOIN dbo.InsideBlock */\nWHERE Id = 1"',
    )

    assert {relation.table.name for relation in relations} == {"Real"}


# --- Seam 2: write_only leaves the fallback out and counts it ---------------------------------


def test_write_only_leaves_a_fallback_relation_out_and_counts_it(monkeypatch, tmp_path) -> None:
    scan = _inline_scan(tmp_path, ObjectName("", "", "dbo", "Orders"), "Response")
    scan.table_relations[0].access_type = "UNRESOLVED"
    scan.table_relations[0].reason = INLINE_SQL_REGEX

    answer = _ask(monkeypatch, tmp_path, scan, "dbo.Orders", write_only=True)

    assert answer.matches == []
    assert answer.excluded_count == 1


# --- Seam 3: the real host ------------------------------------------------------------------


def test_the_host_parses_a_merge_text_and_gives_no_operation() -> None:
    (result,) = HostSqlTextAnalysis.for_project(PROJECT_ROOT).analyze([MERGE_TEXT])

    assert result.parse_errors == ()
    assert result.operations == ()

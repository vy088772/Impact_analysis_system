"""Seam 2: the two extraction sites in the SQL analyzer, over a fake cursor.

`quick_analyze_sp` reads the referenced tables of one stored procedure from the
native dependency query. When that query returns nothing, the regex reader reads
the definition instead. Both keep the schema and the database the reference
states (`.scratch/canonical-object-identity/` ticket 07).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

from canonical_object_identity import ObjectName
from code_analyzer.sql_analyzer import SQLAnalyzer


class FakeCursor:
    """Answers the queries of `quick_analyze_sp` with canned rows."""

    def __init__(self, definition: str, native_rows: List[Tuple[Any, ...]]) -> None:
        self.definition = definition
        self.native_rows = native_rows
        self._last_query = ""

    def execute(self, query: str, *params: Any) -> None:
        self._last_query = query

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if "COUNT(*)" in self._last_query:
            return (1,)
        if "ROUTINE_DEFINITION" in self._last_query:
            return (self.definition, None, None)
        return None

    def fetchall(self) -> List[Tuple[Any, ...]]:
        if "sys.dm_sql_referenced_entities" in self._last_query:
            return self.native_rows
        return []


def _analyze(cursor: FakeCursor):
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    analyzer.db_config = SimpleNamespace(alias="Response")
    return analyzer.quick_analyze_sp("usp_Load", "dbo")


def test_a_native_row_keeps_its_database_and_schema() -> None:
    cursor = FakeCursor(
        definition="CREATE PROCEDURE dbo.usp_Load AS SELECT Id FROM PUR.dbo.Users",
        native_rows=[(None, "PUR", "dbo", "Users")],
    )

    info = _analyze(cursor)

    assert info.dependency_source == "native"
    assert info.referenced_tables == {
        ObjectName(server="", database="PUR", schema="dbo", name="Users")
    }


def test_with_no_native_row_the_regex_reader_keeps_the_schema() -> None:
    cursor = FakeCursor(
        definition="CREATE PROCEDURE dbo.usp_Load AS SELECT Id FROM COMMON.AVM",
        native_rows=[],
    )

    info = _analyze(cursor)

    assert info.dependency_source == "regex"
    assert info.referenced_tables == {
        ObjectName(server="", database="", schema="COMMON", name="AVM")
    }

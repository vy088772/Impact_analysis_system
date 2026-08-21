"""Regression tests for SQLAnalyzer._get_sp_basic_info's definition fetch.

INFORMATION_SCHEMA.ROUTINES.ROUTINE_DEFINITION is NVARCHAR(4000): any stored
procedure whose body is longer than that is silently truncated by SQL Server
itself, well before this code ever sees it. A real cached SP
(usp_ErrorSummaryQry) was truncated exactly at 4000 characters mid-statement,
which later made the SQL Execution Graph's ScriptDom parser report an
"unexpected end of file" on a SQL text that was never actually complete.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.sql_analyzer import SQLAnalyzer


class FakeCursor:
    """Mimics pyodbc's cursor.execute(sql, *params) enough for this test."""

    def __init__(self, routine_definition: Optional[str], object_definition: str) -> None:
        self.routine_definition = routine_definition
        self.object_definition = object_definition
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._last_query = ""

    def execute(self, query: str, *params: Any) -> None:
        self._last_query = query
        self.executed.append((query, params))

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        if "INFORMATION_SCHEMA.ROUTINES" in self._last_query:
            return (self.routine_definition, None, None)
        if "OBJECT_DEFINITION" in self._last_query:
            return (self.object_definition,)
        return None

    def fetchall(self) -> list[Any]:
        return []


def _analyzer_with_cursor(cursor: FakeCursor) -> SQLAnalyzer:
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    return analyzer


def test_truncated_routine_definition_falls_back_to_object_definition() -> None:
    """A 4000-char ROUTINE_DEFINITION (SQL Server's truncation point) must be replaced."""
    full_definition = "CREATE PROCEDURE dbo.usp_Long AS " + ("X" * 5000)
    truncated = full_definition[:4000]
    cursor = FakeCursor(routine_definition=truncated, object_definition=full_definition)

    info = _analyzer_with_cursor(cursor)._get_sp_basic_info("usp_Long", "dbo")

    assert info is not None
    assert info["definition"] == full_definition
    assert len(info["definition"]) > 4000


def test_short_routine_definition_is_not_overwritten_by_object_definition() -> None:
    """A short, non-truncated definition should be returned as-is (no extra query needed)."""
    short_definition = "CREATE PROCEDURE dbo.usp_Short AS SELECT 1;"
    cursor = FakeCursor(routine_definition=short_definition, object_definition="SHOULD NOT BE USED")

    info = _analyzer_with_cursor(cursor)._get_sp_basic_info("usp_Short", "dbo")

    assert info is not None
    assert info["definition"] == short_definition
    assert not any("OBJECT_DEFINITION" in query for query, _ in cursor.executed)


def test_object_definition_fallback_uses_parameterized_query() -> None:
    """The OBJECT_ID lookup must bind the object name as a parameter, never string-format it into SQL."""
    truncated = "X" * 4000
    cursor = FakeCursor(routine_definition=truncated, object_definition="FULL BODY")

    _analyzer_with_cursor(cursor)._get_sp_basic_info("usp_Long", "dbo")

    fallback_calls = [
        (query, params) for query, params in cursor.executed if "OBJECT_DEFINITION" in query
    ]
    assert len(fallback_calls) == 1
    query, params = fallback_calls[0]
    assert "?" in query
    assert "dbo.usp_Long" not in query
    assert params == ("dbo.usp_Long",)


def test_missing_routine_definition_falls_back_to_object_definition() -> None:
    """A NULL ROUTINE_DEFINITION (e.g. encrypted or permission-limited) still tries OBJECT_DEFINITION."""
    cursor = FakeCursor(routine_definition=None, object_definition="RECOVERED BODY")

    info = _analyzer_with_cursor(cursor)._get_sp_basic_info("usp_Hidden", "dbo")

    assert info is not None
    assert info["definition"] == "RECOVERED BODY"


if __name__ == "__main__":
    test_truncated_routine_definition_falls_back_to_object_definition()
    test_short_routine_definition_is_not_overwritten_by_object_definition()
    test_object_definition_fallback_uses_parameterized_query()
    test_missing_routine_definition_falls_back_to_object_definition()
    print("sql_analyzer definition-fetch tests passed")

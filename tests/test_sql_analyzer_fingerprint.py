"""Seam 2: the Fingerprint query of the SQL analyzer, over a fake cursor.

A Fingerprint holds, for each kind group, the latest `modify_date` and the
object count (`.scratch/sql-cache-behind-source/` ticket 01).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, List, Tuple

from code_analyzer.sql_analyzer import SQLAnalyzer
from tests.sql_cache_fixtures import fingerprint


class FingerprintCursor:
    """Answers the Fingerprint query with canned rows of (kind, schema, count, latest time)."""

    def __init__(self, rows: List[Tuple[str, str, int, datetime]]) -> None:
        self.rows = rows
        self.executed: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, query: str, *params: Any) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> List[Any]:
        return [
            SimpleNamespace(kind=k, schema_name=s, object_count=c, latest_modified=t)
            for k, s, c, t in self.rows
        ]


def _analyzer(rows: List[Tuple[str, str, int, datetime]]) -> Tuple[SQLAnalyzer, FingerprintCursor]:
    cursor = FingerprintCursor(rows)
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    analyzer.db_config = SimpleNamespace(alias="Response")
    return analyzer, cursor


def test_the_fingerprint_has_one_entry_for_each_kind_group() -> None:
    analyzer, _ = _analyzer(
        [
            ("procedures", "dbo", 3, datetime(2026, 10, 1, 9, 0, 0)),
            ("views", "dbo", 2, datetime(2026, 9, 1, 8, 30, 0)),
            ("functions", "dbo", 4, datetime(2026, 8, 1, 7, 15, 0, 250000)),
            ("tables", "dbo", 10, datetime(2026, 10, 30, 12, 0, 0)),
        ]
    )

    assert analyzer.read_fingerprint() == fingerprint(
        procedures=(3, "2026-10-01T09:00:00.000000"),
        views=(2, "2026-09-01T08:30:00.000000"),
        functions=(4, "2026-08-01T07:15:00.250000"),
        tables=(10, "2026-10-30T12:00:00.000000"),
    )


def test_the_query_reads_sys_objects_of_the_kind_groups_and_drops_shipped_objects() -> None:
    analyzer, cursor = _analyzer([])

    analyzer.read_fingerprint()

    assert len(cursor.executed) == 1
    query, params = cursor.executed[0]
    assert "sys.objects" in query
    assert "is_ms_shipped = 0" in query
    for object_type in ("'P'", "'V'", "'FN'", "'IF'", "'TF'", "'U'"):
        assert object_type in query
    # One Database only: the query names no other Database.
    assert ".sys.objects" not in query
    assert params == ()


def test_the_rows_of_one_kind_group_in_several_schemas_add_up() -> None:
    analyzer, _ = _analyzer(
        [
            ("procedures", "dbo", 3, datetime(2026, 10, 1, 9, 0, 0)),
            ("procedures", "COMMON", 2, datetime(2026, 10, 5, 9, 0, 0)),
        ]
    )

    assert analyzer.read_fingerprint() == fingerprint(procedures=(5, "2026-10-05T09:00:00.000000"))


def test_the_fingerprint_drops_the_schemas_that_sql_server_owns() -> None:
    analyzer, _ = _analyzer(
        [
            ("tables", "dbo", 1, datetime(2026, 1, 1)),
            ("tables", "sys", 5, datetime(2026, 12, 1)),
            ("tables", "INFORMATION_SCHEMA", 5, datetime(2026, 12, 1)),
            ("tables", "Guest", 5, datetime(2026, 12, 1)),
        ]
    )

    assert analyzer.read_fingerprint() == fingerprint(tables=(1, "2026-01-01T00:00:00.000000"))


def test_a_kind_group_with_no_objects_has_a_zero_count_and_no_latest_time() -> None:
    analyzer, _ = _analyzer([("tables", "dbo", 1, datetime(2026, 1, 1))])

    read = analyzer.read_fingerprint()

    for kind in ("procedures", "views", "functions"):
        assert read[kind] == {"count": 0, "latest_modified": ""}


def test_a_database_with_no_objects_gives_four_empty_entries() -> None:
    analyzer, _ = _analyzer([])

    assert analyzer.read_fingerprint() == fingerprint()

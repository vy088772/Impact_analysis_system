"""Seam 2: the Fingerprint query of the SQL analyzer, over a fake cursor.

A Fingerprint holds, for each kind group, the latest `modify_date` and the
object count (`.scratch/sql-cache-behind-source/` ticket 01). The query returns
one row for each `sys.objects.type`; the analyzer puts each type in its group.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, List, Tuple

from code_analyzer.sql_analyzer import SQLAnalyzer
from tests.sql_cache_fixtures import fingerprint

# One row of the query: (sys.objects.type as SQL Server returns it, count, latest modify_date).
Row = Tuple[str, int, datetime]


class FingerprintCursor:
    """Answers the Fingerprint query with canned rows."""

    def __init__(self, rows: List[Row]) -> None:
        self.rows = rows
        self.executed: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, query: str, *params: Any) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> List[Any]:
        return [
            SimpleNamespace(object_type=t, object_count=c, latest_modified=m)
            for t, c, m in self.rows
        ]


def _analyzer(rows: List[Row]) -> Tuple[SQLAnalyzer, FingerprintCursor]:
    cursor = FingerprintCursor(rows)
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    analyzer.db_config = SimpleNamespace(alias="Response")
    return analyzer, cursor


def _query(cursor: FingerprintCursor) -> str:
    assert len(cursor.executed) == 1
    query, params = cursor.executed[0]
    assert params == ()
    return query


def test_each_object_type_counts_in_its_kind_group() -> None:
    # SQL Server returns `type` as char(2), so a one-letter type ends with a space.
    analyzer, _ = _analyzer(
        [
            ("P ", 3, datetime(2026, 10, 1, 9, 0, 0)),
            ("V ", 2, datetime(2026, 9, 1, 8, 30, 0)),
            ("FN", 1, datetime(2026, 7, 1, 7, 0, 0)),
            ("IF", 2, datetime(2026, 8, 1, 7, 15, 0, 250000)),
            ("TF", 1, datetime(2026, 6, 1)),
            ("U ", 10, datetime(2026, 10, 30, 12, 0, 0)),
        ]
    )

    assert analyzer.read_fingerprint() == fingerprint(
        procedures=(3, datetime(2026, 10, 1, 9, 0, 0)),
        views=(2, datetime(2026, 9, 1, 8, 30, 0)),
        functions=(4, datetime(2026, 8, 1, 7, 15, 0, 250000)),
        tables=(10, datetime(2026, 10, 30, 12, 0, 0)),
    )


def test_the_query_reads_sys_objects_of_the_scanned_database_and_drops_shipped_objects() -> None:
    analyzer, cursor = _analyzer([])

    analyzer.read_fingerprint()

    query = _query(cursor)
    assert "FROM sys.objects" in query
    assert "is_ms_shipped = 0" in query
    for object_type in ("'P'", "'V'", "'FN'", "'IF'", "'TF'", "'U'"):
        assert object_type in query
    # One Database only: the query names no other Database.
    assert ".sys.objects" not in query


def test_the_query_drops_the_schemas_that_sql_server_owns() -> None:
    analyzer, cursor = _analyzer([])

    analyzer.read_fingerprint()

    query = _query(cursor).lower()
    for schema in ("'sys'", "'information_schema'", "'guest'"):
        assert schema in query
    assert "not in" in query
    # The same `db_` prefix rule as the object listing; `_` is a literal, not a wildcard.
    assert "not like 'db[_]%'" in query


def test_an_object_type_outside_the_kind_groups_counts_nowhere() -> None:
    analyzer, _ = _analyzer([("TR", 7, datetime(2026, 12, 1)), ("U ", 1, datetime(2026, 1, 1))])

    assert analyzer.read_fingerprint() == fingerprint(tables=(1, datetime(2026, 1, 1)))


def test_a_kind_group_with_no_objects_has_a_zero_count_and_no_latest_time() -> None:
    analyzer, _ = _analyzer([("U ", 1, datetime(2026, 1, 1))])

    read = analyzer.read_fingerprint()

    for kind in ("procedures", "views", "functions"):
        assert read.to_json()[kind] == {"count": 0, "latest_modified": ""}


def test_a_database_with_no_objects_gives_four_empty_entries() -> None:
    analyzer, _ = _analyzer([])

    assert analyzer.read_fingerprint() == fingerprint()

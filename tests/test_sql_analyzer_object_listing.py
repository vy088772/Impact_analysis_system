"""Seam 2: the object listing of the SQL analyzer, over a fake cursor.

One listing runs one query that selects the schema beside the name, and it
applies no schema filter. The excluded-schema rule runs over the returned rows
(`.scratch/canonical-object-identity/` ticket 08).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

from code_analyzer.sql_analyzer import ObjectListing, SQLAnalyzer, quote_name


class ListingCursor:
    """Answers the listing query with canned rows, and every other query with nothing."""

    def __init__(self, rows: List[Tuple[str, str, str]]) -> None:
        self.rows = rows
        self.executed: List[Tuple[str, Tuple[Any, ...]]] = []
        self._last_query = ""

    def execute(self, query: str, *params: Any) -> None:
        self._last_query = query
        self.executed.append((query, params))

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if "OBJECT_DEFINITION" in self._last_query:
            return ("CREATE PROCEDURE p AS SELECT 1",)
        if "ROUTINE_DEFINITION" in self._last_query:
            return ("CREATE PROCEDURE p AS SELECT 1", None, None)
        return None

    def fetchall(self) -> List[Any]:
        if "UNION ALL" in self._last_query:
            return [SimpleNamespace(kind=k, schema_name=s, object_name=n) for k, s, n in self.rows]
        return []


def _analyzer(rows: List[Tuple[str, str, str]]) -> Tuple[SQLAnalyzer, ListingCursor]:
    cursor = ListingCursor(rows)
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    analyzer.db_config = SimpleNamespace(alias="Response")
    return analyzer, cursor


def test_the_listing_runs_one_query_and_applies_no_schema_filter() -> None:
    analyzer, cursor = _analyzer([("procedures", "dbo", "usp_A")])

    analyzer.list_objects()

    listing_queries = [query for query, _ in cursor.executed]
    assert len(listing_queries) == 1
    assert listing_queries[0].count("UNION ALL") == 3
    assert "schema" in listing_queries[0].lower()
    # No schema condition and no bound parameter: the rule runs over the rows.
    assert "?" not in listing_queries[0]
    assert cursor.executed[0][1] == ()


def test_the_listing_returns_rows_of_kind_schema_and_bare_name() -> None:
    analyzer, _ = _analyzer([("procedures", "COMMON", "usp_Load"), ("tables", "dbo", "Orders")])

    assert analyzer.list_objects() == [
        ObjectListing(kind="procedures", schema="COMMON", name="usp_Load"),
        ObjectListing(kind="tables", schema="dbo", name="Orders"),
    ]


def test_the_listing_drops_the_schemas_that_sql_server_owns() -> None:
    analyzer, _ = _analyzer(
        [
            ("tables", "dbo", "T1"),
            ("tables", "guest", "T2"),
            ("tables", "db_owner", "T3"),
            ("tables", "DB_Reports", "T4"),
            ("tables", "dbXyz", "T5"),
            ("tables", "sys", "T6"),
            ("tables", "INFORMATION_SCHEMA", "T7"),
            ("tables", "Information_Schema", "T8"),
            ("tables", "GUEST", "T9"),
        ]
    )

    assert [(row.schema, row.name) for row in analyzer.list_objects()] == [
        ("dbo", "T1"),
        ("dbXyz", "T5"),
    ]


def test_one_listing_gives_the_four_kinds_of_the_dump_with_their_own_schema() -> None:
    analyzer, _ = _analyzer(
        [
            ("functions", "COMMON", "fn_Rate"),
            ("procedures", "COMMON", "usp_Load"),
            ("procedures", "dbo", "usp_Save"),
            ("tables", "HR", "Staff"),
            ("views", "dbo", "vw_Orders"),
        ]
    )

    data = analyzer.dump_all_sql_objects()

    assert [(item["schema"], item["name"]) for item in data["procedures"]] == [
        ("COMMON", "usp_Load"),
        ("dbo", "usp_Save"),
    ]
    assert [(item["schema"], item["name"]) for item in data["views"]] == [("dbo", "vw_Orders")]
    assert [(item["schema"], item["name"]) for item in data["functions"]] == [("COMMON", "fn_Rate")]
    assert [(item["schema"], item["name"]) for item in data["tables"]] == [("HR", "Staff")]


def test_the_dump_holds_no_cache_wide_schema() -> None:
    analyzer, _ = _analyzer([("tables", "HR", "Staff")])

    assert "schema" not in analyzer.dump_all_sql_objects()


def test_each_fetch_binds_the_schema_the_listing_reported() -> None:
    analyzer, cursor = _analyzer([("procedures", "COMMON", "usp_Load")])

    analyzer.dump_all_sql_objects()

    routine_queries = [
        params for query, params in cursor.executed if "ROUTINE_DEFINITION" in query
    ]
    assert routine_queries == [("usp_Load", "COMMON")]


def test_the_dump_records_a_bare_name_that_two_schemas_hold_in_one_kind() -> None:
    analyzer, _ = _analyzer(
        [
            ("procedures", "COMMON", "usp_Load"),
            ("procedures", "dbo", "USP_LOAD"),
            ("tables", "COMMON", "Orders"),
            ("views", "dbo", "Orders"),
        ]
    )

    data = analyzer.dump_all_sql_objects()

    assert data["name_collisions"] == [
        {"kind": "procedures", "name": "usp_Load", "schemas": ["COMMON", "dbo"]}
    ]


def test_the_dump_records_no_collision_when_each_bare_name_has_one_schema() -> None:
    analyzer, _ = _analyzer([("procedures", "COMMON", "usp_A"), ("procedures", "dbo", "usp_B")])

    assert analyzer.dump_all_sql_objects()["name_collisions"] == []


def test_one_helper_brackets_each_part_and_doubles_a_closing_bracket() -> None:
    assert quote_name("dbo", "Orders") == "[dbo].[Orders]"
    assert quote_name("dbo", "Order Details") == "[dbo].[Order Details]"
    assert quote_name("my]schema", "a.b") == "[my]]schema].[a.b]"


def test_the_definition_fetch_binds_a_bracketed_name() -> None:
    analyzer, cursor = _analyzer([])

    analyzer.get_object_definition("Order]Detail", "COMMON")

    assert cursor.executed == [
        ("SELECT OBJECT_DEFINITION(OBJECT_ID(?))", ("[COMMON].[Order]]Detail]",))
    ]


def test_the_batch_entry_point_analyses_each_procedure_in_its_own_schema() -> None:
    analyzer, _ = _analyzer(
        [
            ("procedures", "COMMON", "usp_Load"),
            ("procedures", "dbo", "usp_Save"),
            ("tables", "dbo", "Orders"),
        ]
    )
    analyzed: List[Tuple[str, str]] = []
    analyzer.get_database_summary = lambda: SimpleNamespace(procedures=[], analyzed_procedures=0)
    analyzer.quick_analyze_sp = lambda name, schema: analyzed.append((schema, name)) or name

    analyzer.analyze_all_procedures()

    assert analyzed == [("COMMON", "usp_Load"), ("dbo", "usp_Save")]


def test_a_typed_menu_name_needs_one_match_across_the_listed_schemas() -> None:
    from code_analyzer.sql_analyzer import _match_typed_procedure

    procedures = [
        ObjectListing("procedures", "COMMON", "usp_Load"),
        ObjectListing("procedures", "dbo", "usp_Load"),
        ObjectListing("procedures", "dbo", "usp_Save"),
    ]

    assert _match_typed_procedure(procedures, "usp_Load") is None
    assert _match_typed_procedure(procedures, "[COMMON].[usp_Load]") == procedures[0]
    assert _match_typed_procedure(procedures, "USP_SAVE") == procedures[2]
    assert _match_typed_procedure(procedures, "sales.usp_Save") is None

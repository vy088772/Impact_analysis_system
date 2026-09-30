"""The quick single-procedure analyzer resolves an unstated schema to `dbo`.

A procedure name that states a schema uses it. A name that states none takes
`dbo`, as a caller outside a module does in SQL Server. A name that `dbo` does
not hold does not exist (unstated-schema-resolves-as-sql-server-does, ticket 07).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

from code_analyzer.sql_analyzer import SQLAnalyzer


class FakeCursor:
    """A catalog of procedures as (schema, name) pairs. It records each existence check."""

    def __init__(self, procedures: List[Tuple[str, str]]) -> None:
        self.procedures = procedures
        self.checked: List[Tuple[str, str]] = []
        self._query = ""
        self._params: Tuple[Any, ...] = ()

    def execute(self, query: str, *params: Any) -> None:
        self._query = query
        self._params = params

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        if "COUNT(*)" in self._query:
            name, schema = self._params
            self.checked.append((schema, name))
            return (int((schema, name) in self.procedures),)
        if "ROUTINE_DEFINITION" in self._query:
            return ("CREATE PROCEDURE x AS SELECT 1", None, None)
        return None

    def fetchall(self) -> List[Tuple[Any, ...]]:
        if "SELECT ROUTINE_SCHEMA" in self._query:
            (name,) = self._params
            return [(schema,) for schema, listed in self.procedures if listed == name]
        return []


def _analyze(procedures: List[Tuple[str, str]], name: str):
    cursor = FakeCursor(procedures)
    analyzer = SQLAnalyzer.__new__(SQLAnalyzer)
    analyzer.cursor = cursor
    analyzer.db_config = SimpleNamespace(alias="eFinance")
    return analyzer.quick_analyze_sp(name, ""), cursor


def test_a_name_with_no_schema_takes_dbo() -> None:
    info, cursor = _analyze([("dbo", "usp_Load")], "usp_Load")

    assert info.exists
    assert info.schema == "dbo"
    assert cursor.checked == [("dbo", "usp_Load")]


def test_a_name_that_two_schemas_hold_takes_dbo() -> None:
    info, cursor = _analyze([("COMMON", "usp_Load"), ("dbo", "usp_Load")], "usp_Load")

    assert info.exists
    assert info.schema == "dbo"
    assert cursor.checked == [("dbo", "usp_Load")]


def test_a_name_that_dbo_does_not_hold_does_not_exist() -> None:
    info, cursor = _analyze([("COMMON", "usp_Load")], "usp_Load")

    assert not info.exists
    assert cursor.checked == [("dbo", "usp_Load")]


def test_the_schema_argument_has_no_default() -> None:
    import inspect

    assert inspect.signature(SQLAnalyzer.quick_analyze_sp).parameters["schema"].default is inspect.Parameter.empty


def test_a_name_that_states_its_schema_uses_it() -> None:
    info, cursor = _analyze([("COMMON", "usp_Load"), ("dbo", "usp_Load")], "[COMMON].[usp_Load]")

    assert info.exists
    assert info.schema == "COMMON"
    assert info.procedure_name == "[COMMON].[usp_Load]"
    assert cursor.checked == [("COMMON", "usp_Load")]

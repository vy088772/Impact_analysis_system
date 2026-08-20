"""Ticket 03: sp_fetcher.fetch_sp_definitions has no live-query fallback.

A gap in the SQL cache must return no definition for that name, not open a
live database connection — see docs/adr/0011-remove-live-query-fallbacks.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import sp_fetcher


class _ConnectionAttempted(AssertionError):
    pass


def _refuse_connect(self, *args, **kwargs):
    raise _ConnectionAttempted("fetch_sp_definitions must not open a live connection")


@pytest.fixture(autouse=True)
def _forbid_live_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if fetch_sp_definitions ever calls SQLAnalyzer.connect().

    Patches only `.connect`, not the class itself: sp_fetcher's own
    `estimate_complexity_from_definition` legitimately builds a bare
    `object.__new__(SQLAnalyzer)` for pure string analysis (no `__init__`,
    no `.connect()`), and that path must keep working.
    """
    monkeypatch.setattr("code_analyzer.sql_analyzer.SQLAnalyzer.connect", _refuse_connect)


def _cache_with_one_procedure() -> dict:
    return {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "usp_Known",
                "definition": "CREATE PROCEDURE usp_Known AS SELECT 1",
                "parameters": [{"name": "@id", "type": "int"}],
            }
        ],
        "sql_execution_graph": {
            "nodes": [
                {"id": "sp:known", "type": "stored_procedure", "name": "usp_Known"},
                {"id": "table:orders", "type": "table", "name": "Orders", "schema": "dbo"},
            ],
            "relationships": [
                {"type": "reads", "source": "sp:known", "target": "table:orders"},
            ],
        },
    }


def test_missing_name_returns_no_definition_and_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp_fetcher, "load_cached", lambda *a, **k: _cache_with_one_procedure())

    results = sp_fetcher.fetch_sp_definitions(["usp_Unknown"], database_alias="OrdersDb")

    assert results == []


def test_cached_name_returns_same_definition_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp_fetcher, "load_cached", lambda *a, **k: _cache_with_one_procedure())

    results = sp_fetcher.fetch_sp_definitions(["usp_Known"], database_alias="OrdersDb")

    assert len(results) == 1
    entry = results[0]
    assert entry["name"] == "usp_Known"
    assert entry["exists"] is True
    assert entry["definition"] == "CREATE PROCEDURE usp_Known AS SELECT 1"
    assert entry["dependency_source"] == "execution_graph"
    assert entry["tables"] == ["dbo.Orders"]


def test_mixed_names_only_return_cached_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp_fetcher, "load_cached", lambda *a, **k: _cache_with_one_procedure())

    results = sp_fetcher.fetch_sp_definitions(
        ["usp_Known", "usp_Unknown"], database_alias="OrdersDb"
    )

    assert [entry["name"] for entry in results] == ["usp_Known"]


def test_no_sql_cache_returns_empty_and_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp_fetcher, "load_cached", lambda *a, **k: None)

    results = sp_fetcher.fetch_sp_definitions(["usp_Anything"], database_alias="OrdersDb")

    assert results == []

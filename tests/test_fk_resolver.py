"""Ticket 03: fk_resolver.resolve_fk_related has no live-query fallback.

A request with no SQL cache must return an empty list, not open a live
database connection or query sys.foreign_keys — see
docs/adr/0011-remove-live-query-fallbacks.md. The PK-naming inference over a
cached scan is unaffected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import fk_resolver


class _ConnectionAttempted(AssertionError):
    pass


def _refuse_connect(self, *args, **kwargs):
    raise _ConnectionAttempted("resolve_fk_related must not open a live connection")


@pytest.fixture(autouse=True)
def _forbid_live_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if resolve_fk_related ever calls SQLAnalyzer.connect()."""
    monkeypatch.setattr("code_analyzer.sql_analyzer.SQLAnalyzer.connect", _refuse_connect)


def _cache_with_pk_naming_relation() -> dict:
    return {
        "database": "OrdersDb",
        "schema": "dbo",
        "tables": [
            {
                "name": "Customer",
                "columns": [{"name": "CustomerCode"}, {"name": "Name"}],
                "primary_keys": ["CustomerCode"],
            },
            {
                "name": "Order",
                "columns": [{"name": "OrderId"}, {"name": "CustomerCode"}],
                "primary_keys": ["OrderId"],
            },
        ],
    }


def test_no_sql_cache_returns_empty_and_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fk_resolver, "load_cached", lambda *a, **k: None)

    result = fk_resolver.resolve_fk_related(["Customer"], database_alias="OrdersDb")

    assert result == []


def test_no_database_alias_returns_empty_and_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fk_resolver, "load_cached", lambda *a, **k: _cache_with_pk_naming_relation())

    result = fk_resolver.resolve_fk_related(["Customer"], database_alias=None)

    assert result == []


def test_sql_cache_still_drives_pk_naming_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fk_resolver, "load_cached", lambda *a, **k: _cache_with_pk_naming_relation())

    result = fk_resolver.resolve_fk_related(["Customer"], database_alias="OrdersDb", depth=1)

    assert result == ["Order"]


def test_no_code_queries_sys_foreign_keys() -> None:
    """Regression guard for the ticket's explicit acceptance criterion."""
    hits = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if "/.git/" in str(path) or "/__pycache__/" in str(path):
            continue
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "FROM sys.foreign_keys" in text or "from sys.foreign_keys" in text.lower():
            hits.append(str(path.relative_to(PROJECT_ROOT)))

    assert hits == []

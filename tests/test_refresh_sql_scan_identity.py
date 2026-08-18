"""Ticket 05 behavior checks: the scan tool's connecting identity (ADR-0010).

`refresh_sql` connects with the global `DB_AUTH_MODE` identity by default. One
`(server, database)` target may carry an explicit credential override, supplied
by the caller (spec-rag's `SQLServerData.json`, one pair per server) and used
only when both a user id and a password are present. Credentials are never read
from or derived from a scanned application's Web.config.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from service import analyze_service, api, sql_cache_store
from service.schemas import RefreshSqlRequest

_TARGET = {
    "alias": "vmsystest07.topmost.com.tw__SysErrorRecord__dbo",
    "server": "vmsystest07.topmost.com.tw",
    "database_name": "SysErrorRecord",
}


def test_the_scan_uses_the_global_identity_by_default() -> None:
    config = settings.build_database_config(**_TARGET)

    assert config.auth_mode == settings.DB_AUTH_MODE
    assert config.user_id == settings.DB_USER_ID
    assert config.password == settings.DB_PASSWORD


def test_a_complete_credential_pair_overrides_the_global_identity() -> None:
    config = settings.build_database_config(**_TARGET, user_id="ScanUser", password="secret")

    assert config.auth_mode == "sql"
    assert config.user_id == "ScanUser"
    assert config.password == "secret"


def test_a_half_filled_override_falls_back_to_the_global_identity() -> None:
    """Only one of the two supplied is treated as "not supplied" — never a
    half-built SQL login that would fail in a confusing way at connect time."""
    for user_id, password in (("ScanUser", ""), ("", "secret"), ("ScanUser", None)):
        config = settings.build_database_config(**_TARGET, user_id=user_id, password=password)

        assert config.auth_mode == settings.DB_AUTH_MODE
        assert config.user_id == settings.DB_USER_ID


def test_get_or_dump_hands_the_override_to_the_analyzer(monkeypatch) -> None:
    seen: dict = {}

    class _FakeAnalyzer:
        def __init__(self, database_alias=None, server=None, database_name=None, **kwargs):
            seen.update(kwargs)

        def connect(self) -> bool:
            return False

    import code_analyzer.sql_analyzer as sql_analyzer_module

    monkeypatch.setattr(sql_analyzer_module, "SQLAnalyzer", _FakeAnalyzer)

    try:
        sql_cache_store.get_or_dump(
            "SysErrorRecord",
            refresh=True,
            server="vmsystest07.topmost.com.tw",
            db_name="SysErrorRecord",
            user_id="ScanUser",
            password="secret",
        )
    except RuntimeError:
        pass  # _FakeAnalyzer.connect() returns False; the call under test already happened.

    assert seen == {"user_id": "ScanUser", "password": "secret"}


def test_the_refresh_sql_route_forwards_the_override(monkeypatch) -> None:
    seen: dict = {}

    def _fake_refresh(database, server, db_name, schema, **kwargs):
        seen.update(kwargs)
        return {"database": database, "db_schema": schema}

    monkeypatch.setattr(analyze_service, "refresh_sql_source", _fake_refresh)

    api.refresh_sql(
        RefreshSqlRequest(
            database="vmsystest07.topmost.com.tw__SysErrorRecord__dbo",
            server="vmsystest07.topmost.com.tw",
            db_name="SysErrorRecord",
            db_user_id="ScanUser",
            db_password="secret",
        )
    )

    assert seen["user_id"] == "ScanUser"
    assert seen["password"] == "secret"


def test_the_refresh_sql_route_sends_no_credentials_by_default(monkeypatch) -> None:
    seen: dict = {}

    def _fake_refresh(database, server, db_name, schema, **kwargs):
        seen.update(kwargs)
        return {"database": database, "db_schema": schema}

    monkeypatch.setattr(analyze_service, "refresh_sql_source", _fake_refresh)

    api.refresh_sql(
        RefreshSqlRequest(
            database="vmsystest07.topmost.com.tw__SysErrorRecord__dbo",
            server="vmsystest07.topmost.com.tw",
            db_name="SysErrorRecord",
        )
    )

    assert seen["user_id"] == ""
    assert seen["password"] == ""

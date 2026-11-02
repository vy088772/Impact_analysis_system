"""Ticket 01 of `.scratch/sql-cache-behind-source/`: each SQL scan records a Fingerprint.

The seam is the Impact HTTP API (`POST /refresh_sql`, `GET /cache_freshness`), through the
FastAPI test client. A fake reader replaces the one Fingerprint reader, and a fake analyzer
replaces the SQL connection of the scan.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import pytest

import code_analyzer.sql_analyzer as sql_analyzer_module
from code_analyzer.sql_fingerprint import Fingerprint
from service import sql_cache_store
from service.sql_cache_store import CacheIdentity, ScanConnection
from tests.sql_cache_fixtures import CACHE_VERSION, cache_payload, fingerprint
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    SERVER,
    client,
    fresh_queue,
    listing,
    sql_root,
    submit_sql,
    wait_for,
    world,
    write_sql,
)


def with_procedures(count: int, latest_modified: datetime = datetime(2026, 10, 1, 9, 0, 0)) -> Fingerprint:
    return fingerprint(procedures=(count, latest_modified))


class FakeReader:
    """Stands in for the one Fingerprint reader. A scan's dump may change what it returns next."""

    def __init__(self) -> None:
        self.current: Optional[Fingerprint] = None
        self.calls: list[tuple[CacheIdentity, ScanConnection]] = []

    def __call__(self, identity: CacheIdentity, connection: ScanConnection) -> Fingerprint:
        self.calls.append((identity, connection))
        if self.current is None:
            raise sql_cache_store.FingerprintUnreadable("資料庫沒有回應")
        return self.current


@pytest.fixture
def reader(monkeypatch):
    fake = FakeReader()
    monkeypatch.setattr(sql_cache_store, "read_fingerprint", fake)
    return fake


@pytest.fixture
def analyzer(monkeypatch, reader):
    """A fake SQL connection for the scan. Its dump changes the Database under the reader."""

    class FakeAnalyzer:
        def __init__(self, database_alias=None, server=None, database_name=None, **_kwargs):
            self.database = database_name

        def connect(self) -> bool:
            return True

        def disconnect(self) -> None:
            pass

        def dump_all_sql_objects(self, progress_callback=None) -> dict:
            # Someone changes a procedure while the scan reads the definitions.
            reader.current = with_procedures(99, datetime(2026, 10, 30, 23, 59, 59))
            return cache_payload(self.database)

    monkeypatch.setattr(sql_analyzer_module, "SQLAnalyzer", FakeAnalyzer)
    return FakeAnalyzer


def scan_record(sql_root, database: str) -> dict:
    meta = sql_root / CacheIdentity.of(SERVER, database).meta_filename
    return json.loads(meta.read_text(encoding="utf-8"))


def test_the_scan_writes_the_fingerprint_that_the_reader_returned_at_the_start(
    world, sql_root, reader, analyzer
) -> None:
    reader.current = with_procedures(3)

    wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")

    record = scan_record(sql_root, "AlphaDb")
    # The committed sample cache pins the JSON form of a Fingerprint.
    assert record["fingerprint"] == with_procedures(3).to_dict()
    assert record["saved_at"]
    assert listing()["Alpha"]["AlphaDb"]["freshness"] == "current"


def test_the_scan_record_keeps_its_other_fields(world, sql_root, reader, analyzer) -> None:
    reader.current = with_procedures(3)

    wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")

    record = scan_record(sql_root, "AlphaDb")
    assert set(record) == {"cache_version", "server", "database", "saved_at", "fingerprint"}
    assert record["server"] == SERVER
    assert record["database"] == "AlphaDb"
    assert record["cache_version"] == CACHE_VERSION


def test_the_scan_passes_its_address_and_account_override_to_the_reader(
    world, sql_root, reader, analyzer
) -> None:
    response = client.post(
        "/refresh_sql",
        json={
            "database": "AlphaDb",
            "server": "dbhost\\NAMED",
            "db_name": "AlphaDb",
            "db_user_id": "ScanUser",
            "db_password": "secret",
        },
    )
    wait_for(response.json()["job_id"], "succeeded")

    assert reader.calls == [
        (CacheIdentity.of("dbhost", "AlphaDb"), ScanConnection("dbhost\\NAMED", "ScanUser", "secret"))
    ]


def test_a_scan_whose_reader_finds_no_fingerprint_records_null(world, sql_root, reader, analyzer) -> None:
    reader.current = None

    wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")

    assert scan_record(sql_root, "AlphaDb")["fingerprint"] is None


def test_a_cache_of_the_previous_format_version_lists_as_outdated(world, sql_root) -> None:
    write_sql(sql_root, "AlphaDb", cache_version=CACHE_VERSION - 1)

    row = listing()["Alpha"]["AlphaDb"]

    assert row["freshness"] == "outdated"
    assert row["last_scanned_at"]


# The one reader, over a fake analyzer: a short reason when it cannot connect or the query fails.


class FakeServer:
    """The SQL Server behind the reader: whether it connects, whether the query fails, and what it saw."""

    def __init__(self) -> None:
        self.connects = True
        self.connect_error: Optional[Exception] = None
        self.fails = False
        self.seen: dict = {}
        self.disconnected = False

    def analyzer(self, database_alias=None, server=None, database_name=None, **kwargs) -> "FakeServer":
        self.seen = {"server": server, "database_name": database_name, **kwargs}
        return self

    def connect(self) -> bool:
        return self.connects

    def disconnect(self) -> None:
        self.disconnected = True

    def read_fingerprint(self) -> Fingerprint:
        if self.fails:
            raise RuntimeError("query failed")
        return with_procedures(1)


@pytest.fixture
def sql_server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(sql_analyzer_module, "SQLAnalyzer", fake.analyzer)
    return fake


def test_the_reader_returns_the_fingerprint_of_the_identity(sql_server) -> None:
    identity = CacheIdentity.of(SERVER, "AlphaDb")

    read = sql_cache_store.read_fingerprint(identity, ScanConnection(SERVER, "ScanUser", "secret"))

    assert read == with_procedures(1)
    assert sql_server.seen == {
        "server": SERVER,
        "database_name": "AlphaDb",
        "user_id": "ScanUser",
        "password": "secret",
    }
    assert sql_server.disconnected


def test_the_reader_connects_to_the_address_of_the_connection(sql_server) -> None:
    identity = CacheIdentity.of("dbhost\\NAMED", "AlphaDb")

    sql_cache_store.read_fingerprint(identity, ScanConnection("dbhost\\NAMED"))

    assert sql_server.seen["server"] == "dbhost\\NAMED"
    assert sql_server.seen["user_id"] == ""


def unreadable_reason(connection: ScanConnection = ScanConnection(SERVER)) -> str:
    with pytest.raises(sql_cache_store.FingerprintUnreadable) as failure:
        sql_cache_store.read_fingerprint(CacheIdentity.of(SERVER, "AlphaDb"), connection)
    return str(failure.value)


def odbc_error(state: str, message: str) -> Exception:
    """A pyodbc error, as the driver raises it: its first argument is the SQLSTATE."""
    pyodbc = pytest.importorskip("pyodbc")
    return pyodbc.Error(state, message)


def test_a_reader_that_cannot_connect_gives_the_reason(sql_server) -> None:
    sql_server.connects = False
    sql_server.connect_error = odbc_error("28000", "Login failed for user 'ScanUser'.")

    assert unreadable_reason() == "SQL Server 拒絕這個登入帳號"


def test_a_reader_whose_login_times_out_gives_the_reason(sql_server) -> None:
    sql_server.connects = False
    sql_server.connect_error = odbc_error("HYT00", "Login timeout expired")

    assert "沒有回應" in unreadable_reason()


def test_a_reader_that_cannot_connect_for_no_known_cause_still_gives_a_reason(sql_server) -> None:
    sql_server.connects = False

    assert unreadable_reason()


def test_a_reader_whose_query_fails_gives_the_reason_and_disconnects(sql_server) -> None:
    sql_server.fails = True

    assert "query failed" in unreadable_reason()
    assert sql_server.disconnected


def test_a_reason_never_holds_the_password(sql_server) -> None:
    sql_server.connects = False
    sql_server.connect_error = RuntimeError("bad connection string PWD=secret;")

    assert "secret" not in unreadable_reason(ScanConnection(SERVER, "ScanUser", "secret"))


def test_a_reason_is_one_short_line(sql_server) -> None:
    sql_server.connects = False
    sql_server.connect_error = RuntimeError("driver said " + "x" * 500 + "\nand a second line")

    reason = unreadable_reason()

    assert "\n" not in reason
    assert len(reason) <= 160

"""Impact#14: the SQL scan and the Fingerprint read fall back to the `ip` of the Database Registry.

The seam is the Impact HTTP API (`POST /refresh_sql`, `POST /refresh_jobs/update_all`,
`POST /cache_freshness/check`), through the FastAPI test client. A fake `pyodbc.connect` fails for
some connection addresses and works for the others. The real `SQLAnalyzer` connects; only its
dump and its Fingerprint query are fakes, because they need a real SQL Server. The addresses are
documentation addresses (RFC 5737).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import pytest

from code_analyzer.sql_analyzer import SQLAnalyzer
from code_analyzer.sql_fingerprint import Fingerprint
from service import analyze_service, source_check, sql_cache_store, system_targets
from service.sql_cache_store import CacheIdentity
from tests.sql_cache_fixtures import CACHE_VERSION, cache_payload, fingerprint
from tests.test_behind_source_api import check, remote, row_of  # noqa: F401  (fixtures and helpers)
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

pyodbc = pytest.importorskip("pyodbc")

IP = "192.0.2.10"
MORNING = datetime(2026, 10, 1, 9, 0, 0)
EVENING = datetime(2026, 10, 30, 18, 0, 0)
BOTH_REASONS = "主機名稱：連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）；IP：SQL Server 拒絕這個登入帳號"

# The real reader: the `remote` fixture replaces it, and these tests put it back.
_REAL_READ_FINGERPRINT = sql_cache_store.read_fingerprint


def procedures(count: int, latest_modified: datetime = MORNING) -> Fingerprint:
    return fingerprint(procedures=(count, latest_modified))


class FakeConnect:
    """Stands in for `pyodbc.connect`: it fails for the addresses in `failing`, else it connects."""

    def __init__(self) -> None:
        self.failing: dict[str, str] = {}
        self.connection_strings: list[str] = []

    def __call__(self, connection_string: str, **_kwargs):
        self.connection_strings.append(connection_string)
        failure = self.failing.get(address_of(connection_string))
        if failure is not None:
            raise pyodbc.Error(failure, f"[{failure}] login failed")
        return FakeConnection()

    @property
    def addresses(self) -> list[str]:
        """The address of each connection, in order."""
        return [address_of(text) for text in self.connection_strings]


def address_of(connection_string: str) -> str:
    match = re.search(r"Server=([^;,]*)", connection_string)
    assert match is not None, connection_string
    return match.group(1)


class FakeCursor:
    def execute(self, *_args) -> None:
        pass

    def fetchone(self):
        return ("AlphaDb", "scan")

    def close(self) -> None:
        pass


class FakeConnection:
    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def close(self) -> None:
        pass


class Database:
    """What the SQL Server answers once a connection works: its Fingerprint and its definitions."""

    def __init__(self) -> None:
        self.fingerprint = procedures(3)


@pytest.fixture
def database(monkeypatch, remote):
    fake = Database()
    monkeypatch.setattr(sql_cache_store, "read_fingerprint", _REAL_READ_FINGERPRINT)
    monkeypatch.setattr(SQLAnalyzer, "read_fingerprint", lambda self: fake.fingerprint)
    monkeypatch.setattr(
        SQLAnalyzer, "dump_all_sql_objects",
        lambda self, progress_callback=None: cache_payload(self.db_config.database_name),
    )
    return fake


@pytest.fixture
def connect(monkeypatch, database):
    fake = FakeConnect()
    monkeypatch.setattr(pyodbc, "connect", fake)
    return fake


def write_registry(*servers: dict) -> None:
    path = system_targets.default_spec_rag_root() / "catalog" / "SQLServerData.json"
    path.write_text(json.dumps({"servers": list(servers)}), encoding="utf-8")


def with_ip(ip: str = IP) -> dict:
    return {"server": SERVER, "ip": ip, "databases": ["AlphaDb"]}


def scan_record(sql_root, database: str) -> dict:
    meta = sql_root / CacheIdentity.of(SERVER, database).meta_filename
    return json.loads(meta.read_text(encoding="utf-8"))


# Refresh Job


def test_a_refresh_job_whose_server_name_fails_and_whose_ip_works_saves_the_cache_of_the_server_name(
    world, sql_root, connect
) -> None:
    write_registry(with_ip())
    connect.failing = {SERVER: "08001"}

    job = wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")

    record = scan_record(sql_root, "AlphaDb")
    assert record["server"] == SERVER
    assert record["fingerprint"] == procedures(3).to_dict()
    assert IP in connect.addresses
    assert IP not in json.dumps(job)
    row = listing()["Alpha"]["AlphaDb"]
    assert row["freshness"] == "current"
    assert row["server"] == SERVER


# Fingerprint read


def test_a_fingerprint_read_whose_server_name_fails_and_whose_ip_works_gives_the_freshness_of_the_fingerprint(
    world, sql_root, connect, database
) -> None:
    write_registry(with_ip())
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    database.fingerprint = procedures(4, EVENING)
    connect.failing = {SERVER: "08001"}

    row = row_of(check(), "Alpha", "AlphaDb")

    assert row["freshness"] == "behind_source"
    assert row["server"] == SERVER
    assert connect.addresses == [SERVER, IP]


def test_when_both_addresses_fail_the_fingerprint_read_failure_holds_both_reasons(
    world, sql_root, connect
) -> None:
    write_registry(with_ip())
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    connect.failing = {SERVER: "08001", IP: "28000"}

    row = row_of(check(), "Alpha", "AlphaDb")

    assert row["freshness"] == "current"
    assert row["source_check_failure"] == BOTH_REASONS


# Both fail, no ip, and a working server name


def test_when_both_addresses_fail_the_refresh_job_fails_with_both_reasons(world, sql_root, connect) -> None:
    write_registry(with_ip())
    connect.failing = {SERVER: "08001", IP: "28000"}

    job = wait_for(submit_sql("AlphaDb")["job_id"], "failed")

    assert job["error"] == f"無法連線資料庫：AlphaDb：{BOTH_REASONS}"


def test_with_no_ip_the_refresh_job_connects_by_the_server_name_only(world, sql_root, connect) -> None:
    write_registry({"server": SERVER, "databases": ["AlphaDb"]})
    connect.failing = {SERVER: "08001"}

    job = wait_for(submit_sql("AlphaDb")["job_id"], "failed")

    assert set(connect.addresses) == {SERVER}
    assert job["error"] == "無法連線資料庫：AlphaDb：連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）"


def test_with_no_ip_the_fingerprint_read_connects_by_the_server_name_only(world, sql_root, connect) -> None:
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    connect.failing = {SERVER: "08001"}

    row = row_of(check(), "Alpha", "AlphaDb")

    assert connect.addresses == [SERVER]
    assert row["source_check_failure"] == "連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）"


def test_a_working_server_name_never_uses_the_ip(world, sql_root, connect, database) -> None:
    write_registry(with_ip())
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    database.fingerprint = procedures(4, EVENING)

    assert row_of(check(), "Alpha", "AlphaDb")["freshness"] == "behind_source"
    wait_for(submit_sql("AlphaDb")["job_id"], "succeeded")

    assert connect.addresses and set(connect.addresses) == {SERVER}


# The log line, the named instance and the scan account override


def test_a_working_ip_after_a_failed_server_name_writes_one_log_line_per_connection(
    world, sql_root, connect, caplog
) -> None:
    write_registry(with_ip())
    write_sql(sql_root, "AlphaDb", fingerprint=procedures(3))
    connect.failing = {SERVER: "08001"}

    with caplog.at_level(logging.WARNING, logger="config.settings"):
        check()

    lines = [record.getMessage() for record in caplog.records if record.name == "config.settings"]
    assert len(lines) == 1
    assert SERVER in lines[0] and IP in lines[0]


def test_the_ip_keeps_the_named_instance_of_the_server(world, sql_root, connect) -> None:
    write_registry(with_ip())
    connect.failing = {f"{SERVER}\\NAMED": "08001"}

    response = client.post(
        "/refresh_sql", json={"database": "AlphaDb", "server": f"{SERVER}\\NAMED", "db_name": "AlphaDb"}
    )
    wait_for(response.json()["job_id"], "succeeded")

    assert f"{IP}\\NAMED" in connect.addresses
    assert scan_record(sql_root, "AlphaDb")["server"] == SERVER


def test_the_scan_account_override_applies_to_both_addresses(world, sql_root, connect) -> None:
    write_registry(with_ip())
    connect.failing = {SERVER: "08001"}

    response = client.post(
        "/refresh_sql",
        json={
            "database": "AlphaDb", "server": SERVER, "db_name": "AlphaDb",
            "db_user_id": "ScanUser", "db_password": "secret",
        },
    )
    wait_for(response.json()["job_id"], "succeeded")

    assert {address_of(text) for text in connect.connection_strings} == {SERVER, IP}
    assert all("UID=ScanUser;PWD=secret;" in text for text in connect.connection_strings)


# Update all


def test_update_all_scans_each_outdated_sql_cache_by_the_ip_when_the_server_name_fails(
    world, sql_root, connect, monkeypatch
) -> None:
    monkeypatch.setattr(analyze_service, "refresh_source", lambda source, **kwargs: {})
    write_registry({"server": SERVER, "ip": IP, "databases": ["AlphaDb", "SharedDb"]})
    write_sql(sql_root, "AlphaDb", cache_version=CACHE_VERSION - 1)
    write_sql(sql_root, "SharedDb", cache_version=CACHE_VERSION - 1)
    connect.failing = {SERVER: "08001"}

    response = client.post("/refresh_jobs/update_all", json={})
    assert response.status_code == 200, response.text
    sql_jobs = [job for job in response.json()["jobs"] if job["kind"] == "sql"]
    for job in sql_jobs:
        wait_for(job["job_id"], "succeeded")

    assert sorted(job["database"] for job in sql_jobs) == sorted(
        [CacheIdentity.of(SERVER, "AlphaDb").key, CacheIdentity.of(SERVER, "SharedDb").key]
    )
    rows = listing()["Alpha"]
    assert rows["AlphaDb"]["freshness"] == "current"
    assert rows["SharedDb"]["freshness"] == "current"
    assert IP in connect.addresses

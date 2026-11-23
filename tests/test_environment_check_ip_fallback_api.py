"""Impact#13: the Environment Check falls back to the `ip` of the Database Registry.

The seam is the Impact HTTP API (`POST /environment/check`), through the FastAPI test client. A
fake `pyodbc.connect` fails for some connection addresses and works for the others. A fake git
probe replaces `git ls-remote`. The addresses are documentation addresses (RFC 5737).
"""

from __future__ import annotations

import json
import logging
import re
import threading

import pytest

from config.settings import settings
from service import environment_check, system_targets
from tests.test_environment_check_api import (  # noqa: F401  (fixtures and helpers)
    SERVER_A,
    SERVER_B,
    check,
    items_of,
    lock_listing,
    two_hosts,
)
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    client,
    fresh_queue,
    sql_root,
    world,
)

pyodbc = pytest.importorskip("pyodbc")

IP_A = "192.0.2.10"
IP_B = "192.0.2.20"


class FakeConnect:
    """Stands in for `pyodbc.connect`: it fails for the addresses in `failing`, else it connects.

    A failure is a SQLSTATE (a pyodbc error) or an exception. A login to an address in `delays`
    takes that many seconds first."""

    def __init__(self) -> None:
        self.failing: dict[str, str | Exception] = {}
        self.delays: dict[str, float] = {}
        self.addresses: list[str] = []
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, connection_string: str, **_kwargs):
        match = re.search(r"Server=([^;,]*)", connection_string)
        assert match is not None, connection_string
        address = match.group(1)
        with self._lock:
            self.addresses.append(address)
        self.release.wait(self.delays.get(address, 0))
        failure = self.failing.get(address)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            raise pyodbc.Error(failure, f"[{failure}] login failed")
        return FakeConnection()

    def tried(self, *addresses: str) -> list[str]:
        """The addresses of `addresses` that the check tried, in order."""
        return [address for address in self.addresses if address in addresses]


class FakeConnection:
    def close(self) -> None:
        pass


@pytest.fixture
def connect(monkeypatch):
    fake = FakeConnect()
    monkeypatch.setattr(pyodbc, "connect", fake)
    monkeypatch.setattr(environment_check, "probe_azure_repos", lambda source: None)
    monkeypatch.setattr(environment_check, "_last", environment_check.LastCheck())
    monkeypatch.setattr(settings, "AZURE_DEVOPS_ORG", "org")
    yield fake
    fake.release.set()


def write_registry(*servers: dict) -> None:
    path = system_targets.default_spec_rag_root() / "catalog" / "SQLServerData.json"
    path.write_text(json.dumps({"servers": list(servers)}), encoding="utf-8")


def test_a_server_whose_name_fails_and_whose_ip_works_passes_and_its_rows_have_no_lock_reason(
    two_hosts, connect
) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})
    connect.failing = {SERVER_A: "08001"}

    servers = items_of(check(), "sql_server")

    assert servers[SERVER_A] == {**servers[SERVER_A], "ok": True, "reason": "", "locks": ""}
    assert connect.tried(SERVER_A, IP_A) == [SERVER_A, IP_A]
    assert lock_listing()["Alpha"]["AlphaDb"] == ""
    assert lock_listing()["Beta"]["BetaDb"] == ""


def test_when_the_server_name_and_the_ip_both_fail_the_reason_holds_both_reasons(two_hosts, connect) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})
    connect.failing = {SERVER_A: "08001", IP_A: "28000"}

    servers = items_of(check(), "sql_server")

    reason = "主機名稱：連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）；IP：SQL Server 拒絕這個登入帳號"
    assert servers[SERVER_A] == {**servers[SERVER_A], "ok": False, "reason": reason, "locks": f"{SERVER_A} 的 SQL 列"}
    assert lock_listing()["Alpha"]["AlphaDb"] == reason


def test_when_both_long_reasons_fail_the_reason_stays_one_short_line_with_both_parts(two_hosts, connect) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})
    connect.failing = {SERVER_A: RuntimeError("名稱" * 200), IP_A: RuntimeError("位址" * 200)}

    reason = items_of(check(), "sql_server")[SERVER_A]["reason"]

    assert len(reason) <= 160
    assert reason.startswith("主機名稱：SQL Server 連線失敗：名稱")
    assert "；IP：SQL Server 連線失敗：位址" in reason


def test_the_ip_connection_keeps_the_named_instance_of_the_server(two_hosts, connect) -> None:
    named = "dbc.example.com\\SQL2019"
    write_registry({"server": named, "ip": "192.0.2.30", "databases": ["Archive"]})
    connect.failing = {named: "08001"}

    servers = items_of(check(), "sql_server")

    assert servers["dbc.example.com"]["ok"] is True
    assert connect.tried(named, "192.0.2.30\\SQL2019") == [named, "192.0.2.30\\SQL2019"]


def test_a_server_with_no_ip_or_an_empty_ip_logs_in_one_time_and_gives_the_reason_of_today(
    two_hosts, connect
) -> None:
    write_registry(
        {"server": SERVER_A, "ip": "", "databases": ["AlphaDb"]},
        {"server": SERVER_B, "databases": ["SharedDb"]},
    )
    connect.failing = {SERVER_A: "08001", SERVER_B: "28000"}

    servers = items_of(check(), "sql_server")

    assert connect.tried(SERVER_A) == [SERVER_A]
    assert connect.tried(SERVER_B) == [SERVER_B]
    assert servers[SERVER_A]["reason"] == "連不到 SQL Server（主機名稱錯誤、網路不通，或伺服器沒有回應）"
    assert servers[SERVER_B]["reason"] == "SQL Server 拒絕這個登入帳號"


def test_when_the_server_name_works_the_check_does_not_use_the_ip(two_hosts, connect) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})

    servers = items_of(check(), "sql_server")

    assert set(servers) == {SERVER_A, SERVER_B}
    assert servers[SERVER_A]["ok"] is True
    assert IP_A not in connect.addresses


def test_a_registry_server_that_names_the_host_in_another_form_gives_its_ip_to_that_host(
    two_hosts, connect
) -> None:
    # The catalog names SERVER_B; the Registry names the same host in capital letters.
    write_registry({"server": SERVER_B.upper(), "ip": IP_B, "databases": ["SharedDb"]})
    connect.failing = {SERVER_B.upper(): "08001"}

    servers = items_of(check(), "sql_server")

    assert set(servers) == {SERVER_A, SERVER_B}
    assert servers[SERVER_B]["ok"] is True
    assert connect.tried(SERVER_B.upper(), IP_B) == [SERVER_B.upper(), IP_B]


def test_a_server_with_an_ip_gets_two_login_limits_plus_the_margin_and_a_server_without_one_gets_one(
    two_hosts, connect, monkeypatch
) -> None:
    # Login limit 0.5 s and margin 0.3 s: 1.3 s with an `ip` and 0.8 s without (13 s and 8 s in production).
    monkeypatch.setattr(environment_check, "SQL_LOGIN_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(environment_check, "_MARGIN_SECONDS", 0.3)
    server_c = "dbc.example.com"
    write_registry(
        {"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]},
        {"server": server_c, "ip": "192.0.2.30", "databases": ["Archive"]},
    )
    # SERVER_A: the server name fails after 0.45 s and the ip works after 0.45 s, 0.9 s in all.
    connect.failing = {SERVER_A: "HYT00"}
    connect.delays = {SERVER_A: 0.45, IP_A: 0.45, SERVER_B: 1.05, server_c: 5, "192.0.2.30": 5}

    servers = items_of(check(), "sql_server")

    assert servers[SERVER_A]["ok"] is True
    # SERVER_B has no ip: its login of 1.05 s runs past its 0.8 s.
    assert servers[SERVER_B]["reason"] == "SQL Server 在 0.5 秒內沒有回應"
    # A server with an ip that gives no answer: the limit of its probe is two logins.
    assert servers[server_c]["reason"] == "SQL Server 在 1 秒內沒有回應"


def warnings_of_server_a(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING and SERVER_A in record.getMessage()
    ]


def test_the_service_writes_one_log_line_when_the_ip_works_after_the_server_name_failed(
    two_hosts, connect, caplog
) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})
    connect.failing = {SERVER_A: "08001"}

    with caplog.at_level(logging.INFO):
        check()

    lines = warnings_of_server_a(caplog)
    assert len(lines) == 1
    assert IP_A in lines[0]


def test_the_service_writes_no_log_line_of_the_ip_when_the_server_name_works_or_both_fail(
    two_hosts, connect, caplog
) -> None:
    write_registry({"server": SERVER_A, "ip": IP_A, "databases": ["AlphaDb"]})

    with caplog.at_level(logging.INFO):
        check()
        connect.failing = {SERVER_A: "08001", IP_A: "08001"}
        check()

    assert warnings_of_server_a(caplog) == []

"""Ticket 03 of `llamaindex-spec-rag/.scratch/spec-update-web/`: the Environment Check endpoint.

The seam is the Impact HTTP API, through the FastAPI test client (Seam S3). A fake SQL probe
replaces the SQL Server login and a fake git probe replaces `git ls-remote`.
"""

from __future__ import annotations

import json
import threading
from typing import Optional

import pytest

from config.settings import settings
from service import analyze_service, environment_check, system_targets
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    build_scan,
    client,
    fresh_queue,
    scan_root,
    sql_root,
    wait_for,
    world,
)

SERVER_A = "dba.example.com"
SERVER_B = "dbb.example.com"


class FakeProbes:
    """Failures by server and by repository; everything else passes."""

    def __init__(self) -> None:
        self.sql_failures: dict[str, str] = {}
        self.git_failures: dict[str, str] = {}
        self.sql_calls: list[tuple[str, str, str, str]] = []
        self.git_calls: list[str] = []
        self.blocked_servers: set[str] = set()
        self.release = threading.Event()
        self.git_running = 0
        self.git_most_at_once = 0
        self._git_lock = threading.Lock()

    def sql(self, server: str, database: str, user_id: str, password: str) -> Optional[str]:
        self.sql_calls.append((server, database, user_id, password))
        if server in self.blocked_servers:
            self.release.wait(timeout=5)
        return self.sql_failures.get(server)

    def git(self, source: dict) -> Optional[str]:
        with self._git_lock:
            self.git_calls.append(source["repo"])
            self.git_running += 1
            self.git_most_at_once = max(self.git_most_at_once, self.git_running)
        threading.Event().wait(0.02)
        with self._git_lock:
            self.git_running -= 1
        return self.git_failures.get(source["repo"])


@pytest.fixture
def probes(monkeypatch):
    fake = FakeProbes()
    monkeypatch.setattr(environment_check, "probe_sql_server", fake.sql)
    monkeypatch.setattr(environment_check, "probe_azure_repos", fake.git)
    monkeypatch.setattr(environment_check, "_last", environment_check.LastCheck())
    monkeypatch.setattr(settings, "AZURE_DEVOPS_ORG", "org")
    yield fake
    fake.release.set()


@pytest.fixture
def two_hosts(world):
    """Two SQL servers, and three repositories in two Azure DevOps projects. Delta shares AlphaRepo."""
    catalog = {
        "systems": [
            {
                "system_id": "Alpha",
                "azure": {"project": "P", "repo": "AlphaRepo", "branch": "", "path": ""},
                "databases": [
                    {"name": "AlphaDb", "server": SERVER_A},
                    {"name": "SharedDb", "server": SERVER_B},
                ],
            },
            {
                "system_id": "Beta",
                "azure": {"project": "P", "repo": "BetaRepo", "branch": "", "path": ""},
                "databases": [{"name": "BetaDb", "server": SERVER_A}],
            },
            {
                "system_id": "Gamma",
                "azure": {"project": "Q", "repo": "GammaRepo", "branch": "", "path": ""},
                "databases": [{"name": "SharedDb", "server": SERVER_B}],
            },
            {
                "system_id": "Delta",
                "azure": {"project": "P", "repo": "AlphaRepo", "branch": "", "path": "Delta"},
                "databases": [],
            },
            {"system_id": "NoCode", "azure": {"project": "", "repo": ""}, "databases": []},
        ]
    }
    catalog_path = system_targets.default_spec_rag_root() / "catalog" / "system_catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    return world


def test_each_server_of_the_database_registry_is_tested_even_when_no_system_declares_it(
    two_hosts, probes
) -> None:
    registry = {
        "servers": [
            {"server": "dbc.example.com\\SQL2019", "uid_env": "", "pwd_env": "", "databases": ["Archive", "Log"]},
            {"server": SERVER_A.upper(), "uid_env": "", "pwd_env": "", "databases": ["RegistryDb"]},
        ]
    }
    registry_path = system_targets.default_spec_rag_root() / "catalog" / "SQLServerData.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    servers = items_of(check(), "sql_server")

    assert set(servers) == {"dbc.example.com", SERVER_A, SERVER_B}
    # It logs in with the named instance, into the first database of the Registry.
    logins = {call[0]: call[1] for call in probes.sql_calls}
    assert logins["dbc.example.com\\SQL2019"] == "Archive"
    assert logins[SERVER_A.upper()] == "RegistryDb"


def check(**body) -> dict:
    response = client.post("/environment/check", json=body)
    assert response.status_code == 200
    return response.json()


def items_of(result: dict, capability: str) -> dict[str, dict]:
    return {item["target"]: item for item in result["capabilities"] if item["capability"] == capability}


def test_the_check_gives_one_item_for_each_server_and_each_repository(two_hosts, probes) -> None:
    result = check()

    assert result["checked_at"]
    servers = items_of(result, "sql_server")
    repositories = items_of(result, "azure_repos")
    assert set(servers) == {SERVER_A, SERVER_B}
    assert set(repositories) == {"P/AlphaRepo", "P/BetaRepo", "Q/GammaRepo"}
    for item in [*servers.values(), *repositories.values()]:
        assert item == {**item, "ok": True, "reason": "", "locks": ""}
    # One git ls-remote for each repository, also when two systems share it.
    assert sorted(probes.git_calls) == ["AlphaRepo", "BetaRepo", "GammaRepo"]
    assert sorted(call[0] for call in probes.sql_calls) == [SERVER_A, SERVER_B]


def test_a_server_that_does_not_answer_in_the_time_limit_fails_and_the_other_server_keeps_its_result(
    two_hosts, probes, monkeypatch
) -> None:
    monkeypatch.setattr(environment_check, "SQL_LOGIN_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(environment_check, "_MARGIN_SECONDS", 0.1)
    probes.blocked_servers = {SERVER_A}

    servers = items_of(check(), "sql_server")

    assert servers[SERVER_A]["ok"] is False
    assert servers[SERVER_A]["reason"] == "SQL Server 在 0.1 秒內沒有回應"
    assert servers[SERVER_A]["locks"] == f"{SERVER_A} 的 SQL 列"
    assert servers[SERVER_B]["ok"] is True


def test_a_repository_whose_ls_remote_fails_fails_and_the_other_repositories_keep_their_result(
    two_hosts, probes
) -> None:
    probes.git_failures = {"AlphaRepo": "git ls-remote 失敗：repository not found"}

    repositories = items_of(check(), "azure_repos")

    assert repositories["P/AlphaRepo"]["ok"] is False
    assert repositories["P/AlphaRepo"]["reason"] == "git ls-remote 失敗：repository not found"
    assert repositories["P/AlphaRepo"]["locks"] == "P/AlphaRepo 的 C# 列"
    # BetaRepo is in the same project, and keeps its own result.
    assert repositories["P/BetaRepo"]["ok"] is True
    assert repositories["Q/GammaRepo"]["ok"] is True


def test_the_check_runs_at_most_a_few_git_ls_remote_at_one_time(two_hosts, probes, monkeypatch) -> None:
    monkeypatch.setattr(environment_check, "GIT_AT_ONCE", 2)

    repositories = items_of(check(), "azure_repos")

    assert all(item["ok"] for item in repositories.values())
    assert probes.git_most_at_once == 2


def lock_listing() -> dict[str, dict[str, str]]:
    response = client.get("/cache_freshness")
    assert response.status_code == 200
    return {
        system["system_id"]: {row["label"]: row["locked_reason"] for row in system["caches"]}
        for system in response.json()["systems"]
    }


def test_the_listing_locks_the_sql_rows_of_a_failed_server_and_the_csharp_rows_of_a_failed_repository(
    two_hosts, probes
) -> None:
    probes.sql_failures = {SERVER_B: "SQL Server 拒絕這個登入帳號"}
    probes.git_failures = {"AlphaRepo": "這台機器沒有 git"}
    check()

    locks = lock_listing()

    assert locks["Alpha"] == {"Alpha": "這台機器沒有 git", "AlphaDb": "", "SharedDb": "SQL Server 拒絕這個登入帳號"}
    # Delta scans another folder of AlphaRepo: the failure of that repository locks it too.
    assert locks["Delta"] == {"Delta": "這台機器沒有 git"}
    assert locks["Beta"] == {"Beta": "", "BetaDb": ""}
    assert locks["Gamma"] == {"Gamma": "", "SharedDb": "SQL Server 拒絕這個登入帳號"}


def test_before_the_first_check_no_row_is_locked(two_hosts, probes) -> None:
    locks = lock_listing()

    assert all(reason == "" for rows in locks.values() for reason in rows.values())
    assert probes.sql_calls == [] and probes.git_calls == []


def test_the_last_result_stays_until_the_next_check(two_hosts, probes) -> None:
    probes.sql_failures = {SERVER_A: "SQL Server 在 5 秒內沒有回應"}
    check()
    assert lock_listing()["Beta"]["BetaDb"] == "SQL Server 在 5 秒內沒有回應"

    probes.sql_failures = {}
    check()

    assert lock_listing()["Beta"]["BetaDb"] == ""


def test_the_check_logs_in_with_the_scan_account_of_the_server(two_hosts, probes) -> None:
    check(sql_credentials={SERVER_A: {"db_user_id": "scan", "db_password": "pw"}})

    by_server = {call[0]: call for call in probes.sql_calls}
    assert by_server[SERVER_A][2:] == ("scan", "pw")
    assert by_server[SERVER_B][2:] == ("", "")


def test_a_refresh_job_for_a_locked_row_gets_409_with_the_reason_and_no_job_starts(
    two_hosts, probes, monkeypatch
) -> None:
    started: list[str] = []
    monkeypatch.setattr(analyze_service, "refresh_sql_source", lambda *args, **_kw: started.append("sql") or {})
    monkeypatch.setattr(analyze_service, "refresh_source", lambda *args, **_kw: started.append("csharp") or {})
    probes.sql_failures = {SERVER_A: "SQL Server 拒絕這個登入帳號"}
    probes.git_failures = {"AlphaRepo": "這台機器沒有 git"}
    check()

    sql = client.post(
        "/refresh_jobs",
        json={"kind": "sql", "sql": {"database": "AlphaDb", "server": SERVER_A.upper(), "db_name": "AlphaDb"}},
    )
    csharp = client.post(
        "/refresh_jobs",
        json={"kind": "csharp", "csharp": {"system": "Alpha", "source": {"project": "P", "repo": "AlphaRepo"}}},
    )
    direct = client.post("/refresh_sql", json={"database": "BetaDb", "server": SERVER_A, "db_name": "BetaDb"})
    other_case = client.post(
        "/refresh_jobs",
        json={"kind": "csharp", "csharp": {"system": "Alpha", "source": {"project": "p", "repo": "alpharepo"}}},
    )

    assert (sql.status_code, sql.json()["detail"]) == (409, "SQL Server 拒絕這個登入帳號")
    assert (csharp.status_code, csharp.json()["detail"]) == (409, "這台機器沒有 git")
    assert direct.status_code == 409
    assert other_case.status_code == 409
    allowed = client.post(
        "/refresh_jobs",
        json={"kind": "csharp", "csharp": {"system": "Beta", "source": {"project": "P", "repo": "BetaRepo"}}},
    )
    assert allowed.status_code == 200
    wait_for(allowed.json()["job_id"], "succeeded")
    assert started == ["csharp"]
    assert lock_listing()["Alpha"]["AlphaDb"] == "SQL Server 拒絕這個登入帳號"


def test_update_all_skips_locked_rows_and_still_submits_the_other_outdated_rows(
    two_hosts, probes, monkeypatch
) -> None:
    monkeypatch.setattr(analyze_service, "refresh_sql_source", lambda *args, **_kw: {})
    monkeypatch.setattr(analyze_service, "refresh_source", lambda *args, **_kw: {})
    probes.sql_failures = {SERVER_A: "SQL Server 拒絕這個登入帳號"}
    probes.git_failures = {"AlphaRepo": "這台機器沒有 git"}
    check()

    response = client.post("/refresh_jobs/update_all", json={})

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    keys = sorted(job["key"] for job in jobs)
    assert keys == sorted(
        [
            f"sql:{SERVER_B}__SharedDb",
            "csharp:" + str(scan_root_of("P", "BetaRepo")),
            "csharp:" + str(scan_root_of("Q", "GammaRepo")),
        ]
    )
    for job in jobs:
        wait_for(job["job_id"], "succeeded", "failed")


def scan_root_of(project: str, repo: str):
    from service import repo_manager

    return repo_manager.repo_dir(project, repo)


def test_the_openapi_export_includes_the_environment_check_and_the_lock_reason() -> None:
    from tools.export_openapi_schema import build_schema

    schema = build_schema()

    assert "/environment/check" in schema["paths"]
    assert "locked_reason" in schema["components"]["schemas"]["CacheFreshnessRow"]["properties"]
    capability = schema["components"]["schemas"]["UpdateCapabilityResult"]["properties"]
    assert set(capability) == {"capability", "target", "ok", "reason", "locks"}

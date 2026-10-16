"""Ticket 08 of `.scratch/cache-refresh-queue/`: the update page shows `behind_source`.

The seam is the Impact HTTP API, through the FastAPI test client. A fake remote head replaces
`git ls-remote`. A fake recorded commit is written into the meta file of the scan.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from service import analyze_service, scan_store, source_check
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    build_scan,
    client,
    fresh_queue,
    listing,
    scan_root,
    sql_root,
    submit_sql,
    wait_for,
    world,
    write_sql,
)


class FakeRemote:
    def __init__(self) -> None:
        self.heads: dict[str, Optional[str]] = {}
        self.calls: list[str] = []

    def __call__(self, source: dict) -> Optional[str]:
        self.calls.append(source["repo"])
        return self.heads.get(source["repo"])


@pytest.fixture
def remote(monkeypatch):
    fake = FakeRemote()
    monkeypatch.setattr(source_check, "fetch_remote_head", fake)
    monkeypatch.setattr(source_check, "_heads", {})
    monkeypatch.setattr(source_check, "_checked_at", None)
    return fake


def record_commit(repo: str, commit: str) -> None:
    scan_store._mem_cache.clear()
    _, meta = scan_store._paths(scan_root(repo))
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["source_commit"] = commit
    meta.write_text(json.dumps(info), encoding="utf-8")


def check() -> dict:
    response = client.post("/cache_freshness/check")
    assert response.status_code == 200
    return response.json()


def row_of(body: dict, system: str, label: str) -> dict:
    for item in body["systems"]:
        if item["system_id"] == system:
            return {row["label"]: row for row in item["caches"]}[label]
    raise AssertionError(system)


def test_a_scan_whose_commit_differs_from_the_remote_head_lists_as_behind_source(world, remote) -> None:
    build_scan("AlphaRepo")
    build_scan("BetaRepo")
    record_commit("AlphaRepo", "aaa")
    record_commit("BetaRepo", "bbb")
    remote.heads = {"AlphaRepo": "aaa", "BetaRepo": "new"}

    body = check()

    assert row_of(body, "Alpha", "Alpha")["freshness"] == "current"
    beta = row_of(body, "Beta", "Beta")
    assert beta["freshness"] == "behind_source"
    assert beta["last_scanned_at"]


def test_the_listing_shows_the_time_of_the_last_check(world, remote) -> None:
    assert client.get("/cache_freshness").json()["source_checked_at"] is None

    body = check()

    assert body["source_checked_at"]
    assert client.get("/cache_freshness").json()["source_checked_at"] == body["source_checked_at"]


def test_check_again_asks_the_remote_again(world, remote) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {"AlphaRepo": "aaa"}
    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "current"

    remote.heads = {"AlphaRepo": "pushed"}

    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "behind_source"
    assert remote.calls.count("AlphaRepo") == 2


def test_a_plain_listing_never_asks_the_remote(world, remote) -> None:
    listing()

    assert remote.calls == []


def test_an_unreachable_repository_is_not_behind_source(world, remote) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {}

    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "current"


def test_an_outdated_cache_stays_outdated_and_a_sql_cache_is_never_behind_source(
    world, remote, sql_root
) -> None:
    write_sql(sql_root, "AlphaDb")
    remote.heads = {"AlphaRepo": "new", "BetaRepo": "new"}

    body = check()

    assert row_of(body, "Alpha", "Alpha")["freshness"] == "outdated"
    assert row_of(body, "Alpha", "AlphaDb")["freshness"] == "current"


def test_a_behind_source_cache_keeps_its_update_button_and_a_refresh_clears_it(
    world, remote, monkeypatch
) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {"AlphaRepo": "new"}
    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "behind_source"

    def fake_refresh(source, **_kwargs) -> dict:
        record_commit("AlphaRepo", "new")
        return {}

    monkeypatch.setattr(analyze_service, "refresh_source", fake_refresh)
    job = client.post(
        "/refresh",
        json={"system": "Alpha", "source": {"project": "P", "repo": "AlphaRepo"}},
    )
    assert job.status_code == 200
    wait_for(job.json()["job_id"], "succeeded")

    assert listing()["Alpha"]["Alpha"]["freshness"] == "current"


def test_update_all_leaves_a_behind_source_cache_out(world, remote, sql_root, monkeypatch) -> None:
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {"AlphaRepo": "new"}
    check()
    submitted: list[str] = []
    monkeypatch.setattr(
        analyze_service, "refresh_source", lambda source, **_kw: submitted.append(source["repo"]) or {}
    )
    monkeypatch.setattr(analyze_service, "refresh_sql_source", lambda **_kw: {})

    response = client.post("/refresh_jobs/update_all", json={})

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert not any("AlphaRepo" in job["key"] for job in jobs)
    for job in jobs:
        wait_for(job["job_id"], "succeeded", "failed")


def test_a_question_never_checks_the_remote_and_answers_normally_for_a_behind_source_system(
    world, remote, sql_root
) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan("AlphaRepo")
    record_commit("AlphaRepo", "aaa")
    remote.heads = {"AlphaRepo": "new"}
    assert row_of(check(), "Alpha", "Alpha")["freshness"] == "behind_source"
    remote.calls.clear()

    response = client.post(
        "/find_by_sp",
        json={
            "source": {"project": "P", "repo": "AlphaRepo"},
            "database": "AlphaDb",
            "db_server": "dbhost.example.com",
            "sp_name": "usp_Save",
        },
    )

    assert response.status_code == 200
    assert response.json()["unusable_caches"] == []
    assert remote.calls == []


def test_ls_remote_keeps_the_token_out_of_the_command_line_and_failures_give_no_head(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(source_check.settings, "AZURE_DEVOPS_ORG", "org")
    monkeypatch.setattr(source_check.settings, "AZURE_DEVOPS_PAT", "s3cret-pat")
    seen: dict = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["env"] = args, kwargs["env"]
        return subprocess.CompletedProcess(args, 0, stdout="abc123\trefs/heads/main\n", stderr="")

    monkeypatch.setattr(source_check.subprocess, "run", fake_run)
    source = {"project": "P", "repo": "R", "branch": "main"}
    assert source_check.fetch_remote_head(source) == "abc123"
    assert "s3cret-pat" not in " ".join(seen["args"])
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"

    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 30)

    monkeypatch.setattr(source_check.subprocess, "run", timeout)
    assert source_check.fetch_remote_head(source) is None

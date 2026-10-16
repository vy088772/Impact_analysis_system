"""Ticket 07 of `.scratch/cache-refresh-queue/`: "update all" submits one Refresh Job per outdated cache.

The seam is the Impact HTTP API (`POST /refresh_jobs/update_all`), through the FastAPI test client.
A fake rebuild replaces the real scan and the real SQL connection.
"""

from __future__ import annotations

import threading

from service import analyze_service
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures)
    SERVER,
    build_scan,
    client,
    fresh_queue,
    listing,
    sql_root,
    wait_for,
    world,
    write_sql,
)


class RecordingRebuild:
    """Fake rebuilds that record what the queue asked for."""

    def __init__(self) -> None:
        self.sql_calls: list[dict] = []
        self.csharp_calls: list[dict] = []
        self.gate = threading.Event()
        self.gate.set()

    def sql(self, database, server, db_name, user_id="", password="", progress_callback=None) -> dict:
        assert self.gate.wait(timeout=5)
        self.sql_calls.append(
            {"database": database, "server": server, "db_name": db_name,
             "user_id": user_id, "password": password}
        )
        return {"database": db_name}

    def csharp(self, source, **kwargs) -> dict:
        assert self.gate.wait(timeout=5)
        self.csharp_calls.append({"source": source, **kwargs})
        return {}


def install(monkeypatch) -> RecordingRebuild:
    fake = RecordingRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    monkeypatch.setattr(analyze_service, "refresh_source", fake.csharp)
    return fake


def update_all(**body) -> list[dict]:
    response = client.post("/refresh_jobs/update_all", json=body)
    assert response.status_code == 200, response.text
    return response.json()["jobs"]


def finish(jobs: list[dict]) -> None:
    for job in jobs:
        wait_for(job["job_id"], "succeeded", "failed")


def test_update_all_submits_one_job_for_each_outdated_cache(world, monkeypatch) -> None:
    fake = install(monkeypatch)

    jobs = update_all()
    finish(jobs)

    assert sorted(job["kind"] for job in jobs) == ["csharp", "csharp", "sql", "sql"]
    assert sorted(call["db_name"] for call in fake.sql_calls) == ["AlphaDb", "SharedDb"]
    assert sorted(call["source"]["repo"] for call in fake.csharp_calls) == ["AlphaRepo", "BetaRepo"]


def test_update_all_submits_no_job_for_a_current_cache(world, sql_root, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb")
    write_sql(sql_root, "SharedDb")
    build_scan("AlphaRepo")
    fake = install(monkeypatch)

    jobs = update_all()
    finish(jobs)

    assert [call["source"]["repo"] for call in fake.csharp_calls] == ["BetaRepo"]
    assert fake.sql_calls == []
    assert [job["kind"] for job in jobs] == ["csharp"]


def test_update_all_with_nothing_outdated_submits_nothing(world, sql_root, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb")
    write_sql(sql_root, "SharedDb")
    build_scan("AlphaRepo")
    build_scan("BetaRepo")
    install(monkeypatch)

    assert update_all() == []


def test_a_cache_with_a_running_job_gets_no_second_job(world, monkeypatch) -> None:
    fake = install(monkeypatch)
    fake.gate.clear()
    running = client.post(
        "/refresh_sql", json={"database": "x", "server": SERVER, "db_name": "AlphaDb"}
    ).json()
    wait_for(running["job_id"], "running")

    jobs = update_all()

    assert all(not job["key"].endswith("__AlphaDb") for job in jobs)
    assert len(jobs) == 3
    fake.gate.set()
    finish(jobs)
    wait_for(running["job_id"], "succeeded")
    assert [call["db_name"] for call in fake.sql_calls].count("AlphaDb") == 1


def test_a_cache_with_a_waiting_job_gets_no_second_job(world, monkeypatch) -> None:
    fake = install(monkeypatch)
    fake.gate.clear()
    client.post(
        "/refresh_sql", json={"database": "x", "server": SERVER, "db_name": "AlphaDb"}
    )
    waiting = client.post(
        "/refresh_sql", json={"database": "y", "server": SERVER, "db_name": "SharedDb"}
    ).json()

    jobs = update_all()

    shared = [job for job in jobs if job["key"].endswith("__SharedDb")]
    assert [job["job_id"] for job in shared] == [waiting["job_id"]]
    fake.gate.set()
    finish(jobs)
    assert [call["db_name"] for call in fake.sql_calls].count("SharedDb") == 1


def test_each_job_shows_its_queue_position(world, monkeypatch) -> None:
    fake = install(monkeypatch)
    fake.gate.clear()

    jobs = update_all()

    assert len(jobs) == 4
    assert all(job["queue_position"] >= 1 or job["status"] == "running" for job in jobs)
    now = [client.get(f"/refresh_jobs/{job['job_id']}").json() for job in jobs]
    assert sorted(job["queue_position"] for job in now) == [0, 1, 2, 3]
    fake.gate.set()
    finish(jobs)


def test_update_all_uses_the_credentials_and_contracts_the_caller_gives(world, monkeypatch) -> None:
    fake = install(monkeypatch)

    jobs = update_all(
        sql_credentials={SERVER: {"db_user_id": "scan", "db_password": "secret"}},
        wrapper_contracts={"Alpha": "alpha-contract"},
    )
    finish(jobs)

    assert {(c["user_id"], c["password"]) for c in fake.sql_calls} == {("scan", "secret")}
    by_repo = {call["source"]["repo"]: call for call in fake.csharp_calls}
    assert by_repo["AlphaRepo"]["wrapper_contract"] == "alpha-contract"
    assert "wrapper_contract" not in by_repo["BetaRepo"]
    assert by_repo["AlphaRepo"]["database"] == "Alpha"


def test_update_all_leaves_the_listing_outdated_until_the_jobs_finish(world, monkeypatch) -> None:
    fake = install(monkeypatch)
    fake.gate.clear()

    jobs = update_all()

    row = listing()["Beta"]["Beta"]
    assert row["freshness"] == "outdated"
    assert row["last_job"]["status"] == "waiting"
    fake.gate.set()
    finish(jobs)

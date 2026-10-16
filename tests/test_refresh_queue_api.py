"""Ticket 02 of `.scratch/cache-refresh-queue/`: Refresh Jobs run one at a time.

The seam is the Impact HTTP API, through the FastAPI test client. A fake rebuild replaces
the real scan and the real SQL connection. A gate (`threading.Event`) holds a fake rebuild
open, so a test can look at a job while it runs and while others wait.
"""

from __future__ import annotations

import threading
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from service import analyze_service, refresh_queue
from service.api import app

client = TestClient(app)

TERMINAL = {"succeeded", "failed", "cancelled"}


@pytest.fixture(autouse=True)
def fresh_queue(monkeypatch):
    """Each test gets its own queue, so no job leaks from one test to the next."""
    monkeypatch.setattr(refresh_queue, "queue", refresh_queue.RefreshQueue())


class FakeRebuild:
    """Records the start order and the overlap of rebuilds. A gate holds each one open."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []
        self.most_at_once = 0
        self._now = 0
        self._lock = threading.Lock()
        self.gates: dict[str, threading.Event] = {}
        self.failures: dict[str, str] = {}
        self.progress: dict[str, list[tuple[str, int, int, str]]] = {}

    def gate(self, name: str) -> threading.Event:
        return self.gates.setdefault(name, threading.Event())

    def sql(self, database, server, db_name, progress_callback=None, **_kwargs) -> dict:
        return self._rebuild(database, progress_callback)

    def csharp(self, source, **_kwargs) -> dict:
        return self._rebuild(source["repo"], None)

    def _rebuild(self, name: str, progress_callback: Callable | None) -> dict:
        with self._lock:
            self.started.append(name)
            self._now += 1
            self.most_at_once = max(self.most_at_once, self._now)
        try:
            for stage, current, total, item in self.progress.get(name, []):
                if progress_callback:
                    progress_callback(stage, current, total, item)
            assert self.gate(name).wait(timeout=5), f"gate for {name} never opened"
            if name in self.failures:
                raise RuntimeError(self.failures[name])
            return {"database": name, "rebuilt": 1, "scope": "system", "files": 3}
        finally:
            with self._lock:
                self._now -= 1
                self.finished.append(name)


@pytest.fixture
def rebuild(monkeypatch) -> FakeRebuild:
    fake = FakeRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    monkeypatch.setattr(analyze_service, "refresh_source", fake.csharp)
    return fake


def sql_body(name: str, server: str = "srv") -> dict:
    return {"database": name, "server": server, "db_name": name}


def csharp_body(repo: str) -> dict:
    return {"system": repo, "source": {"project": "p", "repo": repo}}


def wait_for(job_id: str, *states: str) -> dict:
    deadline = threading.Event()
    job: dict = {}
    for _ in range(200):
        job = client.get(f"/refresh_jobs/{job_id}").json()
        if job["status"] in states:
            return job
        deadline.wait(0.025)
    raise AssertionError(f"job {job_id} never reached {states}; last: {job}")


def test_a_submit_returns_the_job_with_its_state_and_queue_position(rebuild) -> None:
    first = client.post("/refresh_sql", json=sql_body("A")).json()
    wait_for(first["job_id"], "running")
    second = client.post("/refresh_sql", json=sql_body("B")).json()

    assert first["status"] in {"waiting", "running"}
    assert second["status"] == "waiting"
    assert second["queue_position"] == 1

    rebuild.gate("A").set()
    rebuild.gate("B").set()


def test_a_submit_for_a_cache_that_waits_or_runs_returns_the_existing_job(rebuild) -> None:
    running = client.post("/refresh_sql", json=sql_body("A")).json()
    wait_for(running["job_id"], "running")
    waiting = client.post("/refresh_sql", json=sql_body("B")).json()

    again_running = client.post("/refresh_sql", json=sql_body("A")).json()
    again_waiting = client.post("/refresh_sql", json=sql_body("B")).json()

    assert again_running["job_id"] == running["job_id"]
    assert again_waiting["job_id"] == waiting["job_id"]
    rebuild.gate("A").set()
    rebuild.gate("B").set()
    wait_for(waiting["job_id"], "succeeded")
    assert rebuild.started == ["A", "B"]


def test_two_jobs_for_two_caches_run_one_after_the_other(rebuild) -> None:
    first = client.post("/refresh_sql", json=sql_body("A")).json()
    second = client.post("/refresh", json=csharp_body("RepoB")).json()
    wait_for(first["job_id"], "running")

    assert client.get(f"/refresh_jobs/{second['job_id']}").json()["status"] == "waiting"
    assert rebuild.started == ["A"]

    rebuild.gate("A").set()
    wait_for(second["job_id"], "running")
    assert rebuild.finished == ["A"]
    rebuild.gate("RepoB").set()
    wait_for(second["job_id"], "succeeded")

    assert rebuild.started == ["A", "RepoB"]
    assert rebuild.most_at_once == 1


def test_a_cancel_removes_a_waiting_job_and_gives_it_the_state_cancelled(rebuild) -> None:
    running = client.post("/refresh_sql", json=sql_body("A")).json()
    wait_for(running["job_id"], "running")
    waiting = client.post("/refresh_sql", json=sql_body("B")).json()

    response = client.post(f"/refresh_jobs/{waiting['job_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    rebuild.gate("A").set()
    wait_for(running["job_id"], "succeeded")
    assert rebuild.started == ["A"]
    # A cancelled job leaves the line: a new submit for the same cache makes a new job.
    resubmitted = client.post("/refresh_sql", json=sql_body("B")).json()
    assert resubmitted["job_id"] != waiting["job_id"]
    rebuild.gate("B").set()


def test_a_cancel_of_a_running_job_is_refused_and_the_job_continues(rebuild) -> None:
    running = client.post("/refresh_sql", json=sql_body("A")).json()
    wait_for(running["job_id"], "running")

    response = client.post(f"/refresh_jobs/{running['job_id']}/cancel")

    assert response.status_code == 409
    rebuild.gate("A").set()
    assert wait_for(running["job_id"], "succeeded")["status"] == "succeeded"


def test_a_cancel_of_an_unknown_job_is_not_found(rebuild) -> None:
    assert client.post("/refresh_jobs/missing/cancel").status_code == 404


def test_a_failed_job_gets_the_state_failed_and_keeps_its_error_message(rebuild) -> None:
    rebuild.failures["A"] = "database unavailable"
    rebuild.gate("A").set()

    job = client.post("/refresh_sql", json=sql_body("A")).json()
    failed = wait_for(job["job_id"], "failed")

    assert failed["error"] == "database unavailable"


def test_a_failed_job_does_not_stop_the_next_job(rebuild) -> None:
    rebuild.failures["A"] = "boom"
    rebuild.gate("A").set()
    rebuild.gate("B").set()

    first = client.post("/refresh_sql", json=sql_body("A")).json()
    second = client.post("/refresh_sql", json=sql_body("B")).json()

    assert wait_for(first["job_id"], "failed")["status"] == "failed"
    assert wait_for(second["job_id"], "succeeded")["status"] == "succeeded"


def test_the_job_reports_its_stage_and_progress_while_it_runs(rebuild) -> None:
    rebuild.progress["A"] = [("procedures", 3, 10, "usp_SaveOrder")]
    job = client.post("/refresh_sql", json=sql_body("A")).json()

    running = wait_for(job["job_id"], "running")
    for _ in range(200):
        running = client.get(f"/refresh_jobs/{job['job_id']}").json()
        if running["stage"] == "procedures":
            break
        threading.Event().wait(0.025)

    assert (running["stage"], running["current"], running["total"], running["item"]) == (
        "procedures",
        3,
        10,
        "usp_SaveOrder",
    )
    rebuild.gate("A").set()


def test_the_refresh_endpoint_returns_a_job_and_the_result_arrives_with_it(rebuild) -> None:
    rebuild.gate("RepoA").set()

    job = client.post("/refresh", json=csharp_body("RepoA")).json()
    done = wait_for(job["job_id"], "succeeded")

    assert job["kind"] == "csharp"
    assert done["result"]["scope"] == "system"
    assert done["result"]["files"] == 3


def test_the_refresh_sql_endpoint_returns_a_job_and_the_result_arrives_with_it(rebuild) -> None:
    rebuild.gate("A").set()

    job = client.post("/refresh_sql", json=sql_body("A")).json()
    done = wait_for(job["job_id"], "succeeded")

    assert job["kind"] == "sql"
    assert done["result"]["rebuilt"] == 1


def test_a_program_scoped_refresh_stays_direct_and_does_not_use_the_queue(
    rebuild, monkeypatch
) -> None:
    monkeypatch.setattr(
        analyze_service,
        "refresh_source",
        lambda source, **kwargs: {"scope": "program", "partial": True},
    )

    response = client.post(
        "/refresh", json={**csharp_body("RepoA"), "program_names": ["PUR_MasterEdit"]}
    )

    assert response.status_code == 200
    assert response.json()["scope"] == "program"
    assert "job_id" not in response.json()


def test_the_submit_endpoint_accepts_both_cache_kinds(rebuild) -> None:
    rebuild.gate("A").set()
    rebuild.gate("RepoB").set()

    sql = client.post("/refresh_jobs", json={"kind": "sql", "sql": sql_body("A")}).json()
    csharp = client.post(
        "/refresh_jobs", json={"kind": "csharp", "csharp": csharp_body("RepoB")}
    ).json()

    assert sql["kind"] == "sql"
    assert csharp["kind"] == "csharp"
    wait_for(csharp["job_id"], "succeeded")


def test_a_sql_request_without_a_server_is_refused_before_it_queues(rebuild) -> None:
    response = client.post(
        "/refresh_sql", json={"database": "A", "server": "", "db_name": "A"}
    )

    assert response.status_code == 400
    assert rebuild.started == []


def test_the_old_status_path_reads_the_same_job(rebuild) -> None:
    rebuild.gate("A").set()
    job = client.post("/refresh_sql", json=sql_body("A")).json()
    wait_for(job["job_id"], "succeeded")

    old = client.get(f"/refresh_sql/status/{job['job_id']}").json()

    assert old["status"] == "succeeded"
    assert old["job_id"] == job["job_id"]

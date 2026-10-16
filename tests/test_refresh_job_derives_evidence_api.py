"""Ticket 06 of `.scratch/cache-refresh-queue/`: a Refresh Job derives Derived Execution Evidence.

The seam is the Impact HTTP API, through the FastAPI test client. A fake rebuild replaces the
real scan and the real SQL connection; the scan, the SQL cache and the derivation are real, with
the derived-evidence fixtures of the suite (`RatedInvocationsRetention`, `sql_cache_fixtures`).
A spy on the rating step counts how often a derivation really runs, and a gate holds one open.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import ProjectScanResult
from config.settings import settings
from service import (
    analyze_service,
    derived_execution_evidence,
    evidence_refresh,
    refresh_progress,
    refresh_queue,
    repo_manager,
    scan_store,
)
from service.api import app
from service.sql_cache_store import CacheIdentity
from tests.derived_execution_evidence_fixtures import RatedInvocationsRetention
from tests.sql_cache_fixtures import CacheRoot, cache_payload, execution_graph, write_cache

SERVER = "dbhost.example.com"

client = TestClient(app)


def procedure_graph() -> dict:
    return execution_graph(
        "OrdersDb",
        nodes=[{"id": "stored_procedure:dbo.usp_Alpha", "type": "stored_procedure", "schema": "dbo", "name": "usp_Alpha"}],
    )


def build_scan(root: Path) -> ProjectScanResult:
    """One repository scan with one program that calls `dbo.usp_Alpha`."""
    path = root / "AlphaPage.cs"
    page = FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="AlphaPage",
                namespace="",
                file_path=str(path),
                methods=[MethodInfo(name="SaveAlpha", access_modifier="private", return_type="void")],
            )
        ],
    )
    raw = {
        str(path.resolve()): [
            {
                "class_name": "AlphaPage",
                "method_name": "SaveAlpha",
                "command_text_kind": "literal",
                "command_text": "dbo.usp_Alpha",
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[page],
        db_invocations=raw,
        connection_sources={str(path.resolve()): {"conn": "OrdersDb"}},
    )


class RatingSpy:
    """Counts the derivations that really run, and can hold one open."""

    def __init__(self, monkeypatch) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        original = derived_execution_evidence._rated_execution_invocations

        def spy(*args, **kwargs):
            self.calls += 1
            self.started.set()
            assert self.release.wait(timeout=10), "the gate never opened"
            return original(*args, **kwargs)

        monkeypatch.setattr(derived_execution_evidence, "_rated_execution_invocations", spy)

    def hold(self) -> None:
        self.started.clear()
        self.release.clear()


@pytest.fixture(autouse=True)
def fresh_queue(monkeypatch):
    """A queue of its own and no job record from an earlier test (the records are process-wide)."""
    monkeypatch.setattr(refresh_queue, "shared_queue", refresh_queue.RefreshQueue())
    monkeypatch.setattr(refresh_progress, "_SNAPSHOTS", {})


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two systems on one SQL database. Orders has a scanned repository; Billing has none."""
    monkeypatch.setattr(settings, "SCAN_CACHE_ROOT", str(tmp_path / "scan_cache"))
    monkeypatch.setattr(settings, "AZURE_CLONE_ROOT", str(tmp_path / "repos"))
    monkeypatch.setattr(scan_store, "_mem_cache", {})

    class FakeScanner:
        def __init__(self, project_root: str) -> None:
            self.project_root = project_root

        def scan_project(self, analyze_sp: bool = True) -> ProjectScanResult:
            return build_scan(Path(self.project_root))

    monkeypatch.setattr(scan_store, "ProjectScanner", FakeScanner)
    systems = [
        {
            "system_id": "Orders",
            "azure": {"project": "P", "repo": "OrdersRepo", "branch": "", "path": ""},
            "databases": [{"name": "OrdersDb", "server": SERVER}],
        },
        {
            "system_id": "Billing",
            "azure": {"project": "P", "repo": "BillingRepo", "branch": "", "path": ""},
            "databases": [{"name": "OrdersDb", "server": SERVER}],
        },
    ]
    monkeypatch.setattr(evidence_refresh, "catalog_systems", lambda: systems)
    monkeypatch.setattr(derived_execution_evidence, "cached_saved_at", scan_store.cached_saved_at)
    with RatedInvocationsRetention() as retention, CacheRoot() as sql_root:
        write_cache(sql_root, CacheIdentity.of(SERVER, "OrdersDb"), cache_payload("OrdersDb", graph=procedure_graph()))
        retention.sql_root = sql_root
        yield retention


def orders_root() -> Path:
    root = repo_manager.repo_dir("P", "OrdersRepo")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def rebuild(monkeypatch):
    """The fake rebuilds. The C# one writes a new Scan Result; the SQL one rewrites nothing."""

    def csharp(source, **_kwargs) -> dict:
        scan_store.rebuild_scan(repo_manager.repo_dir(source["project"], source["repo"]))
        return {"rebuilt": 1}

    def sql(database, server, db_name, **_kwargs) -> dict:
        return {"database": database, "rebuilt": 1}

    monkeypatch.setattr(analyze_service, "refresh_source", csharp)
    monkeypatch.setattr(analyze_service, "refresh_sql_source", sql)


def wait_for(job_id: str, *states: str) -> dict:
    gate = threading.Event()
    job: dict = {}
    for _ in range(400):
        job = client.get(f"/refresh_jobs/{job_id}").json()
        if job["status"] in states:
            return job
        gate.wait(0.025)
    raise AssertionError(f"job {job_id} never reached {states}; last: {job}")


def refresh_orders() -> dict:
    job = client.post(
        "/refresh", json={"system": "Orders", "source": {"project": "P", "repo": "OrdersRepo"}}
    ).json()
    return wait_for(job["job_id"], "succeeded", "failed")


def ask_find_by_sp(system: str = "Orders") -> dict:
    response = client.post(
        "/find_by_sp",
        json={
            "source": {"project": "P", "repo": f"{system}Repo"},
            "sp_name": "usp_Alpha",
            "database": "OrdersDb",
            "db_server": SERVER,
            "cache_only": False,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_last_stage_of_a_csharp_job_derives_the_evidence_and_the_next_question_does_not(
    world, rebuild, monkeypatch
) -> None:
    spy = RatingSpy(monkeypatch)

    job = refresh_orders()

    assert job["status"] == "succeeded", job["error"]
    # The scopes of Orders: the analyze scope and the lookup scope of its one database.
    assert job["result"]["derivation"] == {"derived": 2, "skipped": 0, "failed": []}
    assert spy.calls == 2
    answer = ask_find_by_sp()
    assert [match["program"] for match in answer["matches"]] == ["alphapage"]
    assert spy.calls == 2, "the question derived again"


def test_the_job_progress_shows_the_derivation_as_its_own_stage(world, rebuild, monkeypatch) -> None:
    spy = RatingSpy(monkeypatch)
    spy.hold()

    submitted = client.post(
        "/refresh", json={"system": "Orders", "source": {"project": "P", "repo": "OrdersRepo"}}
    ).json()
    assert spy.started.wait(timeout=10)
    running = client.get(f"/refresh_jobs/{submitted['job_id']}").json()

    assert running["status"] == "running"
    assert running["stage"] == "deriving_evidence"
    assert running["total"] == 2
    # The job reports the stage. A derivation inside a job is not a question's derivation.
    assert client.get("/derivation_progress").json() == {"active": []}
    spy.release.set()
    assert wait_for(submitted["job_id"], "succeeded")["status"] == "succeeded"


def test_a_sql_job_derives_each_scope_that_reads_the_database_and_skips_one_without_a_scan(
    world, rebuild, monkeypatch
) -> None:
    scan_store.rebuild_scan(orders_root())
    spy = RatingSpy(monkeypatch)

    job = client.post(
        "/refresh_sql", json={"database": "OrdersDb", "server": SERVER, "db_name": "OrdersDb"}
    ).json()
    done = wait_for(job["job_id"], "succeeded", "failed")

    assert done["status"] == "succeeded", done["error"]
    # Orders: two scopes derived. Billing: two scopes, no Scan Result, so skipped.
    assert done["result"]["derivation"] == {"derived": 2, "skipped": 2, "failed": []}
    assert spy.calls == 2
    ask_find_by_sp()
    assert spy.calls == 2


def test_a_failed_rebuild_derives_nothing(world, monkeypatch) -> None:
    spy = RatingSpy(monkeypatch)

    def broken(source, **_kwargs) -> dict:
        raise RuntimeError("clone failed")

    monkeypatch.setattr(analyze_service, "refresh_source", broken)

    job = refresh_orders()

    assert job["status"] == "failed"
    assert "clone failed" in job["error"]
    assert spy.calls == 0


def test_a_scope_that_fails_to_derive_does_not_fail_the_job(world, rebuild, monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("rating broke")

    monkeypatch.setattr(derived_execution_evidence, "_rated_execution_invocations", broken)

    job = refresh_orders()

    assert job["status"] == "succeeded"
    assert job["result"]["derivation"]["derived"] == 0
    assert [item["error"] for item in job["result"]["derivation"]["failed"]] == ["rating broke"] * 2


def test_a_question_that_must_derive_reports_a_progress_stage(world, monkeypatch) -> None:
    scan_store.rebuild_scan(orders_root())
    spy = RatingSpy(monkeypatch)
    spy.hold()
    answers: list[dict] = []
    asking = threading.Thread(target=lambda: answers.append(ask_find_by_sp()))

    assert client.get("/derivation_progress").json() == {"active": []}
    asking.start()
    assert spy.started.wait(timeout=10)
    active = client.get("/derivation_progress").json()["active"]
    spy.release.set()
    asking.join(timeout=10)

    assert [entry["stage"] for entry in active] == ["deriving_evidence"]
    assert active[0]["database"] == "OrdersDb"
    assert [match["program"] for match in answers[0]["matches"]] == ["alphapage"]
    assert client.get("/derivation_progress").json() == {"active": []}


def edit_exclusions(monkeypatch) -> None:
    monkeypatch.setattr(
        derived_execution_evidence, "load_wrapper_review_exclusions", lambda database: ({"edited": database},)
    )


def wait_for_evidence_jobs(count: int) -> list[dict]:
    gate = threading.Event()
    jobs: list[dict] = []
    for _ in range(400):
        jobs = [
            job
            for target in evidence_refresh.all_targets()
            if (job := refresh_queue.shared_queue.latest_for_key(refresh_queue.evidence_key(target.label)))
            and job["status"] == "succeeded"
        ]
        if len(jobs) >= count:
            return jobs
        gate.wait(0.025)
    raise AssertionError(f"expected {count} finished evidence jobs, saw {jobs}")


def test_the_service_starts_a_job_for_a_scope_whose_configuration_changed_while_it_was_down(
    world, rebuild, monkeypatch
) -> None:
    spy = RatingSpy(monkeypatch)
    refresh_orders()
    assert spy.calls == 2
    world.simulate_restart()
    evidence_refresh._seen.clear()
    edit_exclusions(monkeypatch)

    with TestClient(app):  # the lifespan checks the configuration at start
        jobs = wait_for_evidence_jobs(2)

    assert {job["kind"] for job in jobs} == {"evidence"}
    assert spy.calls == 4
    ask_find_by_sp()
    assert spy.calls == 4, "the question derived again after the automatic job"


def test_a_question_that_reads_changed_configuration_starts_a_job_for_the_other_scopes(
    world, rebuild, monkeypatch
) -> None:
    spy = RatingSpy(monkeypatch)
    refresh_orders()
    assert spy.calls == 2
    edit_exclusions(monkeypatch)

    # The lookup scope derives itself, as before. The job refreshes the analyze scope.
    ask_find_by_sp()
    wait_for_evidence_jobs(1)

    assert spy.calls == 4


def test_unchanged_configuration_starts_no_job(world, rebuild, monkeypatch) -> None:
    refresh_orders()
    world.simulate_restart()
    evidence_refresh._seen.clear()

    assert evidence_refresh.check_config_at_start() == 0
    ask_find_by_sp()
    assert [
        target.label
        for target in evidence_refresh.all_targets()
        if refresh_queue.shared_queue.latest_for_key(refresh_queue.evidence_key(target.label))
    ] == []


def test_stale_evidence_is_never_served_after_the_cache_is_rebuilt(world, rebuild, monkeypatch) -> None:
    """ADR-0013 still holds: a changed scan changes the Validity Stamp, so a question derives again."""
    spy = RatingSpy(monkeypatch)
    refresh_orders()
    derived_by_job = spy.calls
    monkeypatch.setattr(derived_execution_evidence, "cached_saved_at", lambda root: "another-time")

    ask_find_by_sp()

    assert spy.calls > derived_by_job

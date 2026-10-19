"""Ticket 03 of `.scratch/cache-refresh-queue/`: the Cache Freshness listing.

The seam is the Impact HTTP API (`GET /cache_freshness`), through the FastAPI test client.
A fake rebuild replaces the real scan and the real SQL connection.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from code_analyzer.project_scanner import ProjectScanResult
from config.settings import settings
from service import analyze_service, refresh_queue, repo_manager, scan_store, system_targets
from service.api import app
from service.sql_cache_store import CacheIdentity
from tests.sql_cache_fixtures import CacheRoot, cache_payload, execution_graph, write_cache

client = TestClient(app)

SERVER = "dbhost.example.com"


def sql_payload(database: str) -> dict:
    return cache_payload(database, graph=execution_graph(database))


@pytest.fixture(autouse=True)
def fresh_queue(monkeypatch):
    monkeypatch.setattr(refresh_queue, "shared_queue", refresh_queue.RefreshQueue())


@pytest.fixture
def sql_root():
    with CacheRoot() as root:
        yield root


@pytest.fixture
def world(tmp_path, monkeypatch, sql_root):
    """A catalog of two systems that share one SQL database, plus a scan cache root."""
    monkeypatch.setattr(settings, "SCAN_CACHE_ROOT", str(tmp_path / "scan_cache"))
    monkeypatch.setattr(settings, "AZURE_CLONE_ROOT", str(tmp_path / "repos"))
    monkeypatch.setattr(scan_store, "_mem_cache", {})

    class FakeScanner:
        def __init__(self, project_root: str) -> None:
            self.project_root = project_root

        def scan_project(self, analyze_sp: bool = True) -> ProjectScanResult:
            return ProjectScanResult(
                project_root=self.project_root, project_name="fake", scan_time=datetime.now()
            )

    monkeypatch.setattr(scan_store, "ProjectScanner", FakeScanner)
    spec_rag = tmp_path / "spec_rag"
    (spec_rag / "catalog").mkdir(parents=True)
    catalog = {
        "systems": [
            {
                "system_id": "Alpha",
                "azure": {"project": "P", "repo": "AlphaRepo", "branch": "", "path": ""},
                "databases": [
                    {"name": "SharedDb", "server": SERVER},
                    {"name": "AlphaDb", "server": SERVER},
                ],
            },
            {
                "system_id": "Beta",
                "azure": {"project": "P", "repo": "BetaRepo", "branch": "", "path": ""},
                "databases": [{"name": "SharedDb", "server": SERVER}],
            },
            {"system_id": "NoCode", "azure": {"project": "", "repo": ""}, "databases": []},
        ]
    }
    (spec_rag / "catalog" / "system_catalog.json").write_text(
        json.dumps(catalog), encoding="utf-8"
    )
    monkeypatch.setattr(system_targets, "default_spec_rag_root", lambda: spec_rag)
    return tmp_path


def scan_root(repo: str):
    root = repo_manager.repo_dir("P", repo)
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_scan(repo: str) -> None:
    scan_store.rebuild_scan(scan_root(repo))


def write_sql(sql_root, database: str, **kwargs) -> None:
    write_cache(sql_root, CacheIdentity.of(SERVER, database), sql_payload(database), **kwargs)


def listing() -> dict[str, dict[str, dict]]:
    response = client.get("/cache_freshness")
    assert response.status_code == 200
    return {
        system["system_id"]: {row["label"]: row for row in system["caches"]}
        for system in response.json()["systems"]
    }


def test_each_cache_lists_with_its_system_freshness_scan_time_and_last_job(world, sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan("AlphaRepo")

    rows = listing()["Alpha"]

    assert rows["Alpha"]["kind"] == "csharp"
    assert rows["Alpha"]["freshness"] == "current"
    assert rows["Alpha"]["last_scanned_at"]
    assert rows["Alpha"]["last_job"] is None
    assert rows["AlphaDb"]["kind"] == "sql"
    assert rows["AlphaDb"]["freshness"] == "current"
    assert rows["AlphaDb"]["last_scanned_at"]
    assert rows["AlphaDb"]["server"] == SERVER
    assert rows["AlphaDb"]["database"] == "AlphaDb"


def test_a_code_cache_lists_the_repository_and_the_folders_it_scans(world) -> None:
    from service import cache_freshness

    row = cache_freshness.csharp_row(
        "Y-DOCs_TTPUR", [], {"repo": "Y-DOCs", "path": ["TTPUR", "ATV", " "]}
    )
    assert row["repo"] == "Y-DOCs"
    assert row["paths"] == ["TTPUR", "ATV"]
    assert cache_freshness.csharp_row("X", [], {"repo": "R", "path": "TTRDQ"})["paths"] == ["TTRDQ"]

    rows = listing()["Alpha"]
    assert rows["Alpha"]["repo"] == "AlphaRepo"
    assert rows["Alpha"]["paths"] == []


def test_a_missing_cache_lists_as_outdated_with_no_scan_time(world) -> None:
    rows = listing()["Alpha"]

    assert rows["Alpha"]["freshness"] == "outdated"
    assert rows["Alpha"]["last_scanned_at"] is None
    assert rows["AlphaDb"]["freshness"] == "outdated"


def test_a_system_with_no_repository_lists_no_code_cache(world) -> None:
    assert listing()["NoCode"] == {}


def test_a_cache_with_an_old_format_version_lists_as_outdated(world, sql_root) -> None:
    write_sql(sql_root, "AlphaDb", cache_version=1)
    build_scan("AlphaRepo")
    scan_store._mem_cache.clear()
    _, meta = scan_store._paths(scan_root("AlphaRepo"))
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["cache_version"] = scan_store._CACHE_VERSION - 1
    meta.write_text(json.dumps(info), encoding="utf-8")

    rows = listing()["Alpha"]

    assert rows["AlphaDb"]["freshness"] == "outdated"
    assert rows["Alpha"]["freshness"] == "outdated"
    # An outdated cache still says when it was last scanned.
    assert rows["AlphaDb"]["last_scanned_at"]
    assert rows["Alpha"]["last_scanned_at"]


def test_an_invalid_cache_lists_as_outdated(world, sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    (sql_root / CacheIdentity.of(SERVER, "AlphaDb").filename).write_text("{not json", encoding="utf-8")
    build_scan("AlphaRepo")
    scan_store._mem_cache.clear()
    pkl, _ = scan_store._paths(scan_root("AlphaRepo"))
    pkl.write_bytes(b"not a pickle")

    rows = listing()["Alpha"]

    assert rows["AlphaDb"]["freshness"] == "outdated"
    assert rows["Alpha"]["freshness"] == "outdated"


def test_a_shared_sql_cache_lists_under_each_system_with_one_state(world, sql_root) -> None:
    listed = listing()
    assert listed["Alpha"]["SharedDb"]["freshness"] == "outdated"
    assert listed["Beta"]["SharedDb"] == listed["Alpha"]["SharedDb"]

    write_sql(sql_root, "SharedDb")
    listed = listing()
    assert listed["Alpha"]["SharedDb"]["freshness"] == "current"
    assert listed["Beta"]["SharedDb"] == listed["Alpha"]["SharedDb"]


class GatedRebuild:
    def __init__(self) -> None:
        self.gates: dict[str, threading.Event] = {}

    def gate(self, name: str) -> threading.Event:
        return self.gates.setdefault(name, threading.Event())

    def sql(self, database, server, db_name, progress_callback=None, **_kwargs) -> dict:
        assert self.gate(db_name).wait(timeout=5)
        return {"database": db_name}

    def failing_sql(self, database, server, db_name, **_kwargs) -> dict:
        raise RuntimeError("database unavailable")


def submit_sql(database: str) -> dict:
    response = client.post(
        "/refresh_sql", json={"database": database, "server": SERVER, "db_name": database}
    )
    assert response.status_code == 200
    return response.json()


def wait_for(job_id: str, *states: str) -> dict:
    gate = threading.Event()
    job: dict = {}
    for _ in range(200):
        job = client.get(f"/refresh_jobs/{job_id}").json()
        if job["status"] in states:
            return job
        gate.wait(0.025)
    raise AssertionError(f"job {job_id} never reached {states}; last: {job}")


def test_a_cache_with_a_running_job_lists_as_refreshing_under_every_system(
    world, sql_root, monkeypatch
) -> None:
    write_sql(sql_root, "SharedDb")
    fake = GatedRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    job = submit_sql("SharedDb")
    wait_for(job["job_id"], "running")

    listed = listing()

    assert listed["Alpha"]["SharedDb"]["freshness"] == "refreshing"
    assert listed["Beta"]["SharedDb"]["freshness"] == "refreshing"
    assert listed["Alpha"]["SharedDb"]["last_job"]["job_id"] == job["job_id"]
    assert listed["Alpha"]["SharedDb"]["last_job"]["status"] == "running"
    fake.gate("SharedDb").set()
    wait_for(job["job_id"], "succeeded")


def test_a_cache_with_only_a_waiting_job_keeps_its_state_and_shows_the_queue_position(
    world, sql_root, monkeypatch
) -> None:
    write_sql(sql_root, "SharedDb")
    fake = GatedRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    running = submit_sql("AlphaDb")
    wait_for(running["job_id"], "running")
    waiting = submit_sql("SharedDb")

    row = listing()["Alpha"]["SharedDb"]

    assert row["freshness"] == "current"
    assert row["last_job"]["job_id"] == waiting["job_id"]
    assert row["last_job"]["status"] == "waiting"
    assert row["last_job"]["queue_position"] == 1
    fake.gate("AlphaDb").set()
    fake.gate("SharedDb").set()
    wait_for(waiting["job_id"], "succeeded")


def test_a_failed_job_keeps_the_previous_state_and_shows_its_error(
    world, sql_root, monkeypatch
) -> None:
    write_sql(sql_root, "SharedDb")
    monkeypatch.setattr(analyze_service, "refresh_sql_source", GatedRebuild().failing_sql)
    job = submit_sql("SharedDb")
    wait_for(job["job_id"], "failed")

    row = listing()["Alpha"]["SharedDb"]

    assert row["freshness"] == "current"
    assert row["last_job"]["status"] == "failed"
    assert row["last_job"]["error"] == "database unavailable"


def test_a_c_sharp_job_makes_the_system_row_refreshing(world, monkeypatch) -> None:
    gate = threading.Event()

    def slow_refresh(source, **_kwargs) -> dict:
        assert gate.wait(timeout=5)
        return {}

    monkeypatch.setattr(analyze_service, "refresh_source", slow_refresh)
    job = client.post(
        "/refresh",
        json={"system": "Alpha", "source": {"project": "P", "repo": "AlphaRepo"}},
    ).json()
    wait_for(job["job_id"], "running")

    row = listing()["Alpha"]["Alpha"]

    assert row["freshness"] == "refreshing"
    gate.set()
    wait_for(job["job_id"], "succeeded")

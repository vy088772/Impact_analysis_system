"""Ticket 04 of `.scratch/cache-refresh-queue/`: a question reports an unusable cache.

The seam is the Impact HTTP API, through the FastAPI test client. A cache that a question
needs is `outdated` or `refreshing`: the endpoint reports it in `unusable_caches` and reads
nothing from it. No test case lets a question scan a repository, clone, or connect to SQL Server.
"""

from __future__ import annotations

import json
import threading

import pytest

from service import analyze_service, scan_store
from tests.test_cache_freshness_api import (  # noqa: F401  (fixtures and helpers)
    SERVER,
    GatedRebuild,
    client,
    fresh_queue,
    scan_root,
    sql_root,
    wait_for,
    world,
    write_sql,
)

SOURCE = {"project": "P", "repo": "AlphaRepo"}


@pytest.fixture(autouse=True)
def no_rebuild_allowed(world, monkeypatch):
    """Any scan, any clone and any SQL connection during a question fails the test."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a question must never rebuild a cache")

    class ForbiddenScanner:
        def __init__(self, *_args, **_kwargs) -> None:
            forbidden()

    monkeypatch.setattr(scan_store, "ProjectScanner", ForbiddenScanner)
    monkeypatch.setattr(scan_store, "rebuild_scan", forbidden)
    monkeypatch.setattr(analyze_service, "refresh_sql_source", forbidden)
    monkeypatch.setattr(analyze_service, "refresh_source", forbidden)
    monkeypatch.setattr("service.repo_manager._clone_or_pull", forbidden)


def make_scan_old_format() -> None:
    scan_store._mem_cache.clear()
    _, meta = scan_store._paths(scan_root("AlphaRepo"))
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["cache_version"] = scan_store._CACHE_VERSION - 1
    meta.write_text(json.dumps(info), encoding="utf-8")


def build_scan() -> None:
    """Save one usable scan directly: the autouse guard forbids the scanner."""
    from datetime import datetime

    from code_analyzer.project_scanner import ProjectScanResult

    root = scan_root("AlphaRepo")
    scan_store.save_scan(
        root, ProjectScanResult(project_root=str(root), project_name="fake", scan_time=datetime.now())
    )


def lookup_body(**fields) -> dict:
    return {"source": SOURCE, "database": "AlphaDb", "db_server": SERVER, **fields}


QUESTIONS = {
    "find_by_sp": ("/find_by_sp", lookup_body(sp_name="usp_Save")),
    "find_by_table": ("/find_by_table", lookup_body(table_name="Orders")),
    "flow_chain_backward": ("/flow_chain", lookup_body(direction="backward", table_name="Orders")),
    "flow_chain_forward": (
        "/flow_chain",
        lookup_body(direction="forward", program_name="OrderPage", anchor_method="Load"),
    ),
    "analyze": ("/analyze", lookup_body(program_names=["OrderPage"])),
}


@pytest.mark.parametrize("question", QUESTIONS)
def test_an_old_format_scan_is_reported_as_outdated_and_never_rebuilt(question: str, sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()
    make_scan_old_format()
    path, body = QUESTIONS[question]

    response = client.post(path, json=body)

    assert response.status_code == 200
    reported = response.json()["unusable_caches"]
    assert [(cache["kind"], cache["state"]) for cache in reported] == [("csharp", "outdated")]
    assert reported[0]["key"].startswith("csharp:")
    assert response.json().get("skipped", False) is False


@pytest.mark.parametrize("question", QUESTIONS)
def test_a_missing_scan_is_reported_as_outdated_by_a_question_that_needs_it(
    question: str, sql_root
) -> None:
    """Only a lookup that is allowed to skip answers "not scanned"; the others report `outdated`."""
    write_sql(sql_root, "AlphaDb")
    path, body = QUESTIONS[question]
    body = {**body, "cache_only": False} if question != "analyze" else body

    response = client.post(path, json=body)

    assert response.status_code == 200
    assert [cache["state"] for cache in response.json()["unusable_caches"]] == ["outdated"]


def test_a_cache_only_lookup_with_no_scan_at_all_still_skips_as_not_scanned(sql_root) -> None:
    write_sql(sql_root, "AlphaDb")

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save"))

    assert response.status_code == 200
    assert response.json()["skipped"] is True
    assert response.json()["unusable_caches"] == []


def test_a_refresh_flag_on_a_question_does_not_rebuild(sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()
    make_scan_old_format()

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save", refresh=True))

    assert response.status_code == 200
    assert response.json()["unusable_caches"][0]["state"] == "outdated"


def test_a_scan_with_a_running_job_is_reported_as_refreshing_even_when_usable(
    sql_root, monkeypatch
) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()
    gate = threading.Event()

    def slow_refresh(source, **_kwargs) -> dict:
        assert gate.wait(timeout=5)
        return {}

    monkeypatch.setattr(analyze_service, "refresh_source", slow_refresh)
    job = client.post("/refresh", json={"system": "Alpha", "source": SOURCE}).json()
    wait_for(job["job_id"], "running")

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save"))

    assert [(c["kind"], c["state"]) for c in response.json()["unusable_caches"]] == [("csharp", "refreshing")]
    gate.set()
    wait_for(job["job_id"], "succeeded")


def test_an_old_format_sql_cache_is_reported_as_outdated_with_its_server_and_database(sql_root) -> None:
    write_sql(sql_root, "AlphaDb", cache_version=1)
    build_scan()

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save"))

    assert response.status_code == 200
    [cache] = response.json()["unusable_caches"]
    assert (cache["kind"], cache["state"], cache["database"]) == ("sql", "outdated", "AlphaDb")
    assert cache["server"] == SERVER


def test_a_sql_cache_with_a_running_job_is_reported_as_refreshing(sql_root, monkeypatch) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()
    fake = GatedRebuild()
    monkeypatch.setattr(analyze_service, "refresh_sql_source", fake.sql)
    job = client.post(
        "/refresh_sql", json={"database": "AlphaDb", "server": SERVER, "db_name": "AlphaDb"}
    ).json()
    wait_for(job["job_id"], "running")

    response = client.post("/find_by_table", json=lookup_body(table_name="Orders"))

    assert [(c["kind"], c["state"]) for c in response.json()["unusable_caches"]] == [("sql", "refreshing")]
    fake.gate("AlphaDb").set()
    wait_for(job["job_id"], "succeeded")


def test_a_sql_cache_that_was_never_scanned_keeps_the_not_scanned_409(sql_root) -> None:
    build_scan()

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save"))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sql_execution_graph_required"


def test_a_usable_cache_reports_nothing(sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()

    response = client.post("/find_by_sp", json=lookup_body(sp_name="usp_Save"))

    assert response.status_code == 200
    assert response.json()["unusable_caches"] == []
    assert response.json()["skipped"] is False


def test_path_evidence_answers_409_with_the_unusable_caches(sql_root) -> None:
    write_sql(sql_root, "AlphaDb")
    build_scan()
    make_scan_old_format()

    response = client.post(
        "/path_evidence", json={**lookup_body(), "path_id": "p1", "program_names": ["OrderPage"]}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "cache_unusable"
    assert [(c["kind"], c["state"]) for c in detail["caches"]] == [("csharp", "outdated")]

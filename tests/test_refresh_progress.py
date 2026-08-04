"""Focused checks for SQL refresh progress state."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import refresh_progress
from service import analyze_service, api
from service.schemas import RefreshSqlProgressResponse, RefreshSqlRequest


def test_refresh_progress_lifecycle() -> None:
    job_id = refresh_progress.create_job("progress-test-job", "TestDb")
    started = refresh_progress.get_job(job_id)
    assert started is not None
    assert started["status"] == "starting"
    assert started["stage"] == "connecting"

    refresh_progress.update_job(
        job_id,
        status="running",
        stage="procedures",
        current=3,
        total=10,
        item="usp_SaveOrder",
    )
    running = refresh_progress.get_job(job_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["current"] == 3
    assert running["total"] == 10
    assert running["item"] == "usp_SaveOrder"

    refresh_progress.complete_job(job_id)
    completed = refresh_progress.get_job(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["stage"] == "completed"


def test_unknown_refresh_progress_job_is_ignored() -> None:
    refresh_progress.update_job("missing-progress-job", current=1, total=1)
    assert refresh_progress.get_job("missing-progress-job") is None


def test_refresh_progress_completion_preserves_final_counts() -> None:
    job_id = refresh_progress.create_job("progress-counts-job", "TestDb")
    refresh_progress.update_job(
        job_id,
        status="running",
        stage="procedures",
        current=3,
        total=10,
    )

    refresh_progress.complete_job(job_id)
    completed = refresh_progress.get_job(job_id)

    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["current"] == 10
    assert completed["total"] == 10


def test_refresh_progress_terminal_state_cannot_be_reopened() -> None:
    job_id = refresh_progress.create_job("progress-terminal-job", "TestDb")
    refresh_progress.update_job(job_id, status="running", stage="procedures", current=3, total=10)
    refresh_progress.fail_job(job_id, "database unavailable")

    refresh_progress.update_job(
        job_id,
        status="running",
        stage="tables",
        current=9,
        total=10,
        error="",
    )
    failed = refresh_progress.get_job(job_id)

    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["stage"] == "failed"
    assert failed["current"] == 3
    assert failed["total"] == 10
    assert failed["error"] == "database unavailable"


def test_refresh_progress_reusing_terminal_job_id_does_not_reopen_job() -> None:
    job_id = refresh_progress.create_job("progress-reused-job", "TestDb")
    refresh_progress.fail_job(job_id, "database unavailable")

    assert refresh_progress.create_job(job_id, "OtherDb") == job_id
    preserved = refresh_progress.get_job(job_id)

    assert preserved is not None
    assert preserved["database"] == "TestDb"
    assert preserved["status"] == "failed"
    assert preserved["error"] == "database unavailable"


def test_refresh_progress_rejects_unknown_status() -> None:
    job_id = refresh_progress.create_job("progress-invalid-status-job", "TestDb")

    try:
        refresh_progress.update_job(job_id, status="paused")
    except ValueError as exc:
        assert str(exc) == "unsupported refresh progress status: paused"
    else:
        raise AssertionError("unknown progress status should be rejected")


def test_refresh_progress_store_remains_bounded_for_active_jobs(monkeypatch) -> None:
    monkeypatch.setattr(refresh_progress, "_SNAPSHOTS", {})
    monkeypatch.setattr(refresh_progress, "_MAX_SNAPSHOTS", 2)

    first = refresh_progress.create_job("bounded-job-1", "TestDb")
    second = refresh_progress.create_job("bounded-job-2", "TestDb")
    third = refresh_progress.create_job("bounded-job-3", "TestDb")

    assert refresh_progress.get_job(first) is None
    assert refresh_progress.get_job(second) is not None
    assert refresh_progress.get_job(third) is not None


def test_refresh_sql_route_marks_failed_job(monkeypatch) -> None:
    def fail_refresh(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(analyze_service, "refresh_sql_source", fail_refresh)

    try:
        api.refresh_sql(
            RefreshSqlRequest(
                database="OrdersDb",
                server="sql-server",
                db_name="Orders",
                job_id="api-failed-progress-job",
            )
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 500
    else:
        raise AssertionError("refresh_sql should expose the refresh failure")

    failed = refresh_progress.get_job("api-failed-progress-job")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["stage"] == "failed"
    assert failed["error"] == "database unavailable"


def test_refresh_sql_status_returns_stable_response_shape() -> None:
    job_id = refresh_progress.create_job("api-status-progress-job", "OrdersDb")

    response = api.refresh_sql_status(job_id)

    assert isinstance(response, RefreshSqlProgressResponse)
    assert response.job_id == job_id
    assert response.database == "OrdersDb"
    assert response.status == "starting"
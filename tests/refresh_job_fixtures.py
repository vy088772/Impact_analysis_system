"""Shared helper for tests that call a refresh route and need the finished Refresh Job.

`/refresh` and `/refresh_sql` submit a Refresh Job and return it at once. A test that checks what
the rebuild did waits for the job to end here.
"""

from __future__ import annotations

from service import refresh_progress, refresh_queue
from service.schemas import RefreshJobResponse


def finished(job: RefreshJobResponse, timeout: float = 10.0) -> dict:
    """Wait for the job to end, and return its final record."""
    assert isinstance(job, RefreshJobResponse), "the route should return a Refresh Job"
    done = refresh_queue.shared_queue.wait_until_finished(job.job_id, timeout=timeout)
    assert done is not None
    assert done["status"] in refresh_progress.TERMINAL_STATUSES, f"job did not end: {done}"
    return done


def succeeded(job: RefreshJobResponse, timeout: float = 10.0) -> dict:
    """Wait for the job and return its result. Fail the test when the job did not succeed."""
    done = finished(job, timeout)
    assert done["status"] == "succeeded", done["error"]
    return done["result"]

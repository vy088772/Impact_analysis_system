"""The Refresh Queue: one ordered line of Refresh Jobs, run one at a time (Impact ADR-0045).

The queue lives in memory. A restart of the Impact service drops the waiting jobs.
One worker thread runs the jobs in the order that they arrive.

A job is keyed by its cache identity: `sql_key()` for a SQL cache, `csharp_key()` for a C# Scan Result.
A submit for a key that already waits or runs returns the existing job. The first request wins:
the options of a later duplicate submit do not change a job that waits or runs.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import refresh_progress

ProgressCallback = Callable[[str, int, int, str], None]
RefreshRun = Callable[[ProgressCallback], dict]


def sql_key(identity_key: str) -> str:
    return f"sql:{identity_key}"


def csharp_key(scan_roots: Iterable[str]) -> str:
    return "csharp:" + "|".join(scan_roots)


CANCELLED = "cancelled"
RUNNING = "running"
NOT_FOUND = "not_found"
FINISHED = "finished"


@dataclass(frozen=True)
class _Pending:
    job_id: str
    key: str
    run: RefreshRun


class RefreshQueue:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._waiting: deque[_Pending] = deque()
        self._running: _Pending | None = None
        self._active_by_key: dict[str, str] = {}
        self._worker: threading.Thread | None = None

    def submit(
        self,
        *,
        key: str,
        kind: str,
        database: str,
        run: RefreshRun,
        job_id: str = "",
    ) -> dict[str, Any]:
        with self._condition:
            existing_id = self._active_by_key.get(key)
            if existing_id is not None:
                return self._snapshot_locked(existing_id)
            if job_id and refresh_progress.get_job(job_id) is not None:
                job_id = ""  # an id that a past job used must not point at that job's record
            new_id = refresh_progress.create_job(job_id, database, kind=kind, key=key)
            self._waiting.append(_Pending(new_id, key, run))
            self._active_by_key[key] = new_id
            self._ensure_worker_locked()
            self._condition.notify_all()
            return self._snapshot_locked(new_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._condition:
            return self._snapshot_locked(job_id)

    def cancel(self, job_id: str) -> str:
        """Cancel a waiting job. A running job is refused: a stop can leave a partly written cache."""
        with self._condition:
            if refresh_progress.get_job(job_id) is None:
                return NOT_FOUND
            if self._running is not None and self._running.job_id == job_id:
                return RUNNING
            for pending in self._waiting:
                if pending.job_id == job_id:
                    self._waiting.remove(pending)
                    self._active_by_key.pop(pending.key, None)
                    refresh_progress.cancel_job(job_id)
                    self._condition.notify_all()
                    return CANCELLED
            return FINISHED

    def wait_until_finished(self, job_id: str, timeout: float = 10.0) -> dict[str, Any] | None:
        """Block until the job ends. Tests and callers that need a result use it."""
        with self._condition:
            self._condition.wait_for(
                lambda: (snapshot := refresh_progress.get_job(job_id)) is None
                or snapshot["status"] in refresh_progress.TERMINAL_STATUSES,
                timeout=timeout,
            )
            return self._snapshot_locked(job_id)

    def _snapshot_locked(self, job_id: str) -> dict[str, Any] | None:
        snapshot = refresh_progress.get_job(job_id)
        if snapshot is None:
            return None
        snapshot["queue_position"] = self._position_locked(job_id)
        return snapshot

    def _position_locked(self, job_id: str) -> int:
        """1 for the next job to run. 0 for a job that runs now or has ended."""
        for index, pending in enumerate(self._waiting, start=1):
            if pending.job_id == job_id:
                return index
        return 0

    def _ensure_worker_locked(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._work, name="refresh-queue-worker", daemon=True
            )
            self._worker.start()

    def _work(self) -> None:
        while True:
            with self._condition:
                if not self._waiting:
                    # Exit under the lock, so a racing submit starts a new worker.
                    self._worker = None
                    return
                pending = self._waiting.popleft()
                self._running = pending
                refresh_progress.update_job(
                    pending.job_id, status=RUNNING, stage="starting", message="開始執行"
                )
                self._condition.notify_all()
            self._run_one(pending)

    def _run_one(self, pending: _Pending) -> None:
        def report(stage: str, current: int, total: int, item: str) -> None:
            refresh_progress.update_job(
                pending.job_id,
                status=RUNNING,
                stage=stage,
                current=current,
                total=total,
                item=item,
                message=f"{stage} {current}/{total}",
            )

        error: str | None = None
        result: dict = {}
        try:
            result = pending.run(report)
        except BaseException as exc:  # noqa: BLE001 - every failure, even SystemExit, ends the job and never the worker
            error = str(exc) or type(exc).__name__
        with self._condition:
            if error is None:
                refresh_progress.complete_job(pending.job_id, result=result)
            else:
                refresh_progress.fail_job(pending.job_id, error)
            self._running = None
            self._active_by_key.pop(pending.key, None)
            self._condition.notify_all()


shared_queue = RefreshQueue()

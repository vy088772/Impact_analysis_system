"""Thread-safe in-memory progress state for SQL cache refresh jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from threading import Lock
import time
import uuid
from typing import Any


@dataclass(frozen=True)
class ProgressSnapshot:
    job_id: str
    database: str
    status: str
    stage: str
    current: int
    total: int
    item: str
    message: str
    error: str
    updated_at: float


_MAX_SNAPSHOTS = 100
_TERMINAL_STATUSES = frozenset({"completed", "failed"})
_VALID_STATUSES = frozenset({"starting", "running", "completed", "failed"})
_LOCK = Lock()
_SNAPSHOTS: dict[str, ProgressSnapshot] = {}


def create_job(job_id: str | None, database: str) -> str:
    normalized_id = (job_id or "").strip() or uuid.uuid4().hex
    snapshot = ProgressSnapshot(
        job_id=normalized_id,
        database=database,
        status="starting",
        stage="connecting",
        current=0,
        total=1,
        item="",
        message="準備連線 SQL Server",
        error="",
        updated_at=time.time(),
    )
    with _LOCK:
        if normalized_id in _SNAPSHOTS:
            return normalized_id
        _SNAPSHOTS[normalized_id] = snapshot
        _prune_locked()
    return normalized_id


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    current: int | None = None,
    total: int | None = None,
    item: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> None:
    with _LOCK:
        snapshot = _SNAPSHOTS.get(job_id)
        if snapshot is None or snapshot.status in _TERMINAL_STATUSES:
            return
        if status is not None and status not in _VALID_STATUSES:
            raise ValueError(f"unsupported refresh progress status: {status}")
        next_total = snapshot.total if total is None else max(0, total)
        next_current = snapshot.current if current is None else max(0, current)
        next_total = max(next_total, next_current)
        _SNAPSHOTS[job_id] = replace(
            snapshot,
            status=snapshot.status if status is None else status,
            stage=snapshot.stage if stage is None else stage,
            current=next_current,
            total=next_total,
            item=snapshot.item if item is None else item,
            message=snapshot.message if message is None else message,
            error=snapshot.error if error is None else error,
            updated_at=time.time(),
        )


def complete_job(
    job_id: str,
    message: str = "SQL refresh 工作已完成；正式 Graph readiness 仍由查詢邊界驗證",
) -> None:
    with _LOCK:
        snapshot = _SNAPSHOTS.get(job_id)
        if snapshot is None or snapshot.status in _TERMINAL_STATUSES:
            return
        total = max(snapshot.total, snapshot.current, 1)
        _SNAPSHOTS[job_id] = replace(
            snapshot,
            status="completed",
            stage="completed",
            current=total,
            total=total,
            item="",
            message=message,
            error="",
            updated_at=time.time(),
        )


def fail_job(job_id: str, error: str) -> None:
    with _LOCK:
        snapshot = _SNAPSHOTS.get(job_id)
        if snapshot is None or snapshot.status in _TERMINAL_STATUSES:
            return
        _SNAPSHOTS[job_id] = replace(
            snapshot,
            status="failed",
            stage="failed",
            message="SQL 快取更新失敗",
            error=error,
            updated_at=time.time(),
        )


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        snapshot = _SNAPSHOTS.get(job_id)
        return asdict(snapshot) if snapshot is not None else None


def _prune_locked() -> None:
    limit = max(1, int(_MAX_SNAPSHOTS))
    overflow = len(_SNAPSHOTS) - limit
    if overflow <= 0:
        return
    completed = sorted(
        (
            snapshot
            for snapshot in _SNAPSHOTS.values()
            if snapshot.status in {"completed", "failed"}
        ),
        key=lambda snapshot: (snapshot.updated_at, snapshot.job_id),
    )
    for snapshot in completed[:overflow]:
        _SNAPSHOTS.pop(snapshot.job_id, None)

    overflow = len(_SNAPSHOTS) - limit
    if overflow <= 0:
        return
    active = sorted(
        _SNAPSHOTS.values(),
        key=lambda snapshot: (snapshot.updated_at, snapshot.job_id),
    )
    for snapshot in active[:overflow]:
        _SNAPSHOTS.pop(snapshot.job_id, None)
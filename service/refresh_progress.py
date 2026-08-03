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
        if snapshot is None:
            return
        _SNAPSHOTS[job_id] = replace(
            snapshot,
            status=snapshot.status if status is None else status,
            stage=snapshot.stage if stage is None else stage,
            current=snapshot.current if current is None else current,
            total=snapshot.total if total is None else total,
            item=snapshot.item if item is None else item,
            message=snapshot.message if message is None else message,
            error=snapshot.error if error is None else error,
            updated_at=time.time(),
        )


def complete_job(job_id: str, message: str = "SQL 快取與 Execution Graph 已完成") -> None:
    update_job(
        job_id,
        status="completed",
        stage="completed",
        current=1,
        total=1,
        item="",
        message=message,
        error="",
    )


def fail_job(job_id: str, error: str) -> None:
    update_job(
        job_id,
        status="failed",
        stage="failed",
        message="SQL 快取更新失敗",
        error=error,
    )


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        snapshot = _SNAPSHOTS.get(job_id)
        return asdict(snapshot) if snapshot is not None else None


def _prune_locked() -> None:
    if len(_SNAPSHOTS) <= _MAX_SNAPSHOTS:
        return
    completed = sorted(
        (
            snapshot
            for snapshot in _SNAPSHOTS.values()
            if snapshot.status in {"completed", "failed"}
        ),
        key=lambda snapshot: snapshot.updated_at,
    )
    for snapshot in completed[: max(0, len(_SNAPSHOTS) - _MAX_SNAPSHOTS)]:
        _SNAPSHOTS.pop(snapshot.job_id, None)
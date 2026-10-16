"""Progress of a Derived Execution Evidence derivation that a question runs (Impact ADR-0045).

A question never rebuilds a cache, but it still derives Derived Execution Evidence when no valid
evidence exists. That derivation reads the existing caches only. While it runs, the service
reports the stage here, and `GET /derivation_progress` shows it, so the web page does not wait
in silence.

A Refresh Job derives evidence as its own last stage and reports it through the job progress.
Inside a Refresh Job this module stays silent, so the page never shows the same work twice.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

DERIVING_EVIDENCE = "deriving_evidence"

_lock = threading.Lock()
_active: dict[int, dict[str, Any]] = {}
_next_token = 0
_local = threading.local()


@contextmanager
def inside_refresh_job() -> Iterator[None]:
    """Mark the current thread as a Refresh Job's derivation stage."""
    previous = getattr(_local, "in_refresh_job", False)
    _local.in_refresh_job = True
    try:
        yield
    finally:
        _local.in_refresh_job = previous


def in_refresh_job() -> bool:
    return bool(getattr(_local, "in_refresh_job", False))


@contextmanager
def question_derivation(database: str) -> Iterator[None]:
    """Report the stage while a question derives evidence. Silent inside a Refresh Job."""
    global _next_token
    if in_refresh_job():
        yield
        return
    with _lock:
        _next_token += 1
        token = _next_token
        _active[token] = {
            "stage": DERIVING_EVIDENCE,
            "database": database,
            "started_at": time.time(),
        }
    try:
        yield
    finally:
        with _lock:
            _active.pop(token, None)


def active() -> list[dict[str, Any]]:
    """The derivations that questions run now, oldest first."""
    with _lock:
        return sorted(_active.values(), key=lambda entry: entry["started_at"])

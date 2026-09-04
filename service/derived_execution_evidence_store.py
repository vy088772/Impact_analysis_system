# service/derived_execution_evidence_store.py
"""Disk-backed retention for Derived Execution Evidence (ADR-0013, ADR-0017).

Extends the in-memory retention `analyze_service._rated_invocations_retention`
already builds (ticket 04/05) with a second tier on disk, so a scope derived
once is read back after a process restart and after an in-memory eviction,
instead of being derived again -- see ADR-0017. Same design as
`scan_store.py`/`sql_cache_store.py`: one file per identity (here, per
`DerivedExecutionEvidenceScope`), replaced in place on every cold derivation.

The freshness rule is not reimplemented here. What is stored alongside the
payload is the exact `_RatedInvocationsValidityStamp` analyze_service already
computes and compares in memory; this module's only job is to get that value
and the payload it goes with onto disk and back, byte for byte. Pickling the
stamp as-is -- rather than re-encoding it to JSON -- is what makes this work
for free: a stamp field that was an "unreadable input" sentinel (a bare
`object()`, see `analyze_service._freshness_or_sentinel`) unpickles into a new
`object()` instance, and a fresh `object()` never equals anything, including
another unpickled copy of the same original -- so "missing never matches",
the rule ticket 05 established for the in-memory comparison, holds here too
with no special-case code.

Concurrency: two requests can race to derive one new scope. Both are allowed
to run and both are allowed to write, because their results are equal (same
inputs, same pure derivation). `store()` never takes a lock -- a lock would
hold a request thread while another derivation ran -- and instead writes a
process-and-call-unique temporary file, then `os.replace()`s it onto the
target. `os.replace` is atomic on the same filesystem, so a concurrent reader
either sees the previous complete file or the new complete file, never a
partial one, and the second writer to finish simply overwrites the first
writer's (equal) result.

Do not key the file by anything but the scope (see the ticket's notes): a key
that also folded in the table or procedure name asked about would multiply
the files per scope and contradict the decision (ADR-0013) that one
derivation serves every object asked within a scope.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from config.settings import settings

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from service.analyze_service import (
        DerivedExecutionEvidenceScope,
        _RatedInvocationsValidityStamp,
    )
    from code_analyzer.csharp_analysis_gateway import DbInvocation

# Payload format version: bump when the shape of `_StoredDerivedExecutionEvidence`
# or of any pickled field inside it changes, so an old on-disk file left by a
# previous version of this module is treated as unreadable (a miss) rather
# than unpickled into an object this version does not expect.
_STORE_VERSION = 1

_DATA_SUFFIX = ".pkl"


@dataclass
class _StoredDerivedExecutionEvidence:
    """Exactly what one scope's disk file holds: version, stamp, and payload.

    `execution_paths` mirrors `analyze_service._RetainedRatedInvocations`:
    `None` means "not built yet for this entry" -- a scope that has only ever
    answered `find_by_sp()` questions never populates it, on disk any more
    than in memory.
    """

    store_version: int
    stamp: "_RatedInvocationsValidityStamp"
    rated_invocations: List["DbInvocation"]
    graph: Dict[str, object]
    execution_paths: Optional[List[Dict[str, object]]]


def _store_root() -> Path:
    root = Path(settings.DERIVED_EXECUTION_EVIDENCE_STORE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _key(scope: "DerivedExecutionEvidenceScope") -> str:
    """A stable, filesystem-safe identity for `scope` alone.

    Built from exactly the fields `DerivedExecutionEvidenceScope` declares
    (repo_roots, database, db_server, db_name, wrapper_contract) -- nothing
    a request carries beyond that, matching the scope's own equality.
    """
    canonical = repr(
        (
            scope.repo_roots,
            scope.database,
            scope.db_server,
            scope.db_name,
            scope.wrapper_contract,
        )
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:24]


def _path(scope: "DerivedExecutionEvidenceScope") -> Path:
    return _store_root() / f"{_key(scope)}{_DATA_SUFFIX}"


def load(scope: "DerivedExecutionEvidenceScope") -> Optional[_StoredDerivedExecutionEvidence]:
    """Read scope's stored evidence, or `None` for anything short of a valid file.

    Missing, unreadable, truncated, or a different `_STORE_VERSION` all fall
    into the same `None` -- the caller derives instead of erroring, exactly
    like `scan_store._load()`/`sql_cache_store._load()` already treat a bad
    cache file as a cache miss rather than a failure.
    """
    path = _path(scope)
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            stored = pickle.load(f)
    except Exception:
        return None
    if not isinstance(stored, _StoredDerivedExecutionEvidence):
        return None
    if stored.store_version != _STORE_VERSION:
        return None
    return stored


def store(
    scope: "DerivedExecutionEvidenceScope",
    stamp: "_RatedInvocationsValidityStamp",
    rated_invocations: List["DbInvocation"],
    graph: Dict[str, object],
    execution_paths: Optional[List[Dict[str, object]]],
) -> None:
    """Atomically replace scope's stored evidence with what was just derived.

    Called on every cold derivation (a disk miss, a stamp mismatch, or an
    explicit refresh) and again whenever Execution Paths are built for a
    scope whose stored evidence did not carry them yet -- so a scope that
    starts out answering only `find_by_sp()` questions still ends up with a
    complete file once a `find_by_table()` question is asked of it.

    Write failure is printed and otherwise swallowed, the same non-fatal
    handling `scan_store._save()`/`sql_cache_store._save()` already use: a
    disk-write problem must not fail the request that already has its answer
    in hand, only cost the next request its reuse.
    """
    root = _store_root()
    target = _path(scope)
    # Unique per process and per call, in the same directory as the target so
    # the final `os.replace` is a same-filesystem rename -- the property that
    # makes it atomic. Uniqueness (pid + a random suffix) means two concurrent
    # writers for the same scope never collide on the temporary file itself,
    # even though they do race to `os.replace` onto the same target.
    tmp = root / f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    payload = _StoredDerivedExecutionEvidence(
        store_version=_STORE_VERSION,
        stamp=stamp,
        rated_invocations=rated_invocations,
        graph=graph,
        execution_paths=execution_paths,
    )
    try:
        with tmp.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, target)
    except Exception as exc:  # 寫檔失敗不致命
        print(f"⚠️  Derived Execution Evidence 磁碟快取寫出失敗（非致命）：{exc}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


__all__ = [
    "load",
    "store",
]

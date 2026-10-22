"""Derived Execution Evidence and the Refresh Queue (Impact ADR-0045).

An analyst never refreshes Derived Execution Evidence, so it has no Cache Freshness and no button.
Two things keep it ready before a question asks for it:

- The last stage of each Refresh Job derives the evidence of each scope that the rebuilt cache
  feeds (`then_derive`). The next question reads it and does not derive again.
- An edit of one of the three configuration inputs (the wrapper contract, the contract registry,
  the wrapper review exclusions) submits a Refresh Job for each affected scope. The service
  notices the edit when it starts (`check_config_at_start`) and when a question reads the
  configuration (`observe_config`).

If a question still finds no valid evidence, it derives it as before and reports a stage
(`derivation_progress`). A question never uses evidence with an old Validity Stamp (ADR-0013).

A catalog system yields the scopes that the spec-rag client builds for it: the scope of an
`/analyze` or `/path_evidence` request (the first declared Database, with its name as `db_name`),
and the scope of a lookup, one for each declared Database (no `db_name`). A scope that the catalog
does not name cannot be derived ahead; a question derives it.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import (
    derivation_progress,
    derived_execution_evidence,
    refresh_queue,
    repo_manager,
    sql_cache_store,
    system_targets,
)
from .derived_execution_evidence import DerivedExecutionEvidenceScope, RatingConfig
from .request_context import cache_identity_of, evidence_root, merge_scans
from .request_context_adapters import RealCacheStore, RealScanStore
from .scan_store import ScanOutdated
from .schemas import AnalyzeRequest, AzureSource, FindBySPRequest

ProgressCallback = Callable[[str, int, int, str], None]

DERIVED = "derived"
SKIPPED = "skipped"

logger = logging.getLogger(__name__)


def catalog_systems() -> List[dict]:
    """Every System the catalog declares. Tests replace this to name their own catalog."""
    return system_targets.load_system_catalog(system_targets.default_spec_rag_root())


@dataclass(frozen=True)
class Target:
    """One scope that a catalog system asks about, with the request that builds it."""

    system_id: str
    source: Dict[str, Any]
    database: str
    db_server: str
    db_name: str
    wrapper_contract: str
    shape: str  # "analyze" or "lookup"

    @property
    def label(self) -> str:
        return f"{self.system_id}:{self.shape}:{self.db_server}/{self.database}"

    def request(self) -> object:
        source = AzureSource(
            project=str(self.source.get("project") or ""),
            repo=str(self.source.get("repo") or ""),
            branch=str(self.source.get("branch") or ""),
            path=self.source.get("path") or "",
        )
        if self.shape == "analyze":
            return AnalyzeRequest(
                program_names=[], source=source, database=self.database,
                db_server=self.db_server, db_name=self.db_name,
                wrapper_contract=self.wrapper_contract,
            )
        return FindBySPRequest(
            sp_name="", source=source, database=self.database, db_server=self.db_server,
            wrapper_contract=self.wrapper_contract, cache_only=False,
        )

    def roots(self) -> List[Path]:
        return repo_manager.peek_scan_roots(self.source)

    def sql_key(self) -> Optional[str]:
        """The Refresh Queue key of the SQL cache this scope reads, or None when it names none."""
        try:
            return refresh_queue.sql_key(sql_cache_store.CacheIdentity.of(self.db_server, self.database).key)
        except ValueError:
            return None

    def scope(self) -> DerivedExecutionEvidenceScope:
        request = self.request()
        identity = cache_identity_of(request, RealCacheStore())
        return DerivedExecutionEvidenceScope.of(
            request, self.roots(),
            identity if isinstance(identity, sql_cache_store.CacheIdentity) else None,
        )


def targets_of(system: dict) -> List[Target]:
    """The scopes of one catalog system, or none when it has no repository."""
    system_id = str(system.get("system_id") or "").strip()
    azure = system_targets.azure_source_of(system)
    if not system_id or azure is None:
        return []
    contract = system.get("wrapper_contract")
    contract = contract.strip() if isinstance(contract, str) else ""
    declared = [
        (str(item.get("server") or ""), str(item.get("name") or "").strip())
        for item in system.get("databases") or []
        if isinstance(item, dict)
    ]
    first_server, first_name = declared[0] if declared else ("", "")
    targets = [Target(system_id, azure, first_name or system_id, first_server, first_name, contract, "analyze")]
    seen: set[tuple[str, str]] = set()
    for server, name in declared:
        identity = (server.strip().casefold(), name.casefold())
        if name and identity not in seen:
            seen.add(identity)
            targets.append(Target(system_id, azure, name, server, "", contract, "lookup"))
    if not seen:
        targets.append(Target(system_id, azure, "", "", "", contract, "lookup"))
    return targets


def all_targets() -> List[Target]:
    return [target for system in catalog_systems() for target in targets_of(system)]


def targets_for_csharp(key: str) -> List[Target]:
    """The scopes that the C# Scan Result with this Refresh Queue key feeds."""
    return [
        target for target in all_targets()
        if refresh_queue.csharp_key(str(root) for root in target.roots()) == key
    ]


def targets_for_sql(key: str) -> List[Target]:
    """The scopes that the SQL cache with this Refresh Queue key feeds."""
    return [target for target in all_targets() if target.sql_key() == key]


def _derive_one(target: Target) -> str:
    """Derive the evidence of one scope from the caches on disk. Reads only; never scans."""
    store = RealScanStore()
    roots = target.roots()
    try:
        scans = [store.read_scan(root) for root in roots]
    except ScanOutdated:
        return SKIPPED
    scan = scans[0] if len(scans) == 1 else merge_scans(scans)
    root = evidence_root(roots, store.resolve_source(target.request()), store)
    derived_execution_evidence.evidence_for_scope(target.scope(), scans, scan, root)
    return DERIVED


def _empty_outcome() -> Dict[str, Any]:
    return {"derived": 0, "skipped": 0, "failed": []}


def derive_targets(targets: Iterable[Target], report: ProgressCallback) -> Dict[str, Any]:
    """The last stage of a Refresh Job: derive the evidence of each scope, as its own stage.

    A scope that cannot be derived (a cache is unusable, or the derivation fails) does not fail the
    job: the cache is already rebuilt, and a question derives that scope as before.
    """
    targets = list(targets)
    outcome = _empty_outcome()
    with derivation_progress.inside_refresh_job():
        report(derivation_progress.DERIVING_EVIDENCE, 0, len(targets), "")
        for index, target in enumerate(targets, start=1):
            report(derivation_progress.DERIVING_EVIDENCE, index, len(targets), target.label)
            try:
                outcome[_derive_one(target)] += 1
            except Exception as exc:  # noqa: BLE001 - one scope must not stop the others
                outcome["failed"].append({"scope": target.label, "error": str(exc) or type(exc).__name__})
    return outcome


def then_derive(
    run: Callable[[ProgressCallback], dict],
    affected_targets: Callable[[], Iterable[Target]],
) -> Callable[[ProgressCallback], dict]:
    """Wrap a rebuild so that derivation is its last stage. A failed rebuild derives nothing."""

    def wrapped(report: ProgressCallback) -> dict:
        result = run(report)
        try:
            targets = list(affected_targets())
        except Exception as exc:  # noqa: BLE001 - a catalog problem must not fail a finished rebuild
            outcome = _empty_outcome()
            outcome["failed"].append({"scope": "catalog", "error": str(exc)})
            return {**result, "derivation": outcome}
        return {**result, "derivation": derive_targets(targets, report)}

    return wrapped


# -- configuration edits ------------------------------------------------------------------------

_SEEN_LIMIT = 1024
_seen_lock = threading.Lock()
_seen: "OrderedDict[DerivedExecutionEvidenceScope, RatingConfig]" = OrderedDict()


def _remember(scope: DerivedExecutionEvidenceScope, config: RatingConfig) -> Optional[RatingConfig]:
    """Record the configuration last read for `scope`; return the one before it, if any."""
    with _seen_lock:
        previous = _seen.pop(scope, None)
        _seen[scope] = config
        while len(_seen) > _SEEN_LIMIT:
            _seen.popitem(last=False)
        return previous


def _submit_for(target: Target) -> None:
    refresh_queue.shared_queue.submit(
        key=refresh_queue.evidence_key(target.label),
        kind="evidence",
        database=target.system_id,
        run=lambda report: derive_targets([target], report),
    )


def observe_config(scope: DerivedExecutionEvidenceScope, config: RatingConfig) -> None:
    """A question read the configuration for `scope`. When it changed, refresh every affected scope.

    The baseline is the configuration read last, or the one the stored evidence was derived with.
    The question itself derives its own scope as before; the sweep runs in the background and
    submits a Refresh Job for each other scope that the edit changes.
    """
    if derivation_progress.in_refresh_job():
        return
    try:
        previous = _remember(scope, config)
        baseline = previous if previous is not None else derived_execution_evidence.recorded_config(scope)
        if baseline is not None and baseline != config:
            start_config_check()
    except Exception as exc:  # noqa: BLE001 - watching the configuration must never fail a question
        logger.warning("設定變更偵測失敗（非致命）：%s", exc)


_sweep_lock = threading.Lock()


def check_config_at_start() -> int:
    """Compare the stored evidence of each catalog scope with the configuration now.

    Submits a Refresh Job for each scope whose stored evidence was derived with other
    configuration. Returns the number of jobs submitted. A scope with no stored evidence has
    nothing to refresh. The service runs it when it starts and when a question reads changed
    configuration.
    """
    submitted = 0
    with _sweep_lock:
        for target in all_targets():
            scope = target.scope()
            config = derived_execution_evidence.rating_config_inputs(scope)
            _remember(scope, config)
            baseline = derived_execution_evidence.recorded_config(scope)
            if baseline is not None and baseline != config:
                _submit_for(target)
                submitted += 1
    return submitted


def install() -> None:
    """Watch the configuration that questions read."""
    derived_execution_evidence.config_read_observer = observe_config


def start_config_check() -> threading.Thread:
    """Run `check_config_at_start` in the background, so a question and the startup do not wait."""

    def run() -> None:
        try:
            check_config_at_start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("設定變更檢查失敗（非致命）：%s", exc)

    thread = threading.Thread(target=run, name="evidence-config-check", daemon=True)
    thread.start()
    return thread

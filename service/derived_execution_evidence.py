# service/derived_execution_evidence.py
"""Derived Execution Evidence for one scope (ADR-0013, ADR-0017).

Derived Execution Evidence is the full set of rated Database Invocations of one
scope, the SQL graph they join, and the Execution Paths built from them. This
module owns the scope, the validity stamp, the in-memory retention, its
eviction, and the calls to the disk store. An endpoint asks
`evidence_for_scope` for the evidence of its scope and filters the answer. It
reads no retention state itself, so the freshness rule lives here only.

The rating step itself (`analyze_service._rated_execution_invocations`) still
lives in `analyze_service`: `/flow_chain` calls it directly until it moves onto
this module too.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from config.settings import settings
from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    load_external_wrapper_contract,
    load_wrapper_review_exclusions,
)
from code_analyzer.models import FileAnalysisResult
from code_analyzer.project_scanner import ProjectScanResult

from . import derived_execution_evidence_store
from . import sql_cache_store
from .contract_registry import load_contract_registry
from .execution_path_builder import (
    build_execution_paths_by_invocation,
    ordered_execution_paths,
)
from .scan_store import cached_commit, cached_saved_at


@dataclass(frozen=True)
class DerivedExecutionEvidenceScope:
    """The identity Derived Execution Evidence is derived for.

    Named in the domain glossary (``CONTEXT.md``) and decided in ADR-0013:
    the repository scan roots, the complete Database identity a request
    routes to, and the wrapper contract selector in force -- exactly the
    inputs `_rated_execution_invocations` reads, and nothing it does not.
    Two requests that agree on these three produce the same derived
    evidence; a request field outside them cannot change it. Frozen and
    built only from hashable field types, so an instance is a valid
    retention key by construction -- a later ticket does not have to
    reshape it to key reuse on.
    """

    repo_roots: Tuple[str, ...]
    database: str
    sql_cache_identity: Optional[sql_cache_store.CacheIdentity]
    db_name: str
    wrapper_contract: str

    @classmethod
    def of(
        cls,
        req: object,
        roots: Iterable[Path],
        sql_cache_identity: Optional[sql_cache_store.CacheIdentity],
    ) -> DerivedExecutionEvidenceScope:
        """Build the scope from a request, its already-resolved scan roots,
        and the SQL Cache Identity its handler built.

        This is the one place a scope is assembled; every derivation call
        site is handed the result rather than reaching into ``req`` itself.
        ``database`` stays next to ``sql_cache_identity``: the wrapper review exclusions
        and the connection aliases read the requested name only.
        """
        wrapper_contract = getattr(req, "wrapper_contract", "")
        return cls(
            repo_roots=tuple(str(Path(root)) for root in roots),
            database=str(getattr(req, "database", "") or "").strip(),
            sql_cache_identity=sql_cache_identity,
            db_name=str(getattr(req, "db_name", "") or "").strip(),
            wrapper_contract=(
                wrapper_contract if isinstance(wrapper_contract, str) else ""
            ),
        )


def _freshness_or_sentinel(recorded_value: Optional[str]) -> object:
    """`recorded_value` if something was actually recorded, else a fresh sentinel.

    A `None` here means the freshness read itself came back empty (the meta
    file backing it is missing or unreadable), not that the tracked input has
    some legitimate, stable "no value" state -- `scan_freshness` below already
    handles the one legitimate case of that kind (no `.git` under a scan root)
    by comparing the source commit only inside an otherwise-present reading.
    A fresh `object()` never equals anything, including another sentinel from
    a previous unreadable call, so an unreadable reading can never be mistaken
    for "unchanged since last time" (ticket 05 -- missing is not a match).
    """
    return recorded_value if recorded_value is not None else object()


def _scan_freshness(root: Path) -> object:
    """The recorded save time and source commit for `root`'s disk-cached scan.

    Read via `scan_store.cached_saved_at`/`cached_commit`, which reflect what
    was last written to disk regardless of whether the in-memory scan object
    handed to this call is the same instance that was scanned or a freshly
    deserialized one -- exactly the identity dependency ticket 05 removes.
    A missing save time (no meta recorded at all) is treated as unreadable
    via `_freshness_or_sentinel`; a missing source commit alongside a present
    save time (no `.git` under `root`) is a legitimate, stable value and
    compares normally.
    """
    saved_at = cached_saved_at(root)
    if saved_at is None:
        return _freshness_or_sentinel(saved_at)
    return (saved_at, cached_commit(root))


@dataclass
class ValidityStamp:
    """Everything the rating step reads besides `scope` itself.

    ADR-0013 names five inputs a retained rating result must track: the repository
    scan, the SQL cache it is joined against, and the three configuration
    reads that shape rating -- the external wrapper contract, the contract
    registry, and the wrapper review exclusions. A mismatch on any one of
    them means a retained result may no longer be correct, so it is never
    served -- unlike the Object Location Index's tolerant staleness rule
    (ADR-0012), a stale match here is a wrong answer, not a slow one.

    `scan_freshness`/`sql_cache_freshness` (ticket 05) compare by each input's
    own recorded save time (the scan additionally by its recorded source
    commit) rather than by Python object identity: identity only meant "has
    this input moved since the last derivation" because `scan_store`'s and
    `sql_cache_store`'s process caches were unbounded and never evicted, so
    the exact same in-memory object always came back until a `refresh`
    replaced it. A bounded cache or a disk-backed retention breaks that --
    a dropped-then-reread object is a new instance carrying unchanged
    content, and object identity would wrongly call that a change. Comparing
    the recorded save time (and, for the scan, the source commit -- the
    better signal of the two, since two scans of unchanged code taken at
    different times still share one commit) survives both: it names what
    changed, not which object happens to represent it.

    The scan's save time and source commit are compared together, not commit
    alone: a partial refresh (`analyze_service`'s program-refresh flow, via
    `scan_store.save_scan`) can change a scan's actual content -- and its
    recorded save time -- without the repository's git commit moving at all
    (a dirty working tree, or files refreshed ahead of a commit). Letting a
    matching commit alone excuse a differing save time would let exactly that
    change go undetected, which is the wrong-answer risk ADR-0013 forbids
    trading for a latency win. Requiring both to match only ever costs an
    extra derivation it did not strictly need; it never serves a stale one.

    The three configuration reads have no identity guarantee either way --
    they are parsed fresh from disk on every call -- so they are compared by
    value.
    """

    scan_freshness: Tuple[object, ...]
    sql_cache_freshness: object
    external_wrapper_contract: Optional[Dict[str, Any]]
    contract_registry: Dict[str, Any]
    wrapper_review_exclusions: Tuple[Dict[str, Any], ...]


def rating_config_inputs(
    scope: DerivedExecutionEvidenceScope,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], Tuple[Dict[str, Any], ...]]:
    """The three configuration reads that shape rating, read fresh every time.

    Backs both the rating step and its validity stamp below: ADR-0013
    requires the freshness check to see a configuration edit exactly as soon
    as the rating step itself would, so neither may cache these separately
    from the other.
    """
    return (
        load_external_wrapper_contract(scope.wrapper_contract),
        load_contract_registry(),
        load_wrapper_review_exclusions(scope.database),
    )


def _validity_stamp(
    scope: DerivedExecutionEvidenceScope,
    scans: Iterable[ProjectScanResult],
) -> ValidityStamp:
    """Take a fresh reading of every input `_rated_execution_invocations` depends on."""
    identity = scope.sql_cache_identity
    # The repair tool rebuilds the graph and keeps the Scan Record's saved_at,
    # so the graph version joins the save time: a rebuilt graph invalidates.
    sql_cache_freshness = None
    if identity is not None:
        cached = sql_cache_store.load_cached(identity)
        if cached is not None:
            sql_cache_freshness = (
                _freshness_or_sentinel(sql_cache_store.cached_saved_at(identity)),
                (cached.get("sql_execution_graph") or {}).get("graph_version"),
            )
    external_wrapper_contract, contract_registry, wrapper_review_exclusions = (
        rating_config_inputs(scope)
    )
    return ValidityStamp(
        scan_freshness=tuple(_scan_freshness(Path(scan.project_root)) for scan in scans),
        sql_cache_freshness=sql_cache_freshness,
        external_wrapper_contract=external_wrapper_contract,
        contract_registry=contract_registry,
        wrapper_review_exclusions=wrapper_review_exclusions,
    )


ExecutionPath = Dict[str, object]


class DerivedExecutionEvidence:
    """One scope's Derived Execution Evidence, as an endpoint receives it.

    `rated_invocations` and `graph` come from one rating. The Execution Paths
    are kept per invocation and built on first use: `paths_of()` gives the
    paths of the invocations an endpoint selected, and `path_by_id()` finds
    one path through an index by path_id. The paths are a pure function of
    the other two parts, so whatever invalidates the rating invalidates the
    paths too, and they need no stamp of their own.

    `on_paths_built` lets the retention write the evidence to disk again when
    the last invocation gets its paths. A partial build stays in memory only:
    a lost partial build costs one rebuild, not a wrong answer. An in-memory
    evidence source in a test, and a partial rating, leave it out.

    The evidence is read-only for every endpoint. An endpoint that changes a
    path copies it first.
    """

    def __init__(
        self,
        rated_invocations: List[DbInvocation],
        graph: Dict[str, object],
        paths_by_invocation: Optional[Sequence[List[ExecutionPath]]] = None,
        on_paths_built: Optional[Callable[["DerivedExecutionEvidence"], None]] = None,
    ) -> None:
        self.rated_invocations = rated_invocations
        self.graph = graph
        self._paths_by_invocation: List[Optional[List[ExecutionPath]]] = (
            list(paths_by_invocation)
            if paths_by_invocation is not None
            else [None] * len(rated_invocations)
        )
        # Positions by object identity: an endpoint selects invocations from
        # `rated_invocations` and hands the same objects back.
        self._positions = {id(invocation): i for i, invocation in enumerate(rated_invocations)}
        self._on_paths_built = on_paths_built
        self._path_index: Optional[Dict[str, List[Tuple[ExecutionPath, DbInvocation]]]] = None

    def paths_of(self, invocations: Iterable[DbInvocation]) -> List[ExecutionPath]:
        """The Execution Paths of `invocations`, in the order of one build over them."""
        invocations = list(invocations)
        positions = [self._positions[id(invocation)] for invocation in invocations]
        missing = sorted({p for p in positions if self._paths_by_invocation[p] is None})
        if missing:
            built = build_execution_paths_by_invocation(
                [self.rated_invocations[p] for p in missing], self.graph
            )
            for position, paths in zip(missing, built):
                self._paths_by_invocation[position] = paths
            if self._on_paths_built is not None and self.built_paths_by_invocation is not None:
                self._on_paths_built(self)
        return ordered_execution_paths(
            (invocation, self._paths_by_invocation[position] or [])
            for invocation, position in zip(invocations, positions)
        )

    def execution_paths(self) -> List[ExecutionPath]:
        """The Execution Paths of the whole scope."""
        return self.paths_of(self.rated_invocations)

    def path_by_id(
        self,
        path_id: str,
        produced_by: Callable[[DbInvocation], bool] = lambda invocation: True,
    ) -> Optional[Tuple[ExecutionPath, DbInvocation]]:
        """The path with `path_id` and the invocation that produced it, or `None`.

        The first call builds the paths of every invocation and indexes them.
        A path_id depends only on its own invocation, but two scan roots can
        hold one relative path. So the index keeps every match, and
        `produced_by` selects among them before the first match wins.
        """
        if self._path_index is None:
            self.paths_of(self.rated_invocations)
            self._path_index = {}
            for invocation, paths in zip(self.rated_invocations, self._paths_by_invocation):
                for path in paths or []:
                    self._path_index.setdefault(str(path.get("path_id") or ""), []).append(
                        (path, invocation)
                    )
        return next(
            (match for match in self._path_index.get(path_id, []) if produced_by(match[1])),
            None,
        )

    @property
    def built_paths_by_invocation(self) -> Optional[List[List[ExecutionPath]]]:
        """The paths of every invocation if all of them are built, else `None`."""
        if any(paths is None for paths in self._paths_by_invocation):
            return None
        return [paths or [] for paths in self._paths_by_invocation]


class EvidenceSource(Protocol):
    """What an endpoint calls to get the evidence of its scope.

    `evidence_for_scope` is the real source. An endpoint test gives an
    in-memory source with fixed invocations and a fixed graph instead.
    """

    def __call__(
        self,
        scope: DerivedExecutionEvidenceScope,
        per_root_scans: List[ProjectScanResult],
        merged_scan: ProjectScanResult,
        root: Path,
        *,
        needed_files: Optional[List[FileAnalysisResult]] = None,
        refresh: bool = False,
    ) -> DerivedExecutionEvidence: ...


@dataclass
class _RetainedEvidence:
    """One scope's evidence, kept until a stamp mismatch or an explicit refresh."""

    stamp: ValidityStamp
    evidence: DerivedExecutionEvidence


# Derived Execution Evidence, retained per scope (ADR-0013).
# Bounded by `settings.DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT` (ticket 06),
# with least-recently-used eviction (ticket 07): the scope evicted when the
# bound is reached is the one that has gone longest without being served, not
# merely the one that arrived longest ago. On a shared service, requests from
# many analysts interleave; an analyst asking many questions about one system
# must not lose that scope just because a hundred unrelated scopes arrived in
# between.
#
# A single Cross-system Lookup sweep, which visits every system in the
# catalog once before returning to the first, is unaffected by this rule:
# when every scope is touched exactly once, "least recently used" and
# "arrived longest ago" name the same scope, so the sweep evicts in the same
# order least-recently-used or first-in-first-out would. The two rules only
# diverge -- and only least-recently-used helps -- once a scope is served more
# than once, exactly the reused-scope case this ticket protects.
#
# An `OrderedDict` gives both rules for the price of one: every place a scope
# is served calls `move_to_end` on it, keeping the least-recently-used entry
# at the front regardless of arrival order, and `_evict_for_new_scope` still
# evicts from the front with `popitem(last=False)`. See `_evict_for_new_scope`
# for the eviction itself.
#
# The pre-existing unbounded in-memory retention this reuse work builds on top
# of -- `analyze_service._scan_cache`, and the process-level caches in
# `scan_store` and `sql_cache_store` -- is deliberately left alone here. Those
# predate this effort and carry their own risk; bounding them is not this
# module's scope.
_retention: OrderedDict[DerivedExecutionEvidenceScope, _RetainedEvidence] = OrderedDict()


def _evict_for_new_scope(scope: DerivedExecutionEvidenceScope) -> None:
    """Evict the least-recently-used retained scope if adding `scope` would exceed the bound.

    A no-op when `scope` is already retained -- replacing an existing entry's
    value never grows the retention, so it never needs to evict. Eviction
    never changes an answer: the evicted scope is read back from disk, or
    derived again, on its next request. It is printed so a service whose reuse
    has stopped working -- because the catalog outgrew the configured bound --
    reports that instead of merely being slow again (ADR-0013).
    """
    if scope in _retention:
        return
    limit = max(1, int(settings.DERIVED_EXECUTION_EVIDENCE_RETENTION_LIMIT))
    if len(_retention) < limit:
        return
    evicted_scope, _ = _retention.popitem(last=False)
    print(
        "⚠️  Derived Execution Evidence retention 已達上限"
        f"（limit={limit}），淘汰最舊的 scope 以容納新的 scope："
        f"evicted database={evicted_scope.database!r} sql_cache_identity={evicted_scope.sql_cache_identity!r} "
        f"repo_roots={evicted_scope.repo_roots!r} / "
        f"new database={scope.database!r} sql_cache_identity={scope.sql_cache_identity!r} "
        f"repo_roots={scope.repo_roots!r}"
    )


def _retain(
    scope: DerivedExecutionEvidenceScope,
    stamp: ValidityStamp,
    rated_invocations: List[DbInvocation],
    graph: Dict[str, object],
    paths_by_invocation: Optional[List[List[ExecutionPath]]],
) -> DerivedExecutionEvidence:
    """Make room for `scope` if needed, then retain its evidence as the newest entry.

    The one call a fresh derivation or a disk hit makes to enter `scope` into
    `_retention`. The evidence writes itself to disk again once every
    invocation has its Execution Paths: a disk hit may supply the rating
    without paths yet built (a scope that had only ever answered
    `find_by_sp()`), so the file is written again to carry the paths -- the
    same "write on every cold derivation" rule, applied to the half of the
    evidence that just went cold.
    """

    def store_with_paths(evidence: DerivedExecutionEvidence) -> None:
        derived_execution_evidence_store.store(
            scope,
            stamp,
            evidence.rated_invocations,
            evidence.graph,
            paths_by_invocation=evidence.built_paths_by_invocation,
        )

    evidence = DerivedExecutionEvidence(
        rated_invocations, graph, paths_by_invocation, on_paths_built=store_with_paths
    )
    _evict_for_new_scope(scope)
    _retention[scope] = _RetainedEvidence(stamp, evidence)
    _retention.move_to_end(scope)
    return evidence


def evidence_for_scope(
    scope: DerivedExecutionEvidenceScope,
    per_root_scans: List[ProjectScanResult],
    merged_scan: ProjectScanResult,
    root: Path,
    *,
    needed_files: Optional[List[FileAnalysisResult]] = None,
    refresh: bool = False,
) -> DerivedExecutionEvidence:
    """The Derived Execution Evidence of `scope`, reused across requests (ADR-0013).

    Looks in memory, then on disk (ADR-0017). A retained result is served only
    when its validity stamp still matches every tracked input; any mismatch
    derives again and replaces what is retained. `refresh` always derives
    again: the one action a caller takes to force freshness skips both the
    memory copy and the disk copy, whatever their stamps say.

    `needed_files` changes only the miss (ADR-0040). Without it, a miss derives
    the whole scope and retains it in memory and on disk. With it, a miss rates
    those C# file results only and retains nothing: the request gets a partial
    evidence, and the next request still finds no retained copy. A hit serves
    the whole scope either way, and the endpoint filters it. Rating is
    independent per file, so a filtered whole result equals a partial one.

    `per_root_scans` is the caller's list of per-root scans, taken *before*
    any multi-root merge -- the stamp reads each root's recorded scan state.
    `merged_scan` and `root` are what the rating step reads.
    """
    stamp = _validity_stamp(scope, per_root_scans)
    if not refresh:
        retained = _retention.get(scope)
        if retained is not None and retained.stamp == stamp:
            _retention.move_to_end(scope)
            return retained.evidence

        stored = derived_execution_evidence_store.load(scope)
        if stored is not None and stored.stamp == stamp:
            return _retain(
                scope, stamp, stored.rated_invocations, stored.graph, stored.paths_by_invocation
            )

    # The rating step still lives in `analyze_service`, which imports this
    # module; the import waits until the first derivation to avoid the cycle.
    from . import analyze_service

    files = merged_scan.csharp_results if needed_files is None else needed_files
    rated_invocations, graph = analyze_service._rated_execution_invocations(
        scope, merged_scan, list(files), root
    )
    if needed_files is not None:
        return DerivedExecutionEvidence(rated_invocations, graph)  # not retained (ADR-0040)
    evidence = _retain(scope, stamp, rated_invocations, graph, None)
    derived_execution_evidence_store.store(
        scope, stamp, rated_invocations, graph, paths_by_invocation=None
    )
    return evidence


__all__ = [
    "DerivedExecutionEvidence",
    "DerivedExecutionEvidenceScope",
    "EvidenceSource",
    "ValidityStamp",
    "evidence_for_scope",
    "rating_config_inputs",
]

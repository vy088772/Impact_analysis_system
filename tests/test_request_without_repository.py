"""A source without a repository has no C# Scan Result (spec-rag spec-update-web ticket 10).

The update page shows no C# row for a catalog system with an empty `azure.repo`. A question
about that system must agree: it reads no scan root and reports no `csharp` cache.
"""

from pathlib import Path

import pytest

from service import analyze_service, cache_freshness
from service.request_context import NoRepository, build_request_context
from service.request_context_adapters import InMemoryCacheStore, InMemoryScanStore, RealScanStore
from service.schemas import (
    AnalyzeRequest,
    AzureSource,
    FindBySPRequest,
    FindByTableRequest,
    FlowChainRequest,
    PathEvidenceRequest,
)
from service.sql_cache_store import CacheIdentity

PROJECT_ONLY = AzureSource(project="System Dept 1")
EMPTY_SOURCE = AzureSource()
NO_REPOSITORY = [pytest.param(PROJECT_ONLY, id="project-only"), pytest.param(EMPTY_SOURCE, id="empty")]


class RecordingRealScanStore(RealScanStore):
    """The real source rule, with a record of each scan read."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read_scan(self, root: Path):
        self.calls.append("read")
        return super().read_scan(root)

    def has_cache(self, root: Path) -> bool:
        self.calls.append("cache")
        return super().has_cache(root)


@pytest.mark.parametrize("source", NO_REPOSITORY)
def test_the_real_scan_store_gives_no_scan_root_for_a_source_without_a_repository(source: AzureSource) -> None:
    store = RealScanStore()

    assert store.peek_scan_roots(store.resolve_source(AnalyzeRequest(source=source, program_names=[]))) == []


def test_the_real_scan_store_keeps_the_scan_root_of_a_source_with_a_repository() -> None:
    store = RealScanStore()
    source = store.resolve_source(AnalyzeRequest(source=AzureSource(project="System Dept 1", repo="Orders"), program_names=[]))

    assert [root.name for root in store.peek_scan_roots(source)] == ["Orders"]


@pytest.mark.parametrize("source", NO_REPOSITORY)
def test_analyze_reports_no_csharp_cache_for_a_source_without_a_repository(source: AzureSource) -> None:
    scans = RecordingRealScanStore()

    response = analyze_service.analyze(
        AnalyzeRequest(system="gPurchase", source=source, program_names=["PoPrintNotice"]),
        scan_store=scans,
        cache_store=InMemoryCacheStore(),
    )

    assert response.unusable_caches == []
    assert response.programs == []
    assert response.source_root == ""
    assert scans.calls == []


@pytest.mark.parametrize("source", NO_REPOSITORY)
def test_find_by_sp_answers_no_match_and_not_skipped_for_a_source_without_a_repository(source: AzureSource) -> None:
    scans = RecordingRealScanStore()

    response = analyze_service.find_by_sp(
        FindBySPRequest(sp_name="usp_Save", source=source, cache_only=True),
        scan_store=scans,
        cache_store=InMemoryCacheStore(),
    )

    assert response.unusable_caches == []
    assert response.skipped is False
    assert response.matches == []
    assert scans.calls == []


@pytest.mark.parametrize("source", NO_REPOSITORY)
def test_find_by_table_answers_no_match_and_not_skipped_for_a_source_without_a_repository(
    source: AzureSource,
) -> None:
    scans = RecordingRealScanStore()

    response = analyze_service.find_by_table(
        FindByTableRequest(table_name="PoHeader", source=source, cache_only=True),
        scan_store=scans,
        cache_store=InMemoryCacheStore(),
    )

    assert response.unusable_caches == []
    assert response.skipped is False
    assert response.matches == []
    assert scans.calls == []


@pytest.mark.parametrize("source", NO_REPOSITORY)
def test_flow_chain_answers_an_empty_chain_for_a_source_without_a_repository(source: AzureSource) -> None:
    response = analyze_service.flow_chain(
        FlowChainRequest(direction="backward", table_name="PoHeader", source=source),
        scan_store=RecordingRealScanStore(),
        cache_store=InMemoryCacheStore(),
    )

    assert response.unusable_caches == []
    assert response.skipped is False


def test_path_evidence_names_the_missing_source_and_no_cache_for_a_source_without_a_repository(
    monkeypatch,
) -> None:
    # A path needs a usable SQL graph first; this test is about the source only.
    monkeypatch.setattr(analyze_service, "_require_sql_execution_graph", lambda database, identity: ({}, {}))

    with pytest.raises(analyze_service.PathEvidenceError) as raised:
        analyze_service.get_path_evidence(
            PathEvidenceRequest(system="gPurchase", source=PROJECT_ONLY, path_id="p1", database="Orders"),
            scan_store=RecordingRealScanStore(),
            cache_store=InMemoryCacheStore(),
        )

    assert raised.value.code == "source_not_found"


def test_an_outdated_sql_cache_of_a_source_without_a_repository_is_still_reported(monkeypatch) -> None:
    identity = CacheIdentity.of("host", "Orders")
    report = {"kind": "sql", "key": "sql:host/Orders", "state": "outdated"}
    monkeypatch.setattr(cache_freshness, "sql_unusable", lambda found: report if found == identity else None)

    context = build_request_context(
        AnalyzeRequest(source=PROJECT_ONLY, database="Orders", program_names=[]),
        scan_store=RecordingRealScanStore(),
        cache_store=InMemoryCacheStore({"Orders": identity}),
    )

    assert not isinstance(context, NoRepository)
    assert context.caches == [report]


def test_a_source_with_a_repository_and_no_cache_is_still_outdated_for_analyze(tmp_path: Path) -> None:
    response = analyze_service.analyze(
        AnalyzeRequest(program_names=["PoPrintNotice"]),
        scan_store=InMemoryScanStore(roots=[tmp_path], outdated_roots={tmp_path}),
        cache_store=InMemoryCacheStore(),
    )

    assert [cache.kind for cache in response.unusable_caches] == ["csharp"]
    assert response.unusable_caches[0].state == "outdated"


def test_a_source_with_a_repository_and_no_cache_is_still_skipped_for_a_lookup(tmp_path: Path) -> None:
    response = analyze_service.find_by_sp(
        FindBySPRequest(sp_name="usp_Save", cache_only=True),
        scan_store=InMemoryScanStore(roots=[tmp_path]),
        cache_store=InMemoryCacheStore(),
    )

    assert response.skipped is True
    assert response.unusable_caches == []

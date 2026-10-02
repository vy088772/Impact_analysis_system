from pathlib import Path
from datetime import datetime

import pytest

from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from code_analyzer.models import FileAnalysisResult, FileType, FrameworkType
from service.analyze_service import AmbiguousDatabaseError, find_by_sp
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.request_context_adapters import InMemoryCacheStore, InMemoryScanStore
from service.schemas import AzureSource, FindBySPRequest
from service.sql_cache_store import AmbiguousServer, CacheIdentity
from tests.sql_cache_fixtures import CacheRoot, cache_payload, execution_graph, write_cache


def test_a_source_without_a_scan_cache_returns_the_same_skipped_response(tmp_path: Path) -> None:
    response = find_by_sp(
        FindBySPRequest(sp_name=" dbo.usp_Save ", database="Orders"),
        scan_store=InMemoryScanStore(roots=[tmp_path]),
        cache_store=InMemoryCacheStore(),
    )

    assert response.model_dump() == {
        "sp_name": "dbo.usp_Save",
        "matches": [],
        "likely_matches": [],
        "diagnostics": [],
        "source_root": "",
        "skipped": True,
    }


@pytest.mark.parametrize("missing", ["first", "second"])
def test_a_multi_folder_source_skips_if_either_root_has_no_cache(tmp_path: Path, missing: str) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    scans = InMemoryScanStore(roots=roots, cached_roots={root for root in roots if root.name != missing})

    response = find_by_sp(
        FindBySPRequest(sp_name="usp_Save", source=AzureSource(path=["first", "second"])),
        scan_store=scans,
        cache_store=InMemoryCacheStore(),
    )

    assert response.skipped is True
    assert response.matches == []
    assert "resolve" not in scans.calls
    assert "scan" not in scans.calls


@pytest.mark.parametrize("refresh,cache_only", [(True, True), (False, False), (False, True)])
def test_a_ready_source_keeps_the_response_and_refresh_bypasses_the_skip(
    tmp_path: Path, refresh: bool, cache_only: bool
) -> None:
    identity = CacheIdentity.of("host", "Orders")
    scan = ProjectScanResult(project_root=str(tmp_path), project_name="orders", scan_time=datetime.now())
    scans = InMemoryScanStore(
        roots=[tmp_path], scans={tmp_path: scan},
        cached_roots={tmp_path} if not refresh else set(),
    )
    with CacheRoot() as cache_root:
        write_cache(cache_root, identity, cache_payload("Orders", graph=execution_graph("Orders")))
        response = find_by_sp(
            FindBySPRequest(sp_name="usp_Save", database="Orders", refresh=refresh, cache_only=cache_only),
            evidence_source=lambda *args, **kwargs: DerivedExecutionEvidence([], {}),
            scan_store=scans,
            cache_store=InMemoryCacheStore({"Orders": identity}),
        )

    assert response.skipped is False
    assert response.matches == []
    assert response.source_root == str(tmp_path)
    if refresh or not cache_only:
        assert "peek" not in scans.calls
        assert "cache" not in scans.calls


@pytest.mark.parametrize("cache_only,refresh", [(True, False), (False, False), (True, True)])
def test_an_ambiguous_database_refuses_before_any_scan_store_call(
    tmp_path: Path, cache_only: bool, refresh: bool
) -> None:
    scans = InMemoryScanStore(roots=[tmp_path])
    caches = InMemoryCacheStore({"Orders": AmbiguousServer("Orders", ("host-a", "host-b"))})

    with pytest.raises(AmbiguousDatabaseError) as error:
        find_by_sp(
            FindBySPRequest(sp_name="usp_Save", database="Orders", cache_only=cache_only, refresh=refresh),
            scan_store=scans, cache_store=caches,
        )

    assert error.value.code == "ambiguous_database"
    assert error.value.database == "Orders"
    assert error.value.servers == ["host-a", "host-b"]
    assert scans.calls == []


def test_identity_lookup_precedes_the_skip(tmp_path: Path) -> None:
    calls: list[str] = []
    response = find_by_sp(
        FindBySPRequest(sp_name="usp_Save", database="Orders"),
        scan_store=InMemoryScanStore(roots=[tmp_path], calls=calls),
        cache_store=InMemoryCacheStore(calls=calls),
    )

    assert response.skipped is True
    assert calls == ["identity", "source", "peek", "cache"]


def test_a_multi_root_source_reports_callers_relative_to_the_repository_root(tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    scans = InMemoryScanStore(
        roots=roots, cached_roots=set(roots), repository_root=tmp_path,
        scans={
            root: ProjectScanResult(
                project_root=str(root), project_name=root.name, scan_time=datetime.now(),
                csharp_results=[FileAnalysisResult(
                    file_path=str(root / "Page.cs"), file_type=FileType.CSHARP, framework=FrameworkType.WEBFORMS,
                )],
            )
            for root in roots
        },
    )
    identity = CacheIdentity.of("host", "Orders")
    evidence = DerivedExecutionEvidence(
        [
            DbInvocation(
                class_name="Page", method_name="Save", database="Orders",
                procedure_name="usp_Save", evidence=InvocationEvidence.PROVEN,
                source=InvocationSourceSpan(f"{folder}/Page.cs", 1, 2),
            )
            for folder in ("first", "second")
        ], {},
    )
    with CacheRoot() as cache_root:
        write_cache(cache_root, identity, cache_payload("Orders", graph=execution_graph("Orders")))
        response = find_by_sp(
            FindBySPRequest(sp_name="usp_Save", database="Orders", source=AzureSource(path=["first", "second"])),
            evidence_source=lambda *args, **kwargs: evidence,
            scan_store=scans, cache_store=InMemoryCacheStore({"Orders": identity}),
        )

    assert response.source_root == str(tmp_path)
    assert [match.file for match in response.matches] == ["first/Page.cs", "second/Page.cs"]
    assert response.skipped is False


def test_a_named_host_bypasses_an_ambiguous_name_lookup(tmp_path: Path) -> None:
    caches = InMemoryCacheStore({"Orders": AmbiguousServer("Orders", ("host-a", "host-b"))})
    response = find_by_sp(
        FindBySPRequest(sp_name="usp_Save", database="Orders", db_server="host-a"),
        scan_store=InMemoryScanStore(roots=[tmp_path]), cache_store=caches,
    )

    assert response.skipped is True
    assert caches.calls == []


def test_an_empty_procedure_name_needs_no_request_preparation() -> None:
    calls: list[str] = []
    response = find_by_sp(
        FindBySPRequest(sp_name=" "),
        scan_store=InMemoryScanStore(calls=calls), cache_store=InMemoryCacheStore(calls=calls),
    )

    assert response.sp_name == ""
    assert response.matches == []
    assert response.skipped is False
    assert calls == []
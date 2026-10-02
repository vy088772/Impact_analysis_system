from pathlib import Path
from datetime import datetime

import pytest

from code_analyzer.project_scanner import ProjectScanResult
from service.analyze_service import AmbiguousDatabaseError, find_by_table
from service.request_context_adapters import InMemoryCacheStore, InMemoryScanStore
from service.schemas import AzureSource, FindByTableRequest
from service.sql_cache_store import AmbiguousServer


def test_a_source_without_a_scan_cache_returns_the_same_skipped_response(tmp_path: Path) -> None:
    scans = InMemoryScanStore(roots=[tmp_path])
    response = find_by_table(
        FindByTableRequest(table_name=" dbo.Orders ", database="Orders"),
        scan_store=scans,
        cache_store=InMemoryCacheStore(),
    )

    assert response.model_dump() == {
        "table_name": "dbo.Orders",
        "matches": [],
        "diagnostics": [],
        "excluded_count": 0,
        "source_root": "",
        "skipped": True,
    }


@pytest.mark.parametrize("missing", ["first", "second"])
def test_a_multi_folder_source_skips_if_either_root_has_no_cache(tmp_path: Path, missing: str) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    scans = InMemoryScanStore(roots=roots, cached_roots={root for root in roots if root.name != missing})
    response = find_by_table(
        FindByTableRequest(table_name="Orders", source=AzureSource(path=["first", "second"])),
        scan_store=scans, cache_store=InMemoryCacheStore(),
    )

    assert response.skipped is True
    assert response.matches == []


@pytest.mark.parametrize("cache_only,refresh", [(True, False), (False, False), (True, True)])
def test_an_ambiguous_database_refuses_before_any_scan_store_call(
    tmp_path: Path, cache_only: bool, refresh: bool
) -> None:
    scans = InMemoryScanStore(roots=[tmp_path])
    caches = InMemoryCacheStore({"Orders": AmbiguousServer("Orders", ("host-a", "host-b"))})
    with pytest.raises(AmbiguousDatabaseError) as error:
        find_by_table(
            FindByTableRequest(table_name="Orders", database="Orders", cache_only=cache_only, refresh=refresh),
            scan_store=scans, cache_store=caches,
        )

    assert error.value.code == "ambiguous_database"
    assert error.value.database == "Orders"
    assert error.value.servers == ["host-a", "host-b"]


@pytest.mark.parametrize("refresh,cache_only", [(True, True), (False, False), (False, True)])
def test_a_ready_source_keeps_the_response_and_refresh_bypasses_the_skip(
    tmp_path: Path, refresh: bool, cache_only: bool
) -> None:
    scan = ProjectScanResult(project_root=str(tmp_path), project_name="orders", scan_time=datetime.now())
    scans = InMemoryScanStore(
        roots=[tmp_path], scans={tmp_path: scan},
        cached_roots={tmp_path} if not refresh else set(),
    )
    response = find_by_table(
        FindByTableRequest(table_name="Orders", refresh=refresh, cache_only=cache_only),
        scan_store=scans, cache_store=InMemoryCacheStore(),
    )

    assert response.skipped is False
    assert response.matches == []
    assert response.source_root == str(tmp_path)
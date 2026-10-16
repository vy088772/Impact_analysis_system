"""The scan store separates a read from a rebuild (ticket 01, ADR-0045)."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from code_analyzer.project_scanner import ProjectScanResult
from config.settings import settings
from service import scan_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SCAN_CACHE_ROOT", str(tmp_path / "cache"))
    scans: list[Path] = []

    class FakeScanner:
        def __init__(self, project_root: str) -> None:
            self.project_root = project_root

        def scan_project(self, analyze_sp: bool = True) -> ProjectScanResult:
            scans.append(Path(self.project_root))
            return ProjectScanResult(
                project_root=self.project_root, project_name="fake", scan_time=datetime.now()
            )

    monkeypatch.setattr(scan_store, "ProjectScanner", FakeScanner)
    monkeypatch.setattr(scan_store, "_mem_cache", {})
    root = tmp_path / "repo"
    root.mkdir()
    return root, scans


def test_read_scan_reports_outdated_for_a_missing_cache_and_never_scans(store) -> None:
    root, scans = store
    with pytest.raises(scan_store.ScanOutdated) as caught:
        scan_store.read_scan(root)
    assert caught.value.freshness == "outdated"
    assert scans == []


def test_read_scan_reports_outdated_for_an_old_format_cache(store) -> None:
    root, scans = store
    scan_store.rebuild_scan(root)
    scan_store._mem_cache.clear()
    _, meta = scan_store._paths(root)
    info = json.loads(meta.read_text(encoding="utf-8"))
    info["cache_version"] = scan_store._CACHE_VERSION - 1
    meta.write_text(json.dumps(info), encoding="utf-8")
    scans.clear()
    with pytest.raises(scan_store.ScanOutdated):
        scan_store.read_scan(root)
    assert scans == []


def test_read_scan_reports_outdated_for_an_invalid_cache(store) -> None:
    root, scans = store
    scan_store.rebuild_scan(root)
    scan_store._mem_cache.clear()
    pkl, _ = scan_store._paths(root)
    pkl.write_bytes(b"not a pickle")
    scans.clear()
    with pytest.raises(scan_store.ScanOutdated):
        scan_store.read_scan(root)
    assert scans == []


def test_rebuild_scan_scans_then_read_scan_returns_the_saved_result(store) -> None:
    root, scans = store
    built = scan_store.rebuild_scan(root)
    assert scans == [root]
    scan_store._mem_cache.clear()
    assert scan_store.read_scan(root).project_root == built.project_root
    assert scans == [root]


def test_rebuild_scan_scans_again_when_a_usable_cache_exists(store) -> None:
    root, scans = store
    scan_store.rebuild_scan(root)
    scan_store.rebuild_scan(root)
    assert scans == [root, root]


def test_the_combined_operation_no_longer_exists() -> None:
    assert not hasattr(scan_store, "get_or_scan")

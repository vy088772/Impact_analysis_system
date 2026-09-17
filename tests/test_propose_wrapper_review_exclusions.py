"""Ticket 06: the Exclusion Candidate Tool's CLI wiring.

The report-builder unit tests live in tests/test_exclusion_candidates.py. This file
only checks that the tool wires a real (stubbed) scan into that builder correctly,
and that the tool never scans twice for the same root and never touches the
exclusion registry file -- "the tool only reads" and "running it twice changes no
file" (ticket 06's own last two checklist items).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import GLOBAL_EXCLUSION_TIER_KEY, SpCatalog  # noqa: E402
from code_analyzer.project_scanner import ProjectScanResult  # noqa: E402
import tools.propose_wrapper_review_exclusions as tool  # noqa: E402

REGISTRY_PATH = PROJECT_ROOT / "config" / "wrapper_review_exclusions.json"


def _scan(root: Path, **overrides) -> ProjectScanResult:
    scan = ProjectScanResult(
        project_root=str(root),
        project_name=root.name,
        scan_time=datetime(2026, 9, 17, 0, 0, 0),
    )
    for name, value in overrides.items():
        setattr(scan, name, value)
    return scan


def _file_key(root: Path, name: str) -> str:
    return str((root / name).resolve())


def _wrapper_call(**overrides) -> dict:
    """One raw wrapper fact whose contract nobody registered, so it stays in review."""
    base = {
        "class_name": "UtilityService",
        "method_name": "GetListFromSysParam",
        "invocation_kind": "source_wrapper",
        "wrapper_method_name": "GetListFromSysParam",
        "wrapper_receiver_type": "IUtilityService",
        "wrapper_source_available": False,
        "wrapper_mode": "unknown",
        "connection_expression": "conn",
        "start_offset": 0,
        "end_offset": 10,
    }
    base.update(overrides)
    return base


def _stub_measurement(monkeypatch, scans_by_root: dict, *, cache: str = "current") -> list:
    calls: list = []

    def fake_get_or_scan(root: Path, refresh: bool = False) -> ProjectScanResult:
        calls.append((Path(root), refresh))
        return scans_by_root[str(Path(root))]

    monkeypatch.setattr(tool.scan_store, "get_or_scan", fake_get_or_scan)
    monkeypatch.setattr(tool.scan_store, "has_cache", lambda root: cache == "current")
    monkeypatch.setattr(tool.scan_store, "cache_status", lambda root: cache)
    monkeypatch.setattr(
        tool.analyze_service,
        "load_sp_catalog",
        lambda database="": SpCatalog.from_databases({}),
    )
    monkeypatch.setattr(tool, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(tool, "load_external_wrapper_contract", lambda name: None)
    monkeypatch.setattr(tool, "load_wrapper_review_exclusions", lambda system: ())
    monkeypatch.setattr(tool, "known_framework_receiver_types", lambda: frozenset())
    return calls


def test_build_report_proposes_a_candidate_for_a_still_unresolved_wrapper_call(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "UtilityService.cs")
    scan = _scan(
        root,
        db_invocations={key: [_wrapper_call()]},
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    _stub_measurement(monkeypatch, {str(root): scan})

    report = tool.build_report([{"system_id": "IQCS", "root": root, "configured_contract": ""}])

    assert len(report["candidates"]) == 1
    candidate = report["candidates"][0]
    assert candidate["receiver_type"] == "IUtilityService"
    assert candidate["method_name"] == "GetListFromSysParam"
    assert candidate["call_count"] == 1
    assert candidate["tier"] == "IQCS"
    assert report["registry_fragment"]["IQCS"] == [
        {
            "receiver_type": "IUtilityService",
            "method_name": "GetListFromSysParam",
            "reason": "proposed_pending_review",
        }
    ]


def test_an_empty_receiver_type_candidate_proposes_the_global_tier(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "UtilityService.cs")
    scan = _scan(
        root,
        db_invocations={key: [_wrapper_call(wrapper_receiver_type="", wrapper_method_name="Format")]},
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    _stub_measurement(monkeypatch, {str(root): scan})

    report = tool.build_report([{"system_id": "IQCS", "root": root, "configured_contract": ""}])

    assert report["candidates"][0]["tier"] == GLOBAL_EXCLUSION_TIER_KEY


def test_a_repeat_run_never_forces_a_rescan_and_the_registry_file_stays_untouched(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "IQCS"
    root.mkdir()
    key = _file_key(root, "UtilityService.cs")
    scan = _scan(
        root,
        db_invocations={key: [_wrapper_call()]},
        connection_sources={key: {"conn": {"database": "OrdersDb", "server": "sql01"}}},
    )
    calls = _stub_measurement(monkeypatch, {str(root): scan})
    target = {"system_id": "IQCS", "root": root, "configured_contract": ""}
    before = REGISTRY_PATH.read_text(encoding="utf-8")

    first = tool.build_report([target])
    second = tool.build_report([target])

    assert [refresh for _, refresh in calls] == [False, False]
    assert first["candidates"] == second["candidates"]
    assert REGISTRY_PATH.read_text(encoding="utf-8") == before

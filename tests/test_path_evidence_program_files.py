"""`/path_evidence` and `/analyze` agree on which program files a name matches.

Both endpoints receive the same program names for the same scan. A name that
`/analyze` reports as not found must not pick up files by substring in
`/path_evidence`, and a name that resolves to one screen reaches only the
invocations on that screen's actions.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service import analyze_service
from service.schemas import PathEvidenceRequest
from tests.program_screen_fixtures import _analyze, _scan
from tests.sql_cache_fixtures import one_server_holds_every_database

_ORDER_CONTROLLERS = {
    "Controllers/OrdersController.cs": ["Index", "Delete"],
    "Controllers/OrderHistoryController.cs": ["Index"],
}


class _Reached(Exception):
    """Raised by a stub to hand what `/path_evidence` selected back to the test."""

    def __init__(self, selected: List) -> None:
        self.selected = selected


def _invocation_on(relative_path: str, class_name: str, method: str) -> DbInvocation:
    return DbInvocation(
        class_name=class_name,
        method_name=method,
        database="OrdersDb",
        procedure_name="usp_Save",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan(relative_path, 0, 10),
        procedure_schema="dbo",
        method_chain=(method,),
        source_snapshot_hash="snapshot-hash",
    )


def _stub_path_evidence_sources(monkeypatch, root: Path, scan) -> None:
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda r, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database
    )
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: {})
    monkeypatch.setattr(
        analyze_service,
        "_require_sql_execution_graph",
        lambda database, sql_cache: ({}, {}),
    )


def _path_evidence_files(monkeypatch, root: Path, scan, program_names: List[str]) -> List[str]:
    """The base names of the C# files `/path_evidence` rates for the names."""
    _stub_path_evidence_sources(monkeypatch, root, scan)

    def stop_at_rating(scope, scan_, matched_files, root_):
        raise _Reached(list(matched_files))

    monkeypatch.setattr(analyze_service, "_rated_execution_invocations", stop_at_rating)
    with pytest.raises(_Reached) as reached:
        analyze_service.get_path_evidence(
            PathEvidenceRequest(path_id="P-1", database="OrdersDb", program_names=program_names)
        )
    return sorted(Path(r.file_path).name for r in reached.value.selected)


def _path_evidence_methods(
    monkeypatch, root: Path, scan, program_names: List[str], invocations: List[DbInvocation]
) -> List[str]:
    """The methods whose invocations `/path_evidence` searches for the path."""
    _stub_path_evidence_sources(monkeypatch, root, scan)
    monkeypatch.setattr(
        analyze_service,
        "_rated_execution_invocations",
        lambda scope, scan_, matched_files, root_: (list(invocations), {}),
    )
    searched: List[str] = []

    def record(invocation_list, graph):
        searched.extend(i.method_name for i in invocation_list)
        return []

    monkeypatch.setattr(analyze_service, "build_execution_paths", record)
    with pytest.raises(analyze_service.PathEvidenceError):
        analyze_service.get_path_evidence(
            PathEvidenceRequest(path_id="P-1", database="OrdersDb", program_names=program_names)
        )
    return searched


def test_a_name_analyze_reports_not_found_matches_no_file_in_path_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path, views=["Views/Orders/Index.cshtml"], controllers=_ORDER_CONTROLLERS
    )

    analyzed = _analyze(monkeypatch, tmp_path, scan, ["Order"])
    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Order"])

    assert analyzed.programs == []
    assert analyzed.not_found == ["Order"]
    assert files == []


def test_a_name_that_resolves_to_a_screen_reaches_that_screens_controller_in_path_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path, views=["Views/Orders/Index.cshtml"], controllers=_ORDER_CONTROLLERS
    )

    analyzed = _analyze(monkeypatch, tmp_path, scan, ["Orders"])
    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Orders"])

    assert [Path(p.file).name for p in analyzed.programs] == ["Index.cshtml"]
    assert files == ["OrdersController.cs"]


def test_a_resolved_screen_reaches_only_the_invocations_on_its_own_actions(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path, views=["Views/Orders/Index.cshtml"], controllers=_ORDER_CONTROLLERS
    )
    controller = "Controllers/OrdersController.cs"
    invocations = [
        _invocation_on(controller, "OrdersController", "Index"),
        _invocation_on(controller, "OrdersController", "Delete"),
    ]

    methods = _path_evidence_methods(monkeypatch, tmp_path, scan, ["Orders"], invocations)

    assert methods == ["Index"]


def test_a_scan_without_razor_files_keeps_the_base_name_match_on_both_endpoints(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(tmp_path, controllers=_ORDER_CONTROLLERS)

    analyzed = _analyze(monkeypatch, tmp_path, scan, ["Order"])
    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Order"])

    assert analyzed.not_found == []
    assert files == ["OrderHistoryController.cs", "OrdersController.cs"]

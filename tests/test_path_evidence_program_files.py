"""`/path_evidence` and `/analyze` agree on which program files a name matches.

Both endpoints receive the same program names for the same scan. A name that
`/analyze` reports as not found must not pick up files by substring in
`/path_evidence`, and a name that resolves to one screen reaches only the
invocations on that screen's actions.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

import pytest

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from code_analyzer.models import MethodSourceSpan, SourceSnapshot
from service import analyze_service
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.execution_path_builder import build_execution_paths
from service.schemas import PathEvidenceRequest
from tests.program_screen_fixtures import _analyze, _scan
from tests.request_context_fixtures import RequestStores

_ORDER_CONTROLLERS = {
    "Controllers/OrdersController.cs": ["Index", "Delete"],
    "Controllers/OrderHistoryController.cs": ["Index"],
}


_NOT_CALLED = object()


class _GivenEvidence:
    """An evidence source with fixed invocations and no graph.

    It records the needed files that `/path_evidence` gives it.
    """

    def __init__(self, invocations: Sequence[DbInvocation] = ()) -> None:
        self.invocations = list(invocations)
        self.needed_files: object = _NOT_CALLED

    def __call__(self, scope, per_root_scans, merged_scan, root, *, needed_files=None, refresh=False):
        self.needed_files = needed_files
        return DerivedExecutionEvidence(self.invocations, {})


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


def _with_controller_source(scan):
    """The scan with a source snapshot of OrdersController, so a found path can show its source."""
    content = (
        "class OrdersController\n{\n"
        "    public void Index() { }\n"
        "    public void Delete() { }\n"
        "}\n"
    )

    def span(method: str) -> MethodSourceSpan:
        start = content.index(f"    public void {method}()")
        return MethodSourceSpan("OrdersController", method, start, content.index("}", start) + 1)

    scan.source_snapshots["Controllers/OrdersController.cs"] = SourceSnapshot(
        relative_path="Controllers/OrdersController.cs",
        content_hash="snapshot-hash",
        content=content,
        method_spans=[span("Index"), span("Delete")],
    )
    return scan


def _path_id_of(invocation: DbInvocation) -> str:
    return str(build_execution_paths([invocation], {})[0]["path_id"])


def _stub_path_evidence_sources(monkeypatch, root: Path, scan) -> None:
    RequestStores.of(root, scan).install_path(monkeypatch)
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda identity: {})
    monkeypatch.setattr(
        analyze_service,
        "_require_sql_execution_graph",
        lambda database, sql_cache_identity: ({}, {}),
    )


def _path_evidence(
    source: _GivenEvidence, path_id: str, program_names: List[str]
) -> analyze_service.PathEvidenceResponse:
    return analyze_service.get_path_evidence(
        PathEvidenceRequest(path_id=path_id, database="OrdersDb", program_names=program_names),
        evidence_source=source,
    )


def _path_evidence_files(monkeypatch, root: Path, scan, program_names: List[str]) -> List[str]:
    """The base names of the C# files `/path_evidence` names as needed for the names."""
    _stub_path_evidence_sources(monkeypatch, root, scan)
    source = _GivenEvidence()
    with pytest.raises(analyze_service.PathEvidenceError):
        _path_evidence(source, "P-1", program_names)
    assert isinstance(source.needed_files, list)
    return sorted(Path(r.file_path).name for r in source.needed_files)


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


def test_a_resolved_screen_finds_the_path_of_its_own_action(monkeypatch, tmp_path: Path) -> None:
    scan = _with_controller_source(
        _scan(tmp_path, views=["Views/Orders/Index.cshtml"], controllers=_ORDER_CONTROLLERS)
    )
    index = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Index")
    delete = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Delete")
    _stub_path_evidence_sources(monkeypatch, tmp_path, scan)

    found = _path_evidence(_GivenEvidence([index, delete]), _path_id_of(index), ["Orders"])

    assert found.path_id == _path_id_of(index)
    assert found.caller_method == "Index"


def test_a_resolved_screen_does_not_find_the_path_of_an_action_it_does_not_own(
    monkeypatch, tmp_path: Path
) -> None:
    """The Orders screen has the Index view only. Delete is an action of the
    controller, but the screen does not own it."""
    scan = _with_controller_source(
        _scan(tmp_path, views=["Views/Orders/Index.cshtml"], controllers=_ORDER_CONTROLLERS)
    )
    index = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Index")
    delete = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Delete")
    _stub_path_evidence_sources(monkeypatch, tmp_path, scan)

    with pytest.raises(analyze_service.PathEvidenceError):
        _path_evidence(_GivenEvidence([index, delete]), _path_id_of(delete), ["Orders"])


def test_without_program_names_path_evidence_asks_for_the_whole_scope(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _with_controller_source(_scan(tmp_path, controllers=_ORDER_CONTROLLERS))
    index = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Index")
    _stub_path_evidence_sources(monkeypatch, tmp_path, scan)
    source = _GivenEvidence([index])

    _path_evidence(source, _path_id_of(index), [])

    assert source.needed_files is None


def test_a_scan_without_razor_files_keeps_the_base_name_match_on_both_endpoints(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(tmp_path, controllers=_ORDER_CONTROLLERS)

    analyzed = _analyze(monkeypatch, tmp_path, scan, ["Order"])
    files = _path_evidence_files(monkeypatch, tmp_path, scan, ["Order"])

    assert analyzed.not_found == []
    assert files == ["OrderHistoryController.cs", "OrdersController.cs"]


def test_a_webforms_program_cannot_find_another_programs_path_in_scope_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _with_controller_source(
        _scan(
            tmp_path,
            views=["Views/Orders/Index.cshtml"],
            controllers={**_ORDER_CONTROLLERS, "Legacy/Alpha.aspx.cs": ["Save"]},
            pages=["Legacy/Alpha.aspx"],
        )
    )
    content = "class Alpha { public void Save() { } }"
    scan.source_snapshots["Legacy/Alpha.aspx.cs"] = SourceSnapshot(
        relative_path="Legacy/Alpha.aspx.cs",
        content_hash="snapshot-hash",
        content=content,
        method_spans=[MethodSourceSpan("Alpha", "Save", 14, len(content) - 2)],
    )
    foreign = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Index")
    own = _invocation_on("Legacy/Alpha.aspx.cs", "Alpha", "Save")
    _stub_path_evidence_sources(monkeypatch, tmp_path, scan)

    found = _path_evidence(_GivenEvidence([own, foreign]), _path_id_of(own), ["Alpha"])
    assert found.caller_class == "Alpha"

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        _path_evidence(_GivenEvidence([own, foreign]), _path_id_of(foreign), ["Alpha"])

    assert error.value.code == "path_not_found"

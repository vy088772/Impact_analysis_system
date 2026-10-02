"""`/analyze` gets its evidence from the Derived Execution Evidence module.

These tests sit on the endpoint seam: `/analyze` takes an evidence source, and
each test gives an in-memory source with fixed invocations and no graph. The
answer then shows which invocations `/analyze` selected from that one result
(.scratch/derived-execution-evidence-one-module/issues/03).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import List, Sequence

from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service import analyze_service
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import AnalyzeRequest
from tests.program_screen_fixtures import _scan
from tests.sql_cache_fixtures import cache_with_procedures, one_server_holds_every_database
from tests.test_shared_component_contributions import (
    _scan as _component_scan,
    _view_component_result,
    _view_result,
)


class _GivenEvidence:
    """An evidence source that gives one fixed evidence object on every call.

    It records the needed files of each call.
    """

    def __init__(self, invocations: Sequence[DbInvocation] = ()) -> None:
        self.evidence = DerivedExecutionEvidence(list(invocations), {})
        self.calls: List[object] = []

    def __call__(self, scope, per_root_scans, merged_scan, root, *, needed_files=None, refresh=False):
        self.calls.append(needed_files)
        return self.evidence


def _invocation_on(
    relative_path: str,
    class_name: str,
    method: str,
    *,
    procedure: str = "usp_Save",
    evidence: InvocationEvidence = InvocationEvidence.PROVEN,
    reason: str = "",
) -> DbInvocation:
    return DbInvocation(
        class_name=class_name,
        method_name=method,
        database="OrdersDb",
        procedure_name=procedure,
        evidence=evidence,
        reason=reason,
        source=InvocationSourceSpan(relative_path, 0, 10),
        procedure_schema="dbo",
        method_chain=(method,),
    )


def _analyze(
    monkeypatch,
    root: Path,
    scan,
    program_names: Sequence[str],
    source: _GivenEvidence,
    *,
    database: str = "OrdersDb",
):
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda r, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store, "load_cached", lambda identity: cache_with_procedures()
    )
    monkeypatch.setattr(
        analyze_service,
        "_require_sql_execution_graph",
        lambda database, sql_cache_identity: ({}, {}),
    )
    return analyze_service.analyze(
        AnalyzeRequest(
            database=database, program_names=list(program_names), include_snippets=False
        ),
        evidence_source=source,
    )


def _callers(paths: Sequence[dict]) -> List[str]:
    return sorted(str(path["caller"]) for path in paths)


def _component_screen(tmp_path: Path):
    """The Order Index screen. It renders the Menu ViewComponent."""
    return _component_scan(
        tmp_path,
        views=[_view_result(tmp_path, "Views/Order/Index.cshtml", view_components=["Menu"])],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[
            _view_component_result(
                tmp_path,
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                extra_methods=["LoadAll"],
            )
        ],
    )


def test_one_analyze_request_asks_the_evidence_source_one_time(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Orders/Index.cshtml", "Views/Invoices/Index.cshtml"],
        controllers={
            "Controllers/OrdersController.cs": ["Index"],
            "Controllers/InvoicesController.cs": ["Index"],
        },
    )
    source = _GivenEvidence()

    response = _analyze(monkeypatch, tmp_path, scan, ["Orders", "Invoices"], source)

    assert len(response.programs) == 2
    assert len(source.calls) == 1
    assert sorted(Path(r.file_path).name for r in source.calls[0]) == [
        "InvoicesController.cs",
        "OrdersController.cs",
    ]


def test_the_needed_files_include_the_files_of_every_shared_component(
    monkeypatch, tmp_path: Path
) -> None:
    source = _GivenEvidence()

    _analyze(monkeypatch, tmp_path, _component_screen(tmp_path), ["Index"], source)

    assert len(source.calls) == 1
    assert sorted(Path(r.file_path).name for r in source.calls[0]) == [
        "MenuViewComponent.cs",
        "OrderController.cs",
    ]


def test_a_webforms_program_reports_only_the_invocations_of_its_own_files(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        pages=["OrderEntry.aspx"],
        controllers={"OrderEntry.aspx.cs": ["Page_Load"], "Billing.cs": ["Run"]},
    )
    own = _invocation_on("OrderEntry.aspx.cs", "OrderEntry", "Page_Load", procedure="usp_Own")
    foreign = _invocation_on("Billing.cs", "Billing", "Run", procedure="usp_Foreign")

    response = _analyze(
        monkeypatch, tmp_path, scan, ["OrderEntry"], _GivenEvidence([foreign, own])
    )

    program = response.programs[0]
    assert [d["procedure_name"] for d in program.database_invocations] == ["usp_Own"]
    assert _callers(program.execution_paths) == ["OrderEntry.Page_Load"]


def test_an_mvc_program_screen_reports_only_the_invocations_of_its_own_actions(
    monkeypatch, tmp_path: Path
) -> None:
    """The Orders screen has the Index view only. Delete is an action of the
    controller, but the screen does not own it."""
    scan = _scan(
        tmp_path,
        views=["Views/Orders/Index.cshtml"],
        controllers={"Controllers/OrdersController.cs": ["Index", "Delete"]},
    )
    index = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Index")
    delete = _invocation_on("Controllers/OrdersController.cs", "OrdersController", "Delete")

    response = _analyze(monkeypatch, tmp_path, scan, ["Orders"], _GivenEvidence([index, delete]))

    program = response.programs[0]
    assert [d["method_name"] for d in program.database_invocations] == ["Index"]
    assert _callers(program.execution_paths) == ["OrdersController.Index"]


def test_a_shared_component_reports_the_invocations_of_its_entry_method(
    monkeypatch, tmp_path: Path
) -> None:
    component = "Components/MenuViewComponent.cs"
    entry = _invocation_on(component, "MenuViewComponent", "InvokeAsync", procedure="usp_Menu")
    other = _invocation_on(component, "MenuViewComponent", "LoadAll", procedure="usp_All")

    response = _analyze(
        monkeypatch,
        tmp_path,
        _component_screen(tmp_path),
        ["Index"],
        _GivenEvidence([other, entry]),
    )

    program = response.programs[0]
    assert [
        (d["procedure_name"], d["shared_component"]["name"])
        for d in program.database_invocations
    ] == [("usp_Menu", "Menu")]
    assert program.stored_procedures == ["usp_Menu"]


def test_two_analyze_requests_on_one_retained_evidence_keep_the_retained_paths(
    monkeypatch, tmp_path: Path
) -> None:
    """Without a SQL graph and without a Database, `/analyze` rewrites the
    unresolved reason of a path. It must rewrite a copy, not the retained path."""
    scan = _scan(tmp_path, pages=["OrderEntry.aspx"], controllers={"OrderEntry.aspx.cs": ["Page_Load"]})
    unresolved = _invocation_on(
        "OrderEntry.aspx.cs",
        "OrderEntry",
        "Page_Load",
        procedure="usp_Missing",
        evidence=InvocationEvidence.UNRESOLVED,
        reason="not_in_resolved_catalog",
    )
    source = _GivenEvidence([unresolved])
    retained = copy.deepcopy(source.evidence.paths_of([unresolved]))

    answers = [
        _analyze(monkeypatch, tmp_path, scan, ["OrderEntry"], source, database="")
        for _ in range(2)
    ]

    for answer in answers:
        path = answer.programs[0].execution_paths[0]
        assert path["unresolved_reason"] == "stored_procedure_not_in_graph"
        assert path["unresolved_targets"] == ["dbo.usp_Missing"]
    assert answers[0].programs[0].execution_paths == answers[1].programs[0].execution_paths
    assert source.evidence.paths_of([unresolved]) == retained

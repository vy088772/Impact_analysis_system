"""`/flow_chain` forward finds the files and actions of a Program Screen (ADR-0019).

Endpoint-seam tests of derived-execution-evidence-one-module, ticket 05. Each test
gives `flow_chain()` fixed Derived Execution Evidence, so the answer shows which
program files the forward direction selected and which actions it owns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from service import analyze_service
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FlowChainRequest
from tests.program_screen_fixtures import _scan
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
    one_server_holds_every_database,
)

_DATABASE = "OrdersDb"


def _graph(procedures: Sequence[str]) -> dict:
    """Each stored procedure updates one table of its own."""
    nodes: List[dict] = []
    relationships: List[dict] = []
    for name in procedures:
        module = f"stored_procedure:dbo.{name}"
        operation = f"dml_operation:{module}:1"
        table = f"table:dbo.T_{name}"
        nodes += [
            {"id": module, "type": "stored_procedure", "schema": "dbo", "name": name},
            {"id": operation, "type": "dml_operation", "module_id": module, "sequence": 1, "operation_type": "UPDATE"},
            {"id": table, "type": "table", "schema": "dbo", "name": f"T_{name}"},
        ]
        relationships += [
            {"type": "contains", "source": module, "target": operation},
            {"type": "writes", "source": operation, "target": table, "columns": ["X"]},
        ]
    return execution_graph(_DATABASE, nodes=nodes, relationships=relationships)


def _invocation(relative_path: str, class_name: str, method_name: str, procedure: str) -> DbInvocation:
    return DbInvocation(
        class_name=class_name,
        method_name=method_name,
        database=_DATABASE,
        procedure_name=procedure,
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan(relative_path=relative_path, start_offset=0, end_offset=10),
        command_text_literal="",
    )


class _Source:
    """An evidence source that gives fixed evidence and records what each request asked for."""

    def __init__(
        self,
        invocations: List[DbInvocation],
        procedures: Sequence[str],
        *,
        paths_by_invocation: Sequence[List[dict]] | None = None,
    ) -> None:
        self._evidence = DerivedExecutionEvidence(
            invocations, _graph(procedures), paths_by_invocation=paths_by_invocation
        )
        self.needed_files: List[List[str]] = []
        self.refreshes: List[bool] = []

    def __call__(self, scope, per_root_scans, merged_scan, root, *, needed_files=None, refresh=False):
        self.needed_files.append([] if needed_files is None else [f.file_path for f in needed_files])
        self.refreshes.append(refresh)
        return self._evidence


def _forward(
    monkeypatch,
    root: Path,
    scan,
    source: _Source,
    program_name: str,
    anchor_method: str,
    *,
    procedures: Sequence[str],
):
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda src, refresh=False: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda r, refresh=False: scan)
    monkeypatch.setattr(analyze_service.sql_cache_store, "find_cache_identity", one_server_holds_every_database)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: cache_payload(_DATABASE, graph=_graph(procedures)),
    )
    return analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "screens", "repo": "screens"},
            direction="forward",
            program_name=program_name,
            anchor_method=anchor_method,
            database=_DATABASE,
            cache_only=False,
            refresh=True,
        ),
        evidence_source=source,
    )


def _procedures(response) -> List[str]:
    assert response.forward_chain is not None
    return [entry["name"] for entry in response.forward_chain["stored_procedures"]]


def _job_duty_scan(root: Path):
    return _scan(
        root,
        views=["Views/JobDuty/JobDutyMtn.cshtml"],
        controllers={"Controllers/JobDutyController.cs": ["JobDutyMtn", "Delete"]},
    )


def test_an_mvc_screen_gets_a_forward_chain_through_its_controller(monkeypatch, tmp_path: Path) -> None:
    source = _Source(
        [
            _invocation("Controllers/JobDutyController.cs", "JobDutyController", "JobDutyMtn", "usp_Save"),
            _invocation("Controllers/JobDutyController.cs", "JobDutyController", "Delete", "usp_Remove"),
        ],
        ["usp_Save", "usp_Remove"],
    )

    response = _forward(
        monkeypatch, tmp_path, _job_duty_scan(tmp_path), source, "JobDutyMtn", "JobDutyMtn",
        procedures=["usp_Save", "usp_Remove"],
    )

    assert response.forward_chain is not None
    assert response.forward_chain["method_path"] == ["JobDutyMtn"]
    assert _procedures(response) == ["dbo.usp_Save"]


def test_forward_uses_the_paths_supplied_by_the_evidence_source(monkeypatch, tmp_path: Path) -> None:
    source = _Source(
        [_invocation("Controllers/JobDutyController.cs", "JobDutyController", "JobDutyMtn", "usp_Save")],
        ["usp_Save"],
        paths_by_invocation=[[
            {
                "path_id": "retained-path",
                "entry_method": "JobDutyController.JobDutyMtn",
                "evidence": "unresolved",
                "unresolved_reason": "called_procedure_not_in_graph",
                "sp_chain": [],
                "reads": [],
                "writes": [],
            }
        ]],
    )

    response = _forward(
        monkeypatch, tmp_path, _job_duty_scan(tmp_path), source, "JobDutyMtn", "JobDutyMtn",
        procedures=["usp_Save"],
    )

    assert response.forward_chain is not None
    assert _procedures(response) == []
    assert [path["path_id"] for path in response.forward_chain["unresolved_paths"]] == ["retained-path"]


def test_forward_keeps_an_empty_path_answer_from_the_evidence_source(monkeypatch, tmp_path: Path) -> None:
    source = _Source(
        [_invocation("Controllers/JobDutyController.cs", "JobDutyController", "JobDutyMtn", "usp_Save")],
        ["usp_Save"],
        paths_by_invocation=[[]],
    )

    response = _forward(
        monkeypatch, tmp_path, _job_duty_scan(tmp_path), source, "JobDutyMtn", "JobDutyMtn",
        procedures=["usp_Save"],
    )

    assert _procedures(response) == []
    assert response.forward_chain["unresolved_paths"] == []


def test_a_webforms_forward_chain_excludes_other_programs_with_the_same_method(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        controllers={"Legacy/Alpha.aspx.cs": ["Save"], "Legacy/Beta.aspx.cs": ["Save"]},
        pages=["Legacy/Alpha.aspx", "Legacy/Beta.aspx"],
    )
    procedures = ["usp_Alpha", "usp_Beta"]
    source = _Source(
        [
            _invocation("Legacy/Alpha.aspx.cs", "Alpha", "Save", "usp_Alpha"),
            _invocation("Legacy/Beta.aspx.cs", "Beta", "Save", "usp_Beta"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "Alpha", "Save", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_Alpha"]


def test_forward_gives_the_module_the_files_of_the_resolution_and_the_refresh_flag(
    monkeypatch, tmp_path: Path
) -> None:
    source = _Source([], [])

    _forward(
        monkeypatch, tmp_path, _job_duty_scan(tmp_path), source, "JobDutyMtn", "JobDutyMtn", procedures=[]
    )

    assert source.needed_files == [[str(tmp_path / "Controllers/JobDutyController.cs")]]
    assert source.refreshes == [True]


def test_an_anchor_that_is_not_an_action_of_the_screen_gives_no_chain(monkeypatch, tmp_path: Path) -> None:
    source = _Source(
        [_invocation("Controllers/JobDutyController.cs", "JobDutyController", "Delete", "usp_Remove")],
        ["usp_Remove"],
    )

    response = _forward(
        monkeypatch, tmp_path, _job_duty_scan(tmp_path), source, "JobDutyMtn", "Delete",
        procedures=["usp_Remove"],
    )

    assert response.forward_chain is None


def test_one_name_that_resolves_to_several_screens_gives_one_merged_chain(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=[
            "Areas/Admin/Views/Report/Summary.cshtml",
            "Areas/Sales/Views/Report/Summary.cshtml",
        ],
        controllers={
            "Areas/Admin/Controllers/ReportController.cs": ["Summary", "AdminOnly"],
            "Areas/Sales/Controllers/ReportController.cs": ["Summary", "SalesOnly"],
        },
    )
    procedures = ["usp_Admin", "usp_Sales", "usp_AdminOnly"]
    source = _Source(
        [
            _invocation("Areas/Admin/Controllers/ReportController.cs", "ReportController", "Summary", "usp_Admin"),
            _invocation("Areas/Sales/Controllers/ReportController.cs", "ReportController", "Summary", "usp_Sales"),
            _invocation("Areas/Admin/Controllers/ReportController.cs", "ReportController", "AdminOnly", "usp_AdminOnly"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "Summary", "Summary", procedures=procedures)

    assert sorted(_procedures(response)) == ["dbo.usp_Admin", "dbo.usp_Sales"]
    assert sorted(source.needed_files[0]) == [
        str(tmp_path / "Areas/Admin/Controllers/ReportController.cs"),
        str(tmp_path / "Areas/Sales/Controllers/ReportController.cs"),
    ]


def test_a_controller_action_of_another_screen_never_joins_the_chain(monkeypatch, tmp_path: Path) -> None:
    """The screen's own controller also holds `Detail`, but the screen reaches only the shared one."""
    scan = _scan(
        tmp_path,
        views=["Views/Order/OrderMtn.cshtml"],
        controllers={
            "Controllers/OrderController.cs": ["OrderMtn", "Detail"],
            "Controllers/SharedApiController.cs": ["Detail"],
        },
        determined_anchors={"Views/Order/OrderMtn.cshtml": [{"controller": "SharedApi", "action": "Detail"}]},
    )
    procedures = ["usp_OrderDetail", "usp_SharedDetail"]
    source = _Source(
        [
            _invocation("Controllers/OrderController.cs", "OrderController", "Detail", "usp_OrderDetail"),
            _invocation("Controllers/SharedApiController.cs", "SharedApiController", "Detail", "usp_SharedDetail"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "OrderMtn", "Detail", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_SharedDetail"]


def test_a_webforms_program_keeps_its_forward_chain_in_a_repository_with_views(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Other/Other.cshtml"],
        controllers={"Legacy/JobDutyMtn.aspx.cs": ["Page_Load", "btnSave_Click"]},
        pages=["Legacy/JobDutyMtn.aspx"],
    )
    source = _Source(
        [_invocation("Legacy/JobDutyMtn.aspx.cs", "JobDutyMtn", "btnSave_Click", "usp_Save")],
        ["usp_Save"],
    )

    response = _forward(
        monkeypatch, tmp_path, scan, source, "JobDutyMtn", "btnSave_Click", procedures=["usp_Save"]
    )

    assert _procedures(response) == ["dbo.usp_Save"]

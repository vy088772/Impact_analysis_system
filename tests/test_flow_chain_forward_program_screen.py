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
from tests.scan_fixtures import with_bound_calls
from tests.request_context_fixtures import RequestStores
from tests.sql_cache_fixtures import (
    cache_payload,
    execution_graph,
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
    stores = RequestStores.of(root, scan)
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
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
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


# ADR-0044: from the anchor action, the chain follows each Bound Call Target into any file of
# the scan root. The program scope selects the anchor action only.


def _service_scan(root: Path, calls: Dict[str, Sequence[str]], services: Dict[str, Sequence[str]]):
    """The JobType screen and its controller, the named service files, and the Bound Call Targets."""
    scan = _scan(
        root,
        views=["Views/JobType/JobTypeMtn.cshtml"],
        controllers={"Controllers/JobTypeController.cs": ["JobTypeMtn", "JobTypeInvalid"], **services},
        determined_anchors={
            "Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]
        },
    )
    return with_bound_calls(scan, "bound_calls.cs", calls)


def test_an_action_reaches_the_stored_procedure_of_the_service_method_it_calls(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _service_scan(
        tmp_path,
        {"JobTypeController.JobTypeInvalid": ["JobTypeService.InvalidateJobType"]},
        {"Services/JobTypeService.cs": ["InvalidateJobType", "GetJobType"]},
    )
    procedures = ["usp_MS_JobTypeInValid", "usp_MS_GetJobType"]
    source = _Source(
        [
            _invocation("Services/JobTypeService.cs", "JobTypeService", "InvalidateJobType", "usp_MS_JobTypeInValid"),
            _invocation("Services/JobTypeService.cs", "JobTypeService", "GetJobType", "usp_MS_GetJobType"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeInvalid", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_MS_JobTypeInValid"]
    assert response.forward_chain["method_path"] == ["JobTypeInvalid", "InvalidateJobType"]
    assert sorted(source.needed_files[0]) == [
        str(tmp_path / "Controllers/JobTypeController.cs"),
        str(tmp_path / "Services/JobTypeService.cs"),
    ]


def test_a_path_joins_by_the_method_that_holds_its_invocation_not_by_its_entry_method(
    monkeypatch, tmp_path: Path
) -> None:
    """The same-file caller chain can start at a method the action never reaches (RTTalentDB:
    the regex parser reads the primary constructor `JobTypeService(` as a method)."""
    scan = _service_scan(
        tmp_path,
        {"JobTypeController.JobTypeMtn": ["JobTypeService.GetJobType"]},
        {"Services/JobTypeService.cs": ["JobTypeService", "GetJobType", "GetOther"]},
    )
    path = {
        "path_id": "service-path",
        "entry_method": "JobTypeService.JobTypeService",
        "caller_class": "JobTypeService",
        "caller_method": "GetJobType",
        "evidence": "unresolved",
        "unresolved_reason": "command_text_method_parameter",
        "sp_chain": [],
        "reads": [],
        "writes": [],
    }
    other = dict(path, path_id="other-path", caller_method="GetOther")
    source = _Source(
        [
            _invocation("Services/JobTypeService.cs", "JobTypeService", "GetJobType", "usp_A"),
            _invocation("Services/JobTypeService.cs", "JobTypeService", "GetOther", "usp_B"),
        ],
        ["usp_A", "usp_B"],
        paths_by_invocation=[[path], [other]],
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeMtn", procedures=["usp_A", "usp_B"])

    assert [p["path_id"] for p in response.forward_chain["unresolved_paths"]] == ["service-path"]


def test_a_service_that_calls_another_service_contributes_its_stored_procedures(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _service_scan(
        tmp_path,
        {
            "JobTypeController.JobTypeMtn": ["JobTypeService.GetJobType"],
            "JobTypeService.GetJobType": ["UtilityService.DataBring"],
        },
        {"Services/JobTypeService.cs": ["GetJobType"], "Services/UtilityService.cs": ["DataBring"]},
    )
    procedures = ["usp_MS_GetJobType", "usp_SYS_DataBring"]
    source = _Source(
        [
            _invocation("Services/JobTypeService.cs", "JobTypeService", "GetJobType", "usp_MS_GetJobType"),
            _invocation("Services/UtilityService.cs", "UtilityService", "DataBring", "usp_SYS_DataBring"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeMtn", procedures=procedures)

    assert sorted(_procedures(response)) == ["dbo.usp_MS_GetJobType", "dbo.usp_SYS_DataBring"]


def test_two_methods_with_one_name_in_two_classes_stay_two_nodes(monkeypatch, tmp_path: Path) -> None:
    scan = _service_scan(
        tmp_path,
        {"JobTypeController.JobTypeMtn": ["JobTypeService.Save"], "OtherService.Save": ["OtherService.Audit"]},
        {"Services/JobTypeService.cs": ["Save"], "Services/OtherService.cs": ["Save", "Audit"]},
    )
    procedures = ["usp_JobType_Save", "usp_Other_Save", "usp_Other_Audit"]
    source = _Source(
        [
            _invocation("Services/JobTypeService.cs", "JobTypeService", "Save", "usp_JobType_Save"),
            _invocation("Services/OtherService.cs", "OtherService", "Save", "usp_Other_Save"),
            _invocation("Services/OtherService.cs", "OtherService", "Audit", "usp_Other_Audit"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeMtn", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_JobType_Save"]


def test_the_reach_has_no_depth_limit_and_stops_each_cycle(monkeypatch, tmp_path: Path) -> None:
    depth = 12
    calls: Dict[str, Sequence[str]] = {"JobTypeController.JobTypeMtn": ["Step0.Run"]}
    calls.update({f"Step{i}.Run": [f"Step{i + 1}.Run"] for i in range(depth)})
    calls[f"Step{depth}.Run"] = ["Step0.Run", "JobTypeController.JobTypeMtn"]
    scan = _service_scan(tmp_path, calls, {f"Services/Step{i}.cs": ["Run"] for i in range(depth + 1)})
    procedures = ["usp_Deepest"]
    source = _Source([_invocation(f"Services/Step{depth}.cs", f"Step{depth}", "Run", "usp_Deepest")], procedures)

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeMtn", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_Deepest"]
    assert len(response.forward_chain["method_path"]) == depth + 2


def test_a_call_with_no_bound_call_target_stops_its_branch(monkeypatch, tmp_path: Path) -> None:
    scan = _service_scan(
        tmp_path,
        {"JobTypeController.JobTypeMtn": ["!ambiguous_implementation"]},
        {"Services/SharedA.cs": ["Run"], "Services/SharedB.cs": ["Run"]},
    )
    procedures = ["usp_A", "usp_B"]
    source = _Source(
        [
            _invocation("Services/SharedA.cs", "SharedA", "Run", "usp_A"),
            _invocation("Services/SharedB.cs", "SharedB", "Run", "usp_B"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "JobTypeMtn", "JobTypeMtn", procedures=procedures)

    assert _procedures(response) == []
    assert response.forward_chain["reachable_methods"] == ["JobTypeMtn"]


def test_a_webforms_chain_does_not_match_the_call_text(monkeypatch, tmp_path: Path) -> None:
    """The regex parser still records call text, but only a Bound Call Target is an edge."""
    scan = _scan(
        tmp_path,
        controllers={"Legacy/Alpha.aspx.cs": ["btnSave_Click", "BindData"], "Legacy/Beta.aspx.cs": ["Helper"]},
        pages=["Legacy/Alpha.aspx", "Legacy/Beta.aspx"],
    )
    scan.csharp_results[0].classes[0].methods[0].calls = ["BindData", "Helper"]
    with_bound_calls(scan, "Legacy/Alpha.aspx.cs", {"Alpha.btnSave_Click": ["Alpha.BindData"]})
    procedures = ["usp_Bind", "usp_Helper"]
    source = _Source(
        [
            _invocation("Legacy/Alpha.aspx.cs", "Alpha", "BindData", "usp_Bind"),
            _invocation("Legacy/Beta.aspx.cs", "Beta", "Helper", "usp_Helper"),
        ],
        procedures,
    )

    response = _forward(monkeypatch, tmp_path, scan, source, "Alpha", "btnSave_Click", procedures=procedures)

    assert _procedures(response) == ["dbo.usp_Bind"]

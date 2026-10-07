"""`/flow_chain` backward walks back to the action and its Program Screens (ADR-0044, ADR-0019).

Endpoint-seam tests of rttalentdb-program-to-sql-chain, ticket 07. Each test gives
`flow_chain()` fixed Derived Execution Evidence for a service method, and the Bound Call
Targets that lead an action to it. The answer shows which Program Screens the backward
chain gives, at which strength.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan
from service import analyze_service
from service.derived_execution_evidence import DerivedExecutionEvidence
from service.schemas import FlowChainRequest
from tests.program_screen_fixtures import _scan
from tests.request_context_fixtures import RequestStores
from tests.scan_fixtures import source_offset, with_bound_calls
from tests.sql_cache_fixtures import cache_payload, execution_graph

_DATABASE = "OrdersDb"
_PROCEDURE = "usp_InvalidateJobType"
_TABLE = "dbo.T_JobType"
_SERVICE = "Services/JobTypeService.cs"
_CONTROLLER = "Controllers/JobTypeController.cs"


def _graph() -> dict:
    module = f"stored_procedure:dbo.{_PROCEDURE}"
    operation = f"dml_operation:{module}:1"
    table = "table:dbo.T_JobType"
    return execution_graph(
        _DATABASE,
        nodes=[
            {"id": module, "type": "stored_procedure", "schema": "dbo", "name": _PROCEDURE},
            {"id": operation, "type": "dml_operation", "module_id": module, "sequence": 1, "operation_type": "UPDATE"},
            {"id": table, "type": "table", "schema": "dbo", "name": "T_JobType"},
        ],
        relationships=[
            {"type": "contains", "source": module, "target": operation},
            {"type": "writes", "source": operation, "target": table, "columns": ["Valid"]},
        ],
    )


def _source_span(relative_path: str, node: str) -> InvocationSourceSpan:
    """A source span inside the method span of `node` (see `tests.scan_fixtures`)."""
    start = source_offset(node)
    return InvocationSourceSpan(relative_path=relative_path, start_offset=start, end_offset=start + 10)


def _invocation(
    relative_path: str,
    class_name: str,
    method_name: str,
    method_chain: Sequence[str] = (),
    *,
    node: str = "",
) -> DbInvocation:
    """A proven invocation inside the method span of `node` (default `class_name.method_name`)."""
    return DbInvocation(
        class_name=class_name,
        method_name=method_name,
        method_chain=tuple(method_chain),
        database=_DATABASE,
        procedure_name=_PROCEDURE,
        evidence=InvocationEvidence.PROVEN,
        source=_source_span(relative_path, node or f"{class_name}.{method_name}"),
        command_text_literal="",
    )


def _service_invocation() -> DbInvocation:
    return _invocation(_SERVICE, "JobTypeService", "InvalidateJobType")


def _source(invocations: List[DbInvocation]):
    evidence = DerivedExecutionEvidence(invocations, _graph())

    def source(scope, per_root_scans, merged_scan, root, *, needed_files=None, refresh=False):
        return evidence

    return source


def _backward(monkeypatch, root: Path, scan, *invocations: DbInvocation) -> List[dict]:
    stores = RequestStores.of(root, scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: cache_payload(_DATABASE, graph=_graph()),
    )
    response = analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "screens", "repo": "screens"},
            direction="backward",
            table_name=_TABLE,
            database=_DATABASE,
            cache_only=False,
            refresh=True,
        ),
        evidence_source=_source(list(invocations)),
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )
    return response.backward_chains


def _job_type_scan(
    root: Path,
    *,
    views: Sequence[str] = ("Views/JobType/JobTypeMtn.cshtml",),
    controllers: Mapping[str, Sequence[str]] = {},
    determined_anchors: Mapping[str, Sequence[Dict]] = {},
    candidate_anchors: Mapping[str, Sequence[Dict]] = {},
    calls: Mapping[str, Sequence[str]] = {"JobTypeController.JobTypeInvalid": ["JobTypeService.InvalidateJobType"]},
):
    scan = _scan(
        root,
        views=list(views),
        controllers={
            _CONTROLLER: ["JobTypeMtn", "JobTypeInvalid"],
            _SERVICE: ["InvalidateJobType"],
            **controllers,
        },
        determined_anchors=determined_anchors,
        candidate_anchors=candidate_anchors,
    )
    return with_bound_calls(scan, _CONTROLLER, calls)


def _screens(chain: dict) -> List[tuple]:
    return sorted(
        (anchor["view"], anchor["action"], anchor["strength"])
        for anchor in chain["ui_anchors"]
        if anchor.get("kind") == "program_screen"
    )


def _service_chain(chains: List[dict]) -> dict:
    return next(chain for chain in chains if chain["method"] == "InvalidateJobType")


def test_a_table_that_a_service_method_reaches_gives_the_action_and_its_view(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path,
        determined_anchors={"Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]},
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert chain["file"] == _SERVICE
    assert chain["ui_anchors"] == [
        {
            "kind": "program_screen",
            "file": "Views/JobType/JobTypeMtn.cshtml",
            "view": "JobTypeMtn",
            "controller_file": _CONTROLLER,
            "action": "JobTypeInvalid",
            "strength": "determined",
        }
    ]


def test_a_same_name_action_gives_its_view_as_determined(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path, calls={"JobTypeController.JobTypeMtn": ["JobTypeService.InvalidateJobType"]}
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [("JobTypeMtn", "JobTypeMtn", "determined")]


def test_the_walk_back_goes_through_a_second_service_with_no_depth_limit(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path,
        controllers={"Services/UtilityService.cs": ["Run"]},
        calls={"JobTypeController.JobTypeMtn": ["UtilityService.Run"]},
    )
    scan = with_bound_calls(
        scan,
        "Services/UtilityService.cs",
        {"UtilityService.Run": ["JobTypeService.InvalidateJobType", "UtilityService.Run"]},
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [("JobTypeMtn", "JobTypeMtn", "determined")]


def test_an_action_that_two_program_screens_hold_gives_both_screens(monkeypatch, tmp_path: Path) -> None:
    anchor = [{"controller": "JobType", "action": "JobTypeInvalid"}]
    scan = _job_type_scan(
        tmp_path,
        views=["Views/JobType/JobTypeMtn.cshtml", "Views/Report/JobTypeReport.cshtml"],
        controllers={"Controllers/ReportController.cs": ["JobTypeReport"]},
        determined_anchors={
            "Views/JobType/JobTypeMtn.cshtml": anchor,
            "Views/Report/JobTypeReport.cshtml": anchor,
        },
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [
        ("JobTypeMtn", "JobTypeInvalid", "determined"),
        ("JobTypeReport", "JobTypeInvalid", "determined"),
    ]


def test_a_screen_that_reaches_the_action_only_through_a_script_url_is_likely(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path,
        candidate_anchors={"Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]},
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [("JobTypeMtn", "JobTypeInvalid", "likely")]


def test_an_action_that_no_screen_holds_gives_no_screen(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(tmp_path)

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert chain["ui_anchors"] == []


def test_a_method_with_no_bound_call_to_it_gives_no_screen(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path,
        determined_anchors={"Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]},
        calls={"JobTypeController.JobTypeInvalid": ["!no_local_implementer"]},
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert chain["ui_anchors"] == []


def test_a_chain_names_the_method_that_holds_the_invocation_not_the_outer_entry(monkeypatch, tmp_path: Path) -> None:
    # On RTTalentDB the regex parser reads a primary constructor `JobTypeService(` as a
    # method, so every service path in the file has that entry method (ticket 05).
    scan = _job_type_scan(
        tmp_path,
        controllers={_SERVICE: ["JobTypeService", "InvalidateJobType", "RestoreJobType"]},
        determined_anchors={"Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]},
        calls={
            "JobTypeController.JobTypeInvalid": ["JobTypeService.InvalidateJobType"],
            "JobTypeController.JobTypeMtn": ["JobTypeService.RestoreJobType"],
        },
    )
    entry = ["JobTypeService"]

    chains = _backward(
        monkeypatch,
        tmp_path,
        scan,
        _invocation(_SERVICE, "JobTypeService", "InvalidateJobType", [*entry, "InvalidateJobType"]),
        _invocation(_SERVICE, "JobTypeService", "RestoreJobType", [*entry, "RestoreJobType"]),
    )

    assert sorted((chain["method"], chain["entry_method"]) for chain in chains) == [
        ("InvalidateJobType", "JobTypeService.JobTypeService"),
        ("RestoreJobType", "JobTypeService.JobTypeService"),
    ]
    by_method = {chain["method"]: _screens(chain) for chain in chains}
    assert by_method == {
        "InvalidateJobType": [("JobTypeMtn", "JobTypeInvalid", "determined")],
        "RestoreJobType": [("JobTypeMtn", "JobTypeMtn", "determined")],
    }


def test_a_screen_that_names_the_action_in_markup_and_in_a_script_url_is_determined(
    monkeypatch, tmp_path: Path
) -> None:
    anchor = [{"controller": "JobType", "action": "JobTypeInvalid"}]
    scan = _job_type_scan(
        tmp_path,
        determined_anchors={"Views/JobType/JobTypeMtn.cshtml": anchor},
        candidate_anchors={"Views/JobType/JobTypeMtn.cshtml": anchor},
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [("JobTypeMtn", "JobTypeInvalid", "determined")]


def test_a_razor_pages_handler_gives_its_page(monkeypatch, tmp_path: Path) -> None:
    scan = _job_type_scan(
        tmp_path,
        views=["Pages/JobTypes.cshtml"],
        controllers={"Pages/JobTypes.cshtml.cs": ["OnPostInvalidate"]},
    )
    scan.razor_results[0].has_page_directive = True
    scan = with_bound_calls(
        scan, "Pages/JobTypes.cshtml.cs", {"JobTypes.OnPostInvalidate": ["JobTypeService.InvalidateJobType"]}
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, _service_invocation()))

    assert _screens(chain) == [("JobTypes", "OnPostInvalidate", "determined")]


def test_a_webforms_chain_names_the_holding_method_and_keeps_the_control_event_of_its_entry(
    monkeypatch, tmp_path: Path
) -> None:
    # The page method calls the holding method through no call text the scan sees, so
    # only the entry method finds the control event.
    scan = _scan(tmp_path, controllers={"Legacy/Alpha.aspx.cs": ["btnSave_Click", "SaveData"]}, pages=["Legacy/Alpha.aspx"])
    scan.aspx_results[0].ui_fields = [
        {"control": "asp:Button", "id": "btnSave", "events": {"Click": "btnSave_Click"}}
    ]

    chains = _backward(
        monkeypatch,
        tmp_path,
        scan,
        _invocation("Legacy/Alpha.aspx.cs", "Alpha", "SaveData", ["btnSave_Click", "SaveData"]),
    )

    assert [(chain["method"], chain["entry_method"]) for chain in chains] == [("SaveData", "Alpha.btnSave_Click")]
    assert chains[0]["ui_anchors"] == [
        {
            "file": str(tmp_path / "Legacy/Alpha.aspx"),
            "control": "asp:Button",
            "id": "btnSave",
            "event": "Click",
            "handler": "btnSave_Click",
        }
    ]


def test_the_backward_chain_from_one_overload_does_not_reach_an_action_that_calls_only_the_other(
    monkeypatch, tmp_path: Path
) -> None:
    """ADR-0044: the stored procedure is in `InvalidateJobType(string)`. `JobTypeMtn` calls only
    `InvalidateJobType(int)`, so it is not a Program Screen action of the chain."""
    scan = _job_type_scan(
        tmp_path,
        determined_anchors={"Views/JobType/JobTypeMtn.cshtml": [{"controller": "JobType", "action": "JobTypeInvalid"}]},
        calls={
            "JobTypeController.JobTypeMtn": ["JobTypeService.InvalidateJobType(int)"],
            "JobTypeController.JobTypeInvalid": ["JobTypeService.InvalidateJobType(string)"],
        },
    )
    with_bound_calls(
        scan,
        _SERVICE,
        {"JobTypeService.InvalidateJobType(int)": [], "JobTypeService.InvalidateJobType(string)": []},
    )
    invocation = _invocation(
        _SERVICE, "JobTypeService", "InvalidateJobType", node="JobTypeService.InvalidateJobType(string)"
    )

    chain = _service_chain(_backward(monkeypatch, tmp_path, scan, invocation))

    assert _screens(chain) == [("JobTypeMtn", "JobTypeInvalid", "determined")]

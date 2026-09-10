"""A specification program code resolves to one Program Screen (ADR-0019).

Every check drives `analyze_service.analyze()` — the seam the spec names — and
asserts on what the analysis reports: which file the program located, which
actions it holds, and which stored procedures those actions reach.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from code_analyzer.models import (
    ClassInfo,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    MethodInfo,
)
from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.razor_parser import RazorParser
from service import analyze_service
from service.schemas import AnalyzeRequest


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _view_result(
    root: Path,
    relative: str,
    *,
    source: str = "",
    determined: Sequence[Dict] = (),
    candidate: Sequence[Dict] = (),
) -> FileAnalysisResult:
    """One scanned view. A view given a `source` is parsed the way a scan parses it."""
    assert not (source and (determined or candidate)), (
        "a parsed view takes its anchors from its own source"
    )
    path = _write(root, relative, source or "@{ /* view */ }")
    if source:
        return RazorParser().parse_file(str(path))
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.RAZOR,
        framework=FrameworkType.MVC,
        view_anchors_determined=list(determined),
        view_anchors_candidate=list(candidate),
    )


def _aspx_result(root: Path, relative: str) -> FileAnalysisResult:
    path = _write(root, relative, "<%@ Page %>")
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.ASPX,
        framework=FrameworkType.WEBFORMS,
    )


def _controller_result(
    root: Path, relative: str, actions: Sequence[str]
) -> FileAnalysisResult:
    path = _write(root, relative, "// controller")
    class_name = Path(relative).stem
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.MVC,
        classes=[
            ClassInfo(
                name=class_name,
                namespace="",
                file_path=str(path),
                methods=[
                    MethodInfo(
                        name=action,
                        access_modifier="public",
                        return_type="IActionResult",
                    )
                    for action in actions
                ],
            )
        ],
    )


def _scan(
    root: Path,
    *,
    views: Sequence[str] = (),
    controllers: Mapping[str, Sequence[str]] = {},
    pages: Sequence[str] = (),
    invocations: Mapping[str, List[Dict]] = {},
    view_sources: Mapping[str, str] = {},
    determined_anchors: Mapping[str, Sequence[Dict]] = {},
    candidate_anchors: Mapping[str, Sequence[Dict]] = {},
) -> ProjectScanResult:
    """One scan result holding the named views, controllers and WebForms pages."""
    controller_results = [
        _controller_result(root, relative, actions)
        for relative, actions in controllers.items()
    ]
    db_invocations: Dict[str, List[Dict]] = {}
    connection_sources: Dict[str, Dict] = {}
    for relative, entries in invocations.items():
        key = str((root / relative).resolve())
        db_invocations[key] = list(entries)
        connection_sources[key] = {"conn": "PUR"}
    return ProjectScanResult(
        project_root=str(root),
        project_name="screens",
        scan_time=datetime.now(),
        csharp_results=controller_results,
        razor_results=[
            _view_result(
                root,
                relative,
                source=view_sources.get(relative, ""),
                determined=determined_anchors.get(relative, ()),
                candidate=candidate_anchors.get(relative, ()),
            )
            for relative in views
        ],
        aspx_results=[_aspx_result(root, relative) for relative in pages],
        db_invocations=db_invocations,
        connection_sources=connection_sources,
    )


def _cached_sql_graph(*procedures: str) -> dict:
    return {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [{"name": name} for name in procedures],
        "sql_execution_graph": {
            "graph_version": 1,
            "database": "OrdersDb",
            "nodes": [
                {
                    "id": f"stored_procedure:dbo.{name}",
                    "type": "stored_procedure",
                    "schema": "dbo",
                    "name": name,
                }
                for name in procedures
            ],
            "relationships": [],
            "parse_errors": [],
        },
    }


def _invocation(class_name: str, method_name: str, procedure: str) -> Dict:
    return {
        "class_name": class_name,
        "method_name": method_name,
        "command_text_kind": "literal",
        "command_text": f"dbo.{procedure}",
        "command_type_stored_procedure": True,
        "terminal_sink": "ExecuteNonQuery",
        "connection_expression": "conn",
        "start_offset": 0,
        "end_offset": 10,
    }


def _analyze(
    monkeypatch,
    root: Path,
    scan: ProjectScanResult,
    program_names: Sequence[str],
    *,
    database: str = "",
    procedures: Sequence[str] = (),
    include_view_layer: bool = False,
):
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [root])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda r, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda db, schema, server="": _cached_sql_graph(*procedures),
    )
    return analyze_service.analyze(
        AnalyzeRequest(
            database=database,
            program_names=list(program_names),
            include_snippets=False,
            include_view_layer=include_view_layer,
            fk_depth=0,
        )
    )


def _actions(program) -> List[str]:
    return [entry["name"] for entry in program.methods]


def _strengths(program) -> Dict[str, str]:
    return {entry["name"]: entry.get("strength", "") for entry in program.methods}


# ─────────────────────────────────────────────────────────────────────────────
# The three entry points
# ─────────────────────────────────────────────────────────────────────────────

def test_a_program_code_naming_a_view_folder_resolves_to_that_folders_views(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/AgentMtn/AgentMtnView.cshtml"],
        controllers={"Controllers/AgentMtnController.cs": ["AgentMtnView", "Save"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["AgentMtn"])

    assert response.not_found == []
    assert len(response.programs) == 1
    program = response.programs[0]
    assert program.file == "Views/AgentMtn/AgentMtnView.cshtml"
    assert _actions(program) == ["AgentMtnView"]


def test_a_program_code_naming_a_view_file_resolves_to_that_file(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/JobDuty/JobDutyMtn.cshtml"],
        controllers={"Controllers/JobDutyController.cs": ["JobDutyMtn", "Delete"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["JobDutyMtn"])

    assert len(response.programs) == 1
    assert response.programs[0].file == "Views/JobDuty/JobDutyMtn.cshtml"


def test_a_view_file_may_carry_a_trailing_view_the_program_code_omits(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Agent/AgentMtnView.cshtml"],
        controllers={"Controllers/AgentController.cs": ["AgentMtnView"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["AgentMtn"])

    assert len(response.programs) == 1
    assert response.programs[0].file == "Views/Agent/AgentMtnView.cshtml"


def test_a_view_whose_folder_names_no_controller_binds_the_one_that_serves_it(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Shared/JobDutyMtn.cshtml"],
        controllers={"Controllers/JobDutyController.cs": ["JobDutyMtn", "Delete"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["JobDutyMtn"])

    program = response.programs[0]
    assert program.file == "Views/Shared/JobDutyMtn.cshtml"
    assert _actions(program) == ["JobDutyMtn"]


def test_two_controllers_declaring_the_same_action_name_bind_neither(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Shared/Index.cshtml"],
        controllers={
            "Controllers/HomeController.cs": ["Index"],
            "Controllers/OrderController.cs": ["Index"],
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["Index"])

    assert response.programs[0].file == "Views/Shared/Index.cshtml"
    assert _actions(response.programs[0]) == []


def test_a_program_code_naming_a_controller_file_resolves_through_it(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Shared/Detail.cshtml"],
        controllers={"Controllers/ReportController.cs": ["Detail", "Export"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["Report"])

    assert len(response.programs) == 1
    program = response.programs[0]
    assert program.file == "Views/Shared/Detail.cshtml"
    assert _actions(program) == ["Detail"]


def test_a_controller_reaches_only_the_views_mvc_would_look_up_for_it(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=[
            "Views/Shared/Index.cshtml",
            "Views/Order/Index.cshtml",
        ],
        controllers={
            "Controllers/HomeController.cs": ["Index"],
            "Controllers/OrderController.cs": ["Index"],
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["Home"])

    assert [program.file for program in response.programs] == [
        "Views/Shared/Index.cshtml"
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Areas
# ─────────────────────────────────────────────────────────────────────────────

def _two_area_scan(tmp_path: Path) -> ProjectScanResult:
    return _scan(
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


def test_an_area_qualified_program_code_resolves_to_that_areas_view(
    monkeypatch, tmp_path: Path
) -> None:
    response = _analyze(
        monkeypatch, tmp_path, _two_area_scan(tmp_path), ["Admin/Summary"]
    )

    assert len(response.programs) == 1
    program = response.programs[0]
    assert program.file == "Areas/Admin/Views/Report/Summary.cshtml"
    assert _actions(program) == ["Summary"]
    assert program.methods[0]["class"] == "ReportController"


def test_two_areas_holding_same_named_views_do_not_collide(
    monkeypatch, tmp_path: Path
) -> None:
    response = _analyze(monkeypatch, tmp_path, _two_area_scan(tmp_path), ["Summary"])

    files = sorted(program.file for program in response.programs)
    assert files == [
        "Areas/Admin/Views/Report/Summary.cshtml",
        "Areas/Sales/Views/Report/Summary.cshtml",
    ]
    for program in response.programs:
        assert _actions(program) == ["Summary"]


# ─────────────────────────────────────────────────────────────────────────────
# Whole-name matching
# ─────────────────────────────────────────────────────────────────────────────

def test_a_program_code_never_matches_a_longer_name_that_contains_it(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/JobDutyMtn/JobDutyMtn.cshtml"],
        controllers={
            "Controllers/JobDutyMtnController.cs": ["JobDutyMtn"],
            "Controllers/JobDutyPersonnelSkillDetailController.cs": ["Index"],
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["JobDuty"])

    assert response.programs == []
    assert response.not_found == ["JobDuty"]


def test_a_program_code_matching_nothing_is_reported_as_not_found(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/JobDuty/JobDutyMtn.cshtml"],
        controllers={"Controllers/JobDutyController.cs": ["JobDutyMtn"]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["NoSuchScreen"])

    assert response.programs == []
    assert response.not_found == ["NoSuchScreen"]


# ─────────────────────────────────────────────────────────────────────────────
# One screen holds one view and its own actions
# ─────────────────────────────────────────────────────────────────────────────

def test_a_program_screen_holds_only_the_actions_whose_name_equals_the_view_name(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Import/ImDecl.cshtml"],
        controllers={
            "Controllers/ImportController.cs": [
                "ImDecl",
                "ImportDeclaration",
                "ImportOverdueQry",
            ]
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["ImDecl"])

    assert _actions(response.programs[0]) == ["ImDecl"]


def test_one_controller_serving_three_views_yields_three_program_screens(
    monkeypatch, tmp_path: Path
) -> None:
    controller = "Controllers/ImportController.cs"
    scan = _scan(
        tmp_path,
        views=[
            "Views/Import/ImDecl.cshtml",
            "Views/Import/ImportDeclaration.cshtml",
            "Views/Import/ImportOverdueQry.cshtml",
        ],
        controllers={
            controller: ["ImDecl", "ImportDeclaration", "ImportOverdueQry"]
        },
        invocations={
            controller: [
                _invocation("ImportController", "ImDecl", "usp_ReadDecl"),
                _invocation(
                    "ImportController", "ImportDeclaration", "usp_SaveDecl"
                ),
                _invocation(
                    "ImportController", "ImportOverdueQry", "usp_QueryOverdue"
                ),
            ]
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["ImDecl", "ImportDeclaration", "ImportOverdueQry"],
        database="OrdersDb",
        procedures=("usp_ReadDecl", "usp_SaveDecl", "usp_QueryOverdue"),
    )

    assert len(response.programs) == 3
    reached = {
        program.file: program.stored_procedures for program in response.programs
    }
    assert reached == {
        "Views/Import/ImDecl.cshtml": ["usp_readdecl"],
        "Views/Import/ImportDeclaration.cshtml": ["usp_savedecl"],
        "Views/Import/ImportOverdueQry.cshtml": ["usp_queryoverdue"],
    }


def test_a_view_folder_program_code_yields_one_screen_per_view_in_the_folder(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=[
            "Views/Import/ImDecl.cshtml",
            "Views/Import/ImportOverdueQry.cshtml",
        ],
        controllers={
            "Controllers/ImportController.cs": ["ImDecl", "ImportOverdueQry"]
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["Import"])

    assert sorted(program.file for program in response.programs) == [
        "Views/Import/ImDecl.cshtml",
        "Views/Import/ImportOverdueQry.cshtml",
    ]


def test_a_resolved_program_screen_reports_its_own_view_in_the_view_layer(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=[
            "Views/Import/ImDecl.cshtml",
            "Views/Import/ImportOverdueQry.cshtml",
        ],
        controllers={
            "Controllers/ImportController.cs": ["ImDecl", "ImportOverdueQry"]
        },
    )

    response = _analyze(
        monkeypatch, tmp_path, scan, ["ImDecl"], include_view_layer=True
    )

    assert [entry["file"] for entry in response.programs[0].view_layer] == [
        "Views/Import/ImDecl.cshtml"
    ]


# ─────────────────────────────────────────────────────────────────────────────
# A screen gains the actions its View Anchors name
# ─────────────────────────────────────────────────────────────────────────────

def test_a_program_screen_holds_the_actions_its_determined_anchors_name(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/OrderQry.cshtml"
    scan = _scan(
        tmp_path,
        views=[view],
        controllers={
            "Controllers/OrderController.cs": ["OrderQry", "Export", "Unrelated"]
        },
        determined_anchors={view: [{"action": "Export"}]},
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["OrderQry"])

    program = response.programs[0]
    assert _actions(program) == ["OrderQry", "Export"]
    assert _strengths(program) == {
        "OrderQry": "determined",
        "Export": "determined",
    }


def test_an_action_reached_only_through_a_candidate_anchor_is_carried_at_likely(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/OrderQry.cshtml"
    scan = _scan(
        tmp_path,
        views=[view],
        controllers={
            "Controllers/OrderController.cs": ["OrderQry", "Export", "Detail"]
        },
        determined_anchors={view: [{"action": "Export"}]},
        candidate_anchors={
            view: [
                {"action": "Export", "controller": "Order"},
                {"action": "Detail", "controller": "Order"},
            ]
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["OrderQry"])

    assert _strengths(response.programs[0]) == {
        "OrderQry": "determined",
        "Export": "determined",
        "Detail": "likely",
    }


def test_an_action_on_a_shared_controller_reaches_only_the_screen_that_anchors_it(
    monkeypatch, tmp_path: Path
) -> None:
    """The shape ADR-0019 names: a shared AJAX controller with no view folder."""
    shared = "Controllers/SharedApiController.cs"
    scan = _scan(
        tmp_path,
        views=["Views/Order/Index.cshtml", "Views/Report/Index.cshtml"],
        controllers={
            "Controllers/OrderController.cs": ["Index"],
            "Controllers/ReportController.cs": ["Index"],
            shared: ["Lookup"],
        },
        candidate_anchors={
            "Views/Order/Index.cshtml": [
                {"action": "Lookup", "controller": "SharedApi"}
            ]
        },
        invocations={
            "Controllers/OrderController.cs": [
                _invocation("OrderController", "Index", "usp_OrderIndex")
            ],
            "Controllers/ReportController.cs": [
                _invocation("ReportController", "Index", "usp_ReportIndex")
            ],
            shared: [_invocation("SharedApiController", "Lookup", "usp_Lookup")],
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Index"],
        database="OrdersDb",
        procedures=("usp_OrderIndex", "usp_ReportIndex", "usp_Lookup"),
    )

    reached = {
        program.file: sorted(program.stored_procedures)
        for program in response.programs
    }
    assert reached == {
        "Views/Order/Index.cshtml": ["usp_lookup", "usp_orderindex"],
        "Views/Report/Index.cshtml": ["usp_reportindex"],
    }
    anchoring = next(
        program
        for program in response.programs
        if program.file == "Views/Order/Index.cshtml"
    )
    assert _strengths(anchoring) == {"Index": "determined", "Lookup": "likely"}


def test_an_area_view_anchors_the_shared_controller_that_sits_outside_every_area(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Areas/Admin/Views/Report/Summary.cshtml"
    shared = "Controllers/SharedApiController.cs"
    scan = _scan(
        tmp_path,
        views=[view],
        controllers={
            "Areas/Admin/Controllers/ReportController.cs": ["Summary"],
            shared: ["Lookup"],
        },
        candidate_anchors={view: [{"action": "Lookup", "controller": "SharedApi"}]},
        invocations={
            shared: [_invocation("SharedApiController", "Lookup", "usp_Lookup")]
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Admin/Summary"],
        database="OrdersDb",
        procedures=("usp_Lookup",),
    )

    program = response.programs[0]
    assert program.file == view
    assert program.stored_procedures == ["usp_lookup"]
    assert _strengths(program) == {"Summary": "determined", "Lookup": "likely"}


def test_a_controller_in_two_screens_contributes_only_the_actions_each_anchors(
    monkeypatch, tmp_path: Path
) -> None:
    shared = "Controllers/SharedApiController.cs"
    scan = _scan(
        tmp_path,
        views=["Views/Order/Index.cshtml", "Views/Report/Index.cshtml"],
        controllers={
            "Controllers/OrderController.cs": ["Index"],
            "Controllers/ReportController.cs": ["Index"],
            shared: ["Lookup", "Export"],
        },
        determined_anchors={
            "Views/Order/Index.cshtml": [
                {"action": "Lookup", "controller": "SharedApi"}
            ],
            "Views/Report/Index.cshtml": [
                {"action": "Export", "controller": "SharedApi"}
            ],
        },
        invocations={
            shared: [
                _invocation("SharedApiController", "Lookup", "usp_Lookup"),
                _invocation("SharedApiController", "Export", "usp_Export"),
            ]
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Index"],
        database="OrdersDb",
        procedures=("usp_Lookup", "usp_Export"),
    )

    reached = {
        program.file: program.stored_procedures for program in response.programs
    }
    assert reached == {
        "Views/Order/Index.cshtml": ["usp_lookup"],
        "Views/Report/Index.cshtml": ["usp_export"],
    }


def test_the_anchored_name_never_admits_the_same_name_on_the_screens_own_controller(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Report.cshtml"
    own = "Controllers/OrderController.cs"
    shared = "Controllers/SharedApiController.cs"
    scan = _scan(
        tmp_path,
        views=[view],
        controllers={own: ["Detail"], shared: ["Detail"]},
        determined_anchors={view: [{"action": "Detail", "controller": "SharedApi"}]},
        invocations={
            own: [_invocation("OrderController", "Detail", "usp_OrderDetail")],
            shared: [_invocation("SharedApiController", "Detail", "usp_SharedDetail")],
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Report"],
        database="OrdersDb",
        procedures=("usp_OrderDetail", "usp_SharedDetail"),
    )

    program = response.programs[0]
    assert program.stored_procedures == ["usp_shareddetail"]
    assert program.methods == [
        {"name": "Detail", "class": "SharedApiController", "strength": "determined"}
    ]


def test_the_ajax_detail_query_appears_in_its_screens_impact_chain(
    monkeypatch, tmp_path: Path
) -> None:
    """The measured repository's shape: the detail query is reached only by URL."""
    view = "Views/Order/OrderQry.cshtml"
    controller = "Controllers/OrderController.cs"
    scan = _scan(
        tmp_path,
        views=[view],
        view_sources={
            view: (
                "@model OrderModel\n"
                "<table><tr><th>Order</th></tr></table>\n"
                "<script>\n"
                "  $.get('/Order/Detail', function (data) { render(data); });\n"
                "</script>\n"
            )
        },
        controllers={controller: ["OrderQry", "Detail"]},
        invocations={
            controller: [
                _invocation("OrderController", "OrderQry", "usp_QueryOrders"),
                _invocation("OrderController", "Detail", "usp_ReadOrderDetail"),
            ]
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["OrderQry"],
        database="OrdersDb",
        procedures=("usp_QueryOrders", "usp_ReadOrderDetail"),
    )

    program = response.programs[0]
    assert sorted(program.stored_procedures) == [
        "usp_queryorders",
        "usp_readorderdetail",
    ]
    assert _strengths(program)["Detail"] == "likely"


# ─────────────────────────────────────────────────────────────────────────────
# WebForms is untouched
# ─────────────────────────────────────────────────────────────────────────────

def test_webforms_program_resolution_is_unchanged(
    monkeypatch, tmp_path: Path
) -> None:
    page = _write(tmp_path, "AgentMtn.aspx", "<%@ Page %>")
    code_behind = _write(tmp_path, "AgentMtn.aspx.cs", "// code behind")
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="webforms",
        scan_time=datetime.now(),
        csharp_results=[
            FileAnalysisResult(
                file_path=str(code_behind),
                file_type=FileType.CSHARP,
                framework=FrameworkType.WEBFORMS,
                classes=[
                    ClassInfo(
                        name="AgentMtn",
                        namespace="",
                        file_path=str(code_behind),
                        methods=[
                            MethodInfo(
                                name="Page_Load",
                                access_modifier="protected",
                                return_type="void",
                            )
                        ],
                    )
                ],
            )
        ],
        aspx_results=[
            FileAnalysisResult(
                file_path=str(page),
                file_type=FileType.ASPX,
                framework=FrameworkType.WEBFORMS,
            )
        ],
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["AgentMtn"])

    assert len(response.programs) == 1
    program = response.programs[0]
    assert program.file == "AgentMtn.aspx.cs"
    assert _actions(program) == ["Page_Load"]


def test_a_webforms_page_beside_razor_views_still_resolves_by_base_name(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Import/ImDecl.cshtml"],
        controllers={
            "Controllers/ImportController.cs": ["ImDecl"],
            "Legacy/AgentMtn.aspx.cs": ["Page_Load"],
        },
        pages=["Legacy/AgentMtn.aspx"],
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["AgentMtn"])

    assert len(response.programs) == 1
    assert response.programs[0].file == "Legacy/AgentMtn.aspx.cs"


def test_a_program_code_naming_one_csharp_file_outright_still_resolves(
    monkeypatch, tmp_path: Path
) -> None:
    scan = _scan(
        tmp_path,
        views=["Views/Import/ImDecl.cshtml"],
        controllers={
            "Controllers/ImportController.cs": ["ImDecl"],
            "Services/BatchJob.cs": ["Run"],
        },
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["BatchJob"])

    assert len(response.programs) == 1
    assert response.programs[0].file == "Services/BatchJob.cs"
    assert _actions(response.programs[0]) == ["Run"]

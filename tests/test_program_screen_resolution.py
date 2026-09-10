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
from service import analyze_service
from service.schemas import AnalyzeRequest


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _view_result(root: Path, relative: str) -> FileAnalysisResult:
    path = _write(root, relative, "@{ /* view */ }")
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.RAZOR,
        framework=FrameworkType.MVC,
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
        razor_results=[_view_result(root, relative) for relative in views],
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

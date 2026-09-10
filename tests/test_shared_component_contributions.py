"""A screen that renders a shared component (ViewComponent or partial view)
reaches that component's stored procedures and tables, labelled as coming
from a shared component rather than the screen's own access
(.scratch/aspnet-mvc-core-analysis/issues/15-viewcomponent-and-partial-view-contributions.md).

Every check drives `analyze_service.analyze()`, following the same pattern
`tests/test_program_screen_resolution.py` uses for Program Screens.
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
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult
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
    view_components: Sequence[str] = (),
    partials: Sequence[str] = (),
) -> FileAnalysisResult:
    path = _write(root, relative, "@{ /* view */ }")
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.RAZOR,
        framework=FrameworkType.MVC,
        view_component_references=list(view_components),
        partial_view_references=list(partials),
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
                        name=action, access_modifier="public", return_type="IActionResult"
                    )
                    for action in actions
                ],
            )
        ],
    )


def _view_component_result(
    root: Path,
    relative: str,
    class_name: str,
    *,
    method: str = "InvokeAsync",
    extra_methods: Sequence[str] = (),
) -> FileAnalysisResult:
    path = _write(root, relative, "// view component")
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.MVC,
        classes=[
            ClassInfo(
                name=class_name,
                namespace="",
                file_path=str(path),
                base_class="ViewComponent",
                methods=[
                    MethodInfo(
                        name=method, access_modifier="public", return_type="Task<IViewComponentResult>"
                    )
                ]
                + [
                    MethodInfo(name=m, access_modifier="private", return_type="void")
                    for m in extra_methods
                ],
            )
        ],
    )


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


def _cached_sql_graph(*procedures: str) -> dict:
    return {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [{"name": name} for name in procedures],
        "sql_execution_graph": {
            "graph_version": 1,
            "database": "OrdersDb",
            "nodes": [
                {"id": f"stored_procedure:dbo.{name}", "type": "stored_procedure", "schema": "dbo", "name": name}
                for name in procedures
            ],
            "relationships": [],
            "parse_errors": [],
        },
    }


def _scan(
    root: Path,
    *,
    views: Sequence[FileAnalysisResult] = (),
    controllers: Mapping[str, Sequence[str]] = {},
    components: Sequence[FileAnalysisResult] = (),
    invocations: Mapping[str, List[Dict]] = {},
    table_relations: Sequence[CSharpTableRelation] = (),
) -> ProjectScanResult:
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
        project_name="shared-components",
        scan_time=datetime.now(),
        csharp_results=[*controller_results, *components],
        razor_results=list(views),
        db_invocations=db_invocations,
        connection_sources=connection_sources,
        table_relations=list(table_relations),
    )


def _analyze(
    monkeypatch,
    root: Path,
    scan: ProjectScanResult,
    program_names: Sequence[str],
    *,
    database: str = "",
    procedures: Sequence[str] = (),
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
            fk_depth=0,
        )
    )


def test_a_view_component_a_screen_renders_contributes_its_stored_procedures(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Index.cshtml"
    component = "Components/CustomerSelectorViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[_view_result(tmp_path, view, view_components=["CustomerSelector"])],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[_view_component_result(tmp_path, component, "CustomerSelectorViewComponent")],
        invocations={
            "Controllers/OrderController.cs": [
                _invocation("OrderController", "Index", "usp_OrderIndex")
            ],
            component: [
                _invocation(
                    "CustomerSelectorViewComponent", "InvokeAsync", "usp_ListCustomers"
                )
            ],
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Index"],
        database="OrdersDb",
        procedures=("usp_OrderIndex", "usp_ListCustomers"),
    )

    program = response.programs[0]
    assert sorted(program.stored_procedures) == ["usp_listcustomers", "usp_orderindex"]


def test_a_partial_view_contributes_the_same_way_a_view_component_does(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Index.cshtml"
    partial = "Views/Shared/_Header.cshtml"
    component = "Components/MenuViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[
            _view_result(tmp_path, view, partials=["_Header"]),
            _view_result(tmp_path, partial, view_components=["Menu"]),
        ],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[_view_component_result(tmp_path, component, "MenuViewComponent")],
        invocations={
            component: [_invocation("MenuViewComponent", "InvokeAsync", "usp_ListMenu")]
        },
    )

    response = _analyze(
        monkeypatch, tmp_path, scan, ["Index"], database="OrdersDb", procedures=("usp_ListMenu",)
    )

    assert response.programs[0].stored_procedures == ["usp_listmenu"]


def test_every_shared_component_contribution_is_labelled(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Index.cshtml"
    component = "Components/MenuViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[_view_result(tmp_path, view, view_components=["Menu"])],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[_view_component_result(tmp_path, component, "MenuViewComponent")],
        invocations={
            "Controllers/OrderController.cs": [
                _invocation("OrderController", "Index", "usp_OrderIndex")
            ],
            component: [_invocation("MenuViewComponent", "InvokeAsync", "usp_ListMenu")],
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Index"],
        database="OrdersDb",
        procedures=("usp_OrderIndex", "usp_ListMenu"),
    )

    program = response.programs[0]
    own = [inv for inv in program.database_invocations if inv["procedure_name"] == "usp_orderindex"]
    shared = [inv for inv in program.database_invocations if inv["procedure_name"] == "usp_listmenu"]
    assert own and "shared_component" not in own[0]
    assert shared and shared[0]["shared_component"] == {
        "kind": "view_component",
        "name": "Menu",
    }
    assert program.shared_component_contributions == [
        {
            "kind": "view_component",
            "name": "Menu",
            "file": component,
            "class": "MenuViewComponent",
            "method": "InvokeAsync",
            "stored_procedures": ["usp_listmenu"],
            "tables": [],
        }
    ]


def test_a_component_rendered_by_many_screens_contributes_to_each(
    monkeypatch, tmp_path: Path
) -> None:
    component = "Components/MenuViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[
            _view_result(tmp_path, "Views/Order/Index.cshtml", view_components=["Menu"]),
            _view_result(tmp_path, "Views/Report/Index.cshtml", view_components=["Menu"]),
        ],
        controllers={
            "Controllers/OrderController.cs": ["Index"],
            "Controllers/ReportController.cs": ["Index"],
        },
        components=[_view_component_result(tmp_path, component, "MenuViewComponent")],
        invocations={
            component: [_invocation("MenuViewComponent", "InvokeAsync", "usp_ListMenu")]
        },
    )

    response = _analyze(
        monkeypatch, tmp_path, scan, ["Index"], database="OrdersDb", procedures=("usp_ListMenu",)
    )

    reached = {program.file: program.stored_procedures for program in response.programs}
    assert reached == {
        "Views/Order/Index.cshtml": ["usp_listmenu"],
        "Views/Report/Index.cshtml": ["usp_listmenu"],
    }
    for program in response.programs:
        assert program.shared_component_contributions[0]["name"] == "Menu"


def test_a_component_reaching_no_database_contributes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Index.cshtml"
    component = "Components/StaticBannerViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[_view_result(tmp_path, view, view_components=["StaticBanner"])],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[_view_component_result(tmp_path, component, "StaticBannerViewComponent")],
        invocations={
            "Controllers/OrderController.cs": [
                _invocation("OrderController", "Index", "usp_OrderIndex")
            ]
        },
    )

    response = _analyze(
        monkeypatch, tmp_path, scan, ["Index"], database="OrdersDb", procedures=("usp_OrderIndex",)
    )

    program = response.programs[0]
    assert program.stored_procedures == ["usp_orderindex"]
    assert program.shared_component_contributions == []
    assert all("shared_component" not in inv for inv in program.database_invocations)


def test_a_view_component_reaches_the_screens_tables_too(
    monkeypatch, tmp_path: Path
) -> None:
    view = "Views/Order/Index.cshtml"
    component_relative = "Components/MenuViewComponent.cs"
    component_result = _view_component_result(
        tmp_path, component_relative, "MenuViewComponent"
    )
    scan = _scan(
        tmp_path,
        views=[_view_result(tmp_path, view, view_components=["Menu"])],
        controllers={"Controllers/OrderController.cs": ["Index"]},
        components=[component_result],
        table_relations=[
            CSharpTableRelation(
                csharp_file=component_result.file_path,
                class_name="MenuViewComponent",
                method_name="InvokeAsync",
                line_number=1,
                table_name="MenuItems",
                database="OrdersDb",
                access_type="READ",
            )
        ],
    )

    response = _analyze(monkeypatch, tmp_path, scan, ["Index"])

    program = response.programs[0]
    assert program.tables == ["MenuItems"]
    assert program.shared_component_contributions == [
        {
            "kind": "view_component",
            "name": "Menu",
            "file": component_relative,
            "class": "MenuViewComponent",
            "method": "InvokeAsync",
            "stored_procedures": [],
            "tables": ["MenuItems"],
        }
    ]


def test_a_measured_repositorys_selector_component_contributes_its_stored_procedures(
    monkeypatch, tmp_path: Path
) -> None:
    """The TOPCSCY-shaped repository (13 Areas, 510 views) leans on shared
    dropdown/selector ViewComponents rendered from many screens — a
    CustomerSelector's own stored procedure must reach every screen that
    renders it, labelled as coming from that shared component."""
    component = "Components/CustomerSelectorViewComponent.cs"
    scan = _scan(
        tmp_path,
        views=[
            _view_result(
                tmp_path, "Views/Order/Create.cshtml", view_components=["CustomerSelector"]
            ),
            _view_result(
                tmp_path, "Views/Invoice/Create.cshtml", view_components=["CustomerSelector"]
            ),
        ],
        controllers={
            "Controllers/OrderController.cs": ["Create"],
            "Controllers/InvoiceController.cs": ["Create"],
        },
        components=[
            _view_component_result(tmp_path, component, "CustomerSelectorViewComponent")
        ],
        invocations={
            component: [
                _invocation(
                    "CustomerSelectorViewComponent", "InvokeAsync", "usp_ListActiveCustomers"
                )
            ]
        },
    )

    response = _analyze(
        monkeypatch,
        tmp_path,
        scan,
        ["Create"],
        database="OrdersDb",
        procedures=("usp_ListActiveCustomers",),
    )

    reached = {program.file: program.stored_procedures for program in response.programs}
    assert reached == {
        "Views/Order/Create.cshtml": ["usp_listactivecustomers"],
        "Views/Invoice/Create.cshtml": ["usp_listactivecustomers"],
    }

"""Shared builders for tests that drive a scan with Razor views and controllers."""

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
from tests.request_context_fixtures import RequestStores
from tests.sql_cache_fixtures import cache_with_procedures


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
    # A code-behind `Alpha.aspx.cs` declares the class `Alpha`, as a real page does.
    class_name = Path(relative).name.split(".")[0]
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
    stores = RequestStores.of(root, scan, database)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda identity: cache_with_procedures(*procedures),
    )
    return analyze_service.analyze(
        AnalyzeRequest(
            database=database,
            program_names=list(program_names),
            include_snippets=False,
            include_view_layer=include_view_layer,
        ),
        scan_store=stores.scan_store,
        cache_store=stores.cache_store,
    )

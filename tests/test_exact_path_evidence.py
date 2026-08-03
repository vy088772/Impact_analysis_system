"""Acceptance checks for exact, path-scoped evidence expansion."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import pytest

from code_analyzer.models import (
    ClassInfo,
    FileAnalysisResult,
    FileType,
    FrameworkType,
    MethodInfo,
    MethodSourceSpan,
    SourceSnapshot,
)
from code_analyzer.project_scanner import ProjectScanResult
from code_analyzer.csharp_analysis_gateway import (
    DbInvocation,
    InvocationEvidence,
    InvocationSourceSpan,
)
from service import analyze_service
from service.execution_path_builder import build_execution_paths
from service.schemas import PathEvidenceRequest


def _cached_path_fixture(tmp_path: Path) -> tuple[ProjectScanResult, dict, str]:
    source_file = tmp_path / "OrderPage.cs"
    content = """class OrderPage
{
    public void Save()
    {
        ExecuteSave();
    }
}
"""
    source_file.write_text(content, encoding="utf-8")
    method_start = content.index("    public void Save()")
    method_end = content.index("\n}", method_start)
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="Save", access_modifier="public", return_type="void")],
            )
        ],
    )
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_SaveOrder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        procedure_schema="dbo",
        method_chain=("Save",),
        source_snapshot_hash="snapshot-hash",
    )
    graph = {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_SaveOrder",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_SaveOrder",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_SaveOrder",
                "sequence": 1,
                "operation_type": "UPDATE",
                "branch_path": ["IF @Mode = 1"],
                "conditions": ["IF @Mode = 1", "Id = @Id"],
                "where": "Id = @Id",
                "read_tables": [],
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["Status"],
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_SaveOrder",
                "sequence": 2,
                "operation_type": "DELETE",
                "branch_path": ["ELSE (NOT (@Mode = 1))"],
                "conditions": ["ELSE (NOT (@Mode = 1))", "Id = @Id"],
                "where": "Id = @Id",
                "read_tables": [],
                "write_tables": ["dbo.SOrder"],
                "written_columns": [],
            },
            {
                "id": "table:dbo.SOrder",
                "type": "table",
                "schema": "dbo",
                "name": "SOrder",
            },
        ],
        "relationships": [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_SaveOrder",
                "target": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_SaveOrder",
                "target": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
                "target": "table:dbo.SOrder",
                "columns": ["Status"],
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:2",
                "target": "table:dbo.SOrder",
            },
        ],
        "parse_errors": [],
    }
    cached = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_SaveOrder",
                "definition": (
                    "CREATE PROCEDURE dbo.usp_SaveOrder AS "
                    "IF @Mode = 1 UPDATE dbo.SOrder SET Status = @Status WHERE Id = @Id; "
                    "ELSE DELETE FROM dbo.SOrder WHERE Id = @Id;"
                ),
            }
        ],
        "views": [],
        "functions": [],
        "sql_execution_graph": graph,
    }
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        source_snapshots={
            "OrderPage.cs": SourceSnapshot(
                relative_path="OrderPage.cs",
                content_hash="snapshot-hash",
                content=content,
                method_spans=[
                    MethodSourceSpan(
                        class_name="OrderPage",
                        method_name="Save",
                        start_offset=method_start,
                        end_offset=method_end,
                    )
                ],
            )
        },
        db_invocations={
            str(source_file.resolve()): [
                {
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "connection_expression": "conn",
                    "start_offset": 0,
                    "end_offset": 10,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )
    path_id = build_execution_paths([invocation], graph)[0]["path_id"]
    return scan, cached, path_id


def test_path_evidence_returns_only_selected_branch_and_source_methods(monkeypatch, tmp_path: Path) -> None:
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema: cached,
    )

    evidence = analyze_service.get_path_evidence(
        PathEvidenceRequest(
            path_id=path_id,
            database="OrdersDb",
            program_names=["OrderPage"],
        )
    )

    assert evidence.path_id == path_id
    assert [method["method"] for method in evidence.csharp_methods] == ["Save"]
    assert "public void Save()" in evidence.csharp_methods[0]["source"]
    assert [procedure["name"] for procedure in evidence.stored_procedures] == [
        "dbo.usp_SaveOrder"
    ]
    assert [operation["operation_type"] for operation in evidence.operations] == ["UPDATE"]
    assert evidence.operations[0]["where"] == "Id = @Id"
    assert evidence.views == []
    assert evidence.functions == []


def test_path_evidence_rejects_stale_source_snapshot(monkeypatch, tmp_path: Path) -> None:
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    scan.source_snapshots.clear()
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema: cached,
    )

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        analyze_service.get_path_evidence(
            PathEvidenceRequest(
                path_id=path_id,
                database="OrdersDb",
                program_names=["OrderPage"],
            )
        )

    assert error.value.code == "stale_path"


def test_path_evidence_rejects_unknown_path_id(monkeypatch, tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema: cached,
    )

    with pytest.raises(analyze_service.PathEvidenceError) as error:
        analyze_service.get_path_evidence(
            PathEvidenceRequest(
                path_id="P-000000000000",
                database="OrdersDb",
                program_names=["OrderPage"],
            )
        )

    assert error.value.code == "path_not_found"


def test_path_evidence_materializes_unresolved_cycle_without_terminal_dml(tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    graph = cached["sql_execution_graph"]
    graph["nodes"].append(
        {
            "id": "stored_procedure:dbo.usp_WriteAudit",
            "type": "stored_procedure",
            "schema": "dbo",
            "name": "usp_WriteAudit",
        }
    )
    graph["relationships"].extend(
        [
            {
                "type": "calls",
                "source": "stored_procedure:dbo.usp_SaveOrder",
                "target": "stored_procedure:dbo.usp_WriteAudit",
                "branch_path": [],
            },
            {
                "type": "calls",
                "source": "stored_procedure:dbo.usp_WriteAudit",
                "target": "stored_procedure:dbo.usp_SaveOrder",
                "branch_path": [],
            },
        ]
    )
    cached["procedures"].append(
        {
            "name": "dbo.usp_WriteAudit",
            "definition": "CREATE PROCEDURE dbo.usp_WriteAudit AS EXEC dbo.usp_SaveOrder;",
        }
    )
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_SaveOrder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        procedure_schema="dbo",
        method_chain=("Save",),
        source_snapshot_hash="snapshot-hash",
    )
    cycle_path = next(
        path
        for path in build_execution_paths([invocation], graph)
        if path["unresolved_reason"] == "stored_procedure_call_cycle"
    )

    evidence = analyze_service._materialize_path_evidence(
        cycle_path,
        invocation,
        scan,
        cached,
        graph,
    )

    assert evidence.evidence == "unresolved"
    assert evidence.unresolved_reason == "stored_procedure_call_cycle"
    assert evidence.operations == []
    assert [item["name"] for item in evidence.stored_procedures] == [
        "dbo.usp_SaveOrder",
        "dbo.usp_WriteAudit",
    ]
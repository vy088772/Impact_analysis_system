"""Acceptance checks for exact, path-scoped evidence expansion."""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace
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
from service.schemas import (
    PathEvidenceRequest,
    PathEvidenceResponse,
    SPMatchProgram,
    TableMatchProgram,
)


def _cached_path_fixture(
    tmp_path: Path,
    *,
    path_id_relative_path: str | None = None,
) -> tuple[ProjectScanResult, dict, str]:
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
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 0,
                    "end_offset": 10,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )
    path_invocation = (
        invocation
        if path_id_relative_path is None
        else replace(
            invocation,
            source=InvocationSourceSpan(path_id_relative_path, 0, 10),
        )
    )
    path_id = build_execution_paths([path_invocation], graph)[0]["path_id"]
    return scan, cached, path_id


def test_path_evidence_returns_only_selected_branch_and_source_methods(monkeypatch, tmp_path: Path) -> None:
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
    )

    evidence = analyze_service.get_path_evidence(
        PathEvidenceRequest(
            path_id=path_id,
            database="OrdersDb",
            program_names=["OrderPage"],
        )
    )

    assert evidence.path_id == path_id
    assert evidence.database == "OrdersDb"
    assert evidence.caller == "OrderPage.Save"
    assert evidence.caller_class == "OrderPage"
    assert evidence.caller_method == "Save"
    assert evidence.procedure_name == "usp_saveorder"
    assert evidence.procedure_schema == "dbo"
    assert evidence.source_span["relative_path"] == "OrderPage.cs"
    assert evidence.source_snapshot_hash
    assert [method["method"] for method in evidence.csharp_methods] == ["Save"]
    assert "public void Save()" in evidence.csharp_methods[0]["source"]
    assert [procedure["name"] for procedure in evidence.stored_procedures] == [
        "dbo.usp_SaveOrder"
    ]
    assert [operation["operation_type"] for operation in evidence.operations] == ["UPDATE"]
    assert evidence.operations[0]["where"] == "Id = @Id"
    assert evidence.views == []
    assert evidence.functions == []


def test_path_evidence_preserves_wrapper_classification_and_database_evidence(tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        procedure_schema="dbo",
        method_chain=("Save",),
        source_snapshot_hash="snapshot-hash",
        external_wrapper_method="ExeProcNon",
        wrapper_contract="sqlobject",
        wrapper_contract_source="explicit",
        wrapper_receiver_type="SQLObject",
        wrapper_contract_candidates=("sqlobject",),
        wrapper_kind="external_wrapper",
        wrapper_status="explicit_selected",
        wrapper_selection_source="explicit",
        wrapper_contract_mode="stored_procedure",
        wrapper_contract_sink="ExecuteNonQuery",
        wrapper_scan_root=str(tmp_path),
        wrapper_review_candidate=False,
        wrapper_method="ExeProcNon",
        wrapper_source_available=False,
        wrapper_stored_procedure_mode=True,
    )
    path = build_execution_paths([invocation], cached["sql_execution_graph"])[0]

    evidence = analyze_service._materialize_path_evidence(
        path,
        invocation,
        scan,
        cached,
        cached["sql_execution_graph"],
    )

    # Canonical wrapper-evidence keys only (ticket 02 collapses the alias
    # sprawl at the WrapperReconciliation/WRAPPER_EVIDENCE_FIELDS seam):
    # wrapper_status/wrapper_classification_status/classification_status ->
    # status, wrapper_selection_source -> selection_source, wrapper_contract
    # -> contract, wrapper_contract_mode -> contract_mode,
    # wrapper_contract_sink -> contract_sink, wrapper_stored_procedure_mode
    # -> stored_procedure_mode, source_snapshot_identity ->
    # source_snapshot_hash. evidence collapses into evidence_status (ticket
    # 03), as do the dual-fact wrapper_receiver_type/wrapper_method.
    assert evidence.wrapper_kind == "external_wrapper"
    assert evidence.status == "explicit_selected"
    assert evidence.selection_source == "explicit"
    assert evidence.contract == "sqlobject"
    assert evidence.contract_mode == "stored_procedure"
    assert evidence.contract_sink == "ExecuteNonQuery"
    assert evidence.wrapper_receiver_type == "SQLObject"
    assert evidence.wrapper_method == "ExeProcNon"
    assert evidence.stored_procedure_mode is True
    assert evidence.evidence_status == "proven"
    assert not hasattr(evidence, "evidence")
    assert evidence.source_snapshot_hash == "snapshot-hash"
    assert evidence.source_provenance["scan_root"] == str(tmp_path)


def test_multi_root_path_evidence_uses_repo_relative_source_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    child_root = tmp_path / "TTPUR"
    sibling_root = tmp_path / "ATV"
    child_root.mkdir()
    sibling_root.mkdir()
    scan, cached, path_id = _cached_path_fixture(
        child_root,
        path_id_relative_path="TTPUR/OrderPage.cs",
    )
    sibling_scan = ProjectScanResult(
        project_root=str(sibling_root),
        project_name="orders",
        scan_time=datetime.now(),
    )

    monkeypatch.setattr(
        analyze_service,
        "resolve_source",
        lambda req: [child_root, sibling_root],
    )
    monkeypatch.setattr(
        analyze_service,
        "_get_scan",
        lambda root, refresh=False: scan if root == child_root else sibling_scan,
    )
    monkeypatch.setattr(analyze_service, "repo_dir", lambda project, repo: tmp_path)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
    )

    evidence = analyze_service.get_path_evidence(
        PathEvidenceRequest(
            path_id=path_id,
            database="OrdersDb",
            program_names=["OrderPage"],
        )
    )

    assert evidence.source_span["relative_path"] == "TTPUR/OrderPage.cs"
    assert evidence.csharp_methods[0]["file"] == "TTPUR/OrderPage.cs"
    assert "public void Save()" in evidence.csharp_methods[0]["source"]


def test_path_evidence_rejects_stale_source_snapshot(monkeypatch, tmp_path: Path) -> None:
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    scan.source_snapshots.clear()
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
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


def test_path_evidence_rejects_drifted_sql_definition_offset(monkeypatch, tmp_path: Path) -> None:
    """A definition-length mismatch must fail loudly even when the recorded
    offset still lands inside the current text's bounds — the failure mode
    issue 01's ScriptDom-write fix alone cannot catch (ticket 02)."""
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    definition = cached["procedures"][0]["definition"]
    terminal_operation = next(
        node
        for node in cached["sql_execution_graph"]["nodes"]
        if node["id"] == "dml_operation:stored_procedure:dbo.usp_SaveOrder:1"
    )
    terminal_operation["source"] = {
        "start_offset": 0,
        "length": 1,
        "module_definition_length": len(definition) - 1,
    }
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
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


def test_path_evidence_accepts_matching_sql_definition_offset(monkeypatch, tmp_path: Path) -> None:
    """No behavior change when the recorded length still matches: evidence
    expansion still slices the operation's source text normally."""
    scan, cached, path_id = _cached_path_fixture(tmp_path)
    definition = cached["procedures"][0]["definition"]
    terminal_operation = next(
        node
        for node in cached["sql_execution_graph"]["nodes"]
        if node["id"] == "dml_operation:stored_procedure:dbo.usp_SaveOrder:1"
    )
    terminal_operation["source"] = {
        "start_offset": 0,
        "length": 6,
        "module_definition_length": len(definition),
    }
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
    )

    evidence = analyze_service.get_path_evidence(
        PathEvidenceRequest(
            path_id=path_id,
            database="OrdersDb",
            program_names=["OrderPage"],
        )
    )

    assert evidence.operations[0]["source_text"] == "CREATE"


def test_path_evidence_rejects_unknown_path_id(monkeypatch, tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": cached,
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

    assert evidence.evidence_status == "unresolved"
    assert evidence.unresolved_reason == "stored_procedure_call_cycle"
    assert evidence.operations == []
    assert [item["name"] for item in evidence.stored_procedures] == [
        "dbo.usp_SaveOrder",
        "dbo.usp_WriteAudit",
    ]


def test_path_evidence_retains_unverified_literal_sp_candidate(monkeypatch, tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    graph = cached["sql_execution_graph"]
    monkeypatch.setattr(
        analyze_service,
        "fetch_sp_definitions",
        lambda sp_names, database_alias=None, db_server=None: [
            {
                "name": sp_names[0],
                "exists": True,
                "parameters": [{"name": "@Id"}],
                "tables": ["dbo.SOrder"],
                "dependency_source": "execution_graph",
                "definition": "CREATE PROCEDURE dbo.usp_SaveOrder AS SELECT 1;",
            }
        ],
    )
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.UNRESOLVED,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        reason="wrapper_source_unavailable",
        procedure_schema="dbo",
        method_chain=("Save",),
        raw_command_text="[dbo].[usp_SaveOrder]",
    )
    path = build_execution_paths([invocation], graph)[0]

    evidence = analyze_service._materialize_path_evidence(
        path,
        invocation,
        scan,
        cached,
        graph,
    )

    assert evidence.evidence_status == "unresolved"
    assert evidence.confirmed is False
    assert len(evidence.literal_sp_candidates) == 1
    candidate = evidence.literal_sp_candidates[0]
    assert candidate["procedure_name"] == "usp_saveorder"
    assert candidate["raw_command_text"] == "[dbo].[usp_SaveOrder]"
    assert candidate["reason"] == "wrapper_source_unavailable"
    assert candidate["sql_cache_matched"] is True
    assert candidate["exists"] is True
    assert candidate["parameters"] == [{"name": "@Id"}]
    assert "CREATE PROCEDURE" in candidate["definition"]


def test_path_evidence_skips_external_wrapper_method_span(tmp_path: Path) -> None:
    scan, cached, _ = _cached_path_fixture(tmp_path)
    graph = cached["sql_execution_graph"]
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="Save",
        database="OrdersDb",
        procedure_name="usp_saveorder",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 0, 10),
        procedure_schema="dbo",
        method_chain=("Save", "ExeProcNon"),
        method_class_chain=("OrderPage", "SQLObject"),
        external_wrapper_method="ExeProcNon",
        source_snapshot_hash="snapshot-hash",
    )
    path = build_execution_paths([invocation], graph)[0]

    evidence = analyze_service._materialize_path_evidence(
        path,
        invocation,
        scan,
        cached,
        graph,
    )

    assert [method["method"] for method in evidence.csharp_methods] == ["Save"]
    assert [procedure["name"] for procedure in evidence.stored_procedures] == [
        "dbo.usp_SaveOrder"
    ]


def test_wrapper_evidence_bag_schemas_drop_evidence_alias_keep_evidence_status() -> None:
    """Regression guard for ticket 03: the wrapper-evidence bag only ever
    exposes ``evidence_status`` on these three response schemas now — the
    ``evidence`` alias must never reappear (``DbInvocation``'s own top-level
    ``evidence: InvocationEvidence`` field, serialized separately by
    ``_serialize_db_invocation``, is untouched and out of scope here)."""
    for model in (PathEvidenceResponse, SPMatchProgram, TableMatchProgram):
        assert "evidence" not in model.model_fields
        assert "evidence_status" in model.model_fields
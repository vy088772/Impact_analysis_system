"""Service-level checks for the C# to SQL execution-path join."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from code_analyzer.models import ClassInfo, FileAnalysisResult, FrameworkType, MethodInfo, FileType
from code_analyzer.project_scanner import CSharpSPRelation, ProjectScanResult
from config.settings import settings
from service import analyze_service
from service import flow_chain_builder
from service import scan_store
from service.schemas import AnalyzeRequest
from code_analyzer.csharp_analysis_gateway import DbInvocation, InvocationEvidence, InvocationSourceSpan


def _cached_sql_graph() -> dict:
    return {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [{"name": "usp_SaveOrder"}],
        "sql_execution_graph": {
            "graph_version": 1,
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
                    "conditions": ["Id = @Id"],
                    "written_columns": ["Status"],
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
                    "type": "writes",
                    "source": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
                    "target": "table:dbo.SOrder",
                    "columns": ["Status"],
                },
            ],
            "parse_errors": [],
        },
    }


def _cached_schema_sql_graph() -> dict:
    cached = _cached_sql_graph()
    cached["procedures"] = [{"name": "usp_SaveOrder", "schema": "sales"}]
    graph = cached["sql_execution_graph"]
    graph["nodes"] = [
        {
            "id": "stored_procedure:sales.usp_SaveOrder",
            "type": "stored_procedure",
            "schema": "sales",
            "name": "usp_SaveOrder",
        },
        {
            "id": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
            "type": "dml_operation",
            "module_id": "stored_procedure:sales.usp_SaveOrder",
            "sequence": 1,
            "operation_type": "UPDATE",
            "conditions": [],
            "written_columns": ["Status"],
        },
        {
            "id": "table:sales.SOrder",
            "type": "table",
            "schema": "sales",
            "name": "SOrder",
        },
    ]
    graph["relationships"] = [
        {
            "type": "contains",
            "source": "stored_procedure:sales.usp_SaveOrder",
            "target": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
        },
        {
            "type": "writes",
            "source": "dml_operation:stored_procedure:sales.usp_SaveOrder:1",
            "target": "table:sales.SOrder",
            "columns": ["Status"],
        },
    ]
    return cached


def test_analyze_returns_direct_sqlclient_execution_path(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[
                    MethodInfo(name="HandleSave", access_modifier="private", return_type="void", calls=["SaveData"]),
                    MethodInfo(name="SaveData", access_modifier="private", return_type="void"),
                ],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={
            str(source_file.resolve()): [
                {
                    "class_name": "OrderPage",
                    "method_name": "SaveData",
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "branch_context": ["if (useAlternate)"],
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "PUR"}},
    )

    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": _cached_sql_graph(),
    )

    response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=["OrderPage"],
            include_snippets=False,
            fk_depth=0,
        )
    )

    assert len(response.programs) == 1
    program = response.programs[0]
    assert len(program.execution_paths) == 1
    path = program.execution_paths[0]
    assert path["entry_method"] == "OrderPage.HandleSave"
    assert path["method_chain"] == ["HandleSave", "SaveData"]
    assert path["sp_chain"] == ["dbo.usp_SaveOrder"]
    assert path["terminal_operation"] == "UPDATE"
    assert path["target"] == "dbo.SOrder"
    assert path["conditions"] == ["if (useAlternate)", "Id = @Id"]
    assert path["evidence"] == "proven"
    assert program.compact_execution_paths[0]["path_id"] == path["path_id"]
    assert program.compact_execution_paths_meta == {
        "total_paths": 1,
        "returned_paths": 1,
        "omitted_paths": 0,
    }


def test_analyze_keeps_source_wrapper_method_flow_in_execution_path(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[
                    MethodInfo(name="HandleSave", access_modifier="private", return_type="void", calls=["SaveData"]),
                    MethodInfo(name="SaveData", access_modifier="private", return_type="void"),
                ],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={
            str(source_file.resolve()): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "SaveData",
                    "wrapper_class_name": "DbWrapper",
                    "wrapper_method_name": "Execute",
                    "wrapper_source_available": True,
                    "wrapper_reaches_stored_procedure_sink": True,
                    "wrapper_mode": "stored_procedure",
                    "receiver_implementation_identity": "DbWrapper",
                    "receiver_binding_provenance": "source",
                    "receiver_expression": "wrapper",
                    "wrapper_method_identity": "DbWrapper.Execute(string)",
                    "wrapper_method_arity": 1,
                    "wrapper_parameter_types": ["string"],
                    "wrapper_method_semantics": "fixed_stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "method_chain": ["SaveData", "Execute"],
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "PUR"}},
    )

    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": _cached_sql_graph(),
    )

    response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=["OrderPage"],
            include_snippets=False,
            fk_depth=0,
        )
    )

    path = response.programs[0].execution_paths[0]
    assert path["entry_method"] == "OrderPage.HandleSave"
    assert path["method_chain"] == ["HandleSave", "SaveData", "Execute"]


def test_source_wrapper_class_hints_align_with_long_method_chain() -> None:
    assert analyze_service._overlay_method_class_chain(
        ["HandleSave", "SaveData", "Execute"],
        ["OrderPage", "OrderPage", ""],
        ("HandleSave", "SaveData", "Execute"),
        ("OrderPage", "DbWrapper"),
    ) == ["OrderPage", "OrderPage", "DbWrapper"]


def test_analyze_keeps_missing_graph_target_as_unresolved(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        sp_relations=[
            CSharpSPRelation(
                csharp_file=str(source_file),
                class_name="OrderPage",
                method_name="SaveData",
                line_number=1,
                sp_name="usp_SaveOrder",
                sp_database="PUR",
                connection_variable="conn",
            )
        ],
        db_invocations={
            str(source_file.resolve()): [
                {
                    "class_name": "OrderPage",
                    "method_name": "SaveData",
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "PUR"}},
    )
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": None)

    paths, compact_payload = analyze_service._build_program_execution_paths(
        AnalyzeRequest(program_names=["OrderPage"], include_snippets=False),
        scan,
        [file_result],
        tmp_path,
    )

    assert len(paths) == 1
    assert paths[0]["evidence"] == "unresolved"
    assert paths[0]["unresolved_reason"] == "stored_procedure_not_in_graph"
    assert paths[0]["unresolved_targets"] == ["dbo.usp_saveorder"]
    assert compact_payload["total_paths"] == 1


def _single_invocation_scan(tmp_path: Path) -> tuple:
    """一支程式、一個已解析的 SP 呼叫——question 是否有傳到排序無關，只借
    這組最小 fixture 當運送問題的載具。"""
    source_file = tmp_path / "OrderPage.cs"
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={
            str(source_file.resolve()): [
                {
                    "class_name": "OrderPage",
                    "method_name": "SaveData",
                    "command_text_kind": "literal",
                    "command_text": "dbo.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "PUR"}},
    )
    return scan, file_result


def _captured_question_reaching_ranking(monkeypatch, tmp_path: Path, *, question: str) -> str:
    """跑一次 `_build_program_execution_paths()`，回傳它實際傳給
    `build_compact_execution_path_payload()` 的 `question` 值。"""
    scan, file_result = _single_invocation_scan(tmp_path)
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": None)

    captured: dict = {}
    original_payload = analyze_service.build_compact_execution_path_payload

    def spy_payload(paths, max_paths=20, *, question=""):
        captured["question"] = question
        return original_payload(paths, max_paths=max_paths, question=question)

    monkeypatch.setattr(analyze_service, "build_compact_execution_path_payload", spy_payload)

    kwargs = {"program_names": ["OrderPage"], "include_snippets": False}
    if question:
        kwargs["question"] = question
    analyze_service._build_program_execution_paths(
        AnalyzeRequest(**kwargs), scan, [file_result], tmp_path,
    )
    return captured["question"]


def test_analyze_passes_the_request_question_into_compact_path_ranking(
    monkeypatch, tmp_path: Path
) -> None:
    """llamaindex-spec-rag ticket 01 of `question-aware-compact-path-selection`:
    `AnalyzeRequest.question` must reach `build_compact_execution_path_payload()`'s
    existing `question` parameter unchanged — the ranking logic itself is not
    touched here, only the missing input.
    """
    assert _captured_question_reaching_ranking(
        monkeypatch, tmp_path, question="轉帳 STCSupplier"
    ) == "轉帳 STCSupplier"


def test_analyze_defaults_the_request_question_to_empty(monkeypatch, tmp_path: Path) -> None:
    """既有呼叫端（未帶 question 的 AnalyzeRequest）維持今天的行為：空字串，
    排序在空 question 下是 no-op（見 test_execution_path_builder.py 的
    inert 測試），這裡只釘住「預設值真的是空字串，不是漏了不傳」。
    """
    assert AnalyzeRequest(program_names=["OrderPage"]).question == ""
    assert _captured_question_reaching_ranking(monkeypatch, tmp_path, question="") == ""


def test_forward_chain_excludes_unresolved_terminal_from_formal_sp_chain(tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            )
        ],
    )
    graph = {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_Dynamic",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Dynamic",
            },
            {
                "id": "unresolved_dynamic_sql:stored_procedure:dbo.usp_Dynamic:1",
                "type": "unresolved_dynamic_sql",
                "module_id": "stored_procedure:dbo.usp_Dynamic",
                "sequence": 1,
                "operation_type": "EXECUTE",
            },
        ],
        "relationships": [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Dynamic",
                "target": "unresolved_dynamic_sql:stored_procedure:dbo.usp_Dynamic:1",
            }
        ],
        "parse_errors": [],
    }
    invocation = DbInvocation(
        class_name="OrderPage",
        method_name="SaveData",
        database="OrdersDb",
        procedure_name="usp_Dynamic",
        evidence=InvocationEvidence.PROVEN,
        source=InvocationSourceSpan("OrderPage.cs", 10, 80),
    )

    response = flow_chain_builder.build_forward_chain(
        [file_result],
        [],
        tmp_path,
        "SaveData",
        graph=graph,
        invocations=[invocation],
    )

    assert response["stored_procedures"] == []
    assert response["execution_paths"][0]["evidence"] == "unresolved"
    assert response["diagnostics"][0]["sp_chain"] == ["dbo.usp_Dynamic"]


def test_forward_chain_without_graph_keeps_inline_sql_but_ignores_legacy_sp_relation(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "OrderPage.cs"
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[
                    MethodInfo(
                        name="SaveData",
                        access_modifier="private",
                        return_type="void",
                        sql_queries=["SELECT * FROM dbo.SOrder"],
                    )
                ],
            )
        ],
    )
    legacy_relation = CSharpSPRelation(
        csharp_file=str(source_file),
        class_name="OrderPage",
        method_name="SaveData",
        line_number=1,
        sp_name="usp_LegacyOnly",
        sp_database="OrdersDb",
        connection_variable="conn",
    )

    response = flow_chain_builder.build_forward_chain(
        [file_result],
        [legacy_relation],
        tmp_path,
        "SaveData",
        fk_depth=0,
        graph=None,
        invocations=[],
    )

    assert response["stored_procedures"] == []
    assert response["execution_paths"] == []
    assert response["diagnostics"] == []
    assert response["inline_sql_tables"] == ["SOrder"]
    assert response["tables"] == ["SOrder"]


def test_analyze_keeps_multiple_connection_labels_database_scoped(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[
                    MethodInfo(name="SaveData", access_modifier="private", return_type="void"),
                    MethodInfo(name="AuditData", access_modifier="private", return_type="void"),
                ],
            )
        ],
    )
    raw_invocations = [
        {
            "class_name": "OrderPage",
            "method_name": "SaveData",
            "command_text_kind": "literal",
            "command_text": "dbo.usp_SaveOrder",
            "command_type_stored_procedure": True,
            "terminal_sink": "ExecuteNonQuery",
            "connection_expression": "orders_conn",
            "start_offset": 10,
            "end_offset": 90,
        },
        {
            "class_name": "OrderPage",
            "method_name": "AuditData",
            "command_text_kind": "literal",
            "command_text": "dbo.usp_SaveOrder",
            "command_type_stored_procedure": True,
            "terminal_sink": "ExecuteNonQuery",
            "connection_expression": "audit_conn",
            "start_offset": 100,
            "end_offset": 180,
        },
    ]
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={str(source_file.resolve()): raw_invocations},
        connection_sources={
            str(source_file.resolve()): {
                "orders_conn": "OrdersDb",
                "audit_conn": "AuditDb",
            }
        },
    )
    monkeypatch.setattr(analyze_service.sql_cache_store, "load_cached", lambda database, schema, server="": _cached_sql_graph())

    paths, _ = analyze_service._build_program_execution_paths(
        AnalyzeRequest(database="OrdersDb", program_names=["OrderPage"], include_snippets=False),
        scan,
        [file_result],
        tmp_path,
    )

    assert len(paths) == 2
    assert paths[0]["evidence"] == "proven"
    assert paths[1]["evidence"] == "unresolved"
    assert paths[1]["unresolved_reason"] == "not_in_resolved_catalog"


def test_analyze_catalog_preserves_schema_qualified_procedure(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={
            str(source_file.resolve()): [
                {
                    "class_name": "OrderPage",
                    "method_name": "SaveData",
                    "command_text_kind": "literal",
                    "command_text": "sales.usp_SaveOrder",
                    "command_type_stored_procedure": True,
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_expression": "conn",
                    "start_offset": 10,
                    "end_offset": 90,
                }
            ]
        },
        connection_sources={str(source_file.resolve()): {"conn": "OrdersDb"}},
    )
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": _cached_schema_sql_graph(),
    )

    paths, _ = analyze_service._build_program_execution_paths(
        AnalyzeRequest(database="OrdersDb", program_names=["OrderPage"], include_snippets=False),
        scan,
        [file_result],
        tmp_path,
    )

    assert len(paths) == 1
    assert paths[0]["evidence"] == "proven"
    assert paths[0]["sp_chain"] == ["sales.usp_SaveOrder"]
    assert paths[0]["target"] == "sales.SOrder"


def test_method_chain_does_not_cross_class_for_unqualified_call() -> None:
    file_result = FileAnalysisResult(
        file_path="OrderPage.cs",
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path="OrderPage.cs",
                methods=[
                    MethodInfo(
                        name="HandleSave",
                        access_modifier="private",
                        return_type="void",
                        calls=["SaveData"],
                    )
                ],
            ),
            ClassInfo(
                name="Helper",
                namespace="",
                file_path="OrderPage.cs",
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            ),
        ],
    )

    assert analyze_service._method_chain_for_file(file_result, "Helper", "SaveData") == ["SaveData"]
    assert analyze_service._method_chain_for_file(file_result, "OrderPage", "SaveData") == ["SaveData"]


def test_analyze_can_disable_execution_paths(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "OrderPage.cs"
    source_file.write_text("class OrderPage {}", encoding="utf-8")
    file_result = FileAnalysisResult(
        file_path=str(source_file),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name="OrderPage",
                namespace="",
                file_path=str(source_file),
                methods=[MethodInfo(name="SaveData", access_modifier="private", return_type="void")],
            )
        ],
    )
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        db_invocations={str(source_file.resolve()): [{"command_text": "dbo.usp_SaveOrder"}]},
    )
    monkeypatch.setattr(analyze_service, "resolve_source", lambda req: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service,
        "_build_program_execution_paths",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("path builder should be skipped")),
    )

    response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=["OrderPage"],
            include_execution_paths=False,
            include_snippets=False,
            fk_depth=0,
        )
    )

    assert response.programs[0].execution_paths == []
    assert response.programs[0].compact_execution_paths == []
    assert response.programs[0].compact_execution_paths_meta == {}


def test_scan_cache_round_trip_keeps_raw_db_invocations() -> None:
    previous_cache_root = settings.SCAN_CACHE_ROOT
    with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as cache_dir:
        root = Path(project_dir)
        source_path = root / "Direct.cs"
        source_path.write_text(
            "using System.Data; using System.Data.SqlClient; "
            "public class Direct { public void Save() { "
            "var conn = new SqlConnection(\"server\"); "
            "var command = new SqlCommand(\"dbo.usp_SaveOrder\", conn); "
            "command.CommandType = CommandType.StoredProcedure; } }",
            encoding="utf-8",
        )
        settings.SCAN_CACHE_ROOT = cache_dir
        try:
            scan_store.clear_cache(root)
            result = scan_store.get_or_scan(root, refresh=True)
            key = str(source_path.resolve())
            assert result.db_invocations[key][0]["command_type_stored_procedure"] is True
            assert result.db_invocations[key][0]["command_text"] == "dbo.usp_SaveOrder"

            cached = scan_store.get_or_scan(root, refresh=False)
            assert cached.db_invocations[key] == result.db_invocations[key]
        finally:
            scan_store.clear_cache(root)
            settings.SCAN_CACHE_ROOT = previous_cache_root
            shutil.rmtree(cache_dir, ignore_errors=True)
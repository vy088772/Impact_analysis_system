"""Acceptance checks for graph-backed reverse lookup and backward flow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_analyzer.models import ClassInfo, FileAnalysisResult, FileType, FrameworkType, MethodInfo
from code_analyzer.project_scanner import CSharpTableRelation, ProjectScanResult
from service import analyze_service
from service.schemas import AnalyzeRequest, FindBySPRequest, FindByTableRequest, FlowChainRequest
from service.sql_execution_graph import build_sql_execution_graph
from tests.sql_cache_fixtures import (
    case_variant_table_write_data,
    case_variant_temp_table_write_data,
)


def _graph() -> dict:
    return {
        "graph_version": 2,
        "database": "OrdersDb",
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_Direct",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Direct",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Direct:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Direct",
                "sequence": 1,
                "operation_type": "UPDATE",
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["Status"],
            },
            {
                "id": "stored_procedure:dbo.usp_Entry",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Entry",
            },
            {
                "id": "stored_procedure:dbo.usp_Nested",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_Nested",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_Nested:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_Nested",
                "sequence": 1,
                "operation_type": "INSERT",
                "write_tables": ["dbo.SOrder"],
                "written_columns": ["OrderNo"],
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
                "source": "stored_procedure:dbo.usp_Direct",
                "target": "dml_operation:stored_procedure:dbo.usp_Direct:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Direct:1",
                "target": "table:dbo.SOrder",
                "columns": ["Status"],
            },
            {
                "type": "calls",
                "source": "stored_procedure:dbo.usp_Entry",
                "target": "stored_procedure:dbo.usp_Nested",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_Nested",
                "target": "dml_operation:stored_procedure:dbo.usp_Nested:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_Nested:1",
                "target": "table:dbo.SOrder",
                "columns": ["OrderNo"],
            },
        ],
        "parse_errors": [],
    }


def _file(root: Path, name: str, methods: list[MethodInfo]) -> FileAnalysisResult:
    path = root / name
    return FileAnalysisResult(
        file_path=str(path),
        file_type=FileType.CSHARP,
        framework=FrameworkType.WEBFORMS,
        classes=[
            ClassInfo(
                name=Path(name).name.split(".")[0],
                namespace="",
                file_path=str(path),
                methods=methods,
            )
        ],
    )


def _scan(root: Path) -> ProjectScanResult:
    direct = _file(
        root,
        "DirectPage.cs",
        [MethodInfo(name="SaveDirect", access_modifier="private", return_type="void")],
    )
    nested = _file(
        root,
        "NestedPage.cs",
        [MethodInfo(name="SaveNested", access_modifier="private", return_type="void")],
    )
    page = _file(
        root,
        "OrderPage.aspx.cs",
        [
            MethodInfo(
                name="HandleSave",
                access_modifier="private",
                return_type="void",
                calls=["SaveData"],
            ),
            MethodInfo(name="SaveData", access_modifier="private", return_type="void"),
        ],
    )
    aspx = FileAnalysisResult(
        file_path=str(root / "OrderPage.aspx"),
        file_type=FileType.ASPX,
        framework=FrameworkType.WEBFORMS,
        ui_fields=[
            {
                "control": "asp:Button",
                "id": "btnSave",
                "events": {"Click": "HandleSave"},
            }
        ],
    )
    raw = {
        str((root / name).resolve()): [
            {
                "class_name": class_name,
                "method_name": method_name,
                "command_text_kind": "literal",
                "command_text": procedure,
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
        for name, class_name, method_name, procedure in (
            ("DirectPage.cs", "DirectPage", "SaveDirect", "dbo.usp_Direct"),
            ("NestedPage.cs", "NestedPage", "SaveNested", "dbo.usp_Entry"),
            ("OrderPage.aspx.cs", "OrderPage", "SaveData", "dbo.usp_Entry"),
        )
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[direct, nested, page],
        aspx_results=[aspx],
        db_invocations=raw,
        connection_sources={
            str((root / name).resolve()): {"conn": "OrdersDb"}
            for name in ("DirectPage.cs", "NestedPage.cs", "OrderPage.aspx.cs")
        },
    )


def _scan_with_calls(
    root: Path,
    calls: list[tuple[str, str, str, str]],
) -> ProjectScanResult:
    """Build a scan where each `(file, class, method, procedure)` is one program.

    A minimal variant of `_scan()` for tests that build their own SQL
    Execution Graph from stored-procedure text (tickets that only exercise
    graph construction, not the wrapper/ASPX surfaces `_scan()` also covers).
    """
    csharp_results = [
        _file(root, file_name, [MethodInfo(name=method_name, access_modifier="private", return_type="void")])
        for file_name, _, method_name, _ in calls
    ]
    raw = {
        str((root / file_name).resolve()): [
            {
                "class_name": class_name,
                "method_name": method_name,
                "command_text_kind": "literal",
                "command_text": procedure,
                "command_type_stored_procedure": True,
                "terminal_sink": "ExecuteNonQuery",
                "connection_expression": "conn",
                "start_offset": 10,
                "end_offset": 90,
            }
        ]
        for file_name, class_name, method_name, procedure in calls
    }
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=csharp_results,
        aspx_results=[],
        db_invocations=raw,
        connection_sources={
            str((root / file_name).resolve()): {"conn": "OrdersDb"} for file_name, _, _, _ in calls
        },
    )


def test_find_by_table_reports_writes_regardless_of_stored_procedure_case(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 01: a lower-case write must count the same as an upper-case one.

    Before the repair, `_ensure_referenced_node()` returned a dangling id for
    whichever reference to `VQM` was registered second, unresolving that
    write's whole Execution Path -- the analyst's response silently dropped
    it, with nothing to signal that anything was missing.
    """
    scan = _scan_with_calls(
        tmp_path,
        [
            ("UpperPage.cs", "UpperPage", "SaveUpper", "dbo.usp_WriteUpper"),
            ("LowerPage.cs", "LowerPage", "SaveLower", "dbo.usp_WriteLower"),
        ],
    )
    graph = build_sql_execution_graph(case_variant_table_write_data())
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {
            "database": "OrdersDb",
            "schema": "dbo",
            "sql_execution_graph": graph,
        },
    )

    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.VQM",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert {match.program for match in response.matches} == {"upperpage", "lowerpage"}
    assert all(match.evidence_status == "proven" for match in response.matches)


def test_find_by_table_keeps_a_real_write_behind_a_case_variant_temp_table_read(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 01: a dangling temp-table id must not unresolve the write beside it.

    `#TempStage` is created in one case and read back in another -- the same
    shape that made `#Order` and `#tmpPart` the two largest sources of
    dangling ids in the PUR cache. Before the repair, this put the temp
    table's id in `missing_targets` and downgraded the whole operation --
    including its proven write to `dbo.RealTable` -- to `unresolved`, so
    `filter_table_accesses()` produced no record for it at all.
    """
    scan = _scan_with_calls(
        tmp_path,
        [("TempPage.cs", "TempPage", "SaveWithTemp", "dbo.usp_WriteWithTemp")],
    )
    graph = build_sql_execution_graph(case_variant_temp_table_write_data())
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {
            "database": "OrdersDb",
            "schema": "dbo",
            "sql_execution_graph": graph,
        },
    )

    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.RealTable",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert [match.program for match in response.matches] == ["temppage"]
    assert response.matches[0].evidence_status == "proven"


def test_find_by_table_write_only_uses_graph_writers(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert [(match.program, match.access_type, match.operation_type) for match in response.matches] == [
        ("directpage", "UPDATE", "UPDATE"),
        ("nestedpage", "WRITE_INDIRECT", "INSERT"),
        ("orderpage", "WRITE_INDIRECT", "INSERT"),
    ]
    assert all(match.via_sp is True for match in response.matches)
    assert all(match.evidence_status == "proven" for match in response.matches)
    assert all(match.path_id for match in response.matches)


def test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces(
    monkeypatch,
    tmp_path: Path,
) -> None:
    scan = _scan(tmp_path)
    direct_file = str((tmp_path / "DirectPage.cs").resolve())
    scan.db_invocations[direct_file][0].update(
        {
            "invocation_kind": "source_wrapper",
            "wrapper_method_name": "ExeProcNon",
            "wrapper_receiver_type": "SQLObject",
            "wrapper_source_available": False,
            "wrapper_mode": "stored_procedure",
        }
    )
    monkeypatch.setattr(analyze_service, "resolve_source", lambda request: [tmp_path])
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [
                {"name": "dbo.usp_Direct"},
                {"name": "dbo.usp_Entry"},
                {"name": "dbo.usp_Nested"},
            ],
            "sql_execution_graph": _graph(),
        },
    )

    analyze_response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=["DirectPage"],
            include_snippets=False,
            fk_depth=0,
            wrapper_contract="sqlobject",
        )
    )
    invocation = analyze_response.programs[0].database_invocations[0]
    path = analyze_response.programs[0].execution_paths[0]

    sp_response = analyze_service.find_by_sp(
        FindBySPRequest(
            source={"project": "orders", "repo": "orders"},
            sp_name="dbo.usp_Direct",
            database="OrdersDb",
            cache_only=False,
            wrapper_contract="sqlobject",
        )
    )
    table_response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
            wrapper_contract="sqlobject",
        )
    )
    flow_response = analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "orders", "repo": "orders"},
            direction="backward",
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
            wrapper_contract="sqlobject",
        )
    )

    sp_match = next(match for match in sp_response.matches if match.program == "directpage")
    table_match = next(match for match in table_response.matches if match.program == "directpage")
    flow_match = next(chain for chain in flow_response.backward_chains if chain["program"] == "DirectPage.cs")
    parity_keys = (
        "wrapper_kind",
        "wrapper_status",
        "wrapper_classification_status",
        "classification_status",
        "status",
        "wrapper_selection_source",
        "selection_source",
        "wrapper_contract",
        "contract",
        "selected_contract",
        "wrapper_contract_mode",
        "contract_mode",
        "wrapper_contract_sink",
        "contract_sink",
        "wrapper_receiver_type",
        "receiver_type",
        "wrapper_method",
        "stored_procedure_mode",
        "wrapper_stored_procedure_mode",
        "evidence_status",
        "evidence_reason",
        "source_snapshot_identity",
        "source_provenance",
        "invocation_mode",
        "terminal_sink",
        "connection_source",
        "method_semantics",
        "command_text_kind",
        "command_text_literal",
        "contract_fingerprint",
        "contract_signature_version",
        "signature_version",
        "contract_lifecycle_status",
        "contract_status",
        "implementation_snapshot_reference",
        "comparison_report_reference",
        "procedure_name",
        "unresolved_reason",
    )

    def values(item):
        return {
            key: item.get(key) if isinstance(item, dict) else getattr(item, key)
            for key in parity_keys
        }

    expected = values(invocation)
    assert values(path) == expected
    assert values(sp_match) == expected
    assert values(table_match) == expected
    assert values(flow_match) == expected


def test_find_by_sp_accepts_schema_qualified_name(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.find_by_sp(
        FindBySPRequest(
            source={"project": "orders", "repo": "orders"},
            sp_name="dbo.usp_Direct",
            database="OrdersDb",
            cache_only=False,
        )
    )

    assert [(match.program, match.file) for match in response.matches] == [
        ("directpage", "DirectPage.cs")
    ]


def test_find_by_sp_exposes_likely_invocation_as_diagnostic(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    scan.connection_sources.pop(str((tmp_path / "DirectPage.cs").resolve()))
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.find_by_sp(
        FindBySPRequest(
            source={"project": "orders", "repo": "orders"},
            sp_name="dbo.usp_Direct",
            database="OrdersDb",
            cache_only=False,
        )
    )

    assert response.matches == []
    assert len(response.diagnostics) == 1
    diagnostic = response.diagnostics[0]
    assert diagnostic["evidence"] == "likely"
    assert diagnostic["reason"] == "unique_across_catalogs"
    assert diagnostic["database"] is None
    assert diagnostic["database_candidates"] == ["OrdersDb"]
    assert diagnostic["caller"] == "DirectPage.SaveDirect"
    assert diagnostic["source_span"]["relative_path"] == "DirectPage.cs"


def test_backward_flow_preserves_graph_path_and_ui_anchor(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "orders", "repo": "orders"},
            direction="backward",
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
        )
    )

    order_chain = next(
        chain for chain in response.backward_chains if chain["file"] == "OrderPage.aspx.cs"
    )
    assert order_chain["entry_method"] == "OrderPage.HandleSave"
    assert order_chain["sp_chain"] == ["dbo.usp_Entry", "dbo.usp_Nested"]
    assert order_chain["path_id"]
    assert order_chain["evidence"] == "proven"
    assert order_chain["ui_anchors"] == [
        {
            "file": str(tmp_path / "OrderPage.aspx"),
            "control": "asp:Button",
            "id": "btnSave",
            "event": "Click",
            "handler": "HandleSave",
        }
    ]


def test_find_by_table_exposes_likely_invocation_as_diagnostic(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    scan.connection_sources.pop(str((tmp_path / "DirectPage.cs").resolve()))
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
        )
    )

    assert all(match.program != "directpage" for match in response.matches)
    assert any(
        item["evidence"] == "likely"
        and item["reason"] == "unique_across_catalogs"
        and item["database_candidates"] == ["OrdersDb"]
        for item in response.diagnostics
    )


def test_backward_flow_exposes_likely_invocation_as_diagnostic(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    scan.connection_sources.pop(str((tmp_path / "DirectPage.cs").resolve()))
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=False: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.flow_chain(
        FlowChainRequest(
            source={"project": "orders", "repo": "orders"},
            direction="backward",
            table_name="dbo.SOrder",
            database="OrdersDb",
            cache_only=False,
        )
    )

    assert any(
        item["evidence"] == "likely"
        and item["reason"] == "unique_across_catalogs"
        and item["database_candidates"] == ["OrdersDb"]
        for item in response.diagnostics
    )


def test_analyze_keeps_likely_invocation_diagnostic_out_of_formal_counts(monkeypatch, tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    scan.connection_sources.pop(str((tmp_path / "DirectPage.cs").resolve()))
    monkeypatch.setattr(analyze_service, "resolve_source", lambda request: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)
    monkeypatch.setattr(
        analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {"database": "OrdersDb", "schema": "dbo", "sql_execution_graph": _graph()},
    )

    response = analyze_service.analyze(
        AnalyzeRequest(
            database="OrdersDb",
            program_names=["DirectPage"],
            include_snippets=False,
            fk_depth=0,
        )
    )

    program = response.programs[0]
    assert program.stored_procedures == []
    assert program.database_invocations[0]["evidence"] == "likely"
    assert program.diagnostics[0]["database_candidates"] == ["OrdersDb"]
    assert program.execution_paths[0]["evidence"] == "likely"
    assert program.execution_paths[0]["writes"] == []


def test_analyze_without_database_keeps_source_facts_without_formal_relationships(
    monkeypatch,
    tmp_path: Path,
) -> None:
    scan = _scan(tmp_path)
    scan.connection_sources.clear()
    scan.table_relations = [
        CSharpTableRelation(
            csharp_file=str(tmp_path / "DirectPage.cs"),
            class_name="DirectPage",
            method_name="SaveDirect",
            line_number=12,
            table_name="dbo.SOrder",
            database="OrdersDb",
            access_type="READ",
            sql_preview="SELECT * FROM dbo.SOrder",
        )
    ]
    monkeypatch.setattr(analyze_service, "resolve_source", lambda request: [tmp_path])
    monkeypatch.setattr(analyze_service, "_get_scan", lambda root, refresh=False: scan)

    response = analyze_service.analyze(
        AnalyzeRequest(
            program_names=["DirectPage"],
            include_snippets=False,
            fk_depth=0,
        )
    )

    program = response.programs[0]
    assert program.methods == [{"name": "SaveDirect", "class": "DirectPage"}]
    assert program.tables == ["dbo.SOrder"]
    assert program.stored_procedures == []
    assert program.database_invocations[0]["procedure_name"] == "usp_direct"
    assert program.database_invocations[0]["evidence"] == "unresolved"
    assert program.execution_paths[0]["evidence"] == "unresolved"
    assert program.execution_paths[0]["writes"] == []
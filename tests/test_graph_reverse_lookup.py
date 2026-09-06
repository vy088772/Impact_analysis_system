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


def _scan_one_program_multiple_calls(
    root: Path,
    file_name: str,
    class_name: str,
    calls: list[tuple[str, str]],
) -> ProjectScanResult:
    """One C# file/class making several distinct stored-procedure calls.

    `_scan_with_calls()` gives every call its own file, so it cannot build
    the ticket-02 scenario where one *program* reaches a table through
    several stored procedures. Each call gets its own source offset so its
    Execution Path's `path_id` differs from the others.
    """
    methods = [
        MethodInfo(name=method_name, access_modifier="private", return_type="void")
        for method_name, _ in calls
    ]
    file_result = _file(root, file_name, methods)
    resolved_path = str((root / file_name).resolve())
    raw_entries = [
        {
            "class_name": class_name,
            "method_name": method_name,
            "command_text_kind": "literal",
            "command_text": procedure_name,
            "command_type_stored_procedure": True,
            "terminal_sink": "ExecuteNonQuery",
            "connection_expression": "conn",
            "start_offset": index * 100 + 10,
            "end_offset": index * 100 + 90,
        }
        for index, (method_name, procedure_name) in enumerate(calls)
    ]
    return ProjectScanResult(
        project_root=str(root),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[file_result],
        aspx_results=[],
        db_invocations={resolved_path: raw_entries},
        connection_sources={resolved_path: {"conn": "OrdersDb"}},
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


# --------------------------------------------------- reverse-lookup-drops-proven-writes, ticket 02


def test_find_by_table_reports_unresolved_dynamic_sql_and_write_only_excludes_it(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 02: Unresolved Dynamic SQL becomes visible instead of absent.

    `usp_Dynamic` runs dynamic text the SQL analyzer never parses -- it has no
    `reads`/`writes` of its own, so it can never match a table by name. No
    repair will ever prove what it does; the reverse lookup can only say that
    it exists and that the table asked about cannot be ruled out. It is not a
    mutation: `write_only=True` must still exclude it, and must say so via
    `excluded_count` instead of silently returning a shorter list.
    """
    data = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_Dynamic",
                "definition": """CREATE PROCEDURE dbo.usp_Dynamic
AS
BEGIN
    EXEC(@sql);
END;
""",
            },
        ],
        "views": [],
        "functions": [],
        "tables": [],
    }
    graph = build_sql_execution_graph(data)
    scan = _scan_with_calls(
        tmp_path,
        [("DynamicPage.cs", "DynamicPage", "SaveDynamic", "dbo.usp_Dynamic")],
    )
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

    touches = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.VQM",
            database="OrdersDb",
            cache_only=False,
            write_only=False,
        )
    )

    assert [match.program for match in touches.matches] == ["dynamicpage"]
    match = touches.matches[0]
    assert match.evidence_status == "unresolved"
    assert match.reason == "unresolved_dynamic_sql"
    assert match.access_type == "UNRESOLVED"
    assert touches.excluded_count == 0

    writes_only = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.VQM",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert writes_only.matches == []
    assert writes_only.excluded_count == 1


def test_find_by_table_reports_one_record_per_stored_procedure_reaching_the_table(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 02 / ADR-0016: one program, two stored procedures, two records.

    `_prefer_table_match()` used to key by file and keep only the
    highest-ranked access fact -- one program writing the same table through
    two different stored procedures reported only one of them, and the
    response did not say which, or that there were two.
    """
    data = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_WriteA",
                "definition": "CREATE PROCEDURE dbo.usp_WriteA AS INSERT INTO dbo.Ledger (Id) VALUES (1);",
            },
            {
                "name": "dbo.usp_WriteB",
                "definition": "CREATE PROCEDURE dbo.usp_WriteB AS UPDATE dbo.Ledger SET Id = 1;",
            },
        ],
        "views": [],
        "functions": [],
        "tables": [{"name": "dbo.Ledger"}],
    }
    graph = build_sql_execution_graph(data)
    scan = _scan_one_program_multiple_calls(
        tmp_path,
        "LedgerPage.cs",
        "LedgerPage",
        [("SaveA", "dbo.usp_WriteA"), ("SaveB", "dbo.usp_WriteB")],
    )
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
            table_name="dbo.Ledger",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert {match.program for match in response.matches} == {"ledgerpage"}
    assert len(response.matches) == 2
    assert len({match.path_id for match in response.matches}) == 2
    assert all(match.evidence_status == "proven" for match in response.matches)


def test_find_by_table_reports_a_read_and_a_write_from_the_same_program(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 02 / ADR-0016: a read never hides a write for the same program.

    One program reads `Ledger` through one stored procedure and writes it
    through another. Both facts must survive -- the old file-keyed dedup kept
    only the write.
    """
    data = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_ReadLedger",
                "definition": "CREATE PROCEDURE dbo.usp_ReadLedger AS SELECT Id FROM dbo.Ledger;",
            },
            {
                "name": "dbo.usp_WriteLedger",
                "definition": "CREATE PROCEDURE dbo.usp_WriteLedger AS UPDATE dbo.Ledger SET Id = 1;",
            },
        ],
        "views": [],
        "functions": [],
        "tables": [{"name": "dbo.Ledger"}],
    }
    graph = build_sql_execution_graph(data)
    scan = _scan_one_program_multiple_calls(
        tmp_path,
        "LedgerPage.cs",
        "LedgerPage",
        [("Load", "dbo.usp_ReadLedger"), ("Save", "dbo.usp_WriteLedger")],
    )
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
            table_name="dbo.Ledger",
            database="OrdersDb",
            cache_only=False,
            write_only=False,
        )
    )

    assert {(match.access_type, match.evidence_status) for match in response.matches} == {
        ("READ", "proven"),
        ("UPDATE", "proven"),
    }
    assert len(response.matches) == 2


def test_find_by_table_reports_a_proven_read_beside_an_unproven_write_from_the_same_program(
    monkeypatch, tmp_path: Path
) -> None:
    """ADR-0016's own motivating case: an unproven write must not win the file's
    one seat and displace a proven read, or the reverse.

    `usp_WriteLedger`'s write to `Ledger` sits in the same DML operation as a
    read of a table the graph has no node for, so the whole path downgrades to
    `unresolved` (decision 3) -- it produces an `UNRESOLVED` record, not an
    `UPDATE` one. Under the old file-keyed dedup, `_table_match_rank()` scored
    a write above a read regardless of Evidence Status, so this record would
    have won the file's one seat and the proven read from `usp_ReadLedger`
    would have been discarded with it. Both must survive as separate records.
    """
    graph = {
        "graph_version": 4,
        "database": "OrdersDb",
        "nodes": [
            {
                "id": "stored_procedure:dbo.usp_ReadLedger",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_ReadLedger",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_ReadLedger:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_ReadLedger",
                "sequence": 1,
                "operation_type": "SELECT",
            },
            {
                "id": "stored_procedure:dbo.usp_WriteLedger",
                "type": "stored_procedure",
                "schema": "dbo",
                "name": "usp_WriteLedger",
            },
            {
                "id": "dml_operation:stored_procedure:dbo.usp_WriteLedger:1",
                "type": "dml_operation",
                "module_id": "stored_procedure:dbo.usp_WriteLedger",
                "sequence": 1,
                "operation_type": "UPDATE",
            },
            {"id": "table:dbo.Ledger", "type": "table", "schema": "dbo", "name": "Ledger"},
        ],
        "relationships": [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_ReadLedger",
                "target": "dml_operation:stored_procedure:dbo.usp_ReadLedger:1",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_ReadLedger:1",
                "target": "table:dbo.Ledger",
            },
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_WriteLedger",
                "target": "dml_operation:stored_procedure:dbo.usp_WriteLedger:1",
            },
            {
                "type": "writes",
                "source": "dml_operation:stored_procedure:dbo.usp_WriteLedger:1",
                "target": "table:dbo.Ledger",
            },
            {
                "type": "reads",
                "source": "dml_operation:stored_procedure:dbo.usp_WriteLedger:1",
                "target": "table:dbo.Missing",
            },
        ],
        "parse_errors": [],
    }
    scan = _scan_one_program_multiple_calls(
        tmp_path,
        "LedgerPage.cs",
        "LedgerPage",
        [("Load", "dbo.usp_ReadLedger"), ("Save", "dbo.usp_WriteLedger")],
    )
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

    all_access = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.Ledger",
            database="OrdersDb",
            cache_only=False,
            write_only=False,
        )
    )

    assert {(match.access_type, match.evidence_status) for match in all_access.matches} == {
        ("READ", "proven"),
        ("UNRESOLVED", "unresolved"),
    }
    assert len(all_access.matches) == 2
    assert all_access.excluded_count == 0

    writes_only = analyze_service.find_by_table(
        FindByTableRequest(
            source={"project": "orders", "repo": "orders"},
            table_name="dbo.Ledger",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert writes_only.matches == []
    assert writes_only.excluded_count == 2


def test_find_by_table_collapses_two_identical_execution_paths_into_one_record(
    monkeypatch, tmp_path: Path
) -> None:
    """Ticket 02 / ADR-0016: two identical Execution Paths still collapse to one.

    Deduplicating by Execution Path identity, not by file, must still collapse
    a genuine repeat -- the same call site's fact reaching the response twice
    is not two facts. Both raw invocations here share every field, including
    the source span, so they produce the same `path_id`.
    """
    data = {
        "database": "OrdersDb",
        "schema": "dbo",
        "procedures": [
            {
                "name": "dbo.usp_WriteLedger",
                "definition": "CREATE PROCEDURE dbo.usp_WriteLedger AS UPDATE dbo.Ledger SET Id = 1;",
            },
        ],
        "views": [],
        "functions": [],
        "tables": [{"name": "dbo.Ledger"}],
    }
    graph = build_sql_execution_graph(data)
    file_path = tmp_path / "LedgerPage.cs"
    duplicate_call = {
        "class_name": "LedgerPage",
        "method_name": "Save",
        "command_text_kind": "literal",
        "command_text": "dbo.usp_WriteLedger",
        "command_type_stored_procedure": True,
        "terminal_sink": "ExecuteNonQuery",
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 90,
    }
    scan = ProjectScanResult(
        project_root=str(tmp_path),
        project_name="orders",
        scan_time=datetime.now(),
        csharp_results=[
            _file(tmp_path, "LedgerPage.cs", [MethodInfo(name="Save", access_modifier="private", return_type="void")])
        ],
        aspx_results=[],
        db_invocations={str(file_path.resolve()): [dict(duplicate_call), dict(duplicate_call)]},
        connection_sources={str(file_path.resolve()): {"conn": "OrdersDb"}},
    )
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
            table_name="dbo.Ledger",
            database="OrdersDb",
            cache_only=False,
            write_only=True,
        )
    )

    assert len(response.matches) == 1
    assert response.matches[0].program == "ledgerpage"
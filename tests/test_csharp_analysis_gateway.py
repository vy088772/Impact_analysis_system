"""Ticket 02 behavior checks: direct SqlClient invocation detection via CSharpAnalysisGateway."""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.csharp_analysis_gateway import (
    CSharpAnalysisGateway,
    InvocationEvidence,
    SpCatalog,
    normalize_procedure_name,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
import code_analyzer.static_analyzer_host as static_analyzer_host_module
import code_analyzer.csharp_analysis_gateway as gateway_module


def _raw_invocation(**overrides) -> dict:
    base = {
        "class_name": "PUR_SOMaintain",
        "method_name": "DeleteData",
        "command_text_kind": "literal",
        "command_text": "usp_SO_Delete",
        "command_type_stored_procedure": True,
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 90,
    }
    base.update(overrides)
    return base


def _sqlobject_wrapper_contract() -> dict:
    return {
        "name": "sqlobject",
        "receiver_types": ["SQLObject"],
        "methods": {
            "ExeProcNon": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"},
            "ExeProcRead": {"mode": "stored_procedure", "sink": "ExecuteReader"},
            "CreateReader": {"mode": "inline_sql", "sink": "ExecuteReader"},
            "CreateTable": {"mode": "call_site", "sink": "ExecuteReader"},
            "CreateDataSet": {"mode": "call_site", "sink": "ExecuteReader"},
        },
    }


def test_wrapper_reconciliation_boundary_classifies_contract_sources_and_review_gaps(tmp_path: Path) -> None:
    """One gateway boundary exposes deterministic wrapper selection provenance."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    source_root = str(tmp_path)

    source = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="Execute",
            wrapper_receiver_type="LocalWrapper",
            wrapper_source_available=True,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
    )
    assert source.wrapper_kind == "source_wrapper"
    assert source.status == "source_wrapper"
    assert source.selection_source == "source_code"
    assert source.contract == ""
    assert source.review_candidate is False
    assert source.active_contract is False
    assert source.stored_procedure_mode is True
    assert source.scan_root == source_root
    assert source.source_span.relative_path == "OrderPage.cs"

    explicit = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="ExeProcNon",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
        explicit_contract=_sqlobject_wrapper_contract(),
    )
    assert explicit.status == "explicit_selected"
    assert explicit.selection_source == "explicit"
    assert explicit.contract == "sqlobject"
    assert explicit.contract_mode == "stored_procedure"
    assert explicit.contract_sink == "ExecuteNonQuery"
    assert explicit.candidate_contracts == ("sqlobject",)

    auto = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="ExeProcNon",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
    )
    assert auto.status == "auto_selected"
    assert auto.selection_source == "auto_receiver_type"
    assert auto.contract == "sqlobject"

    missing_method = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="NewMethod",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
    )
    assert missing_method.status == "unresolved_method"
    assert missing_method.contract == "sqlobject"
    assert missing_method.review_candidate is True
    assert missing_method.active_contract is False
    assert missing_method.reason == "method_not_in_contract"

    unknown_receiver = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="ExeProcNon",
            wrapper_receiver_type="UnknownDbHelper",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
    )
    assert unknown_receiver.status == "unresolved_contract"
    assert unknown_receiver.reason == "no_contract_matches_receiver_type"
    assert unknown_receiver.receiver_type == "UnknownDbHelper"
    assert unknown_receiver.wrapper_method == "ExeProcNon"
    assert unknown_receiver.review_candidate is True
    assert unknown_receiver.active_contract is False
    unknown_payload = unknown_receiver.to_dict()
    assert unknown_payload["observed_method"] == "ExeProcNon"
    assert unknown_payload["unresolved_reason"] == "no_contract_matches_receiver_type"

    mismatched = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="ExeProcNon",
            wrapper_receiver_type="OtherDbObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        scan_root=source_root,
        explicit_contract=_sqlobject_wrapper_contract(),
    )
    assert mismatched.status == "receiver_mismatch"
    assert mismatched.reason == "receiver_type_does_not_match_contract"
    assert mismatched.candidate_contracts == ("sqlobject",)


def test_wrapper_reconciliation_boundary_keeps_ambiguity_and_mode_rules_machine_readable(
    monkeypatch,
) -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    monkeypatch.setattr(
        gateway_module,
        "external_wrapper_contract_candidates",
        lambda _receiver_type: [
            {"name": "sqlobject-v1", "receiver_types": ["SQLObject"]},
            {"name": "sqlobject-v2", "receiver_types": ["SQLObject"]},
        ],
    )

    ambiguous = gateway.reconcile_wrapper(
        "SqlObjectPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="ExeProcNon",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
    )
    assert ambiguous.status == "ambiguous_contract"
    assert ambiguous.candidate_contracts == ("sqlobject-v1", "sqlobject-v2")
    assert ambiguous.review_candidate is True
    assert ambiguous.active_contract is False
    assert ambiguous.reason == "multiple_contracts_match_receiver_type"

    contract = _sqlobject_wrapper_contract()
    inline = gateway.reconcile_wrapper(
        "SqlObjectPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="CreateReader",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="inline_sql",
            command_type_stored_procedure=False,
            command_text="SELECT * FROM SOrder",
        ),
        explicit_contract=contract,
    )
    assert inline.status == "explicit_selected"
    assert inline.contract_mode == "inline_sql"
    assert inline.stored_procedure_mode is False
    assert inline.mode_reason == "inline_sql"

    call_site = gateway.reconcile_wrapper(
        "SqlObjectPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="CreateTable",
            wrapper_receiver_type="SQLObject",
            wrapper_source_available=False,
            wrapper_mode="unknown",
        ),
        explicit_contract=contract,
    )
    assert call_site.status == "explicit_selected"
    assert call_site.contract_mode == "call_site"
    assert call_site.stored_procedure_mode is False
    assert call_site.mode_reason == "call_site_requires_explicit_stored_procedure_mode"

    ambiguous_invocation = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_mode="stored_procedure",
            )
        ],
    )[0]
    assert ambiguous_invocation.evidence is InvocationEvidence.UNRESOLVED
    assert ambiguous_invocation.wrapper_review_candidate is True
    assert ambiguous_invocation.wrapper_unresolved_reason == (
        "multiple_contracts_match_receiver_type"
    )


def test_direct_invocation_evidence_honors_explicit_contract_selector() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="ExeProcNon",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [raw],
        explicit_contract="missing-contract",
    )[0]

    assert invocation.wrapper_status == "unresolved_contract"
    assert invocation.wrapper_unresolved_reason == "configured_contract_not_found"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "wrapper_source_unavailable"


def test_resolved_invocation_retains_wrapper_reconciliation_provenance(tmp_path: Path) -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    proven = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_mode="stored_procedure",
                command_text="usp_SaveOrder",
            )
        ],
        scan_root=str(tmp_path),
    )[0]
    assert proven.evidence is InvocationEvidence.PROVEN
    assert proven.wrapper_kind == "external_wrapper"
    assert proven.wrapper_status == "auto_selected"
    assert proven.wrapper_classification_status == "auto_selected"
    assert proven.wrapper_selection_source == "auto_receiver_type"
    assert proven.wrapper_contract == "sqlobject"
    assert proven.wrapper_contract_mode == "stored_procedure"
    assert proven.wrapper_contract_sink == "ExecuteNonQuery"
    assert proven.wrapper_scan_root == str(tmp_path)
    assert proven.wrapper_receiver_type == "SQLObject"
    assert proven.wrapper_method == "ExeProcNon"
    assert proven.external_wrapper_method == "ExeProcNon"

    unresolved = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="UnknownDbHelper",
                wrapper_source_available=False,
                wrapper_mode="stored_procedure",
            )
        ],
        scan_root=str(tmp_path),
    )[0]
    assert unresolved.evidence is InvocationEvidence.UNRESOLVED
    assert unresolved.wrapper_status == "unresolved_contract"
    assert unresolved.wrapper_unresolved_reason == "no_contract_matches_receiver_type"
    assert unresolved.wrapper_scan_root == str(tmp_path)
    assert unresolved.wrapper_receiver_type == "UnknownDbHelper"
    assert unresolved.wrapper_method == "ExeProcNon"
    assert unresolved.external_wrapper_method == "ExeProcNon"


def test_normalize_procedure_name_strips_schema_and_brackets() -> None:
    """Only the bare, case-insensitive procedure name is used for catalog matching."""
    assert normalize_procedure_name("usp_SO_Delete") == "usp_so_delete"
    assert normalize_procedure_name("dbo.usp_SO_Delete") == "usp_so_delete"
    assert normalize_procedure_name("[dbo].[usp_SO_Delete]") == "usp_so_delete"


def test_catalog_merges_case_variants_of_one_database_identity() -> None:
    catalog = SpCatalog.from_databases({
        "OrdersDb": ["usp_SaveOrder"],
        "ordersdb": ["usp_DeleteOrder"],
    })

    assert catalog.databases_containing("usp_saveorder") == ["OrdersDb"]
    assert catalog.contains("ORDERSDB", "usp_deleteorder")


def test_explicit_stored_procedure_type_with_catalog_hit_is_proven() -> None:
    """An explicit CommandType.StoredProcedure call matching the resolved database's catalog is proven."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocations = gateway.resolve_direct_invocations("Ship/PUR_SOMaintain.aspx.cs", [_raw_invocation()])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.class_name == "PUR_SOMaintain"
    assert invocation.method_name == "DeleteData"
    assert invocation.database == "Y-Docs_TTPUR"
    assert invocation.procedure_name == "usp_so_delete"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.source.relative_path == "Ship/PUR_SOMaintain.aspx.cs"
    assert invocation.source.start_offset == 10
    assert invocation.source.end_offset == 90


def test_schema_qualified_catalog_matching_does_not_cross_same_name_schemas() -> None:
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["dbo.usp_SO_Delete", "sales.usp_SO_Delete"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    proven = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="sales.usp_SO_Delete")],
    )[0]
    unresolved = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="reporting.usp_SO_Delete")],
    )[0]

    assert proven.evidence is InvocationEvidence.PROVEN
    assert proven.procedure_schema == "sales"
    assert unresolved.evidence is InvocationEvidence.UNRESOLVED
    assert unresolved.reason == "not_in_resolved_catalog"


def test_bare_catalog_entries_are_scoped_to_default_schema_for_qualified_calls() -> None:
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(command_text="sales.usp_SO_Delete")],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "not_in_resolved_catalog"


def test_inline_sql_without_stored_procedure_type_is_not_reported() -> None:
    """A SqlCommand call that never sets CommandType.StoredProcedure is plain SQL, not an SP invocation."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = _raw_invocation(command_text="SELECT * FROM SOrder", command_type_stored_procedure=False)
    invocations = gateway.resolve_direct_invocations("Ship/PUR_SOMaintain.aspx.cs", [raw])

    assert invocations == []


def test_ordinary_method_without_database_invocation_fact_is_not_reported() -> None:
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = {
        "class_name": "PUR_SOMaintain",
        "method_name": "FormatOrderNumber",
        "command_text_kind": "none",
        "command_text": None,
        "command_type_stored_procedure": False,
        "start_offset": 200,
        "end_offset": 230,
    }

    assert gateway.resolve_direct_invocations("f.cs", [raw]) == []


def test_dynamic_command_text_is_unresolved() -> None:
    """A variable-built command text cannot be identified statically, so it stays unresolved."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = _raw_invocation(command_text_kind="dynamic", command_text=None)
    invocations = gateway.resolve_direct_invocations("f.cs", [raw])

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].procedure_name is None
    assert invocations[0].database == "Y-Docs_TTPUR"


def test_branch_assigned_procedure_names_keep_separate_contexts() -> None:
    """Each finite procedure candidate remains tied to the branch that assigns it."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_Default", "usp_Alternate"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw_invocations = [
        _raw_invocation(
            command_text="usp_Default",
            branch_context=[],
        ),
        _raw_invocation(
            command_text="usp_Alternate",
            branch_context=["if (useAlternate)"],
        ),
    ]

    invocations = gateway.resolve_direct_invocations("f.cs", raw_invocations)

    assert [invocation.procedure_name for invocation in invocations] == [
        "usp_default",
        "usp_alternate",
    ]
    assert [invocation.branch_context for invocation in invocations] == [
        (),
        ("if (useAlternate)",),
    ]
    assert all(invocation.evidence is InvocationEvidence.PROVEN for invocation in invocations)


def test_adapter_invocations_use_catalog_evidence_and_unknown_mode_stays_unresolved() -> None:
    """Dapper and EF facts share the same catalog gate without proving unknown modes."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw_invocations = [
        _raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="dapper",
            wrapper_mode="stored_procedure",
        ),
        _raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="entity_framework",
            wrapper_mode="stored_procedure",
        ),
        _raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="dapper",
            wrapper_mode="unknown",
            command_type_stored_procedure=False,
        ),
    ]

    invocations = gateway.resolve_direct_invocations("f.cs", raw_invocations)

    assert [invocation.evidence for invocation in invocations] == [
        InvocationEvidence.PROVEN,
        InvocationEvidence.PROVEN,
        InvocationEvidence.UNRESOLVED,
    ]
    assert invocations[-1].reason == "adapter_mode_unresolved"


def test_unknown_adapter_connection_with_cross_database_name_is_unresolved() -> None:
    catalog = SpCatalog.from_databases({
        "OrdersDb": ["usp_SaveOrder"],
        "ArchiveDb": ["usp_SaveOrder"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="dapper",
            wrapper_mode="stored_procedure",
            connection_expression="connection",
        )],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "ambiguous_cross_database"
    assert invocation.database is None


def test_resolved_database_without_catalog_hit_is_unresolved_not_guessed() -> None:
    """A resolved database that does not contain the named procedure must not be fabricated as proven."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Insert"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database == "Y-Docs_TTPUR"
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_unique_across_catalogs_is_likely() -> None:
    """When the connection source cannot be resolved, a globally unique procedure name is only likely."""
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["usp_SO_Delete"],
        "OtherDb": ["usp_Something_Else"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.LIKELY
    assert invocations[0].database is None
    assert invocations[0].database_candidates == ("Y-Docs_TTPUR",)
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_ambiguous_across_catalogs_is_unresolved() -> None:
    """A same-named procedure in multiple databases must remain unresolved without a known connection source."""
    catalog = SpCatalog.from_databases({
        "Y-Docs_TTPUR": ["usp_SO_Delete"],
        "Y-Docs_TTRDQ": ["usp_SO_Delete"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database is None
    assert invocations[0].procedure_name == "usp_so_delete"


def test_unknown_connection_source_and_unknown_name_is_unresolved() -> None:
    """A procedure name absent from every known catalog stays unresolved, never guessed."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Insert"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocations = gateway.resolve_direct_invocations("f.cs", [_raw_invocation()])

    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].database is None
    assert invocations[0].procedure_name == "usp_so_delete"


def test_gateway_detects_real_direct_sqlclient_invocation_via_static_analyzer_host() -> None:
    """End-to-end: the real Roslyn host output feeds the gateway to a proven Database Invocation."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "Foo.cs"
        source_path.write_text(
            "public class Foo {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"usp_DoThing\", conn);\n"
            "        cmd.CommandType = CommandType.StoredProcedure;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "    private void Inline() {\n"
            "        var conn2 = new SqlConnection(\"x\");\n"
            "        var cmd2 = new SqlCommand(\"SELECT * FROM Foo\", conn2);\n"
            "        cmd2.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]
        assert len(raw_invocations) == 2
        assert raw_invocations[1]["command_type_stored_procedure"] is False

        catalog = SpCatalog.from_databases({"MyDb": ["usp_DoThing"]})
        gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "MyDb"})
        invocations = gateway.resolve_direct_invocations("Foo.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.PROVEN
        assert invocations[0].procedure_name == "usp_dothing"
        assert invocations[0].database == "MyDb"


def test_static_analyzer_host_emits_default_and_conditional_procedure_assignments() -> None:
    """A command text variable yields one raw fact for every reachable finite assignment."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "BranchFixture.cs"
        source_path.write_text(
            "public class BranchFixture {\n"
            "    private void Run(bool useAlternate) {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        string procedure = \"usp_Default\";\n"
            "        if (useAlternate)\n"
            "            procedure = \"usp_Alternate\";\n"
            "        var cmd = new SqlCommand(procedure, conn);\n"
            "        cmd.CommandType = CommandType.StoredProcedure;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert {invocation["command_text"] for invocation in raw_invocations} == {
            "usp_Default",
            "usp_Alternate",
        }
        assert any(invocation["branch_context"] == [] for invocation in raw_invocations)
        assert any(
            invocation["branch_context"] == ["if (useAlternate)"]
            for invocation in raw_invocations
        )


def test_static_analyzer_host_drops_unconditionally_overwritten_procedure_values() -> None:
    """An unconditional later assignment supersedes an earlier finite candidate."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "OverwriteFixture.cs"
        source_path.write_text(
            "public class OverwriteFixture {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        string procedure = \"usp_Obsolete\";\n"
            "        procedure = \"usp_Default\";\n"
            "        var cmd = new SqlCommand(procedure, conn);\n"
            "        cmd.CommandType = CommandType.StoredProcedure;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert [invocation["command_text"] for invocation in raw_invocations] == ["usp_Default"]


def test_static_analyzer_host_drops_nested_value_overwritten_by_outer_branch_assignment() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NestedOverwriteFixture.cs"
        source_path.write_text(
            "public class NestedOverwriteFixture {\n"
            "    private void Run(bool useAlternate, bool useNested) {\n"
            "        var procedure = \"usp_Default\";\n"
            "        if (useAlternate) {\n"
            "            if (useNested)\n"
            "                procedure = \"usp_Obsolete\";\n"
            "            procedure = \"usp_Final\";\n"
            "        }\n"
            "        var command = new SqlCommand(procedure, conn);\n"
            "        command.CommandType = CommandType.StoredProcedure;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert {invocation["command_text"] for invocation in raw_invocations} == {
            "usp_Default",
            "usp_Final",
        }


def test_static_analyzer_host_preserves_same_text_at_distinct_direct_call_sites() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "DuplicateCallSites.cs"
        source_path.write_text(
            "public class DuplicateCallSites {\n"
            "    private void Run() {\n"
            "        var first = new SqlCommand(\"usp_SaveOrder\", conn);\n"
            "        first.CommandType = CommandType.StoredProcedure;\n"
            "        var second = new SqlCommand(\"usp_SaveOrder\", conn);\n"
            "        second.CommandType = CommandType.StoredProcedure;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert len(raw_invocations) == 2
        assert len({invocation["start_offset"] for invocation in raw_invocations}) == 2


def test_static_analyzer_host_preserves_constructor_default_with_conditional_command_text() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandTextBranches.cs"
        source_path.write_text(
            "public class CommandTextBranches {\n"
            "    private void Run(bool useAlternate) {\n"
            "        var command = new SqlCommand(\"usp_Default\", conn);\n"
            "        if (useAlternate)\n"
            "            command.CommandText = \"usp_Alternate\";\n"
            "        command.CommandType = CommandType.StoredProcedure;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert {invocation["command_text"] for invocation in raw_invocations} == {
            "usp_Default",
            "usp_Alternate",
        }
        assert any(invocation["branch_context"] == [] for invocation in raw_invocations)
        assert any(
            invocation["branch_context"] == ["if (useAlternate)"]
            for invocation in raw_invocations
        )


def test_static_analyzer_host_does_not_promote_unconditional_text_for_conditional_command_type() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandTypeBranch.cs"
        source_path.write_text(
            "public class CommandTypeBranch {\n"
            "    private void Run(bool useAlternate) {\n"
            "        var command = new SqlCommand(\"usp_Default\", conn);\n"
            "        if (useAlternate)\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "direct_sqlclient"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_stored_procedure"] is False


def test_static_analyzer_host_emits_dapper_and_entity_framework_sp_facts() -> None:
    """Common adapter SP modes feed the same gateway evidence rules as SqlClient."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AdapterFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "public class AdapterFixture {\n"
            "    private IDbConnection connection;\n"
            "    private DbContext context;\n"
            "    private void Dapper(bool useAlternate) {\n"
            "        var procedure = \"usp_Default\";\n"
            "        if (useAlternate)\n"
            "            procedure = \"usp_Alternate\";\n"
            "        connection.Query<int>(procedure, commandType: CommandType.StoredProcedure);\n"
            "        connection.Query<int>(\"SELECT 1\");\n"
            "        connection.Execute(\"usp_Unknown\", commandType: commandType);\n"
            "        helper.Execute(\"usp_SaveOrder\", commandType: CommandType.StoredProcedure);\n"
            "    }\n"
            "    private void DapperOverwritten() {\n"
            "        var procedure = \"usp_Obsolete\";\n"
            "        procedure = \"usp_Default\";\n"
            "        connection.Query<int>(procedure, commandType: CommandType.StoredProcedure);\n"
            "    }\n"
            "    private void EntityFramework() {\n"
            "        context.Database.ExecuteSqlRaw(\"EXEC dbo.usp_SaveOrder @Id\");\n"
            "        context.Database.ExecuteSqlRaw(\"UPDATE SOrder SET Status = 1\");\n"
            "    }\n"
            "    private void OrdinaryHelpers() {\n"
            "        var conn = new CommandHelper();\n"
            "        conn.Execute(\"usp_NotDapper\", commandType: CommandType.StoredProcedure);\n"
            "        var context = new CommandHelper();\n"
            "        context.ExecuteSqlRaw(\"EXEC dbo.usp_NotEntityFramework\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") in {"dapper", "entity_framework"}
        ]

        dapper = [item for item in raw_invocations if item["invocation_kind"] == "dapper"]
        entity_framework = [
            item for item in raw_invocations
            if item["invocation_kind"] == "entity_framework"
        ]
        assert {item["command_text"] for item in dapper} >= {
            "usp_Default",
            "usp_Alternate",
            "usp_Unknown",
        }
        assert all(item["connection_expression"] != "helper" for item in dapper)
        assert "usp_Obsolete" not in {item["command_text"] for item in dapper}
        assert "usp_NotDapper" not in {item["command_text"] for item in raw_invocations}
        assert "usp_NotEntityFramework" not in {item["command_text"] for item in raw_invocations}
        assert any(item["wrapper_mode"] == "inline_sql" for item in dapper)
        assert any(
            item["wrapper_mode"] == "stored_procedure"
            and item["command_text"] == "dbo.usp_SaveOrder"
            for item in entity_framework
        )
        assert any(item["wrapper_mode"] == "inline_sql" for item in entity_framework)

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Default", "usp_Alternate", "usp_SaveOrder"]}),
            connection_sources={"connection": "OrdersDb", "context.Database": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("AdapterFixture.cs", raw_invocations)

        proven = {
            (invocation.method_name, invocation.procedure_name)
            for invocation in invocations
            if invocation.evidence is InvocationEvidence.PROVEN
        }
        assert ("Dapper", "usp_default") in proven
        assert ("Dapper", "usp_alternate") in proven
        assert ("EntityFramework", "usp_saveorder") in proven
        assert all(invocation.procedure_name != "usp_unknown" for invocation in invocations)


def test_gateway_detects_source_wrapper_sp_mode_but_skips_inline_mode() -> None:
    """A source-backed wrapper is proven only when its call-site mode selects SP execution."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "WrapperFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", false);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
        gateway = CSharpAnalysisGateway(catalog, connection_sources={"wrapper": "OrdersDb"})

        invocations = gateway.resolve_direct_invocations("WrapperFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].class_name == "OrderPage"
        assert invocations[0].method_name == "Save"
        assert invocations[0].procedure_name == "usp_saveorder"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_traces_source_wrapper_across_files() -> None:
    """Batch C# analysis makes a wrapper in one source file available to its caller."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        wrapper_path = Path(temp_dir) / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = Path(temp_dir) / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files([wrapper_path, caller_path])

        assert len(results) == 2
        caller_result = results[1]
        wrapper_invocations = [
            invocation
            for invocation in caller_result["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]
        assert len(wrapper_invocations) == 1
        assert wrapper_invocations[0]["method_chain"] == ["Save", "Execute"]


def test_static_analyzer_host_disambiguates_same_named_wrappers_by_namespace() -> None:
    """A fully qualified caller receiver selects the matching same-named wrapper definition."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first_wrapper_path = root / "FirstWrapper.cs"
        first_wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace First {\n"
            "    public class DbWrapper {\n"
            "        private readonly SqlConnection _connection;\n"
            "        public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "        public void Execute(string commandText, bool storedProcedure) {\n"
            "            var command = new SqlCommand(commandText, _connection);\n"
            "            command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        second_wrapper_path = root / "SecondWrapper.cs"
        second_wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace Second {\n"
            "    public class DbWrapper {\n"
            "        private readonly SqlConnection _connection;\n"
            "        public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "        public void Execute(string commandText, bool storedProcedure) {\n"
            "            var command = new SqlCommand(commandText, _connection);\n"
            "            command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new object();\n"
            "        var wrapper = new First.DbWrapper(null);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files(
            [first_wrapper_path, second_wrapper_path, caller_path],
            source_roots=[root],
        )

        caller_invocations = [
            invocation
            for invocation in results[2]["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]
        assert len(caller_invocations) == 1
        assert caller_invocations[0]["wrapper_source_available"] is True
        assert caller_invocations[0]["wrapper_class_name"] == "DbWrapper"
        assert caller_invocations[0]["wrapper_method_name"] == "Execute"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", caller_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_keeps_wrapper_source_available_across_batches() -> None:
    """Every C# batch keeps the full source root as wrapper-analysis context."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_path = root / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        with patch.object(static_analyzer_host_module, "_MAX_HOST_COMMAND_CHARS", 1):
            results = host.analyze_csharp_files([caller_path, wrapper_path], source_roots=[root])

        caller_result = results[0]
        assert any(
            invocation.get("invocation_kind") == "source_wrapper"
            and invocation.get("wrapper_source_available") is True
            for invocation in caller_result["db_invocations"]
        )


def test_source_wrapper_string_sp_mode_is_catalog_validated() -> None:
    """A wrapper selecting SP mode through a string discriminator is proven and inline mode is skipped."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "StringModeFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, string mode) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        if (mode == \"SP\")\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "        else\n"
            "            command.CommandType = CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", \"SP\");\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", \"Text\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("StringModeFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].method_name == "Save"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_source_wrapper_propagates_constructor_connection_to_catalog() -> None:
    """A wrapper field assigned from its constructor receives the caller's database source."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_path = root / "DbWrapper.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "OrderPage.cs"
        caller_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files([wrapper_path, caller_path], source_roots=[root])
        raw_invocations = results[1]["db_invocations"]
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].database == "OrdersDb"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_source_wrapper_without_ado_net_sink_is_unresolved() -> None:
    """StoredProcedure configuration without command execution is not sink proof."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NoSinkFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    public void Execute(string commandText, bool storedProcedure) {\n"
            "        var command = new SqlCommand(commandText, null);\n"
            "        command.CommandType = storedProcedure ? CommandType.StoredProcedure : CommandType.Text;\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = new DbWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocation = result["db_invocations"][0]
        assert raw_invocation["wrapper_reaches_stored_procedure_sink"] is False

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations("NoSinkFixture.cs", [raw_invocation])[0]

        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "wrapper_sink_unresolved"


def test_source_wrapper_tracks_command_properties_assigned_after_creation() -> None:
    """A wrapper that configures an empty SqlCommand through properties still yields a proven SP call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "PropertySetupFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, string mode) {\n"
            "        var command = new SqlCommand();\n"
            "        command.CommandText = commandText;\n"
            "        command.Connection = _connection;\n"
            "        if (mode == \"SP\")\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", \"SP\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("PropertySetupFixture.cs", result["db_invocations"])

        assert len(invocations) == 1
        assert invocations[0].procedure_name == "usp_saveorder"
        assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_unavailable_wrapper_source_retains_literal_candidate_as_unresolved() -> None:
    """A missing wrapper implementation retains its literal target without proving the call."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        command_text="usp_SaveOrder",
        invocation_kind="source_wrapper",
        wrapper_source_available=False,
        wrapper_reaches_stored_procedure_sink=False,
        wrapper_mode="stored_procedure",
        connection_expression="conn",
    )

    invocations = gateway.resolve_direct_invocations("f.cs", [raw])

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].reason == "wrapper_source_unavailable"
    assert invocations[0].procedure_name == "usp_saveorder"
    assert invocations[0].raw_command_text == "usp_SaveOrder"


def test_external_wrapper_contract_proves_sqlobject_sp_mode_but_skips_inline_mode() -> None:
    """A trusted external contract supplies sink proof without requiring local wrapper source."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )

    sp_invocation = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            )
        ],
    )
    inline_invocation = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="SELECT * FROM SOrder",
                wrapper_method_name="CreateReader",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="inline_sql",
                command_type_stored_procedure=False,
                connection_expression="conn",
            )
        ],
    )

    assert len(sp_invocation) == 1
    assert sp_invocation[0].evidence is InvocationEvidence.PROVEN
    assert sp_invocation[0].procedure_name == "usp_saveorder"
    assert sp_invocation[0].external_wrapper_method == "ExeProcNon"
    assert inline_invocation == []


def test_external_wrapper_contract_auto_selects_unique_receiver_type() -> None:
    """A unique receiver-backed contract should not require system catalog wiring."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocations = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            )
        ],
    )

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.PROVEN
    assert invocations[0].wrapper_contract == "sqlobject"
    assert invocations[0].wrapper_contract_source == "auto_receiver_type"
    assert invocations[0].wrapper_receiver_type == "SQLObject"
    assert invocations[0].wrapper_contract_candidates == ("sqlobject",)


def test_external_wrapper_contract_ambiguity_stays_unresolved(monkeypatch) -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    monkeypatch.setattr(
        gateway_module,
        "external_wrapper_contract_candidates",
        lambda _receiver_type: [
            {"name": "sqlobject-v1", "receiver_types": ["SQLObject"]},
            {"name": "sqlobject-v2", "receiver_types": ["SQLObject"]},
        ],
    )

    invocations = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            )
        ],
    )

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].wrapper_contract == ""
    assert invocations[0].wrapper_contract_source == "ambiguous_receiver_type"
    assert invocations[0].wrapper_contract_candidates == (
        "sqlobject-v1",
        "sqlobject-v2",
    )


def test_external_wrapper_contract_does_not_apply_to_other_receiver_type() -> None:
    """A contract scoped to SQLObject must not prove an unrelated wrapper with the same method name."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )

    invocations = gateway.resolve_direct_invocations(
        "OtherPage.cs",
        [
            _raw_invocation(
                command_text="usp_SaveOrder",
                invocation_kind="source_wrapper",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="OtherDbObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            )
        ],
    )

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].reason == "wrapper_source_unavailable"


def test_external_wrapper_call_site_contract_requires_stored_procedure_mode() -> None:
    """A call-site wrapper is proven only when its invocation selects SP mode."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )

    invocations = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="CreateTable",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            ),
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="CreateTable",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="inline_sql",
                command_type_stored_procedure=False,
                connection_expression="conn",
            ),
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="CreateTable",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="unknown",
                connection_expression="conn",
            ),
        ],
    )

    assert len(invocations) == 2
    assert invocations[0].evidence is InvocationEvidence.PROVEN
    assert invocations[0].wrapper_contract == "sqlobject"
    assert invocations[1].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[1].reason == "wrapper_mode_unresolved"


def test_external_wrapper_create_dataset_call_site_contract_handles_all_modes() -> None:
    """CreateDataSet uses its call-site mode to distinguish SP and inline SQL."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )

    invocations = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="CreateDataSet",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="stored_procedure",
                connection_expression="conn",
            ),
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="SELECT * FROM SOrder",
                wrapper_method_name="CreateDataSet",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="inline_sql",
                command_type_stored_procedure=False,
                connection_expression="conn",
            ),
            _raw_invocation(
                invocation_kind="source_wrapper",
                command_text="usp_SaveOrder",
                wrapper_method_name="CreateDataSet",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_reaches_stored_procedure_sink=False,
                wrapper_mode="unknown",
                connection_expression="conn",
            ),
        ],
    )

    assert len(invocations) == 2
    assert invocations[0].evidence is InvocationEvidence.PROVEN
    assert invocations[0].external_wrapper_method == "CreateDataSet"
    assert invocations[0].wrapper_contract == "sqlobject"
    assert invocations[1].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[1].reason == "wrapper_mode_unresolved"


def test_inline_wrapper_mode_is_not_a_stored_procedure_invocation() -> None:
    """A source-backed wrapper selecting inline SQL is omitted from SP invocations."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="SELECT * FROM SOrder",
        command_type_stored_procedure=False,
        wrapper_source_available=True,
        wrapper_reaches_stored_procedure_sink=True,
        wrapper_mode="inline_sql",
        connection_expression="conn",
    )

    assert gateway.resolve_direct_invocations("f.cs", [raw]) == []


def test_static_analyzer_host_preserves_unavailable_wrapper_candidate() -> None:
    """A missing wrapper implementation leaves unresolved source evidence, never a proven call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "OrderPage.cs"
        source_path.write_text(
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var wrapper = GetExternalWrapper();\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "    private object GetExternalWrapper() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_source_available"] is False
        assert raw_invocations[0]["wrapper_mode"] == "stored_procedure"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("OrderPage.cs", raw_invocations)

        assert len(invocations) == 1
        assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
        assert invocations[0].reason == "wrapper_source_unavailable"
        assert invocations[0].procedure_name == "usp_saveorder"
        assert invocations[0].raw_command_text == "usp_SaveOrder"


def test_static_analyzer_host_ignores_ui_helpers_with_boolean_arguments() -> None:
    """UI helper flags must not be mistaken for external wrapper mode selectors."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "UiHelpers.cs"
        source_path.write_text(
            "public class UiHelpers {\n"
            "    private string ScriptText { get; }\n"
            "    private void Show(Page page, UpdatePanel panel) {\n"
            "        CommonFunction.AlertMsg(page, \"done\", true);\n"
            "        ScriptManager.RegisterStartupScript(panel, typeof(string), \"key\", \"alert(1)\", true);\n"
            "        ScriptManager.RegisterStartupScript(this.Page, typeof(string), \"key2\", \"alert(2)\", true);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)

        assert result["db_invocations"] == []


def test_static_analyzer_host_keeps_string_typed_unknown_wrapper_candidates() -> None:
    """String-typed dynamic command text remains eligible for wrapper review."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "DynamicWrapper.cs"
        source_path.write_text(
            "public class DynamicWrapper {\n"
            "    private void Save(string procedure) {\n"
            "        var wrapper = GetExternalWrapper();\n"
            "        wrapper.Execute(procedure, true);\n"
            "    }\n"
            "    private object GetExternalWrapper() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)

        assert len(result["db_invocations"]) == 1
        assert result["db_invocations"][0]["wrapper_mode"] == "stored_procedure"
        assert result["db_invocations"][0]["command_text_kind"] == "dynamic"


def test_static_analyzer_host_applies_external_sqlobject_wrapper_contract() -> None:
    """Known external SQLObject methods distinguish SP, inline SQL, and dynamic calls."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "SqlObjectPage.cs"
        source_path.write_text(
            "public class SqlObjectPage {\n"
            "    private void EnableData() {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.ExeProcNon(\"[dbo].[usp_Enable]\", null);\n"
            "    }\n"
            "    private void SaveData() {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.CreateTable(\"[dbo].[usp_Save]\", null, \"table\", \"SP\");\n"
            "    }\n"
            "    private void PreviewData() {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.CreateReader(\"SELECT * FROM SOrder\");\n"
            "    }\n"
            "    private void DynamicData(string procedure) {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.ExeProcRead(procedure, null);\n"
            "    }\n"
            "    private object GetExternalSqlObject() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            invocation
            for invocation in result["db_invocations"]
            if invocation.get("invocation_kind") == "source_wrapper"
        ]

        assert {invocation["method_name"] for invocation in raw_invocations} == {
            "EnableData",
            "SaveData",
            "DynamicData",
        }
        by_method = {invocation["method_name"]: invocation for invocation in raw_invocations}
        assert by_method["EnableData"]["wrapper_mode"] == "stored_procedure"
        assert by_method["EnableData"]["command_type_stored_procedure"] is True
        assert by_method["SaveData"]["wrapper_mode"] == "stored_procedure"
        assert by_method["SaveData"]["command_type_stored_procedure"] is True
        assert by_method["DynamicData"]["wrapper_mode"] == "stored_procedure"
        assert by_method["DynamicData"]["command_type_stored_procedure"] is True
        assert by_method["DynamicData"]["command_text_kind"] == "dynamic"
        assert by_method["DynamicData"]["command_text"] is None
        assert {
            invocation["wrapper_receiver_type"]
            for invocation in raw_invocations
        } == {"SQLObject"}

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Enable", "usp_Save"]}),
            connection_sources={"obj": "OrdersDb"},
        )
        observations = {
            invocation["method_name"]: gateway.reconcile_wrapper_observation(
                "SqlObjectPage.cs",
                invocation,
                scan_root=temp_dir,
            )
            for invocation in raw_invocations
        }
        assert observations["EnableData"]["wrapper_receiver_type"] == "SQLObject"
        assert observations["EnableData"]["wrapper_status"] == "auto_selected"
        assert observations["EnableData"]["evidence_status"] == "proven"
        assert observations["SaveData"]["wrapper_contract_mode"] == "call_site"
        assert observations["SaveData"]["stored_procedure_mode"] is True
        assert observations["SaveData"]["evidence_status"] == "proven"
        assert observations["DynamicData"]["wrapper_status"] == "auto_selected"
        assert observations["DynamicData"]["evidence_status"] == "unresolved"
        assert observations["DynamicData"]["evidence_reason"] == "dynamic_command_text"


if __name__ == "__main__":
    test_normalize_procedure_name_strips_schema_and_brackets()
    test_explicit_stored_procedure_type_with_catalog_hit_is_proven()
    test_inline_sql_without_stored_procedure_type_is_not_reported()
    test_dynamic_command_text_is_unresolved()
    test_resolved_database_without_catalog_hit_is_unresolved_not_guessed()
    test_unknown_connection_source_unique_across_catalogs_is_likely()
    test_unknown_connection_source_ambiguous_across_catalogs_is_unresolved()
    test_unknown_connection_source_and_unknown_name_is_unresolved()
    test_gateway_detects_real_direct_sqlclient_invocation_via_static_analyzer_host()
    print("CSharpAnalysisGateway tests passed")

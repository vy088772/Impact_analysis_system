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
    invocation_wrapper_evidence_fields,
    normalize_procedure_name,
    wrapper_observation_identity,
)
from code_analyzer.static_analyzer_host import StaticAnalyzerHost
import code_analyzer.static_analyzer_host as static_analyzer_host_module
import code_analyzer.csharp_analysis_gateway as gateway_module
from service.execution_path_builder import build_execution_paths


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
        "terminal_sink": "ExecuteNonQuery",
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
            receiver_implementation_identity="LocalWrapper",
            wrapper_source_available=True,
            wrapper_mode="stored_procedure",
            wrapper_method_semantics="fixed_stored_procedure",
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
    assert explicit.method_semantics == "fixed_stored_procedure"

    # A receiver type name alone cannot select a contract (spec item 70/168):
    # without an explicit contract selector, a matching receiver_types entry
    # is not enough -- this must stay an unresolved review candidate.
    no_auto_select = gateway.reconcile_wrapper(
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
    assert no_auto_select.status == "unresolved_contract"
    assert no_auto_select.selection_source == "unresolved_receiver_type"
    assert no_auto_select.contract == ""
    assert no_auto_select.review_candidate is True
    assert no_auto_select.reason == "no_contract_matches_receiver_type"

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
        explicit_contract=_sqlobject_wrapper_contract(),
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
    assert unknown_receiver.method_semantics == "unresolved"
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


def test_external_contract_without_explicit_selector_never_auto_selects_by_receiver_name() -> None:
    """auto_select and receiver-name inference are removed from the contract
    domain and runtime path (spec item 70): a registry entry whose
    receiver_types matches the observed receiver is never enough on its own
    -- only an explicit contract selector may choose a contract."""
    registry = {
        "vendor-one": {
            "name": "vendor-one",
            "receiver_types": ["Vendor.One.SQLObject"],
            "methods": {
                "Execute": {
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                }
            },
        }
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts=registry,
    )

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="Vendor.One.SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )
    reconciliation = gateway.reconcile_wrapper("f.cs", raw)

    assert reconciliation.status == "unresolved_contract"
    assert reconciliation.selection_source == "unresolved_receiver_type"
    assert reconciliation.reason == "no_contract_matches_receiver_type"
    assert reconciliation.candidate_contracts == ()
    assert gateway.resolve_direct_invocations("f.cs", [raw])[0].evidence is (
        InvocationEvidence.UNRESOLVED
    )


def test_receiver_binding_without_selector_never_auto_selects_registry_contract() -> None:
    """A concrete binding supplies provenance, not an implicit selector."""
    registry = {
        "vendor-one": {
            "name": "vendor-one",
            "receiver_types": ["Vendor.One.SQLObject"],
            "methods": {
                "Execute": {
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                }
            },
        }
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts=registry,
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="Vendor.One.SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
        receiver_binding={
            "implementation_identity": "Vendor.One.SQLObject",
            "assembly_identity": "Vendor.One",
            "assembly_revision": "1.0.0",
            "provenance": "verified_metadata",
        },
    )

    reconciliation = gateway.reconcile_wrapper("f.cs", raw)
    invocation = gateway.resolve_direct_invocations("f.cs", [raw])[0]

    assert reconciliation.status == "unresolved_contract"
    assert reconciliation.selection_source == "unresolved_receiver_type"
    assert reconciliation.contract == ""
    assert reconciliation.contract_mode == ""
    assert reconciliation.contract_sink == ""
    assert reconciliation.candidate_contracts == ()
    assert reconciliation.review_candidate is True
    assert reconciliation.active_contract is False
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.wrapper_contract == ""
    assert invocation.wrapper_status == "unresolved_contract"
    assert invocation.invocation_mode == "stored_procedure"
    matching_graph = {
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
                "module": {
                    "type": "stored_procedure",
                    "schema": "dbo",
                    "name": "usp_SaveOrder",
                },
                "sequence": 1,
                "operation_type": "UPDATE",
                "branch_path": [],
                "conditions": [],
                "read_tables": [],
                "write_tables": ["dbo.SOrder"],
                "written_columns": [],
            },
        ],
        "relationships": [
            {
                "type": "contains",
                "source": "stored_procedure:dbo.usp_SaveOrder",
                "target": "dml_operation:stored_procedure:dbo.usp_SaveOrder:1",
            }
        ],
    }
    paths = build_execution_paths([invocation], matching_graph)
    assert len(paths) == 1
    assert paths[0]["evidence"] == "unresolved"
    assert paths[0]["confirmed"] is False
    assert paths[0]["terminal_operation"] is None
    assert paths[0]["target"] == ""


def test_external_contract_explicit_selection_still_requires_exact_qualified_identity() -> None:
    """Once a contract is explicitly selected, its receiver_types must still
    match the observed receiver's exact qualified identity."""
    registry = {
        "vendor-one": {
            "name": "vendor-one",
            "receiver_types": ["Vendor.One.SQLObject"],
            "methods": {
                "Execute": {
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                }
            },
        }
    }
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts=registry,
    )

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="Vendor.Two.SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )
    reconciliation = gateway.reconcile_wrapper("f.cs", raw, explicit_contract="vendor-one")

    assert reconciliation.status == "receiver_mismatch"
    assert reconciliation.reason == "receiver_type_does_not_match_contract"


def test_wrapper_review_exclusion_marks_reviewed_non_wrapper_call_not_applicable() -> None:
    """A curated per-system exclusion list lets a human triage decision short-
    circuit contract classification for calls already confirmed to be ordinary
    framework methods (e.g. String.Format), not database wrapper calls."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={"sqlfunc": _sqlobject_wrapper_contract()},
        wrapper_review_exclusions=[
            {
                "receiver_type": "",
                "method_name": "Add",
                "reason": "framework_method_not_sqlfunc",
            }
        ],
    )

    reconciliation = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="Add",
            wrapper_receiver_type="",
            wrapper_source_available=False,
            wrapper_mode="unknown",
        ),
        explicit_contract="sqlfunc",
    )

    assert reconciliation.status == "not_applicable"
    assert reconciliation.reason == "framework_method_not_sqlfunc"
    assert reconciliation.review_candidate is False


def test_wrapper_review_exclusion_leaves_observation_evidence_not_applicable() -> None:
    """The exclusion decision must also flow through to the evidence rating so
    the wrapper summary stops counting the call as unresolved."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={"sqlfunc": _sqlobject_wrapper_contract()},
        wrapper_review_exclusions=[
            {
                "receiver_type": "",
                "method_name": "Add",
                "reason": "framework_method_not_sqlfunc",
            }
        ],
    )

    observation = gateway.reconcile_wrapper_observation(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="Add",
            wrapper_receiver_type="",
            wrapper_source_available=False,
            wrapper_mode="unknown",
        ),
        explicit_contract="sqlfunc",
    )

    assert observation["status"] == "not_applicable"
    assert observation["evidence_status"] == "not_applicable"
    assert observation["evidence_reason"] == "framework_method_not_sqlfunc"
    assert observation["review_candidate"] is False


def test_wrapper_review_exclusion_is_scoped_to_exact_receiver_and_method() -> None:
    """An exclusion keyed to an unknown receiver must not swallow a call whose
    receiver type is actually known and simply happens to share the method
    name -- exclusions are exact-match triage decisions, not name wildcards."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={"sqlfunc": _sqlobject_wrapper_contract()},
        wrapper_review_exclusions=[
            {
                "receiver_type": "",
                "method_name": "Add",
                "reason": "framework_method_not_sqlfunc",
            }
        ],
    )

    reconciliation = gateway.reconcile_wrapper(
        "OrderPage.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="Add",
            wrapper_receiver_type="Dictionary",
            wrapper_source_available=False,
            wrapper_mode="unknown",
        ),
        explicit_contract="sqlfunc",
    )

    assert reconciliation.status != "not_applicable"


def test_stc_wrapper_review_exclusions_are_loaded_from_repository_config() -> None:
    """Regression guard tying config/wrapper_review_exclusions.json to the
    loader: the reviewed STC framework-method false positives (Add, Write,
    FindControl, DataTable.Select, string.Replace, ...) must still resolve,
    and an unrelated system id must see no exclusions at all."""
    stc_exclusions = gateway_module.load_wrapper_review_exclusions("STC")
    normalized = gateway_module._normalize_wrapper_review_exclusions(stc_exclusions)

    assert normalized[("", "add")] == "reviewed_2026-08-14_not_sqlfunc_dictionary_or_collection_add"
    assert normalized[("", "findcontrol")]
    assert normalized[("datatable", "select")]
    assert normalized[("string", "replace")]

    assert gateway_module.load_wrapper_review_exclusions("PUR") == ()
    assert gateway_module.load_wrapper_review_exclusions("") == ()


def test_external_contract_without_receiver_identity_cannot_be_selected() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "incomplete",
        "methods": {
            "Execute": {
                "mode": "stored_procedure",
                "sink": "ExecuteNonQuery",
            }
        },
    }

    reconciliation = gateway.reconcile_wrapper(
        "f.cs",
        _raw_invocation(
            invocation_kind="source_wrapper",
            wrapper_method_name="Execute",
            wrapper_receiver_type="Vendor.One.SQLObject",
            wrapper_source_available=False,
            wrapper_mode="stored_procedure",
        ),
        explicit_contract=contract,
    )

    assert reconciliation.status == "receiver_mismatch"
    assert reconciliation.reason == "receiver_type_does_not_match_contract"


def test_external_contract_overloads_require_raw_signature_identity() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "overloaded",
        "receiver_types": ["SQLObject"],
        "methods": {
            "Execute": [
                {
                    "method_identity": "SQLObject.Execute(string)",
                    "arity": 1,
                    "parameter_types": ["string"],
                    "mode": "stored_procedure",
                    "sink": "ExecuteNonQuery",
                },
                {
                    "method_identity": "SQLObject.Execute(string, bool)",
                    "arity": 2,
                    "parameter_types": ["string", "bool"],
                    "mode": "inline_sql",
                    "sink": "ExecuteReader",
                },
            ]
        },
    }

    exact_raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
        wrapper_method_identity="SQLObject.Execute(string)",
        wrapper_method_arity=1,
        wrapper_parameter_types=["string"],
    )
    exact = gateway.reconcile_wrapper("f.cs", exact_raw, explicit_contract=contract)
    assert exact.status == "explicit_selected"
    assert exact.contract_mode == "stored_procedure"
    assert exact.method_semantics == "fixed_stored_procedure"

    ambiguous_raw = dict(exact_raw)
    ambiguous_raw.pop("wrapper_method_identity")
    ambiguous_raw.pop("wrapper_method_arity")
    ambiguous_raw.pop("wrapper_parameter_types")
    ambiguous = gateway.reconcile_wrapper(
        "f.cs",
        ambiguous_raw,
        explicit_contract=contract,
    )
    assert ambiguous.status == "ambiguous_overload"
    assert ambiguous.reason == "ambiguous_overload"
    assert ambiguous.overload_candidates == (
        "SQLObject.Execute(string)",
        "SQLObject.Execute(string, bool)",
    )

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [ambiguous_raw],
        explicit_contract=contract,
    )[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "ambiguous_overload"
    assert invocation.overload_candidates == ambiguous.overload_candidates


def _sqlfunc_createreader_contract() -> dict:
    """Mirrors the real sqlfunc contract's CreateReader overload set: two
    arity-2 siblings differing only in SqlParameter vs SqlParameter[], both
    running the exact same inline_sql -> ExecuteReader semantics."""
    return {
        "name": "sqlfunc",
        "receiver_types": ["SQLFunc"],
        "methods": {
            "CreateReader": [
                {
                    "method_identity": "sqlfunc.createreader(string)",
                    "arity": 1,
                    "parameter_types": ["string"],
                    "mode": "inline_sql",
                    "sink": "ExecuteReader",
                },
                {
                    "method_identity": "sqlfunc.createreader(string,system.data.sqlclient.sqlparameter)",
                    "arity": 2,
                    "parameter_types": ["string", "system.data.sqlclient.sqlparameter"],
                    "mode": "inline_sql",
                    "sink": "ExecuteReader",
                },
                {
                    "method_identity": "sqlfunc.createreader(string,system.data.sqlclient.sqlparameter[])",
                    "arity": 2,
                    "parameter_types": ["string", "system.data.sqlclient.sqlparameter[]"],
                    "mode": "inline_sql",
                    "sink": "ExecuteReader",
                },
            ]
        },
    }


def test_ambiguous_overload_still_rates_evidence_when_candidates_share_mode_and_sink() -> None:
    """CreateReader's SqlParameter vs SqlParameter[] siblings can't be told
    apart from an arity-2 call site alone, but both run the exact same
    command text through the exact same sink -- so the database evidence
    should still be ratable, while the exact overload identity stays a
    visible review fact rather than silently disappearing."""
    catalog = SpCatalog.from_databases({"STC": []})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "STC"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="select CompanyCode,CompanyTitle from YMTTCompany order by CompanyTitle",
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLFunc",
        wrapper_source_available=False,
        wrapper_mode="inline_sql",
        wrapper_method_arity=2,
        terminal_sink="ExecuteReader",
        connection_expression="conn",
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_sqlfunc_createreader_contract()
    )
    assert reconciliation.status == "ambiguous_overload"
    assert reconciliation.reason == "ambiguous_overload_mode_resolved"
    assert reconciliation.contract_mode == "inline_sql"
    assert reconciliation.contract_sink == "ExecuteReader"
    assert "sqlfunc.createreader(string,system.data.sqlclient.sqlparameter)" in (
        reconciliation.overload_candidates
    )
    assert "sqlfunc.createreader(string,system.data.sqlclient.sqlparameter[])" in (
        reconciliation.overload_candidates
    )
    assert reconciliation.review_candidate is True

    invocation = gateway.resolve_direct_invocations(
        "f.cs", [raw], explicit_contract=_sqlfunc_createreader_contract()
    )[0]
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.wrapper_status == "ambiguous_overload"
    assert invocation.wrapper_unresolved_reason == "ambiguous_overload_mode_resolved"


def _sqlfunc_createreader_contract_with_assembly() -> dict:
    """`_sqlfunc_createreader_contract` plus the Implementation Snapshot assembly identity a
    real decompiled contract carries -- ticket 06's symbol acceptance rule checks a bound
    symbol's own containing assembly against exactly this field."""
    contract = _sqlfunc_createreader_contract()
    contract["implementation_snapshots"] = [{"assembly_identity": "sqlfunc-dll-sha256-fixture"}]
    return contract


def test_semantic_bound_method_facts_rejects_mismatched_assembly() -> None:
    """`_semantic_bound_method_facts` is the one shared gate both the primary contract match
    and the multi-contract-name disambiguation loop use to decide whether to trust a bound
    identity -- test it directly so a future change to either call site can't quietly stop
    routing through the same acceptance rule."""
    raw = _raw_invocation(
        wrapper_method_identity="SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])",
        wrapper_parameter_types=["string", "System.Data.SqlClient.SqlParameter[]"],
        wrapper_assembly_identity="real-dll-hash",
    )
    method_facts = gateway_module._wrapper_method_facts(raw)

    identity, parameter_types, accepted = gateway_module._semantic_bound_method_facts(
        raw, method_facts, {"assembly_identity": "real-dll-hash"}
    )
    assert accepted is True
    assert identity == "SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])"
    assert parameter_types == ("string", "System.Data.SqlClient.SqlParameter[]")

    identity, parameter_types, accepted = gateway_module._semantic_bound_method_facts(
        raw, method_facts, {"assembly_identity": "unrelated-dll-hash"}
    )
    assert accepted is False
    assert identity == ""
    assert parameter_types == ()

    # No bound identity at all (the compiler never resolved a symbol, or no semantic model
    # was available): never accepted, regardless of the contract's assembly identity.
    unbound_raw = _raw_invocation(wrapper_method_identity="", wrapper_assembly_identity="")
    identity, parameter_types, accepted = gateway_module._semantic_bound_method_facts(
        unbound_raw,
        gateway_module._wrapper_method_facts(unbound_raw),
        {"assembly_identity": "real-dll-hash"},
    )
    assert accepted is False
    assert identity == ""


def test_semantic_binding_resolves_bound_method_identity_to_one_overload() -> None:
    """Ticket 06: once the compiler binds a call to one exact method symbol -- reported as
    wrapper_method_identity/wrapper_parameter_types, alongside the bound symbol's own assembly
    identity -- the contract match uses that identity instead of arity alone, so CreateReader's
    SqlParameter[] sibling stops being an unresolvable review candidate."""
    catalog = SpCatalog.from_databases({"STC": []})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "STC"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="select CompanyCode,CompanyTitle from YMTTCompany order by CompanyTitle",
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLFunc",
        wrapper_source_available=False,
        wrapper_mode="inline_sql",
        wrapper_method_arity=2,
        wrapper_method_identity="SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])",
        wrapper_parameter_types=["string", "System.Data.SqlClient.SqlParameter[]"],
        wrapper_assembly_identity="sqlfunc-dll-sha256-fixture",
        terminal_sink="ExecuteReader",
        connection_expression="conn",
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_sqlfunc_createreader_contract_with_assembly()
    )
    assert reconciliation.status == "explicit_selected"
    assert reconciliation.reason == ""
    assert reconciliation.review_candidate is False
    assert reconciliation.contract_mode == "inline_sql"
    assert reconciliation.contract_sink == "ExecuteReader"

    invocation = gateway.resolve_direct_invocations(
        "f.cs", [raw], explicit_contract=_sqlfunc_createreader_contract_with_assembly()
    )[0]
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.wrapper_status == "explicit_selected"


def test_semantic_binding_falls_back_when_no_symbol_was_resolved() -> None:
    """Ticket 06: a call whose symbol the compiler could not resolve (or for which no
    semantic model was available) carries no wrapper_method_identity at all, and lands
    exactly where it did before this ticket -- an arity-2 call still can't tell CreateReader's
    SqlParameter vs SqlParameter[] siblings apart from argument count alone."""
    catalog = SpCatalog.from_databases({"STC": []})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "STC"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLFunc",
        wrapper_source_available=False,
        wrapper_mode="inline_sql",
        wrapper_method_arity=2,
        terminal_sink="ExecuteReader",
        connection_expression="conn",
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_sqlfunc_createreader_contract_with_assembly()
    )
    assert reconciliation.status == "ambiguous_overload"
    assert reconciliation.reason == "ambiguous_overload_mode_resolved"


def test_semantic_binding_rejects_symbol_from_unexpected_assembly() -> None:
    """Ticket 06 symbol acceptance rule: a bound symbol whose own containing assembly differs
    from the assembly identity the contract records is never adopted. The call falls back to
    the argument-count path exactly as if the compiler had not resolved a symbol at all --
    this system refuses to guess even when the compiler handed it a name."""
    catalog = SpCatalog.from_databases({"STC": []})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "STC"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLFunc",
        wrapper_source_available=False,
        wrapper_mode="inline_sql",
        wrapper_method_arity=2,
        wrapper_method_identity="SQLFunc.CreateReader(string,System.Data.SqlClient.SqlParameter[])",
        wrapper_parameter_types=["string", "System.Data.SqlClient.SqlParameter[]"],
        wrapper_assembly_identity="a-different-assembly-entirely",
        terminal_sink="ExecuteReader",
        connection_expression="conn",
    )

    reconciliation = gateway.reconcile_wrapper(
        "f.cs", raw, explicit_contract=_sqlfunc_createreader_contract_with_assembly()
    )
    assert reconciliation.status == "ambiguous_overload"
    assert reconciliation.reason == "ambiguous_overload_mode_resolved"

    invocation = gateway.resolve_direct_invocations(
        "f.cs", [raw], explicit_contract=_sqlfunc_createreader_contract_with_assembly()
    )[0]
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.wrapper_status == "ambiguous_overload"


def test_external_contract_single_signatureless_method_stays_unresolved_against_specific_overload() -> None:
    """A contract's lone signature-less method entry must not silently match a raw call
    whose facts already reveal a specific arity/parameter overload."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "sqlobject",
        "receiver_types": ["SQLObject"],
        "methods": {
            "Execute": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"},
        },
    }

    # No observed signature at all: nothing to contradict the lone entry, so it may still apply.
    unqualified_raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )
    unqualified = gateway.reconcile_wrapper("f.cs", unqualified_raw, explicit_contract=contract)
    assert unqualified.status == "explicit_selected"
    assert unqualified.contract_mode == "stored_procedure"

    # Observed facts reveal a specific 2-arg overload the signature-less entry cannot confirm.
    specific_raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
        wrapper_method_arity=2,
        wrapper_parameter_types=["string", "bool"],
    )
    specific = gateway.reconcile_wrapper("f.cs", specific_raw, explicit_contract=contract)
    assert specific.status == "ambiguous_overload"
    assert specific.reason == "ambiguous_overload"

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [specific_raw],
        explicit_contract=contract,
    )[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "ambiguous_overload"


def test_ambiguous_source_overload_retains_structured_candidate_facts() -> None:
    """Ambiguous source overload candidates keep bound implementation, receiver type,
    method name, arity, and parameter types as structured facts, not opaque identity
    strings, so downstream review/grouping can still reason about them."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="IndexedOverloadWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        wrapper_overload_ambiguous=True,
        wrapper_overload_candidates=[
            {
                "method_identity": "IndexedOverloadWrapper.Execute(string, string)",
                "implementation_identity": "IndexedOverloadWrapper",
                "receiver_type": "IndexedOverloadWrapper",
                "method_name": "Execute",
                "method_arity": 2,
                "parameter_types": ["string", "string"],
            },
            {
                "method_identity": "IndexedOverloadWrapper.Execute(object, object)",
                "implementation_identity": "IndexedOverloadWrapper",
                "receiver_type": "IndexedOverloadWrapper",
                "method_name": "Execute",
                "method_arity": 2,
                "parameter_types": ["object", "object"],
            },
        ],
    )

    reconciliation = gateway.reconcile_wrapper("f.cs", raw)
    assert reconciliation.status == "ambiguous_overload"
    expected_facts = (
        {
            "method_identity": "IndexedOverloadWrapper.Execute(string, string)",
            "implementation_identity": "IndexedOverloadWrapper",
            "receiver_type": "IndexedOverloadWrapper",
            "method_name": "Execute",
            "method_arity": 2,
            "parameter_types": ("string", "string"),
        },
        {
            "method_identity": "IndexedOverloadWrapper.Execute(object, object)",
            "implementation_identity": "IndexedOverloadWrapper",
            "receiver_type": "IndexedOverloadWrapper",
            "method_name": "Execute",
            "method_arity": 2,
            "parameter_types": ("object", "object"),
        },
    )
    assert reconciliation.overload_candidate_facts == expected_facts

    invocation = gateway.resolve_direct_invocations("f.cs", [raw])[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.overload_candidate_facts == expected_facts
    assert invocation.wrapper_overload_candidate_facts == expected_facts


def test_wrapper_reconciliation_boundary_keeps_ambiguity_and_mode_rules_machine_readable() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    # Ambiguity is still detectable through an explicit multi-name selector
    # (a caller-provided binding) -- not through receiver-name auto-select,
    # which is removed from the contract domain and runtime path.
    ambiguous_registry = {
        "sqlobject-v1": {
            "name": "sqlobject-v1",
            "receiver_types": ["SQLObject"],
            "methods": {"ExeProcNon": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}},
        },
        "sqlobject-v2": {
            "name": "sqlobject-v2",
            "receiver_types": ["SQLObject"],
            "methods": {"ExeProcNon": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}},
        },
    }
    ambiguous_gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts=ambiguous_registry,
    )
    ambiguous_raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="ExeProcNon",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
    )
    ambiguous = ambiguous_gateway.reconcile_wrapper(
        "SqlObjectPage.cs",
        ambiguous_raw,
        explicit_contract=("sqlobject-v1", "sqlobject-v2"),
    )
    assert ambiguous.status == "ambiguous_contract"
    assert ambiguous.candidate_contracts == ("sqlobject-v1", "sqlobject-v2")
    assert ambiguous.review_candidate is True
    assert ambiguous.active_contract is False
    assert ambiguous.reason == "multiple_contracts_match_receiver_type"

    ambiguous_invocation = ambiguous_gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [ambiguous_raw],
        explicit_contract=("sqlobject-v1", "sqlobject-v2"),
    )[0]
    assert ambiguous_invocation.evidence is InvocationEvidence.UNRESOLVED
    assert ambiguous_invocation.wrapper_review_candidate is True
    assert ambiguous_invocation.wrapper_unresolved_reason == (
        "multiple_contracts_match_receiver_type"
    )

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
        explicit_contract="sqlobject",
    )[0]
    assert proven.evidence is InvocationEvidence.PROVEN
    assert proven.wrapper_kind == "external_wrapper"
    assert proven.wrapper_status == "explicit_selected"
    assert proven.wrapper_classification_status == "explicit_selected"
    assert proven.wrapper_selection_source == "explicit"
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


def test_stored_procedure_projection_separates_execution_and_evidence_fields() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [_raw_invocation(command_text="dbo.usp_SaveOrder")],
    )[0]
    projected = invocation_wrapper_evidence_fields(invocation)

    assert projected["connection_expression"] == "conn"
    assert projected["connection_source"] == "OrdersDb"
    assert projected["invocation_mode"] == "stored_procedure"
    assert projected["procedure_name"] == "usp_saveorder"
    assert projected["terminal_sink"] == "ExecuteNonQuery"
    assert projected["evidence"] == "proven"
    assert projected["evidence_status"] == "proven"


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


def test_inline_sql_without_stored_procedure_type_is_a_database_invocation() -> None:
    """A direct SqlCommand text call keeps its execution evidence without becoming an SP."""
    catalog = SpCatalog.from_databases({"Y-Docs_TTPUR": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "Y-Docs_TTPUR"})

    raw = _raw_invocation(
        invocation_kind="direct_sqlclient",
        command_text="SELECT * FROM SOrder",
        command_type_stored_procedure=False,
        receiver_type="SqlCommand",
        receiver_name="cmd",
        command_text_argument='"SELECT * FROM SOrder"',
        command_text_literal="SELECT * FROM SOrder",
        terminal_sink="ExecuteReader",
    )
    invocations = gateway.resolve_direct_invocations("Ship/PUR_SOMaintain.aspx.cs", [raw])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.method_semantics == "fixed_inline_sql"
    assert invocation.invocation_mode == "inline_sql"
    assert invocation.command_text_kind == "literal"
    assert invocation.raw_command_text == "SELECT * FROM SOrder"
    assert invocation.procedure_name is None
    assert invocation.terminal_sink == "ExecuteReader"
    assert invocation.connection_expression == "conn"
    assert invocation.connection_source == "Y-Docs_TTPUR"
    assert invocation.receiver_type == "SqlCommand"
    assert invocation.receiver_name == "cmd"
    assert invocation.command_text_argument == '"SELECT * FROM SOrder"'
    assert invocation.provenance == "static_analyzer_host"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.reason == "inline_sql"
    assert invocation.source.start_offset == 10
    assert invocation.source.end_offset == 90

    projected = invocation_wrapper_evidence_fields(invocation)
    assert projected["method_semantics"] == "fixed_inline_sql"
    assert projected["invocation_mode"] == "inline_sql"
    assert projected["command_text_kind"] == "literal"
    assert projected["command_text_argument"] == '"SELECT * FROM SOrder"'
    assert projected["literal_value"] == "SELECT * FROM SOrder"
    assert projected["terminal_sink"] == "ExecuteReader"
    assert projected["connection_expression"] == "conn"
    assert projected["connection_source"] == "Y-Docs_TTPUR"
    assert projected["provenance"] == "static_analyzer_host"


def test_literal_sql_operations_remain_inline_even_when_the_text_looks_like_an_sp() -> None:
    """Text mode owns the classification; SQL shape and procedure prefixes do not promote it to SP."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    sql_statements = [
        "SELECT * FROM SOrder",
        "INSERT INTO SOrder (OrderNo) VALUES ('A1')",
        "UPDATE SOrder SET Status = 1",
        "DELETE FROM SOrder WHERE OrderNo = 'A1'",
        "usp_SaveOrder",
    ]

    invocations = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text=statement,
                command_type_stored_procedure=False,
                terminal_sink="ExecuteNonQuery",
            )
            for statement in sql_statements
        ],
    )

    assert len(invocations) == len(sql_statements)
    assert [invocation.invocation_mode for invocation in invocations] == [
        "inline_sql"
    ] * len(sql_statements)
    assert [invocation.raw_command_text for invocation in invocations] == sql_statements
    assert all(invocation.procedure_name is None for invocation in invocations)
    assert all(invocation.evidence is InvocationEvidence.PROVEN for invocation in invocations)


def test_inline_exec_keeps_inline_mode_and_rates_embedded_target_separately() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="\n/* generated */\nEXEC dbo.usp_SaveOrder @OrderId",
                command_type_stored_procedure=False,
                command_type_mode="text",
                terminal_sink="ExecuteNonQuery",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.procedure_name is None
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.procedure_name == "usp_saveorder"
    assert invocation.embedded_procedure_target.procedure_schema == "dbo"
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.PROVEN
    assert invocation_wrapper_evidence_fields(invocation)["embedded_target"]["evidence"] == "proven"


def test_inline_sql_records_top_level_exec_target_after_another_statement() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="SELECT 1; EXEC dbo.usp_SaveOrder @OrderId",
                command_type_stored_procedure=False,
                command_type_mode="text",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.procedure_name == "usp_saveorder"


def test_leading_sql_comments_keep_known_text_statements_inline() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    statements = [
        "\n-- generated\nSELECT * FROM SOrder",
        "/* generated */ INSERT INTO SOrder (OrderNo) VALUES ('A1')",
        "/* generated */ UPDATE SOrder SET Status = 1",
        "-- generated\nDELETE FROM SOrder WHERE OrderNo = 'A1'",
        "/* generated */ MERGE SOrder AS target USING SOrderStage AS source ON 1 = 0;",
    ]

    invocations = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            {
                **_raw_invocation(command_text=statement),
                "command_type_stored_procedure": None,
                "command_type_mode": "",
            }
            for statement in statements
        ],
    )

    assert [invocation.invocation_mode for invocation in invocations] == [
        "inline_sql"
    ] * len(statements)
    assert all(invocation.evidence is InvocationEvidence.PROVEN for invocation in invocations)


def test_procedure_shaped_text_without_mode_is_only_a_weak_hint() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(command_text="usp_SaveOrder")
    raw.pop("command_type_stored_procedure")
    raw.pop("command_type_mode", None)

    invocation = gateway.resolve_direct_invocations("OrderPage.cs", [raw])[0]

    assert invocation.invocation_mode == "unresolved"
    assert invocation.procedure_name is None
    assert invocation.procedure_name_hint == "usp_saveorder"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "procedure_prefix_without_mode"


def test_command_text_candidate_preserves_value_span_and_provenance() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="usp_SaveOrder",
                command_text_source_span={
                    "relative_path": "OrderPage.cs",
                    "start_offset": 120,
                    "end_offset": 151,
                },
                command_text_provenance="assignment:procedure = \"usp_SaveOrder\"",
                branch_context=["if (useSave)"],
            )
        ],
    )[0]

    assert invocation.source.start_offset == 10
    assert invocation.command_text_source is not None
    assert invocation.command_text_source.start_offset == 120
    assert invocation.command_text_source.end_offset == 151
    assert invocation.command_text_provenance == (
        'assignment:procedure = "usp_SaveOrder"'
    )
    projected = invocation_wrapper_evidence_fields(invocation)
    assert projected["command_text_source_span"]["start_offset"] == 120
    assert projected["command_text_provenance"] == (
        'assignment:procedure = "usp_SaveOrder"'
    )


def test_gateway_expands_finite_command_text_candidates_without_losing_branches() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Default", "usp_Alternate"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        command_text=None,
        command_text_kind="candidate_set",
        command_text_candidates=[
            {
                "command_text": "usp_Default",
                "command_text_kind": "literal",
                "branch_context": [],
                "source_span": {
                    "relative_path": "OrderPage.cs",
                    "start_offset": 120,
                    "end_offset": 151,
                },
                "command_text_provenance": "declaration:procedure = \"usp_Default\"",
            },
            {
                "command_text": "usp_Alternate",
                "command_text_kind": "literal",
                "branch_context": ["if (useAlternate)"],
                "source_span": {
                    "relative_path": "OrderPage.cs",
                    "start_offset": 180,
                    "end_offset": 219,
                },
                "command_text_provenance": "assignment:procedure = \"usp_Alternate\"",
            },
        ],
    )

    invocations = gateway.resolve_direct_invocations("OrderPage.cs", [raw])

    assert [invocation.procedure_name for invocation in invocations] == [
        "usp_default",
        "usp_alternate",
    ]
    assert [invocation.branch_context for invocation in invocations] == [
        (),
        ("if (useAlternate)",),
    ]
    assert [invocation.command_text_provenance for invocation in invocations] == [
        'declaration:procedure = "usp_Default"',
        'assignment:procedure = "usp_Alternate"',
    ]


def test_incomplete_command_text_candidate_stays_unresolved() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        command_text=None,
        command_text_kind="candidate_set",
        command_text_candidates=["usp_SaveOrder"],
    )

    invocation = gateway.resolve_direct_invocations("OrderPage.cs", [raw])[0]

    assert invocation.procedure_name is None
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "dynamic_command_text"
    assert invocation.command_text_provenance == "candidate_provenance_incomplete"


def test_inline_exec_target_keeps_catalog_miss_separate_from_inline_evidence() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_OtherOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="EXECUTE dbo.usp_SaveOrder @OrderId",
                command_type_stored_procedure=False,
                command_type_mode="text",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.embedded_procedure_target.reason == "not_in_resolved_catalog"
    assert invocation.reason == "inline_sql"


def test_inline_exec_target_is_preserved_when_terminal_sink_is_unresolved() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="EXEC dbo.usp_SaveOrder @OrderId",
                command_type_stored_procedure=False,
                command_type_mode="text",
                terminal_sink="",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "terminal_sink_unresolved"
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.PROVEN


def test_dynamic_inline_exec_target_remains_unresolved_without_a_fabricated_name() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="EXEC(@commandText)",
                command_type_stored_procedure=False,
                command_type_mode="text",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.procedure_name is None
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.embedded_procedure_target.reason == "embedded_exec_target_dynamic"


def test_external_text_wrapper_keeps_inline_exec_target_as_additional_evidence() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_source_available=False,
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLObject",
        wrapper_mode="inline_sql",
        command_type_stored_procedure=False,
        command_type_mode="text",
        connection_expression="conn",
        command_text="EXEC dbo.usp_SaveOrder @OrderId",
        terminal_sink="ExecuteReader",
    )

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [raw],
        explicit_contract=_sqlobject_wrapper_contract(),
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.procedure_name is None
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.procedure_name == "usp_saveorder"
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.PROVEN


def test_adapter_text_exec_is_retained_as_inline_invocation() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="dapper",
        adapter_mode="inline_sql",
        wrapper_mode="inline_sql",
        command_type_stored_procedure=False,
        command_type_mode="text",
        command_text="EXEC dbo.usp_SaveOrder @OrderId",
        terminal_sink="ExecuteReader",
    )

    invocation = gateway.resolve_direct_invocations("OrderPage.cs", [raw])[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.procedure_name is None
    assert invocation.evidence is InvocationEvidence.PROVEN
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.procedure_name == "usp_saveorder"


def test_inline_wrapper_target_survives_missing_contract_sink() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["dbo.usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "text-only-contract",
        "receiver_types": ["SQLObject"],
        "methods": {"CreateReader": {"mode": "inline_sql"}},
    }
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_source_available=False,
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLObject",
        wrapper_mode="inline_sql",
        command_text="EXEC dbo.usp_SaveOrder @OrderId",
        command_type_stored_procedure=False,
        command_type_mode="text",
        terminal_sink="",
        connection_expression="conn",
    )

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [raw],
        explicit_contract=contract,
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "wrapper_contract_sink_unresolved"
    assert invocation.embedded_procedure_target is not None
    assert invocation.embedded_procedure_target.evidence is InvocationEvidence.PROVEN


def test_direct_inline_sql_without_a_terminal_sink_remains_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_text="SELECT * FROM SOrder",
                command_type_stored_procedure=False,
                terminal_sink="",
            )
        ],
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.raw_command_text == "SELECT * FROM SOrder"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "terminal_sink_unresolved"


def test_direct_stored_procedure_without_an_explicit_terminal_sink_remains_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_type_stored_procedure=True,
                command_text="usp_SaveOrder",
                terminal_sink="",
            )
        ],
    )[0]

    assert invocation.procedure_name is None
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "terminal_sink_unresolved"


def test_direct_stored_procedure_without_terminal_sink_fact_remains_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    raw = _raw_invocation(command_text="usp_SaveOrder")
    raw.pop("terminal_sink")

    invocation = gateway.resolve_direct_invocations("OrderPage.cs", [raw])[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "terminal_sink_unresolved"


def test_direct_stored_procedure_with_blank_terminal_sink_fact_remains_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [_raw_invocation(command_text="usp_SaveOrder", terminal_sink="   ")],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "terminal_sink_unresolved"


def test_direct_stored_procedure_with_incomplete_literal_command_text_is_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [_raw_invocation(command_text="   ")],
    )[0]

    assert invocation.procedure_name is None
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "dynamic_command_text"


def test_unknown_direct_command_type_remains_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [
            _raw_invocation(
                command_type_stored_procedure=False,
                command_type_mode="unknown",
                command_text="SELECT * FROM SOrder",
            )
        ],
    )[0]

    assert invocation.method_semantics == "unresolved"
    assert invocation.invocation_mode == "unresolved"
    assert invocation.command_type_mode == "unknown"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "command_type_unresolved"


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


def test_adapter_stored_procedure_preserves_common_invocation_metadata() -> None:
    """Adapter SP calls retain the same mode, sink, and command facts as direct calls."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw_invocations = [
        _raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="dapper",
            wrapper_mode="stored_procedure",
            terminal_sink="ExecuteNonQuery",
        ),
        _raw_invocation(
            command_text="usp_SaveOrder",
            invocation_kind="entity_framework",
            wrapper_mode="stored_procedure",
            terminal_sink="ExecuteNonQuery",
        ),
    ]

    invocations = gateway.resolve_direct_invocations("f.cs", raw_invocations)

    assert [
        (
            invocation.invocation_mode,
            invocation.method_semantics,
            invocation.command_type_mode,
            invocation.terminal_sink,
            invocation.procedure_name,
            invocation.evidence,
        )
        for invocation in invocations
    ] == [
        (
            "stored_procedure",
            "fixed_stored_procedure",
            "stored_procedure",
            "ExecuteNonQuery",
            "usp_saveorder",
            InvocationEvidence.PROVEN,
        ),
        (
            "stored_procedure",
            "fixed_stored_procedure",
            "stored_procedure",
            "ExecuteNonQuery",
            "usp_saveorder",
            InvocationEvidence.PROVEN,
        ),
    ]


def test_direct_and_adapter_unknown_terminal_sinks_stay_unresolved() -> None:
    """Only the shared terminal-sink vocabulary can produce rated invocations."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    invocations = gateway.resolve_direct_invocations(
        "f.cs",
        [
            _raw_invocation(
                command_text="usp_SaveOrder",
                terminal_sink="ExecuteMystery",
            ),
            _raw_invocation(
                command_text="usp_SaveOrder",
                invocation_kind="dapper",
                wrapper_mode="stored_procedure",
                terminal_sink="ExecuteMystery",
            ),
            _raw_invocation(
                command_text="usp_SaveOrder",
                invocation_kind="dapper",
                wrapper_mode="unknown",
                command_type_stored_procedure=True,
                terminal_sink="ExecuteNonQuery",
            ),
        ],
    )

    assert [invocation.evidence for invocation in invocations] == [
        InvocationEvidence.UNRESOLVED,
        InvocationEvidence.UNRESOLVED,
        InvocationEvidence.UNRESOLVED,
    ]
    assert [invocation.reason for invocation in invocations] == [
        "terminal_sink_unresolved",
        "terminal_sink_unresolved",
        "adapter_mode_unresolved",
    ]


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


def test_resolved_connection_source_scopes_same_named_procedure_to_one_catalog() -> None:
    catalog = SpCatalog.from_databases({
        "OrdersDb": ["usp_SaveOrder"],
        "ArchiveDb": ["usp_ArchiveOrder"],
    })
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "ArchiveDb"})

    invocation = gateway.resolve_direct_invocations(
        "OrderPage.cs",
        [_raw_invocation(command_text="usp_SaveOrder")],
    )[0]

    assert invocation.database == "ArchiveDb"
    assert invocation.database_candidates == ()
    assert invocation.procedure_name == "usp_saveorder"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "not_in_resolved_catalog"


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


def test_explicit_null_connection_source_stays_unresolved_even_when_catalog_is_unique() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [_raw_invocation(connection_expression=None)],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "connection_source_unresolved"
    assert invocation.database is None
    assert invocation.database_candidates == ("OrdersDb",)


def test_multiple_connection_candidates_stay_unresolved_when_catalog_is_unique() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SO_Delete"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={})

    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [
            _raw_invocation(
                connection_expression=None,
                connection_expression_candidates=(
                    "method:Run:orders",
                    "method:Run:audit",
                ),
            )
        ],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "ambiguous_connection_source"
    assert invocation.database is None
    assert invocation.database_candidates == ("OrdersDb",)


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

        assert len(invocations) == 2
        stored_procedure, inline_sql = invocations
        assert stored_procedure.evidence is InvocationEvidence.PROVEN
        assert stored_procedure.procedure_name == "usp_dothing"
        assert stored_procedure.database == "MyDb"
        assert inline_sql.invocation_mode == "inline_sql"
        assert inline_sql.raw_command_text == "SELECT * FROM Foo"
        assert inline_sql.procedure_name is None
        assert inline_sql.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_recognizes_numeric_command_type_cast_as_stored_procedure() -> None:
    """A `(CommandType)4` cast is recognized the same as `CommandType.StoredProcedure`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NumericCommandType.cs"
        source_path.write_text(
            "public class NumericCommandType {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"usp_DoThing\", conn);\n"
            "        cmd.CommandType = (CommandType)4;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_stored_procedure"] is True
        assert raw_invocations[0]["command_type_mode"] == "stored_procedure"


def test_static_analyzer_host_recognizes_numeric_command_type_cast_as_table_direct() -> None:
    """A `(CommandType)512` cast resolves to `TableDirect` and is never misclassified as stored-procedure or text."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NumericTableDirectCommandType.cs"
        source_path.write_text(
            "public class NumericTableDirectCommandType {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"Foo\", conn);\n"
            "        cmd.CommandType = (CommandType)512;\n"
            "        cmd.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_stored_procedure"] is False
        assert raw_invocations[0]["command_type_mode"] == "unknown"


def test_static_analyzer_host_recognizes_numeric_command_type_cast_as_text() -> None:
    """A `(CommandType)1` cast is recognized the same as `CommandType.Text`."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NumericTextCommandType.cs"
        source_path.write_text(
            "public class NumericTextCommandType {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM Foo\", conn);\n"
            "        cmd.CommandType = (CommandType)1;\n"
            "        cmd.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_stored_procedure"] is False
        assert raw_invocations[0]["command_type_mode"] == "text"


def test_static_analyzer_host_treats_unmapped_numeric_command_type_cast_as_unresolved() -> None:
    """A numeric cast with no defined mapping (e.g. `(CommandType)999`) stays unresolved."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "UnmappedNumericCommandType.cs"
        source_path.write_text(
            "public class UnmappedNumericCommandType {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"usp_DoThing\", conn);\n"
            "        cmd.CommandType = (CommandType)999;\n"
            "        cmd.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_stored_procedure"] is False
        assert raw_invocations[0]["command_type_mode"] == "unknown"


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
        assert all(
            invocation["command_text_source_start_offset"] is not None
            and invocation["command_text_source_end_offset"] is not None
            and invocation["command_text_provenance"]
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
            item["wrapper_mode"] == "inline_sql"
            and item["command_text"] == "EXEC dbo.usp_SaveOrder @Id"
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
        assert all(invocation.procedure_name != "usp_unknown" for invocation in invocations)
        entity_exec = next(
            invocation
            for invocation in invocations
            if invocation.method_name == "EntityFramework"
            and invocation.raw_command_text == "EXEC dbo.usp_SaveOrder @Id"
        )
        assert entity_exec.invocation_mode == "inline_sql"
        assert entity_exec.procedure_name is None
        assert entity_exec.evidence is InvocationEvidence.PROVEN
        assert entity_exec.embedded_procedure_target is not None
        assert entity_exec.embedded_procedure_target.procedure_name == "usp_saveorder"
        assert entity_exec.embedded_procedure_target.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_preserves_ado_net_fill_as_terminal_sink() -> None:
    """SqlDataAdapter.Fill remains a first-class sink for the command it executes."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AdoAdapterFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class AdoAdapterFixture {\n"
            "    private void Load(SqlConnection conn) {\n"
            "        var command = new SqlCommand(\"usp_Load\", conn);\n"
            "        command.CommandType = CommandType.StoredProcedure;\n"
            "        var table = new DataTable();\n"
            "        var adapter = new SqlDataAdapter(command);\n"
            "        adapter.Fill(table);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_text"] == "usp_Load"
        assert raw_invocations[0]["command_type_mode"] == "stored_procedure"
        assert raw_invocations[0]["terminal_sink"] == "Fill"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Load"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "AdoAdapterFixture.cs",
            raw_invocations,
        )[0]

        assert invocation.invocation_mode == "stored_procedure"
        assert invocation.procedure_name == "usp_load"
        assert invocation.terminal_sink == "Fill"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_analyzes_adapter_constructor_text_for_tables_and_datasets() -> None:
    """ADO.NET adapter constructors enter the same inline invocation shape for DataTable and DataSet fills."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AdoAdapterConstructorFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class AdoAdapterConstructorFixture {\n"
            "    private void LoadTable(SqlConnection conn) {\n"
            "        var adapter = new SqlDataAdapter(\"SELECT 1\", conn);\n"
            "        var table = new DataTable();\n"
            "        adapter.Fill(table);\n"
            "    }\n"
            "    private void LoadDataSet(SqlConnection conn) {\n"
            "        var adapter = new SqlDataAdapter(\"UPDATE SOrder SET Status = 1\", conn);\n"
            "        var dataSet = new DataSet();\n"
            "        adapter.Fill(dataSet);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert {item["command_text"] for item in raw_invocations} == {
            "SELECT 1",
            "UPDATE SOrder SET Status = 1",
        }
        assert all(item["invocation_kind"] == "direct_sqlclient" for item in raw_invocations)
        assert all(item["command_type_mode"] == "default_text" for item in raw_invocations)
        assert all(item["terminal_sink"] == "Fill" for item in raw_invocations)

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": []}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations(
            "AdoAdapterConstructorFixture.cs",
            raw_invocations,
        )

        assert {
            invocation.raw_command_text: (
                invocation.invocation_mode,
                invocation.terminal_sink,
                invocation.evidence,
            )
            for invocation in invocations
        } == {
            "SELECT 1": ("inline_sql", "Fill", InvocationEvidence.PROVEN),
            "UPDATE SOrder SET Status = 1": (
                "inline_sql",
                "Fill",
                InvocationEvidence.PROVEN,
            ),
        }


def test_static_analyzer_host_analyzes_fluent_adapter_fill() -> None:
    """A fluent adapter constructor still exposes Fill as the terminal sink."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "FluentAdapterFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class FluentAdapterFixture {\n"
            "    private void Load(SqlConnection conn) {\n"
            "        new SqlDataAdapter(\"SELECT 1\", conn).Fill(new DataTable());\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)

        assert len(result["db_invocations"]) == 1
        raw = result["db_invocations"][0]
        assert raw["command_text"] == "SELECT 1"
        assert raw["terminal_sink"] == "Fill"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": []}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "FluentAdapterFixture.cs",
            result["db_invocations"],
        )[0]

        assert invocation.invocation_mode == "inline_sql"
        assert invocation.terminal_sink == "Fill"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_links_select_command_assigned_to_adapter() -> None:
    """An adapter configured through SelectCommand still preserves Fill sink evidence."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AssignedAdapterFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class AssignedAdapterFixture {\n"
            "    private void Load(SqlConnection conn) {\n"
            "        var command = new SqlCommand(\"usp_Load\", conn);\n"
            "        command.CommandType = CommandType.StoredProcedure;\n"
            "        var adapter = new SqlDataAdapter();\n"
            "        adapter.SelectCommand = command;\n"
            "        adapter.Fill(new DataSet());\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)

        assert len(result["db_invocations"]) == 1
        raw = result["db_invocations"][0]
        assert raw["command_text"] == "usp_Load"
        assert raw["terminal_sink"] == "Fill"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Load"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "AssignedAdapterFixture.cs",
            result["db_invocations"],
        )[0]

        assert invocation.invocation_mode == "stored_procedure"
        assert invocation.procedure_name == "usp_load"
        assert invocation.terminal_sink == "Fill"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_classifies_comment_prefixed_adapter_text_as_inline() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommentedAdapterFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "public class CommentedAdapterFixture {\n"
            "    private IDbConnection connection;\n"
            "    private void Run() {\n"
            "        connection.Query<int>(\"/* generated */ SELECT 1\");\n"
            "        connection.Query<int>(\"-- generated\\nMERGE SOrder AS target USING SOrderStage AS source ON 1 = 0;\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        adapter_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "dapper"
        ]

        assert len(adapter_invocations) == 2
        assert all(item["wrapper_mode"] == "inline_sql" for item in adapter_invocations)


def test_static_analyzer_host_resolves_entity_framework_branch_and_sp_modes() -> None:
    """EF adapters retain finite command text branches and explicit SP mode."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "EntityFrameworkBranchFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "public class EntityFrameworkBranchFixture {\n"
            "    private DbContext context;\n"
            "    private void Run(bool alternate) {\n"
            "        var sql = \"SELECT 1\";\n"
            "        if (alternate)\n"
            "            sql = \"UPDATE SOrder SET Status = 1\";\n"
            "        context.Database.ExecuteSqlRaw(sql);\n"
            "        context.Database.ExecuteSqlRaw(\"usp_Save\", commandType: CommandType.StoredProcedure);\n"
            "        context.Database.ExecuteSqlRaw(\"usp_Unknown\", commandType: commandType);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "entity_framework"
        ]

        assert {item["command_text"] for item in raw_invocations} >= {
            "SELECT 1",
            "UPDATE SOrder SET Status = 1",
            "usp_Save",
            "usp_Unknown",
        }
        raw_by_text = {item["command_text"]: item for item in raw_invocations}
        assert raw_by_text["SELECT 1"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["UPDATE SOrder SET Status = 1"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["usp_Save"]["wrapper_mode"] == "stored_procedure"
        assert raw_by_text["usp_Unknown"]["wrapper_mode"] == "unknown"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
            connection_sources={"context.Database": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations(
            "EntityFrameworkBranchFixture.cs",
            raw_invocations,
        )
        by_text = {invocation.raw_command_text: invocation for invocation in invocations}

        for command_text in ("SELECT 1", "UPDATE SOrder SET Status = 1"):
            invocation = by_text[command_text]
            assert invocation.invocation_mode == "inline_sql"
            assert invocation.evidence is InvocationEvidence.PROVEN

        stored = by_text["usp_Save"]
        assert stored.invocation_mode == "stored_procedure"
        assert stored.procedure_name == "usp_save"
        assert stored.evidence is InvocationEvidence.PROVEN

        unresolved = by_text["usp_Unknown"]
        assert unresolved.invocation_mode == "unresolved"
        assert unresolved.reason == "adapter_mode_unresolved"
        assert unresolved.evidence is InvocationEvidence.UNRESOLVED


def test_gateway_classifies_source_wrapper_sp_and_inline_modes() -> None:
    """Source-backed wrapper semantics preserve both SP and inline call sites."""
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
            "        var connection = GetConnection();\n"
            "        var wrapper = new DbWrapper(connection);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", true);\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var connection = GetConnection();\n"
            "        var wrapper = new DbWrapper(connection);\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", false);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
        gateway = CSharpAnalysisGateway(catalog, connection_sources={"connection": "OrdersDb"})

        invocations = gateway.resolve_direct_invocations("WrapperFixture.cs", result["db_invocations"])

        assert len(invocations) == 2
        by_method = {invocation.method_name: invocation for invocation in invocations}

        save = by_method["Save"]
        assert save.invocation_mode == "stored_procedure"
        assert save.procedure_name == "usp_saveorder"
        assert save.evidence is InvocationEvidence.PROVEN
        assert save.wrapper_method_semantics == "call_site"
        assert save.wrapper_method_identity == "DbWrapper.Execute(string,bool)"
        assert save.wrapper_method_arity == 2
        assert save.wrapper_parameter_types == ("string", "bool")

        preview = by_method["Preview"]
        assert preview.invocation_mode == "inline_sql"
        assert preview.procedure_name is None
        assert preview.raw_command_text == "SELECT * FROM SOrder"
        assert preview.evidence is InvocationEvidence.PROVEN
        assert preview.wrapper_method_semantics == "call_site"
        assert preview.terminal_sink == "ExecuteNonQuery"


def test_source_wrapper_branch_assigned_finite_targets_are_each_catalog_validated() -> None:
    """Finite caller assignments produce separate source-wrapper candidates."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class FixedSpWrapper {
    private readonly SqlConnection connection;
    public FixedSpWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class BranchTargetPage {
    private void Run(SqlConnection connection, bool alternate) {
        string procedure = "usp_Default";
        if (alternate)
            procedure = "usp_Alternate";
        var wrapper = new FixedSpWrapper(connection);
        wrapper.Execute(procedure);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "BranchTargetFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert {item["command_text"] for item in raw_invocations} == {
            "usp_Default",
            "usp_Alternate",
        }
        assert all(
            item["wrapper_method_semantics"] == "fixed_stored_procedure"
            for item in raw_invocations
        )

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases(
                {"OrdersDb": ["usp_Default", "usp_Alternate"]}
            ),
            connection_sources={"connection": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations(
            "BranchTargetFixture.cs", raw_invocations
        )

        assert {invocation.procedure_name for invocation in invocations} == {
            "usp_default",
            "usp_alternate",
        }
        assert all(invocation.evidence is InvocationEvidence.PROVEN for invocation in invocations)
        assert any("if (alternate)" in context for invocation in invocations for context in invocation.branch_context)


def test_source_backed_fixed_text_wrapper_keeps_procedure_shaped_text_inline() -> None:
    """Source Text semantics must win over a procedure-shaped command string."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_ReadAsText"]}),
        connection_sources={"obj": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        class_name="OrderPage",
        method_name="Preview",
        wrapper_method_name="CreateReader",
        wrapper_receiver_type="SQLObject",
        receiver_type="Vendor.Data.SQLObject",
        receiver_name="obj",
        receiver_expression="obj",
        receiver_binding={
            "expression": "obj",
            "concrete_type": "Vendor.Data.SQLObject",
            "implementation_identity": "Vendor.Data.SQLObject",
            "assembly_identity": "Vendor.Data",
            "assembly_revision": "1.4.0.0",
            "provenance": "source",
        },
        wrapper_implementation_identity="Vendor.Data.SQLObject",
        wrapper_assembly_identity="Vendor.Data",
        wrapper_assembly_revision="1.4.0.0",
        wrapper_method_identity="Vendor.Data.SQLObject.CreateReader(string)",
        wrapper_method_arity=1,
        wrapper_parameter_types=["string"],
        wrapper_method_semantics="fixed_inline_sql",
        wrapper_source_available=True,
        wrapper_mode="inline_sql",
        command_type_stored_procedure=False,
        command_type_mode="text",
        connection_expression="obj",
        command_text="usp_ReadAsText",
        command_text_kind="literal",
        terminal_sink="ExecuteReader",
        wrapper_reaches_stored_procedure_sink=True,
    )

    invocations = gateway.resolve_direct_invocations("OrderPage.cs", [raw])

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.invocation_mode == "inline_sql"
    assert invocation.method_semantics == "fixed_inline_sql"
    assert invocation.raw_command_text == "usp_ReadAsText"
    assert invocation.procedure_name is None
    assert invocation.terminal_sink == "ExecuteReader"
    assert invocation.wrapper_implementation_identity == "Vendor.Data.SQLObject"
    assert invocation.wrapper_assembly_identity == "Vendor.Data"
    assert invocation.wrapper_assembly_revision == "1.4.0.0"
    assert invocation.wrapper_method_identity == "Vendor.Data.SQLObject.CreateReader(string)"
    assert invocation.wrapper_method_arity == 1
    assert invocation.wrapper_parameter_types == ("string",)
    assert invocation.evidence is InvocationEvidence.PROVEN

    observation = gateway.reconcile_wrapper_observation("OrderPage.cs", raw)
    assert observation["method_semantics"] == "fixed_inline_sql"
    assert observation["invocation_mode"] == "inline_sql"
    assert observation["command_text_literal"] == "usp_ReadAsText"
    assert observation["terminal_sink"] == "ExecuteReader"
    assert observation["connection_expression"] == "obj"
    assert observation["connection_source"] == "OrdersDb"
    assert observation["evidence_status"] == "proven"
    assert observation["provenance"] == "static_analyzer_host"


def test_static_analyzer_host_does_not_treat_arbitrary_stored_procedure_member_as_enum() -> None:
    """A property named StoredProcedure is not proof of CommandType semantics."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class DbWrapper {
    private readonly SqlConnection connection;
    public DbWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText, Settings settings) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = settings.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class Settings { public CommandType StoredProcedure { get; set; } }

public class SettingsPage {
    private void Run(SqlConnection connection, Settings settings) {
        var wrapper = new DbWrapper(connection);
        wrapper.Execute("usp_Settings", settings);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "SettingsFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_semantics"] == "unresolved"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Settings"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "SettingsFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "wrapper_mode_unresolved"


def test_static_analyzer_host_recognizes_numeric_command_type_cast_in_wrapper_body() -> None:
    """A wrapper's `(CommandType)4` assignment is recognized as a fixed stored-procedure wrapper."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class NumericCommandTypeWrapper {
    private readonly SqlConnection connection;
    public NumericCommandTypeWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = (CommandType)4;
        command.ExecuteNonQuery();
    }
}

public class NumericCommandTypePage {
    private void Run(SqlConnection connection) {
        var wrapper = new NumericCommandTypeWrapper(connection);
        wrapper.Execute("usp_DoThing");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NumericCommandTypeWrapperFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_semantics"] == "fixed_stored_procedure"


def test_source_backed_sqlobject_fixture_preserves_semantics_binding_and_overloads() -> None:
    """Source implementation facts, not names or prefixes, drive wrapper classification."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

namespace Vendor.One {
    public interface IWrapper { }

    public class SQLObject : IWrapper {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public object CreateReader(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            return command.ExecuteReader();
        }

        public object GetFirstValue(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            return command.ExecuteScalar();
        }

        public void Edit(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            command.ExecuteNonQuery();
        }

        public void FillData(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            var adapter = new SqlDataAdapter(command);
            var table = new DataTable();
            adapter.Fill(table);
        }

        public object ExeProcRead(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.StoredProcedure;
            return command.ExecuteReader();
        }

        public void ExeProcNon(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }

        public object CreateTable(string commandText, string mode) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = mode == "SP"
                ? CommandType.StoredProcedure
                : CommandType.Text;
            return command.ExecuteReader();
        }

        public object CreateDataSet(string commandText, string mode) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = mode == "SP"
                ? CommandType.StoredProcedure
                : CommandType.Text;
            return command.ExecuteReader();
        }

        public object Select(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            return command.ExecuteReader();
        }

        public object Select(object commandText) {
            var command = new SqlCommand(commandText.ToString(), connection);
            command.CommandType = CommandType.StoredProcedure;
            return command.ExecuteNonQuery();
        }

        public object Ambiguous(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            return command.ExecuteReader();
        }

        public object Ambiguous(object commandText) {
            var command = new SqlCommand(commandText.ToString(), connection);
            command.CommandType = CommandType.StoredProcedure;
            return command.ExecuteNonQuery();
        }
    }
}

namespace Vendor.Two {
    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public object CreateReader(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.StoredProcedure;
            return command.ExecuteReader();
        }
    }
}

public class SQLObjectPage {
    private void Run(dynamic unknownValue, SqlConnection connection) {
        var textObject = new Vendor.One.SQLObject(connection);
        textObject.CreateReader("usp_TextReader");
        textObject.GetFirstValue("usp_TextScalar");
        textObject.Edit("usp_TextEdit");
        textObject.ExeProcRead("usp_FixedReader");
        textObject.ExeProcNon("usp_FixedNonQuery");
        textObject.CreateTable("usp_CallTable", "SP");
        textObject.CreateTable("usp_TextTable", "Text");
        textObject.CreateDataSet("usp_CallDataSet", "SP");
        string knownText = "usp_KnownOverload";
        textObject.Select(knownText);
        textObject.FillData("usp_FillData");

        var otherObject = new Vendor.Two.SQLObject(connection);
        otherObject.CreateReader("usp_OtherImplementation");
        Vendor.One.SQLObject assignedObject;
        assignedObject = new Vendor.One.SQLObject(connection);
        assignedObject.CreateReader("usp_AssignedImplementation");
        Vendor.One.IWrapper interfaceObject;
        interfaceObject = new Vendor.One.SQLObject(connection);
        interfaceObject.CreateReader("usp_InterfaceImplementation");
        textObject.Ambiguous(unknownValue);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "SQLObjectFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 14
        assert all(item["wrapper_source_available"] is True for item in raw_invocations)
        assert any(
            item["wrapper_method_name"] == "CreateReader"
            and item["wrapper_method_semantics"] == "fixed_inline_sql"
            and item["wrapper_method_identity"] == "Vendor.One.SQLObject.CreateReader(string)"
            and item["receiver_implementation_identity"] == "Vendor.One.SQLObject"
            for item in raw_invocations
        )
        assert any(
            item["wrapper_method_name"] == "CreateReader"
            and item["wrapper_method_semantics"] == "fixed_stored_procedure"
            and item["receiver_implementation_identity"] == "Vendor.Two.SQLObject"
            for item in raw_invocations
        )
        assert any(
            item["wrapper_method_name"] == "Ambiguous"
            and item["wrapper_overload_ambiguous"] is True
            and len(item["wrapper_overload_candidates"]) == 2
            for item in raw_invocations
        )
        fill_raw = next(
            item
            for item in raw_invocations
            if item.get("command_text") == "usp_FillData"
        )
        assert fill_raw["terminal_sink"] == "Fill"
        interface_raw = next(
            item
            for item in raw_invocations
            if item.get("command_text") == "usp_InterfaceImplementation"
        )
        assert interface_raw["receiver_construction_facts"] == [
            "new Vendor.One.SQLObject(connection)"
        ]
        assert interface_raw["receiver_assignment_facts"] == [
            "interfaceObject = new Vendor.One.SQLObject(connection)"
        ]

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases(
                {
                    "OrdersDb": [
                        "usp_TextReader",
                        "usp_TextScalar",
                        "usp_TextEdit",
                        "usp_FixedReader",
                        "usp_FixedNonQuery",
                        "usp_CallTable",
                        "usp_TextTable",
                        "usp_CallDataSet",
                        "usp_KnownOverload",
                        "usp_FillData",
                        "usp_OtherImplementation",
                        "usp_AssignedImplementation",
                        "usp_InterfaceImplementation",
                    ]
                }
            ),
            connection_sources={"connection": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations(
            "SQLObjectFixture.cs",
            raw_invocations,
        )

        def find_by_text(command_text: str):
            return next(
                invocation
                for invocation in invocations
                if invocation.raw_command_text == command_text
            )

        for command_text, sink in {
            "usp_TextReader": "ExecuteReader",
            "usp_TextScalar": "ExecuteScalar",
            "usp_TextEdit": "ExecuteNonQuery",
            "usp_FillData": "Fill",
        }.items():
            invocation = find_by_text(command_text)
            assert invocation.invocation_mode == "inline_sql"
            assert invocation.method_semantics == "fixed_inline_sql"
            assert invocation.procedure_name is None
            assert invocation.terminal_sink == sink
            assert invocation.evidence is InvocationEvidence.PROVEN

        known_overload = next(
            invocation
            for invocation in invocations
            if invocation.wrapper_method == "Select"
        )
        assert known_overload.wrapper_method_identity == (
            "Vendor.One.SQLObject.Select(string)"
        )
        assert known_overload.wrapper_parameter_types == ("string",)
        assert known_overload.command_text_argument == "knownText"
        assert known_overload.raw_command_text == "usp_KnownOverload"
        assert known_overload.invocation_mode == "inline_sql"
        assert known_overload.method_semantics == "fixed_inline_sql"
        assert known_overload.evidence is InvocationEvidence.PROVEN
        assert known_overload.reason == "inline_sql"

        text_table = find_by_text("usp_TextTable")
        assert text_table.invocation_mode == "inline_sql"
        assert text_table.method_semantics == "call_site"
        assert text_table.procedure_name is None
        assert text_table.terminal_sink == "ExecuteReader"
        assert text_table.evidence is InvocationEvidence.PROVEN

        for command_text, sink in {
            "usp_FixedReader": "ExecuteReader",
            "usp_FixedNonQuery": "ExecuteNonQuery",
        }.items():
            invocation = find_by_text(command_text)
            assert invocation.invocation_mode == "stored_procedure"
            assert invocation.method_semantics == "fixed_stored_procedure"
            assert invocation.procedure_name == command_text.casefold()
            assert invocation.terminal_sink == sink
            assert invocation.evidence is InvocationEvidence.PROVEN

        call_table = find_by_text("usp_CallTable")
        assert call_table.invocation_mode == "stored_procedure"
        assert call_table.method_semantics == "call_site"
        assert call_table.wrapper_method_identity == (
            "Vendor.One.SQLObject.CreateTable(string,string)"
        )
        assert call_table.wrapper_parameter_types == ("string", "string")
        assert call_table.evidence is InvocationEvidence.PROVEN

        call_dataset = find_by_text("usp_CallDataSet")
        assert call_dataset.invocation_mode == "stored_procedure"
        assert call_dataset.method_semantics == "call_site"
        assert call_dataset.evidence is InvocationEvidence.PROVEN

        other = find_by_text("usp_OtherImplementation")
        assert other.wrapper_implementation_identity == "Vendor.Two.SQLObject"
        assert other.invocation_mode == "stored_procedure"
        assert other.method_semantics == "fixed_stored_procedure"
        assert other.evidence is InvocationEvidence.PROVEN

        assigned = find_by_text("usp_AssignedImplementation")
        assert assigned.wrapper_implementation_identity == "Vendor.One.SQLObject"
        assert assigned.connection_source == "OrdersDb"
        assert assigned.invocation_mode == "inline_sql"
        assert assigned.method_semantics == "fixed_inline_sql"
        assert assigned.evidence is InvocationEvidence.PROVEN

        interface_bound = find_by_text("usp_InterfaceImplementation")
        assert interface_bound.wrapper_implementation_identity == "Vendor.One.SQLObject"
        assert interface_bound.wrapper_receiver_type == "Vendor.One.IWrapper"
        assert interface_bound.connection_source == "OrdersDb"
        assert interface_bound.invocation_mode == "inline_sql"
        assert interface_bound.evidence is InvocationEvidence.PROVEN

        ambiguous = next(
            invocation
            for invocation in invocations
            if invocation.wrapper_method == "Ambiguous"
        )
        assert ambiguous.evidence is InvocationEvidence.UNRESOLVED
        assert ambiguous.reason == "ambiguous_overload"
        assert ambiguous.invocation_mode == "unresolved"
        assert len(ambiguous.wrapper_overload_candidates) == 2
        assert all(
            identity.startswith("Vendor.One.SQLObject.Ambiguous(")
            for identity in ambiguous.wrapper_overload_candidates
        )


def test_source_sqlobject_optional_mode_defaults_table_and_dataset_to_text() -> None:
    """SQLObject call-site methods use their source default Text when mode is omitted."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class SQLObject {
    private readonly SqlConnection connection;
    public SQLObject(SqlConnection connection) { this.connection = connection; }

    public object CreateTable(string commandText, string mode = "Text") {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = mode == "SP"
            ? CommandType.StoredProcedure
            : CommandType.Text;
        return command.ExecuteReader();
    }

    public object CreateDataSet(string commandText, string mode = "Text") {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = mode == "SP"
            ? CommandType.StoredProcedure
            : CommandType.Text;
        return command.ExecuteReader();
    }
}

public class SQLObjectDefaultPage {
    private void Run(SqlConnection connection) {
        var obj = new SQLObject(connection);
        obj.CreateTable("usp_DefaultTable");
        obj.CreateDataSet("usp_DefaultDataSet");
        obj.CreateTable("usp_ExplicitTable", "SP");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "SQLObjectDefaultFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 3
        raw_by_text = {item["command_text"]: item for item in raw_invocations}
        assert raw_by_text["usp_DefaultTable"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["usp_DefaultDataSet"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["usp_ExplicitTable"]["wrapper_mode"] == "stored_procedure"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_ExplicitTable"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations(
            "SQLObjectDefaultFixture.cs",
            raw_invocations,
        )
        by_text = {invocation.raw_command_text: invocation for invocation in invocations}

        for command_text in ("usp_DefaultTable", "usp_DefaultDataSet"):
            invocation = by_text[command_text]
            assert invocation.invocation_mode == "inline_sql"
            assert invocation.method_semantics == "call_site"
            assert invocation.procedure_name is None
            assert invocation.evidence is InvocationEvidence.PROVEN

        explicit = by_text["usp_ExplicitTable"]
        assert explicit.invocation_mode == "stored_procedure"
        assert explicit.procedure_name == "usp_explicittable"
        assert explicit.evidence is InvocationEvidence.PROVEN


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


def test_static_analyzer_host_uses_qualified_parameter_types_for_overload_selection() -> None:
    """Same-named parameter types in different namespaces must not collide."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

namespace Vendor.One {
    public class Token { }

    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(Vendor.One.Token value) {
            var command = new SqlCommand("usp_InlineToken", connection);
            command.CommandType = CommandType.Text;
            command.ExecuteNonQuery();
        }

        public void Execute(Vendor.Two.Token value) {
            var command = new SqlCommand("usp_StoredToken", connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }
    }
}

namespace Vendor.Two {
    public class Token { }
}

public class TokenPage {
    private void Run(SqlConnection connection) {
        var wrapper = new Vendor.One.SQLObject(connection);
        wrapper.Execute(new Vendor.One.Token());
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "QualifiedOverloadFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_identity"] == (
            "Vendor.One.SQLObject.Execute(Vendor.One.Token)"
        )
        assert raw_invocations[0]["wrapper_overload_ambiguous"] is False

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_StoredToken"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "QualifiedOverloadFixture.cs",
            raw_invocations,
        )[0]

        assert invocation.wrapper_method_identity == (
            "Vendor.One.SQLObject.Execute(Vendor.One.Token)"
        )
        assert invocation.method_semantics == "fixed_inline_sql"
        assert invocation.invocation_mode == "inline_sql"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_traces_receiver_assignment_from_other_method() -> None:
    """A concrete field assignment outside the call method still binds the receiver."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

namespace Vendor.One {
    public interface IWrapper { }

    public class SQLObject : IWrapper {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            command.ExecuteReader();
        }
    }
}

public class OtherMethodPage {
    private Vendor.One.IWrapper wrapper;

    private void Run() {
        wrapper.Execute("usp_OtherMethod");
    }

    private void Initialize(SqlConnection connection) {
        wrapper = new Vendor.One.SQLObject(connection);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "OtherMethodBindingFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["receiver_type"] == "Vendor.One.IWrapper"
        assert raw["receiver_implementation_identity"] == "Vendor.One.SQLObject"
        assert raw["receiver_assignment_facts"] == [
            "wrapper = new Vendor.One.SQLObject(connection)"
        ]
        assert raw["receiver_construction_facts"] == [
            "new Vendor.One.SQLObject(connection)"
        ]

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_OtherMethod"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "OtherMethodBindingFixture.cs", raw_invocations
        )[0]
        assert invocation.database == "OrdersDb"
        assert invocation.invocation_mode == "inline_sql"


def test_static_analyzer_host_traces_receiver_binding_across_partial_classes() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wrapper_path = root / "SQLObject.cs"
        wrapper_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "namespace Vendor.One {\n"
            "    public interface IWrapper { }\n"
            "    public class SQLObject : IWrapper {\n"
            "        private readonly SqlConnection connection;\n"
            "        public SQLObject(SqlConnection connection) { this.connection = connection; }\n"
            "        public void Execute(string commandText) {\n"
            "            var command = new SqlCommand(commandText, connection);\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "            command.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        call_path = root / "PartialPage.Call.cs"
        call_path.write_text(
            "using System.Data.SqlClient;\n"
            "using Vendor.One;\n"
            "public partial class PartialPage {\n"
            "    private IWrapper wrapper;\n"
            "    private void Run() {\n"
            "        wrapper.Execute(\"usp_Partial\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        assignment_path = root / "PartialPage.Initialize.cs"
        assignment_path.write_text(
            "using System.Data.SqlClient;\n"
            "using Vendor.One;\n"
            "public partial class PartialPage {\n"
            "    private void Initialize(SqlConnection connection) {\n"
            "        wrapper = new SQLObject(connection);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files(
            [wrapper_path, call_path, assignment_path],
            source_roots=[root],
        )
        raw_invocations = [
            item
            for item in results[1]["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["receiver_implementation_identity"] == (
            "Vendor.One.SQLObject"
        )
        assert raw_invocations[0]["receiver_assignment_facts"] == [
            "wrapper = new SQLObject(connection)"
        ]

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Partial"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "PartialPage.Call.cs",
            raw_invocations,
        )[0]
        assert invocation.database == "OrdersDb"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_ignores_command_type_assignment_after_sink() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class AfterSinkWrapper {
    private readonly SqlConnection connection;
    public AfterSinkWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.ExecuteNonQuery();
        command.CommandType = CommandType.StoredProcedure;
    }
}

public class AfterSinkPage {
    private void Run(SqlConnection connection) {
        var wrapper = new AfterSinkWrapper(connection);
        wrapper.Execute("usp_AfterSink");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AfterSinkFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_semantics"] == "fixed_inline_sql"
        assert raw_invocations[0]["terminal_sink"] == "ExecuteNonQuery"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_AfterSink"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "AfterSinkFixture.cs",
            raw_invocations,
        )[0]
        assert invocation.invocation_mode == "inline_sql"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_ignores_command_text_assignment_after_sink() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class CommandTextAfterSinkWrapper {
    private readonly SqlConnection connection;
    public CommandTextAfterSinkWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute() {
        var command = new SqlCommand("usp_BeforeSink", connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
        command.CommandText = "usp_AfterSink";
    }
}

public class CommandTextAfterSinkPage {
    private void Run(SqlConnection connection) {
        var wrapper = new CommandTextAfterSinkWrapper(connection);
        wrapper.Execute();
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandTextAfterSinkFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_text"] == "usp_BeforeSink"
        assert raw_invocations[0]["wrapper_method_semantics"] == "fixed_stored_procedure"


def test_static_analyzer_host_resolves_property_initializer_receiver_connection() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public interface IWrapper { }

public class PropertyWrapper : IWrapper {
    private readonly SqlConnection connection;
    public PropertyWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class PropertyInitializerPage {
    private readonly SqlConnection connection;
    private IWrapper wrapper { get; } = new PropertyWrapper(connection);

    private void Run() {
        wrapper.Execute("usp_PropertyInitializer");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "PropertyInitializerFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["receiver_implementation_identity"] == "PropertyWrapper"
        assert raw["receiver_construction_facts"] == [
            "new PropertyWrapper(connection)"
        ]
        assert raw["connection_expression"] == "connection"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_PropertyInitializer"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "PropertyInitializerFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.PROVEN
        assert invocation.database == "OrdersDb"


def test_static_analyzer_host_finds_constructor_in_sibling_partial_declaration() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        method_path = root / "PartialWrapper.Methods.cs"
        method_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public partial class PartialWrapper {\n"
            "    private readonly SqlConnection connection;\n"
            "    public void Execute(string commandText) {\n"
            "        var command = new SqlCommand(commandText, connection);\n"
            "        command.CommandType = CommandType.StoredProcedure;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        constructor_path = root / "PartialWrapper.Constructor.cs"
        constructor_path.write_text(
            "using System.Data.SqlClient;\n"
            "public partial class PartialWrapper {\n"
            "    public PartialWrapper(SqlConnection connection) { this.connection = connection; }\n"
            "}\n",
            encoding="utf-8",
        )
        caller_path = root / "PartialWrapper.Page.cs"
        caller_path.write_text(
            "using System.Data.SqlClient;\n"
            "public class PartialWrapperPage {\n"
            "    private void Run(SqlConnection connection) {\n"
            "        var wrapper = new PartialWrapper(connection);\n"
            "        wrapper.Execute(\"usp_PartialConstructor\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        results = host.analyze_csharp_files(
            [method_path, constructor_path, caller_path],
            source_roots=[root],
        )
        raw_invocations = [
            item
            for item in results[2]["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["connection_expression"] == "connection"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_PartialConstructor"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "PartialWrapper.Page.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.PROVEN
        assert invocation.database == "OrdersDb"


def test_static_analyzer_host_uses_command_text_argument_index_for_ambiguous_overloads() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class IndexedOverloadWrapper {
    private readonly SqlConnection connection;
    public IndexedOverloadWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string prefix, string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.Text;
        command.ExecuteReader();
    }

    public void Execute(object prefix, object commandText) {
        var command = new SqlCommand(commandText.ToString(), connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class IndexedOverloadPage {
    private void Run(dynamic unknownValue, SqlConnection connection) {
        var wrapper = new IndexedOverloadWrapper(connection);
        wrapper.Execute(unknownValue, unknownValue);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "IndexedOverloadFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["wrapper_overload_ambiguous"] is True
        assert raw["command_text_argument"] == "unknownValue"
        assert raw["command_text"] is None


def test_static_analyzer_host_ambiguous_overload_candidates_keep_structured_facts() -> None:
    """Ambiguous overload candidates must retain bound implementation, receiver type,
    method name, arity, and parameter types as structured facts (not opaque identity
    strings), so review/grouping can still reason about each candidate."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class IndexedOverloadWrapper {
    private readonly SqlConnection connection;
    public IndexedOverloadWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string prefix, string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.Text;
        command.ExecuteReader();
    }

    public void Execute(object prefix, object commandText) {
        var command = new SqlCommand(commandText.ToString(), connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class IndexedOverloadPage {
    private void Run(dynamic unknownValue, SqlConnection connection) {
        var wrapper = new IndexedOverloadWrapper(connection);
        wrapper.Execute(unknownValue, unknownValue);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "IndexedOverloadCandidateFactsFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["wrapper_overload_ambiguous"] is True

        candidates = raw["wrapper_overload_candidates"]
        assert len(candidates) == 2
        for candidate in candidates:
            assert isinstance(candidate, dict)
            assert candidate["method_name"] == "Execute"
            assert candidate["method_arity"] == 2
            assert len(candidate["parameter_types"]) == 2
            assert candidate["implementation_identity"] == raw["wrapper_implementation_identity"]
            assert candidate["receiver_type"] == raw["wrapper_receiver_type"]
            assert candidate["method_identity"]

        parameter_type_sets = {tuple(candidate["parameter_types"]) for candidate in candidates}
        assert parameter_type_sets == {("string", "string"), ("object", "object")}

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "IndexedOverloadCandidateFactsFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "ambiguous_overload"
        assert {
            fact["method_name"] for fact in invocation.wrapper_overload_candidate_facts
        } == {"Execute"}
        assert {
            tuple(fact["parameter_types"]) for fact in invocation.wrapper_overload_candidate_facts
        } == {("string", "string"), ("object", "object")}


def test_static_analyzer_host_does_not_guess_between_cross_method_connections() -> None:
    """Multiple concrete assignments keep connection provenance unresolved."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

namespace Vendor.One {
    public interface IWrapper { }

    public class SQLObject : IWrapper {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }
    }
}

public class MultipleConnectionPage {
    private Vendor.One.IWrapper wrapper;

    private void Run() {
        wrapper.Execute("usp_MultiConnection");
    }

    private void InitializeOrders(SqlConnection connection) {
        wrapper = new Vendor.One.SQLObject(connection);
    }

    private void InitializeAudit(SqlConnection connection) {
        wrapper = new Vendor.One.SQLObject(connection);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "MultipleConnectionFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["connection_expression"] is None
        raw_connection_candidates = tuple(
            raw_invocations[0]["connection_expression_candidates"]
        )
        assert len(raw_connection_candidates) == 2
        assert all(
            candidate.startswith("method:") and candidate.endswith(":connection")
            for candidate in raw_connection_candidates
        )

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases(
                {
                    "OrdersDb": ["usp_MultiConnection"],
                    "AuditDb": ["usp_MultiConnection"],
                }
            ),
            connection_sources={
                "connection": "OrdersDb",
            },
        )
        invocation = gateway.resolve_direct_invocations(
            "MultipleConnectionFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "ambiguous_connection_source"
        assert invocation.connection_expression_candidates == raw_connection_candidates


def test_static_analyzer_host_resolves_imported_wrapper_and_parameter_types() -> None:
    """Imported receiver and argument types retain their source-qualified identities."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;
using VO = Vendor.One;

namespace Vendor.One {
    public class Token { }

    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(Token value) {
            var command = new SqlCommand("usp_ImportedText", connection);
            command.CommandType = CommandType.Text;
            command.ExecuteReader();
        }

        public void Execute(Vendor.Two.Token value) {
            var command = new SqlCommand("usp_ImportedStored", connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }
    }
}

namespace Vendor.Two {
    public class Token { }
}

public class ImportedPage {
    private void Run(SqlConnection connection) {
        var wrapper = new VO.SQLObject(connection);
        wrapper.Execute(new VO.Token());
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "ImportedWrapperFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["receiver_implementation_identity"] == (
            "Vendor.One.SQLObject"
        )
        assert raw_invocations[0]["wrapper_method_identity"] == (
            "Vendor.One.SQLObject.Execute(Vendor.One.Token)"
        )
        assert raw_invocations[0]["wrapper_method_semantics"] == "fixed_inline_sql"


def test_static_analyzer_host_does_not_select_non_matching_known_overload() -> None:
    """A known argument type with no exact overload must not select another method."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

namespace Vendor.One {
    public class Token { }
    public class OtherToken { }

    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(Token value) {
            var command = new SqlCommand("usp_Token", connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }
    }
}

public class NonMatchingOverloadPage {
    private void Run(SqlConnection connection) {
        var wrapper = new Vendor.One.SQLObject(connection);
        wrapper.Execute(new Vendor.One.OtherToken());
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NonMatchingOverloadFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]
        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_source_available"] is True
        assert raw_invocations[0]["wrapper_unresolved_reason"] == "overload_not_found"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Token"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "NonMatchingOverloadFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "overload_not_found"


def test_static_analyzer_host_keeps_unbound_source_wrapper_outside_external_fallback() -> None:
    """A source method with no concrete receiver binding cannot auto-select a registry contract."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class SQLObject {
    private readonly SqlConnection connection;
    public SQLObject(SqlConnection connection) { this.connection = connection; }

    public void ExeProcNon(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class UnboundSourcePage {
    private void Run(SqlConnection connection) {
        SQLObject wrapper = GetWrapper();
        wrapper.ExeProcNon("usp_Unbound");
    }

    private SQLObject GetWrapper() { return null; }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "UnboundSourceFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_source_available"] is True
        assert raw_invocations[0]["wrapper_unresolved_reason"] == (
            "receiver_binding_unresolved"
        )

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Unbound"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "UnboundSourceFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "receiver_binding_unresolved"


def test_static_analyzer_host_does_not_duplicate_unbound_source_wrapper_as_dapper() -> None:
    """An unresolved source method wins over adapter heuristics with the same method name."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class SQLObject {
    private readonly SqlConnection connection;
    public SQLObject(SqlConnection connection) { this.connection = connection; }

    public void Query(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class UnboundDapperPage {
    private IDbConnection connection;

    private void Run() {
        connection.Query("usp_Unbound", commandType: CommandType.StoredProcedure);
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "UnboundDapperFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        source_wrapper_invocations = [
            item
            for item in raw_invocations
            if item.get("invocation_kind") == "source_wrapper"
        ]
        assert not source_wrapper_invocations
        assert [
            item["command_text"]
            for item in raw_invocations
            if item.get("invocation_kind") == "dapper"
        ] == ["usp_Unbound"]


def test_static_analyzer_host_fails_closed_for_multiple_wrapper_sql_commands() -> None:
    """A wrapper method with multiple commands cannot inherit the first command's semantics."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class MultiCommandWrapper {
    private readonly SqlConnection connection;
    public MultiCommandWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var first = new SqlCommand(commandText, connection);
        first.CommandType = CommandType.StoredProcedure;
        first.ExecuteNonQuery();
        var second = new SqlCommand(commandText, connection);
        second.CommandType = CommandType.Text;
        second.ExecuteReader();
    }
}

public class MultiCommandPage {
    private void Run(SqlConnection connection) {
        var wrapper = new MultiCommandWrapper(connection);
        wrapper.Execute("usp_MultiCommand");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "MultiCommandFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_semantics"] == "unresolved"
        assert raw_invocations[0]["wrapper_unresolved_reason"] == (
            "multiple_sql_commands"
        )
        assert raw_invocations[0].get("terminal_sink") in (None, "")

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_MultiCommand"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "MultiCommandFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "multiple_sql_commands"


def test_static_analyzer_host_filters_used_wrapper_overloads_by_full_identity() -> None:
    """Using one overload must not hide a same-named uncalled implementation."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class OverloadedWrapper {
    private readonly SqlConnection connection;
    public OverloadedWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection);
        command.CommandType = CommandType.Text;
        command.ExecuteReader();
    }

    public void Execute(int commandId) {
        var command = new SqlCommand("usp_Integer", connection);
        command.CommandType = CommandType.StoredProcedure;
        command.ExecuteNonQuery();
    }
}

public class OverloadedPage {
    private void Run(SqlConnection connection) {
        var wrapper = new OverloadedWrapper(connection);
        wrapper.Execute("usp_String");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "OverloadedFilterFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        direct_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "direct_sqlclient"
        ]

        assert {item["command_text"] for item in direct_invocations} == {
            "usp_Integer"
        }


def test_static_analyzer_host_preserves_ambiguity_for_same_named_imports() -> None:
    """Unqualified types imported from multiple namespaces remain ambiguous."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;
using First;
using Second;

namespace First {
    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.StoredProcedure;
            command.ExecuteNonQuery();
        }
    }
}

namespace Second {
    public class SQLObject {
        private readonly SqlConnection connection;
        public SQLObject(SqlConnection connection) { this.connection = connection; }

        public void Execute(string commandText) {
            var command = new SqlCommand(commandText, connection);
            command.CommandType = CommandType.Text;
            command.ExecuteNonQuery();
        }
    }
}

public class AmbiguousImportedPage {
    private void Run(SqlConnection connection) {
        var wrapper = new SQLObject(connection);
        wrapper.Execute("usp_AmbiguousImported");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AmbiguousImportedFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_overload_ambiguous"] is True
        raw_candidates = raw_invocations[0]["wrapper_overload_candidates"]
        assert {candidate["method_identity"] for candidate in raw_candidates} == {
            "First.SQLObject.Execute(string)",
            "Second.SQLObject.Execute(string)",
        }
        for candidate in raw_candidates:
            assert candidate["method_name"] == "Execute"
            assert candidate["method_arity"] == 1
            assert candidate["parameter_types"] == ["string"]
        assert raw_invocations[0]["receiver_implementation_identity"] == ""

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_AmbiguousImported"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "AmbiguousImportedFixture.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "ambiguous_overload"
        assert invocation.wrapper_overload_candidates == (
            "First.SQLObject.Execute(string)",
            "Second.SQLObject.Execute(string)",
        )


def test_wrapper_observation_identity_distinguishes_connection_sources() -> None:
    """Refresh/discovery grouping keeps equivalent wrappers on separate sources."""
    base = {
        "implementation_identity": "Vendor.One.SQLObject",
        "receiver_type": "Vendor.One.IWrapper",
        "method_identity": "Vendor.One.SQLObject.Execute(string)",
        "method_arity": 1,
        "parameter_types": ["string"],
        "method_semantics": "fixed_stored_procedure",
        "invocation_mode": "stored_procedure",
        "terminal_sink": "ExecuteNonQuery",
    }
    orders = {
        **base,
        "connection_expression": "ordersConnection",
        "connection_source": "OrdersDb",
        "database_candidates": ["OrdersDb"],
    }
    audit = {
        **base,
        "connection_expression": "auditConnection",
        "connection_source": "AuditDb",
        "database_candidates": ["AuditDb"],
    }
    assert wrapper_observation_identity(orders) != wrapper_observation_identity(audit)


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
            "        var wrapper = new First.DbWrapper(conn);\n"
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
            connection_sources={"conn": "OrdersDb"},
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
    """A string call-site discriminator preserves SP and inline outcomes."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "StringModeFixture.cs"
        source_path.write_text(
            "using System.Data;\n"
            "using System.Data.SqlClient;\n"
            "public class DbWrapper {\n"
            "    private readonly SqlConnection _connection;\n"
            "    public DbWrapper(SqlConnection connection) { _connection = connection; }\n"
            "    public void Execute(string commandText, string mode) {\n"
            "        var command = new SqlCommand(commandText, _connection);\n"
            "        if (mode == \"SP\")\n"
            "            command.CommandType = CommandType.StoredProcedure;\n"
            "        else\n"
            "            command.CommandType = CommandType.Text;\n"
            "        command.ExecuteNonQuery();\n"
            "    }\n"
            "}\n"
            "public class OrderPage {\n"
            "    private void Save() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"usp_SaveOrder\", \"SP\");\n"
            "    }\n"
            "    private void Preview() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var wrapper = new DbWrapper(conn);\n"
            "        wrapper.Execute(\"SELECT * FROM SOrder\", \"Text\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("StringModeFixture.cs", result["db_invocations"])

        assert len(invocations) == 2
        by_method = {invocation.method_name: invocation for invocation in invocations}
        assert by_method["Save"].invocation_mode == "stored_procedure"
        assert by_method["Save"].evidence is InvocationEvidence.PROVEN
        assert by_method["Preview"].invocation_mode == "inline_sql"
        assert by_method["Preview"].raw_command_text == "SELECT * FROM SOrder"
        assert by_method["Preview"].evidence is InvocationEvidence.PROVEN


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


def test_source_wrapper_fixed_sp_requires_named_terminal_sink() -> None:
    """A sink reachability boolean cannot replace a known terminal sink name."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="Execute",
        wrapper_receiver_type="DbWrapper",
        receiver_implementation_identity="DbWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        wrapper_method_semantics="fixed_stored_procedure",
        command_type_mode="stored_procedure",
        wrapper_reaches_stored_procedure_sink=True,
        command_text="usp_SaveOrder",
    )
    raw.pop("terminal_sink")

    invocation = gateway.resolve_direct_invocations("f.cs", [raw])[0]
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "wrapper_sink_unresolved"


def test_source_wrapper_fixed_sp_rejects_unknown_terminal_sink() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    invocation = gateway.resolve_direct_invocations(
        "f.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                wrapper_method_name="Execute",
                wrapper_receiver_type="DbWrapper",
                receiver_implementation_identity="DbWrapper",
                wrapper_source_available=True,
                wrapper_mode="stored_procedure",
                wrapper_method_semantics="fixed_stored_procedure",
                command_type_mode="stored_procedure",
                command_text="usp_SaveOrder",
                terminal_sink="ExecuteMystery",
                wrapper_reaches_stored_procedure_sink=True,
            )
        ],
    )[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "wrapper_sink_unresolved"


def test_static_analyzer_host_does_not_treat_command_fill_as_adapter_sink() -> None:
    """Only a recognized adapter receiver can provide Fill terminal-sink evidence."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class DbWrapper {
    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, null);
        command.CommandType = CommandType.StoredProcedure;
        command.Fill();
    }
}

public class FillPage {
    private void Save() {
        var wrapper = new DbWrapper();
        wrapper.Execute("usp_SaveOrder");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "InvalidCommandFillFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocation = next(
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        )

        assert raw_invocation["terminal_sink"] is None
        assert raw_invocation["wrapper_reaches_stored_procedure_sink"] is False

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"wrapper": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "InvalidCommandFillFixture.cs",
            [raw_invocation],
        )[0]

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


def test_external_wrapper_contract_proves_sqlobject_sp_and_inline_modes() -> None:
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
    assert len(inline_invocation) == 1
    assert inline_invocation[0].evidence is InvocationEvidence.PROVEN
    assert inline_invocation[0].invocation_mode == "inline_sql"
    assert inline_invocation[0].procedure_name is None
    assert inline_invocation[0].raw_command_text == "SELECT * FROM SOrder"
    assert inline_invocation[0].external_wrapper_method == "CreateReader"


def test_external_fixed_contract_semantics_override_conflicting_raw_mode() -> None:
    """A fixed external contract cannot be overridden by a raw mode heuristic."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )

    invocation = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [
            _raw_invocation(
                invocation_kind="source_wrapper",
                wrapper_method_name="ExeProcNon",
                wrapper_receiver_type="SQLObject",
                wrapper_source_available=False,
                wrapper_mode="inline_sql",
                command_text="usp_SaveOrder",
                connection_expression="conn",
            )
        ],
    )[0]

    assert invocation.method_semantics == "fixed_stored_procedure"
    assert invocation.invocation_mode == "stored_procedure"
    assert invocation.procedure_name == "usp_saveorder"
    assert invocation.evidence is InvocationEvidence.PROVEN


def test_external_wrapper_contract_requires_explicit_selection_even_for_unique_receiver_type() -> None:
    """A receiver type that uniquely matches one contract's receiver_types is
    still not enough on its own: auto-select and receiver-name inference are
    removed from the contract domain and runtime path (spec item 70).
    Without an explicit selector the call must stay an unresolved review
    candidate; only an explicit ``wrapper_contract`` selector can prove it."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="usp_SaveOrder",
        wrapper_method_name="ExeProcNon",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_reaches_stored_procedure_sink=False,
        wrapper_mode="stored_procedure",
        connection_expression="conn",
    )

    unresolved = gateway.resolve_direct_invocations("SqlObjectPage.cs", [raw])

    assert len(unresolved) == 1
    assert unresolved[0].evidence is InvocationEvidence.UNRESOLVED
    assert unresolved[0].wrapper_contract == ""
    assert unresolved[0].wrapper_contract_source == "unresolved_receiver_type"
    assert unresolved[0].wrapper_contract_candidates == ()

    explicit = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs", [raw], explicit_contract="sqlobject"
    )

    assert len(explicit) == 1
    assert explicit[0].evidence is InvocationEvidence.PROVEN
    assert explicit[0].wrapper_contract == "sqlobject"
    assert explicit[0].wrapper_contract_source == "explicit"
    assert explicit[0].wrapper_receiver_type == "SQLObject"
    assert explicit[0].wrapper_contract_candidates == ("sqlobject",)


def test_external_wrapper_contract_ambiguity_stays_unresolved() -> None:
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    registry = {
        "sqlobject-v1": {
            "name": "sqlobject-v1",
            "receiver_types": ["SQLObject"],
            "methods": {"ExeProcNon": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}},
        },
        "sqlobject-v2": {
            "name": "sqlobject-v2",
            "receiver_types": ["SQLObject"],
            "methods": {"ExeProcNon": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}},
        },
    }
    gateway = CSharpAnalysisGateway(
        catalog,
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts=registry,
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
        explicit_contract=("sqlobject-v1", "sqlobject-v2"),
    )

    assert len(invocations) == 1
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[0].wrapper_contract == ""
    assert invocations[0].wrapper_contract_source == "explicit"
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

    assert len(invocations) == 3
    assert invocations[0].evidence is InvocationEvidence.PROVEN
    assert invocations[0].wrapper_contract == "sqlobject"
    assert invocations[1].evidence is InvocationEvidence.PROVEN
    assert invocations[1].invocation_mode == "inline_sql"
    assert invocations[1].procedure_name is None
    assert invocations[1].raw_command_text == "usp_SaveOrder"
    assert invocations[2].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[2].reason == "wrapper_mode_unresolved"


def test_external_wrapper_call_site_contract_uses_declared_default_text_mode() -> None:
    """A contract-declared default Text mode applies only when the mode is omitted."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})
    contract = {
        "name": "sqlobject-default-text",
        "receiver_types": ["SQLObject"],
        "methods": {
            "CreateTable": {
                "mode": "call_site",
                "default_mode": "inline_sql",
                "sink": "ExecuteReader",
            }
        },
    }

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="usp_SaveOrder",
        command_type_stored_procedure=False,
        wrapper_method_name="CreateTable",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        terminal_sink="ExecuteReader",
        connection_expression="conn",
    )

    invocation = gateway.resolve_direct_invocations(
        "SqlObjectPage.cs",
        [raw],
        explicit_contract=contract,
    )[0]

    assert invocation.invocation_mode == "inline_sql"
    assert invocation.method_semantics == "call_site"
    assert invocation.procedure_name is None
    assert invocation.raw_command_text == "usp_SaveOrder"
    assert invocation.evidence is InvocationEvidence.PROVEN


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

    assert len(invocations) == 3
    assert invocations[0].evidence is InvocationEvidence.PROVEN
    assert invocations[0].external_wrapper_method == "CreateDataSet"
    assert invocations[0].wrapper_contract == "sqlobject"
    assert invocations[1].evidence is InvocationEvidence.PROVEN
    assert invocations[1].invocation_mode == "inline_sql"
    assert invocations[1].procedure_name is None
    assert invocations[1].raw_command_text == "SELECT * FROM SOrder"
    assert invocations[2].evidence is InvocationEvidence.UNRESOLVED
    assert invocations[2].reason == "wrapper_mode_unresolved"


def test_inline_wrapper_mode_is_an_inline_database_invocation() -> None:
    """A source-backed wrapper selecting inline SQL remains a formal invocation."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="SELECT * FROM SOrder",
        command_type_stored_procedure=False,
        receiver_implementation_identity="SQLObject",
        wrapper_source_available=True,
        wrapper_reaches_stored_procedure_sink=True,
        wrapper_mode="inline_sql",
        wrapper_method_semantics="fixed_inline_sql",
        connection_expression="conn",
    )

    invocations = gateway.resolve_direct_invocations("f.cs", [raw])
    assert len(invocations) == 1
    assert invocations[0].invocation_mode == "inline_sql"
    assert invocations[0].procedure_name is None
    assert invocations[0].raw_command_text == "SELECT * FROM SOrder"
    assert invocations[0].evidence is InvocationEvidence.PROVEN


def test_source_wrapper_without_method_semantics_does_not_infer_mode_from_legacy_facts() -> None:
    """Source-backed wrappers require implementation semantics instead of legacy mode hints."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        receiver_implementation_identity="DbWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        command_type_mode="stored_procedure",
        command_text="usp_SaveOrder",
        connection_expression="conn",
        wrapper_reaches_stored_procedure_sink=True,
        wrapper_method_semantics="unknown",
    )

    invocation = gateway.resolve_direct_invocations("WrapperFixture.cs", [raw])[0]

    assert invocation.invocation_mode == "unresolved"
    assert invocation.method_semantics == "unresolved"
    assert invocation.reason == "wrapper_mode_unresolved"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED


def test_source_wrapper_without_receiver_binding_stays_unresolved() -> None:
    """A declared receiver type alone cannot select a source implementation."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_receiver_type="IWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        wrapper_method_semantics="fixed_stored_procedure",
        command_type_mode="stored_procedure",
        command_text="usp_SaveOrder",
        connection_expression="conn",
        wrapper_reaches_stored_procedure_sink=True,
    )

    invocation = gateway.resolve_direct_invocations("WrapperFixture.cs", [raw])[0]

    assert invocation.invocation_mode == "unresolved"
    assert invocation.reason == "receiver_binding_unresolved"
    assert invocation.evidence is InvocationEvidence.UNRESOLVED


def test_source_wrapper_null_constructor_connection_is_not_proven() -> None:
    """A null constructor argument cannot be attributed to a connection source."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"wrapper": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        receiver_implementation_identity="DbWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        wrapper_method_semantics="fixed_stored_procedure",
        command_text="usp_SaveOrder",
        connection_expression=None,
        terminal_sink="ExecuteNonQuery",
    )

    invocation = gateway.resolve_direct_invocations("WrapperFixture.cs", [raw])[0]

    assert invocation.database is None
    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "connection_source_unresolved"
    assert invocation.procedure_name == "usp_saveorder"


def test_dynamic_source_wrapper_preserves_semantics_and_connection_metadata() -> None:
    """Dynamic source-wrapper targets remain unresolved without dropping source facts."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        receiver_implementation_identity="DbWrapper",
        wrapper_source_available=True,
        wrapper_mode="stored_procedure",
        wrapper_method_semantics="fixed_stored_procedure",
        command_text_kind="dynamic",
        command_text=None,
        connection_expression="conn",
        terminal_sink="ExecuteNonQuery",
        wrapper_method_identity="DbWrapper.Execute(string)",
        wrapper_method_arity=1,
        wrapper_parameter_types=["string"],
    )

    invocation = gateway.resolve_direct_invocations("WrapperFixture.cs", [raw])[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "dynamic_command_text"
    assert invocation.method_semantics == "fixed_stored_procedure"
    assert invocation.invocation_mode == "stored_procedure"
    assert invocation.terminal_sink == "ExecuteNonQuery"
    assert invocation.connection_expression == "conn"
    assert invocation.database == "OrdersDb"


def test_external_dynamic_wrapper_preserves_contract_metadata() -> None:
    """External dynamic calls retain selected contract facts in unresolved output."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contract=_sqlobject_wrapper_contract(),
    )
    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        wrapper_method_name="ExeProcNon",
        wrapper_receiver_type="SQLObject",
        wrapper_source_available=False,
        wrapper_mode="stored_procedure",
        command_text_kind="dynamic",
        command_text=None,
        connection_expression="conn",
        terminal_sink="ExecuteNonQuery",
    )

    invocation = gateway.resolve_direct_invocations("WrapperFixture.cs", [raw])[0]

    assert invocation.evidence is InvocationEvidence.UNRESOLVED
    assert invocation.reason == "dynamic_command_text"
    assert invocation.method_semantics == "fixed_stored_procedure"
    assert invocation.invocation_mode == "stored_procedure"
    assert invocation.terminal_sink == "ExecuteNonQuery"
    assert invocation.connection_expression == "conn"
    assert invocation.database == "OrdersDb"


def test_source_backed_call_site_unknown_mode_stays_unresolved() -> None:
    """A source call-site wrapper must not default an unknown mode to inline SQL."""
    catalog = SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]})
    gateway = CSharpAnalysisGateway(catalog, connection_sources={"conn": "OrdersDb"})

    raw = _raw_invocation(
        invocation_kind="source_wrapper",
        command_text="usp_SaveOrder",
        wrapper_method_name="CreateTable",
        wrapper_receiver_type="SQLObject",
        receiver_implementation_identity="SQLObject",
        wrapper_source_available=True,
        wrapper_reaches_stored_procedure_sink=True,
        wrapper_mode="unknown",
        wrapper_method_semantics="call_site",
        command_type_mode="unknown",
        connection_expression="conn",
    )

    invocations = gateway.resolve_direct_invocations("f.cs", [raw])
    assert len(invocations) == 1
    assert invocations[0].invocation_mode == "unresolved"
    assert invocations[0].method_semantics == "call_site"
    assert invocations[0].reason == "wrapper_mode_unresolved"
    assert invocations[0].evidence is InvocationEvidence.UNRESOLVED


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


def test_static_analyzer_host_keeps_direct_sqlclient_facts_alongside_ui_helpers() -> None:
    """UI helpers in one class must not hide a real direct SqlClient call."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "MixedCalls.cs"
        source_path.write_text(
            "public class MixedCalls {\n"
            "    private void Run() {\n"
            "        CommonFunction.AlertMsg(this, \"done\", true);\n"
            "        ScriptManager.RegisterStartupScript(this.Page, typeof(string), \"key\", \"alert(1)\", true);\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        cmd.ExecuteReader();\n"
            "        var cmd2 = new SqlCommand(\"initial\", conn);\n"
            "        cmd2.CommandText = \"UPDATE SOrder SET Status = 1\";\n"
            "        cmd2.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 2
        raw = next(item for item in raw_invocations if item["receiver_name"] == "cmd")
        assert raw["invocation_kind"] == "direct_sqlclient"
        assert raw["receiver_type"] == "SqlCommand"
        assert raw["receiver_name"] == "cmd"
        assert raw["command_text_argument"] == '"SELECT * FROM SOrder"'
        assert raw["command_text_literal"] == "SELECT * FROM SOrder"
        assert raw["connection_expression"] == "conn"
        assert raw["terminal_sink"] == "ExecuteReader"

        reassigned = next(
            item for item in raw_invocations if item["receiver_name"] == "cmd2"
        )
        assert reassigned["command_text_argument"] == '"UPDATE SOrder SET Status = 1"'
        assert reassigned["command_text_literal"] == "UPDATE SOrder SET Status = 1"
        assert reassigned["terminal_sink"] == "ExecuteNonQuery"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocations = gateway.resolve_direct_invocations("MixedCalls.cs", raw_invocations)

        assert len(invocations) == 2
        assert all(invocation.invocation_mode == "inline_sql" for invocation in invocations)
        assert all(invocation.evidence is InvocationEvidence.PROVEN for invocation in invocations)
        assert {
            invocation.raw_command_text: invocation.terminal_sink
            for invocation in invocations
        } == {
            "SELECT * FROM SOrder": "ExecuteReader",
            "UPDATE SOrder SET Status = 1": "ExecuteNonQuery",
        }


def test_static_analyzer_host_preserves_unknown_command_type_mode() -> None:
    """A runtime CommandType assignment cannot be promoted to inline SQL."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "UnknownCommandType.cs"
        source_path.write_text(
            "public class UnknownCommandType {\n"
            "    private void Run(object mode) {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        cmd.CommandType = mode;\n"
            "        cmd.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["command_type_mode"] == "unknown"
        assert raw["command_type_stored_procedure"] is False
        assert raw["terminal_sink"] == "ExecuteReader"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "UnknownCommandType.cs", raw_invocations
        )[0]
        assert invocation.invocation_mode == "unresolved"
        assert invocation_wrapper_evidence_fields(invocation)["command_type_mode"] == "unknown"
        assert invocation.reason == "command_type_unresolved"


def test_static_analyzer_host_uses_the_last_command_type_assignment() -> None:
    """A later Text assignment overrides an earlier StoredProcedure assignment."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "CommandTypeOverride.cs"
        source_path.write_text(
            "public class CommandTypeOverride {\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        cmd.CommandType = CommandType.StoredProcedure;\n"
            "        cmd.CommandType = CommandType.Text;\n"
            "        cmd.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["command_type_mode"] == "text"
        assert raw_invocations[0]["command_type_stored_procedure"] is False

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "CommandTypeOverride.cs", raw_invocations
        )[0]
        assert invocation.invocation_mode == "inline_sql"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_wrapper_semantics_use_effective_command_type_assignment() -> None:
    """A later unconditional Text assignment overrides a conditional SP assignment."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class WrapperWithOverride {
    private readonly SqlConnection connection;
    public WrapperWithOverride(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText, string mode) {
        var command = new SqlCommand(commandText, connection);
        if (mode == "SP")
            command.CommandType = CommandType.StoredProcedure;
        command.CommandType = CommandType.Text;
        command.ExecuteNonQuery();
    }
}

public class OverridePage {
    private void Run(SqlConnection connection) {
        var wrapper = new WrapperWithOverride(connection);
        wrapper.Execute("usp_Override", "SP");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "WrapperOverrideFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["wrapper_method_semantics"] == "fixed_inline_sql"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Override"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "WrapperOverrideFixture.cs", raw_invocations
        )[0]
        assert invocation.invocation_mode == "inline_sql"
        assert invocation.procedure_name is None
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_reads_command_type_from_object_initializer() -> None:
    """An object initializer still supplies fixed StoredProcedure semantics."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class ObjectInitializerWrapper {
    private readonly SqlConnection connection;

    public ObjectInitializerWrapper(SqlConnection connection) {
        this.connection = connection;
    }

    public void Execute(string commandText) {
        var command = new SqlCommand(commandText, connection) {
            CommandType = CommandType.StoredProcedure
        };
        command.ExecuteNonQuery();
    }
}

public class ObjectInitializerPage {
    private void Run(SqlConnection connection) {
        var wrapper = new ObjectInitializerWrapper(connection);
        wrapper.Execute("usp_ObjectInitializer");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "ObjectInitializerFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["wrapper_method_semantics"] == "fixed_stored_procedure"
        assert raw["command_type_mode"] == "stored_procedure"
        assert raw["wrapper_terminal_sink"] == "ExecuteNonQuery"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_ObjectInitializer"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "ObjectInitializerFixture.cs", raw_invocations
        )[0]
        assert invocation.invocation_mode == "stored_procedure"
        assert invocation.evidence is InvocationEvidence.PROVEN


def test_static_analyzer_host_keeps_member_and_fluent_sqlcommand_receivers() -> None:
    """Member-assigned and fluent commands retain their sink facts."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "ReceiverShapes.cs"
        source_path.write_text(
            "public class ReceiverShapes {\n"
            "    private SqlCommand cmd;\n"
            "    private void Run() {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        this.cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        this.cmd.ExecuteReader();\n"
            "        new SqlCommand(\"UPDATE SOrder SET Status = 1\", conn).ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert {
            invocation["command_text_literal"]: (
                invocation["receiver_name"],
                invocation["terminal_sink"],
            )
            for invocation in raw_invocations
        } == {
            "SELECT * FROM SOrder": ("this.cmd", "ExecuteReader"),
            "UPDATE SOrder SET Status = 1": (None, "ExecuteNonQuery"),
        }


def test_static_analyzer_host_retains_terminal_sink_branch_context() -> None:
    """A unique conditional sink contributes its predicate to raw evidence."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "ConditionalSink.cs"
        source_path.write_text(
            "public class ConditionalSink {\n"
            "    private void Run(bool read) {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        if (read) cmd.ExecuteReader();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0]["branch_context"] == ["if (read)"]


def test_static_analyzer_host_matches_terminal_sinks_to_command_branches() -> None:
    """Branch-local direct commands retain their matching ADO.NET sink."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "BranchCalls.cs"
        source_path.write_text(
            "public class BranchCalls {\n"
            "    private void Run(bool read) {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        if (read) {\n"
            "            var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "            cmd.ExecuteReader();\n"
            "        } else {\n"
            "            var cmd = new SqlCommand(\"DELETE FROM SOrder\", conn);\n"
            "            cmd.ExecuteNonQuery();\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 2
        assert {
            invocation["command_text_literal"]: invocation["terminal_sink"]
            for invocation in raw_invocations
        } == {
            "SELECT * FROM SOrder": "ExecuteReader",
            "DELETE FROM SOrder": "ExecuteNonQuery",
        }


def test_static_analyzer_host_leaves_ambiguous_terminal_sinks_unresolved() -> None:
    """Different branch sinks must not be collapsed to the first sink found."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "AmbiguousSink.cs"
        source_path.write_text(
            "public class AmbiguousSink {\n"
            "    private void Run(bool read) {\n"
            "        var conn = new SqlConnection(\"x\");\n"
            "        var cmd = new SqlCommand(\"SELECT * FROM SOrder\", conn);\n"
            "        if (read) cmd.ExecuteReader();\n"
            "        else cmd.ExecuteNonQuery();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = result["db_invocations"]

        assert len(raw_invocations) == 1
        assert raw_invocations[0].get("terminal_sink") in (None, "")

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"conn": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "AmbiguousSink.cs", raw_invocations
        )[0]
        assert invocation.evidence is InvocationEvidence.UNRESOLVED
        assert invocation.reason == "terminal_sink_unresolved"


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
            "PreviewData",
            "DynamicData",
        }
        by_method = {invocation["method_name"]: invocation for invocation in raw_invocations}
        assert by_method["EnableData"]["wrapper_mode"] == "stored_procedure"
        assert by_method["EnableData"]["command_type_stored_procedure"] is True
        assert by_method["SaveData"]["wrapper_mode"] == "stored_procedure"
        assert by_method["SaveData"]["command_type_stored_procedure"] is True
        assert by_method["PreviewData"]["wrapper_mode"] == "inline_sql"
        assert by_method["PreviewData"]["command_type_stored_procedure"] is False
        assert by_method["PreviewData"]["command_text"] == "SELECT * FROM SOrder"
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
        # auto-select and receiver-name inference are removed from the
        # contract domain and runtime path (spec item 70): the SQLObject
        # contract must be selected explicitly, even though its
        # receiver_types uniquely matches "SQLObject".
        observations = {
            invocation["method_name"]: gateway.reconcile_wrapper_observation(
                "SqlObjectPage.cs",
                invocation,
                scan_root=temp_dir,
                explicit_contract="sqlobject",
            )
            for invocation in raw_invocations
        }
        assert observations["EnableData"]["wrapper_receiver_type"] == "SQLObject"
        assert observations["EnableData"]["wrapper_status"] == "explicit_selected"
        assert observations["EnableData"]["evidence_status"] == "proven"
        assert observations["SaveData"]["wrapper_contract_mode"] == "call_site"
        assert observations["SaveData"]["stored_procedure_mode"] is True
        assert observations["SaveData"]["evidence_status"] == "proven"
        assert observations["PreviewData"]["wrapper_status"] == "explicit_selected"
        assert observations["PreviewData"]["invocation_mode"] == "inline_sql"
        assert observations["PreviewData"]["evidence_status"] == "proven"
        assert observations["DynamicData"]["wrapper_status"] == "explicit_selected"
        assert observations["DynamicData"]["evidence_status"] == "unresolved"
        assert observations["DynamicData"]["evidence_reason"] == "dynamic_command_text"


def test_static_analyzer_host_applies_sqlobject_default_text_without_sp_mode() -> None:
    """SQLObject table and dataset calls need explicit SP evidence to enter SP mode."""
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "SqlObjectDefaultPage.cs"
        source_path.write_text(
            "public class SqlObjectDefaultPage {\n"
            "    private void Run(string mode) {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.CreateTable(\"usp_DefaultTable\", null, \"table\");\n"
            "        obj.CreateDataSet(\"usp_DefaultDataSet\");\n"
            "        obj.CreateTable(\"usp_ExplicitTable\", null, \"table\", \"SP\");\n"
            "        obj.CreateDataSet(\"usp_DynamicMode\", mode);\n"
            "    }\n"
            "    private object GetExternalSqlObject() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]
        raw_by_text = {item["command_text"]: item for item in raw_invocations}

        assert raw_by_text["usp_DefaultTable"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["usp_DefaultDataSet"]["wrapper_mode"] == "inline_sql"
        assert raw_by_text["usp_ExplicitTable"]["wrapper_mode"] == "stored_procedure"
        assert raw_by_text["usp_DynamicMode"]["wrapper_mode"] == "unknown"

        # The scanner now reports argument count for every external/unavailable
        # wrapper call (previously always null), so a contract entry must
        # declare its own arity per overload to stay resolvable -- a
        # signature-less entry can no longer silently match every call site.
        contract = {
            "name": "sqlobject",
            "receiver_types": ["SQLObject"],
            "methods": {
                "CreateTable": [
                    {"arity": 3, "mode": "call_site", "sink": "ExecuteReader"},
                    {"arity": 4, "mode": "call_site", "sink": "ExecuteReader"},
                ],
                "CreateDataSet": [
                    {"arity": 1, "mode": "call_site", "sink": "ExecuteReader"},
                    {"arity": 2, "mode": "call_site", "sink": "ExecuteReader"},
                ],
            },
        }
        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_ExplicitTable"]}),
            connection_sources={"obj": "OrdersDb"},
            external_wrapper_contract=contract,
        )
        invocations = gateway.resolve_direct_invocations(
            "SqlObjectDefaultPage.cs",
            raw_invocations,
        )
        by_text = {invocation.raw_command_text: invocation for invocation in invocations}

        for command_text in ("usp_DefaultTable", "usp_DefaultDataSet"):
            invocation = by_text[command_text]
            assert invocation.invocation_mode == "inline_sql"
            assert invocation.procedure_name is None
            assert invocation.evidence is InvocationEvidence.PROVEN

        explicit = by_text["usp_ExplicitTable"]
        assert explicit.invocation_mode == "stored_procedure"
        assert explicit.procedure_name == "usp_explicittable"
        assert explicit.evidence is InvocationEvidence.PROVEN

        dynamic = by_text["usp_DynamicMode"]
        assert dynamic.invocation_mode == "unresolved"
        assert dynamic.reason == "wrapper_mode_unresolved"
        assert dynamic.evidence is InvocationEvidence.UNRESOLVED


def test_static_analyzer_host_preserves_external_inline_non_prefix_and_dynamic_facts() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "ExternalWrapperPage.cs"
        source_path.write_text(
            "public class ExternalWrapperPage {\n"
            "    private void InlineData() {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.Execute(\"SELECT * FROM SOrder\");\n"
            "    }\n"
            "    private void NonPrefixData() {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.Execute(\"SaveOrder\");\n"
            "    }\n"
            "    private void DynamicData(string commandText) {\n"
            "        SQLObject obj = GetExternalSqlObject();\n"
            "        obj.Execute(commandText);\n"
            "    }\n"
            "    private object GetExternalSqlObject() { return null; }\n"
            "}\n",
            encoding="utf-8",
        )

        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert {item["method_name"] for item in raw_invocations} == {
            "InlineData",
            "NonPrefixData",
            "DynamicData",
        }
        by_method = {item["method_name"]: item for item in raw_invocations}
        assert all(item["wrapper_source_available"] is False for item in raw_invocations)
        assert by_method["InlineData"]["command_text"] == "SELECT * FROM SOrder"
        assert by_method["InlineData"]["wrapper_mode"] == "unknown"
        assert by_method["NonPrefixData"]["command_text"] == "SaveOrder"
        assert by_method["NonPrefixData"]["wrapper_mode"] == "unknown"
        assert by_method["DynamicData"]["command_text"] is None
        assert by_method["DynamicData"]["command_text_kind"] == "dynamic"
        assert {item["wrapper_receiver_type"] for item in raw_invocations} == {"SQLObject"}

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_SaveOrder"]}),
            connection_sources={"obj": "OrdersDb"},
        )
        contract = {
            "name": "external-execute",
            "receiver_types": ["SQLObject"],
            "methods": {
                "Execute": {
                    "arity": 1,
                    "mode": "inline_sql",
                    "sink": "ExecuteReader",
                }
            },
        }
        invocations = gateway.resolve_direct_invocations(
            "ExternalWrapperPage.cs",
            raw_invocations,
            explicit_contract=contract,
        )
        by_method = {invocation.method_name: invocation for invocation in invocations}
        assert by_method["InlineData"].evidence is InvocationEvidence.PROVEN
        assert by_method["InlineData"].invocation_mode == "inline_sql"
        assert by_method["NonPrefixData"].evidence is InvocationEvidence.PROVEN
        assert by_method["NonPrefixData"].raw_command_text == "SaveOrder"
        assert by_method["DynamicData"].evidence is InvocationEvidence.UNRESOLVED
        assert by_method["DynamicData"].reason == "dynamic_command_text"


def test_static_analyzer_host_maps_named_source_wrapper_arguments() -> None:
    host = StaticAnalyzerHost.for_project(PROJECT_ROOT)
    host.ensure_ready()

    source = """
using System.Data;
using System.Data.SqlClient;

public class NamedWrapper {
    private readonly SqlConnection connection;
    public NamedWrapper(SqlConnection connection) { this.connection = connection; }

    public void Execute(string commandText, bool storedProcedure) {
        var command = new SqlCommand(commandText, connection);
        if (storedProcedure) {
            command.CommandType = CommandType.StoredProcedure;
        } else {
            command.CommandType = CommandType.Text;
        }
        command.ExecuteReader();
    }
}

public class NamedWrapperPage {
    private void Run(SqlConnection connection) {
        var wrapper = new NamedWrapper(connection);
        wrapper.Execute(storedProcedure: true, commandText: "usp_Named");
    }
}
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "NamedWrapperFixture.cs"
        source_path.write_text(source, encoding="utf-8")
        result = host.analyze_csharp(source_path)
        raw_invocations = [
            item
            for item in result["db_invocations"]
            if item.get("invocation_kind") == "source_wrapper"
        ]

        assert len(raw_invocations) == 1
        raw = raw_invocations[0]
        assert raw["command_text_kind"] == "literal"
        assert raw["command_text"] == "usp_Named"
        assert raw["command_text_argument"] == '"usp_Named"'
        assert raw["command_type_stored_procedure"] is True
        assert raw["wrapper_mode"] == "stored_procedure"
        assert raw["wrapper_method_semantics"] == "call_site"

        gateway = CSharpAnalysisGateway(
            SpCatalog.from_databases({"OrdersDb": ["usp_Named"]}),
            connection_sources={"connection": "OrdersDb"},
        )
        invocation = gateway.resolve_direct_invocations(
            "NamedWrapperFixture.cs",
            raw_invocations,
        )[0]
        assert invocation.evidence is InvocationEvidence.PROVEN
        assert invocation.procedure_name == "usp_named"
        assert invocation.invocation_mode == "stored_procedure"
        assert invocation.method_semantics == "call_site"


if __name__ == "__main__":
    test_normalize_procedure_name_strips_schema_and_brackets()
    test_explicit_stored_procedure_type_with_catalog_hit_is_proven()
    test_inline_sql_without_stored_procedure_type_is_a_database_invocation()
    test_dynamic_command_text_is_unresolved()
    test_resolved_database_without_catalog_hit_is_unresolved_not_guessed()
    test_unknown_connection_source_unique_across_catalogs_is_likely()
    test_unknown_connection_source_ambiguous_across_catalogs_is_unresolved()
    test_unknown_connection_source_and_unknown_name_is_unresolved()
    test_gateway_detects_real_direct_sqlclient_invocation_via_static_analyzer_host()
    print("CSharpAnalysisGateway tests passed")

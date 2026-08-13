from __future__ import annotations

import json
from pathlib import Path

from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.external_wrapper_contracts import (
    canonical_contract_behavior_signature,
    compare_implementation_snapshot,
    compute_contract_fingerprint,
)
from service.contract_acceptance import (
    ContractAcceptanceError,
    accept_external_wrapper_contract,
)


def _operation(
    *,
    identity: str = "Vendor.Data.SQLObject.Run(System.String)",
    mode: str = "stored_procedure",
    sink: str = "ExecuteNonQuery",
    revision: str = "1.0.0",
) -> dict:
    return {
        "method_identity": identity,
        "method_name": "Run",
        "method_arity": 1,
        "parameter_types": ["System.String"],
        "argument_roles": {"command_text": 0},
        "effective_command_semantics": mode,
        "terminal_sink": sink,
        "connection_behavior_boundary": "constructor_connection",
        "branch_rules": [{"mode": mode, "sink": sink}],
        "assembly_revision": revision,
        "body_complete": True,
    }


def _snapshot(*operations: dict, complete: bool = True) -> dict:
    return {
        "artifact_identity": "vendor-data.dll@sha256:abc",
        "assembly_identity": "Vendor.Data",
        "assembly_revision": "1.0.0",
        "behavior_surface_unit": "Vendor.Data.SQLObject",
        "complete": complete,
        "methods": list(operations),
        "helper_operations_complete": True,
        "inherited_operations_complete": True,
    }


def _versioned_proposal(name: str, snapshot: dict) -> dict:
    operation = snapshot["methods"][0]
    return {
        "name": name,
        "receiver_types": ["Vendor.Data.SQLObject"],
        "implementation_snapshot": snapshot,
        "methods": {
            "Run": {
                "mode": operation["effective_command_semantics"],
                "sink": operation["terminal_sink"],
                "method_arity": 1,
                "parameter_types": ["System.String"],
            }
        },
    }


def test_behavior_signature_ignores_discovery_order_and_source_provenance() -> None:
    first = {
        "name": "first",
        "receiver_types": ["Vendor.Data.SQLObject"],
        "methods": [_operation()],
        "source_formatting": "pretty",
        "discovery_order": ["Run"],
    }
    second = {
        "name": "second",
        "receiver_types": ["Other.Name"],
        "methods": [_operation(identity="Vendor.Data.SQLObject.Run( System.String )")],
        "source_formatting": "compact",
        "discovery_order": ["helper", "Run"],
    }

    assert canonical_contract_behavior_signature(first) == canonical_contract_behavior_signature(second)
    assert compute_contract_fingerprint(first) == compute_contract_fingerprint(second)


def test_behavior_change_creates_a_new_fingerprint() -> None:
    stored_procedure = _snapshot(_operation())
    inline_sql = _snapshot(_operation(mode="inline_sql", sink="ExecuteReader"))

    assert compute_contract_fingerprint(stored_procedure) != compute_contract_fingerprint(inline_sql)


def test_distinct_implementation_boundaries_do_not_share_a_fingerprint() -> None:
    first = _snapshot(_operation())
    second = {
        **first,
        "assembly_identity": "Vendor.Other",
        "behavior_surface_unit": "Vendor.Other.SQLObject",
    }

    assert canonical_contract_behavior_signature(first) == canonical_contract_behavior_signature(second)
    assert compute_contract_fingerprint(first) != compute_contract_fingerprint(second)


def test_incomplete_and_mixed_revision_snapshots_are_review_only() -> None:
    incomplete = compare_implementation_snapshot(_snapshot(_operation(), complete=False))
    mixed = compare_implementation_snapshot(
        {
            **_snapshot(_operation()),
            "methods": [_operation(revision="1.0.0"), _operation(identity="Vendor.Data.SQLObject.Read(System.String)", revision="2.0.0")],
        }
    )

    assert incomplete["status"] == "review"
    assert "incomplete_snapshot" in incomplete["unresolved_reasons"]
    assert mixed["status"] == "review"
    assert "mixed_assembly_revision" in mixed["unresolved_reasons"]


def test_missing_surface_roles_and_unknown_overloads_are_review_only() -> None:
    missing_roles = _snapshot(_operation())
    missing_roles["methods"][0].pop("argument_roles")
    unknown_overloads = _snapshot(_operation())
    unknown_overloads["unknown_overloads"] = ["Vendor.Data.SQLObject.Run(?)"]

    missing_result = compare_implementation_snapshot(missing_roles)
    overload_result = compare_implementation_snapshot(unknown_overloads)

    assert missing_result["status"] == "review"
    assert "argument_roles_missing" in missing_result["unresolved_reasons"]
    assert "Vendor.Data.SQLObject.Run(?)" not in missing_result["unresolved_operations"]
    assert overload_result["status"] == "review"
    assert "unknown_overload" in overload_result["unresolved_reasons"]


def test_contract_acceptance_preserves_overload_semantics(tmp_path: Path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")

    result = accept_external_wrapper_contract(
        {
            "name": "vendor-overloads",
            "receiver_types": ["Vendor.Data.SQLObject"],
            "methods": {
                "Run": [
                    {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                        "method_arity": 1,
                        "parameter_types": ["System.String"],
                    },
                    {
                        "mode": "inline_sql",
                        "sink": "ExecuteReader",
                        "method_arity": 2,
                        "parameter_types": ["System.String", "System.Boolean"],
                    },
                ]
            },
        },
        registry_path=registry_path,
    )

    assert result["registry_diff"]["after"]["contracts"]["vendor-overloads"]["methods"]["Run"] == [
        {
            "mode": "stored_procedure",
            "sink": "ExecuteNonQuery",
            "method_arity": 1,
            "parameter_types": ["System.String"],
        },
        {
            "mode": "inline_sql",
            "sink": "ExecuteReader",
            "method_arity": 2,
            "parameter_types": ["System.String", "System.Boolean"],
        },
    ]


def test_snapshot_and_method_projection_conflicts_are_review_only(tmp_path: Path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    proposal = _versioned_proposal("vendor-conflict", _snapshot(_operation()))
    proposal["methods"]["Run"]["mode"] = "inline_sql"

    try:
        accept_external_wrapper_contract(
            proposal,
            registry_path=registry_path,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "incomplete_implementation_snapshot"
        assert "conflicting_semantics" in exc.details
    else:
        raise AssertionError("conflicting snapshot and method semantics must stay review-only")


def test_non_database_utility_is_not_reported_as_missing_surface_operation() -> None:
    snapshot = _snapshot(_operation())
    snapshot["methods"].append(
        {
            "method_identity": "Vendor.Data.SQLObject.FormatLabel(System.String)",
            "method_name": "FormatLabel",
            "database_operation": False,
            "body_complete": False,
        }
    )

    result = compare_implementation_snapshot(snapshot)

    assert result["status"] == "accepted"
    assert result["unresolved_operations"] == []


def test_acceptance_appends_changed_versioned_contract_without_mutating_old_revision(tmp_path: Path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")

    first = accept_external_wrapper_contract(
        _versioned_proposal("vendor", _snapshot(_operation())),
        registry_path=registry_path,
        apply=True,
    )
    first_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    first_name = first["contract"]
    first_entry = first_registry["contracts"][first_name]

    second = accept_external_wrapper_contract(
        _versioned_proposal(
            "vendor",
            _snapshot(_operation(mode="inline_sql", sink="ExecuteReader")),
        ),
        registry_path=registry_path,
        apply=True,
    )
    second_registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert second["contract"] != first_name
    assert len(second_registry["contracts"]) == 2
    assert second_registry["contracts"][first_name] == first_entry

    third = accept_external_wrapper_contract(
        _versioned_proposal("vendor", _snapshot(_operation())),
        registry_path=registry_path,
        apply=True,
    )
    third_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert third["contract"] == first_name
    assert third["comparison_report"]["comparison_report_reference"] != first["comparison_report"][
        "comparison_report_reference"
    ]
    assert len(third_registry["comparison_report_history"]) == 3
    assert (
        third_registry["contracts"][first_name]["comparison_reports"]["latest"]
        == third["comparison_report"]["latest_reference"]
    )


def test_source_semantics_win_and_record_contract_conflict() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "vendor",
        "contract_fingerprint": "fp-vendor",
        "signature_version": "contract-behavior-v1",
        "receiver_types": ["Vendor.Data.SQLObject"],
        "methods": {
            "Run": {
                "mode": "stored_procedure",
                "sink": "ExecuteNonQuery",
                "method_arity": 1,
                "parameter_types": ["System.String"],
            }
        },
    }
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "Page",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "Vendor.Data.SQLObject",
        "wrapper_source_available": True,
        "receiver_binding": {
            "implementation_identity": "Vendor.Data.SQLObject",
            "assembly_identity": "Vendor.Data",
            "assembly_revision": "1.0.0",
        },
        "wrapper_method_semantics": "fixed_inline_sql",
        "wrapper_method_arity": 1,
        "wrapper_parameter_types": ["System.String"],
        "wrapper_terminal_sink": "ExecuteReader",
        "wrapper_mode": "inline_sql",
        "command_text_kind": "literal",
        "command_text": "SELECT 1",
        "connection_expression": "conn",
        "start_offset": 1,
        "end_offset": 20,
    }

    reconciliation = gateway.reconcile_wrapper(
        "Page.cs",
        raw,
        explicit_contract=contract,
    )

    payload = reconciliation.to_dict()
    assert reconciliation.stored_procedure_mode is False
    assert payload["source_contract_conflict"] is True
    assert payload["contract_fingerprint"] == "fp-vendor"
    assert "method_semantics_conflict" in payload["source_contract_conflict_reason"]


def test_external_invocation_retains_contract_revision_provenance() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
        connection_sources={"conn": "OrdersDb"},
    )
    contract = {
        "name": "vendor",
        "contract_fingerprint": "fp-vendor",
        "signature_version": "contract-behavior-v1",
        "status": "accepted",
        "implementation_snapshot_reference": "snapshot-vendor-1",
        "comparison_report_reference": "comparison-vendor-1",
        "receiver_types": ["Vendor.Data.SQLObject"],
        "methods": {
            "Run": {
                "mode": "stored_procedure",
                "sink": "ExecuteNonQuery",
                "method_arity": 1,
                "parameter_types": ["System.String"],
            }
        },
    }
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "Page",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "Vendor.Data.SQLObject",
        "wrapper_source_available": False,
        "wrapper_method_arity": 1,
        "wrapper_parameter_types": ["System.String"],
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_Save",
        "connection_expression": "conn",
        "start_offset": 1,
        "end_offset": 20,
        "terminal_sink": "ExecuteNonQuery",
    }

    invocation = gateway.resolve_direct_invocations(
        "Page.cs",
        [raw],
        explicit_contract=contract,
    )[0]
    fields = gateway.reconcile_wrapper_observation(
        "Page.cs",
        raw,
        explicit_contract=contract,
    )

    assert invocation.contract_fingerprint == "fp-vendor"
    assert invocation.contract_signature_version == "contract-behavior-v1"
    assert invocation.contract_lifecycle_status == "accepted"
    assert invocation.implementation_snapshot_reference == "snapshot-vendor-1"
    assert invocation.comparison_report_reference == "comparison-vendor-1"
    assert fields["contract_fingerprint"] == "fp-vendor"
    assert fields["contract_status"] == "accepted"


def test_bound_implementation_identity_without_selector_stays_unresolved() -> None:
    """A concrete binding cannot select a registry contract implicitly."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={
            "vendor-one": {
                "name": "vendor-one",
                "receiver_types": ["Vendor.One.SQLObject"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                        "method_arity": 1,
                        "parameter_types": ["System.String"],
                    }
                },
            },
            "vendor-two": {
                "name": "vendor-two",
                "receiver_types": ["Vendor.Two.SQLObject"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                        "method_arity": 1,
                        "parameter_types": ["System.String"],
                    }
                },
            },
        },
    )
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "Page",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "SQLObject",
        "receiver_binding": {
            "implementation_identity": "Vendor.Two.SQLObject",
            "assembly_identity": "Vendor.Two.Data",
            "assembly_revision": "2.0.0",
        },
        "wrapper_source_available": False,
        "wrapper_method_arity": 1,
        "wrapper_parameter_types": ["System.String"],
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_Save",
        "connection_expression": "conn",
        "start_offset": 1,
        "end_offset": 20,
        "terminal_sink": "ExecuteNonQuery",
    }

    invocation = gateway.resolve_direct_invocations("Page.cs", [raw])[0]

    assert invocation.wrapper_contract == ""
    assert invocation.wrapper_selection_source == "unresolved_receiver_type"
    assert invocation.wrapper_status == "unresolved_contract"
    assert invocation.wrapper_review_candidate is True
    assert invocation.evidence.value == "unresolved"


def test_implementation_identity_without_assembly_identity_stays_unresolved() -> None:
    """A traced implementation identity alone, without an assembly identity,
    is not a genuine Receiver Implementation Binding (spec item 168) -- it
    must not select a contract, the same as a bare receiver type name."""
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={
            "vendor-two": {
                "name": "vendor-two",
                "receiver_types": ["Vendor.Two.SQLObject"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                        "method_arity": 1,
                        "parameter_types": ["System.String"],
                    }
                },
            },
        },
    )
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "Page",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "SQLObject",
        "receiver_binding": {
            "implementation_identity": "Vendor.Two.SQLObject",
        },
        "wrapper_source_available": False,
        "wrapper_method_arity": 1,
        "wrapper_parameter_types": ["System.String"],
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_Save",
        "connection_expression": "conn",
        "start_offset": 1,
        "end_offset": 20,
        "terminal_sink": "ExecuteNonQuery",
    }

    invocation = gateway.resolve_direct_invocations("Page.cs", [raw])[0]

    assert invocation.wrapper_contract == ""
    assert invocation.wrapper_unresolved_reason == "no_contract_matches_receiver_type"
    assert invocation.evidence.value == "unresolved"


def test_lifecycle_marked_legacy_contract_requires_explicit_selection() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({"OrdersDb": ["usp_Save"]}),
        connection_sources={"conn": "OrdersDb"},
        external_wrapper_contracts={
            "legacy": {
                "name": "legacy",
                "status": "legacy_unverified",
                "receiver_types": ["Vendor.Data.SQLObject"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                        "method_arity": 1,
                        "parameter_types": ["System.String"],
                    }
                },
            }
        },
    )
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "Page",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": "Vendor.Data.SQLObject",
        "wrapper_source_available": False,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_Save",
        "connection_expression": "conn",
        "start_offset": 1,
        "end_offset": 20,
        "terminal_sink": "ExecuteNonQuery",
    }

    unresolved = gateway.resolve_direct_invocations("Page.cs", [raw])[0]
    selected = gateway.resolve_direct_invocations(
        "Page.cs",
        [raw],
        explicit_contract="legacy",
    )[0]

    assert unresolved.reason == "wrapper_source_unavailable"
    assert unresolved.wrapper_unresolved_reason == "no_contract_matches_receiver_type"
    assert unresolved.wrapper_contract == ""
    assert selected.wrapper_contract == "legacy"
    assert selected.contract_lifecycle_status == "legacy_unverified"


def test_legacy_contract_apply_without_explicit_binding_is_rejected(tmp_path: Path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "legacy": {
                        "receiver_types": ["Vendor.Data.SQLObject"],
                        "methods": {
                            "Run": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteNonQuery",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        accept_external_wrapper_contract(
            {
                "name": "legacy",
                "receiver_types": ["Vendor.Data.SQLObject"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteNonQuery",
                    },
                    "Read": {
                        "mode": "inline_sql",
                        "sink": "ExecuteReader",
                    },
                },
            },
            registry_path=registry_path,
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "legacy_contract_requires_explicit_binding"
    else:
        raise AssertionError("legacy mutation without a selector must remain review-only")
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from types import SimpleNamespace

from service.contract_preflight import (
    normalize_contract_selector,
    run_contract_preflight,
)
from code_analyzer.csharp_analysis_gateway import CSharpAnalysisGateway, SpCatalog
from code_analyzer.external_wrapper_contracts import validate_implementation_snapshot
from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service


def test_selector_array_with_missing_member_is_unspecified_as_a_whole() -> None:
    result = normalize_contract_selector(
        ["alpha", "missing"],
        {"contracts": {"alpha": {}, "beta": {}}},
    )

    assert result.status == "unspecified"
    assert result.candidates == ()
    assert result.original == ["alpha", "missing"]
    assert result.reason == "selector_contract_not_found"


def test_malformed_selector_values_are_unspecified_with_diagnostics() -> None:
    registry = {"contracts": {"alpha": {}}}

    invalid_string = normalize_contract_selector("missing", registry)
    partial_array = normalize_contract_selector(["alpha", 42], registry)
    invalid_type = normalize_contract_selector({"name": "alpha"}, registry)

    assert invalid_string.status == "unspecified"
    assert invalid_string.reason == "selector_contract_not_found"
    assert partial_array.status == "unspecified"
    assert partial_array.reason == "selector_type_invalid"
    assert invalid_type.status == "unspecified"
    assert invalid_type.reason == "selector_type_invalid"


def _proposal(name: str, assembly: str) -> dict:
    return {
        "name": name,
        "receiver_types": [f"{assembly}.SQLObject"],
        "implementation_snapshot": {
            "artifact_identity": f"{assembly}.dll@sha256:abc",
            "assembly_identity": assembly,
            "assembly_revision": "1.0.0",
            "behavior_surface_unit": f"{assembly}.SQLObject",
            "complete": True,
            "methods": [
                {
                    "method_identity": f"{assembly}.SQLObject.Run(System.String)",
                    "method_name": "Run",
                    "method_arity": 1,
                    "parameter_types": ["System.String"],
                    "argument_roles": {"command_text": 0},
                    "effective_command_semantics": "stored_procedure",
                    "terminal_sink": "ExecuteNonQuery",
                    "connection_behavior_boundary": "constructor_connection",
                    "branch_rules": [
                        {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}
                    ],
                    "assembly_revision": "1.0.0",
                    "body_complete": True,
                }
            ],
            "helper_operations_complete": True,
            "inherited_operations_complete": True,
        },
    }


def test_complete_snapshot_is_staged_with_fingerprint_and_selector() -> None:
    snapshot = {
        "artifact_identity": "vendor-data.dll@sha256:abc",
        "assembly_identity": "Vendor.Data",
        "assembly_revision": "1.0.0",
        "behavior_surface_unit": "Vendor.Data.SQLObject",
        "complete": True,
        "methods": [
            {
                "method_identity": "Vendor.Data.SQLObject.Run(System.String)",
                "method_name": "Run",
                "method_arity": 1,
                "parameter_types": ["System.String"],
                "argument_roles": {"command_text": 0},
                "effective_command_semantics": "stored_procedure",
                "terminal_sink": "ExecuteNonQuery",
                "connection_behavior_boundary": "constructor_connection",
                "branch_rules": [
                    {"mode": "stored_procedure", "sink": "ExecuteNonQuery"}
                ],
                "assembly_revision": "1.0.0",
                "body_complete": True,
            }
        ],
        "helper_operations_complete": True,
        "inherited_operations_complete": True,
    }
    scan = SimpleNamespace(
        contract_proposals=[
            {
                "name": "vendor",
                "receiver_types": ["Vendor.Data.SQLObject"],
                "implementation_snapshot": snapshot,
            }
        ]
    )

    result = run_contract_preflight(
        [scan],
        selector=None,
        registry={"contracts": {}},
    )

    assert result.onboarding_status == "created"
    assert result.formal_selector == "vendor"
    entry = result.formal_registry["contracts"]["vendor"]
    assert entry["contract_fingerprint"] == result.proposals[0]["contract_fingerprint"]
    assert "evidence_kind" not in entry
    assert result.to_dict()["staged_selector"] == "vendor"


def test_decompiled_snapshot_validation_accepts_complete_surface() -> None:
    snapshot = _proposal("vendor", "Vendor.Data")["implementation_snapshot"]

    validation = validate_implementation_snapshot(snapshot)

    assert validation["complete"] is True
    assert validation["unresolved_reasons"] == []


def test_decompiled_snapshot_validation_reuses_existing_incomplete_reasons() -> None:
    snapshot = _proposal("vendor", "Vendor.Data")["implementation_snapshot"]
    snapshot["unknown_overloads"] = ["Vendor.Data.SQLObject.Run(?)"]
    snapshot["methods"][0].pop("connection_behavior_boundary")
    snapshot["methods"].append(
        {
            **snapshot["methods"][0],
            "method_identity": "Vendor.Data.SQLObject.Read(System.String)",
            "method_name": "Read",
            "assembly_revision": "2.0.0",
            "connection_behavior_boundary": "constructor_connection",
        }
    )

    validation = validate_implementation_snapshot(snapshot)

    assert validation["complete"] is False
    assert "unknown_overload" in validation["unresolved_reasons"]
    assert "connection_behavior_boundary_missing" in validation["unresolved_reasons"]
    assert "mixed_assembly_revision" in validation["unresolved_reasons"]


def test_decompiled_snapshot_validation_identifies_translation_problem() -> None:
    snapshot = _proposal("vendor", "Vendor.Data")["implementation_snapshot"]
    snapshot["methods"][0]["unresolved_reason"] = "decompiler_translation_problem"
    snapshot["translation_problem_methods"] = ["Run"]

    validation = validate_implementation_snapshot(snapshot)

    assert validation["complete"] is False
    assert "decompiler_translation_problem" in validation["unresolved_reasons"]


def test_decompiled_snapshot_validation_rejects_unclassified_public_method() -> None:
    """Ticket 02: a public method the decompiler could not classify makes the surface incomplete,
    and the rejection reason names that method."""
    snapshot = _proposal("vendor", "Vendor.Data")["implementation_snapshot"]
    snapshot["public_database_operations_complete"] = False
    snapshot["unclassified_public_methods"] = ["Vendor.Data.SQLObject.Open(System.String)"]

    validation = validate_implementation_snapshot(snapshot)

    assert validation["complete"] is False
    assert "database_behavior_surface_incomplete" in validation["unresolved_reasons"]
    assert (
        "unclassified_public_method:Vendor.Data.SQLObject.Open(System.String)"
        in validation["unresolved_reasons"]
    )


def test_preflight_rejects_a_snapshot_with_an_unclassified_public_method() -> None:
    """Ticket 02: Contract Preflight rejects a snapshot with an incomplete public database
    behavior surface, and never reaches the registry with a silent gap."""
    proposal = _proposal("vendor", "Vendor.Data")
    proposal["implementation_snapshot"]["public_database_operations_complete"] = False
    proposal["implementation_snapshot"]["unclassified_public_methods"] = [
        "Vendor.Data.SQLObject.Open(System.String)"
    ]
    scan = SimpleNamespace(contract_proposals=[proposal])

    result = run_contract_preflight([scan], selector=None, registry={"contracts": {}})

    assert result.onboarding_status != "created"
    assert "vendor" not in result.formal_registry.get("contracts", {})
    assert len(result.review_candidates) == 1
    reasons = result.review_candidates[0]["unresolved_reasons"]
    assert "database_behavior_surface_incomplete" in reasons
    assert any(
        reason == "unclassified_public_method:Vendor.Data.SQLObject.Open(System.String)"
        for reason in reasons
    )


def test_multiple_complete_proposals_are_sorted_and_equivalent_fingerprint_is_reused() -> None:
    proposals = [_proposal("zeta", "Vendor.Zeta"), _proposal("alpha", "Vendor.Alpha")]
    first = run_contract_preflight(
        [SimpleNamespace(contract_proposals=proposals)],
        registry={"contracts": {}},
    )

    assert first.formal_selector == ("alpha", "zeta")
    second = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[proposals[0]])],
        registry=first.formal_registry,
    )
    assert second.onboarding_status == "reused"
    assert second.formal_selector == "zeta"
    assert sorted(second.formal_registry["contracts"]) == ["alpha", "zeta"]


def test_duplicate_fingerprint_proposals_in_one_run_reuse_the_same_name() -> None:
    """A repeated fingerprint discovered multiple times in one run must collapse to
    one entry, not mint an escalating chain of "<name>-<fingerprint prefix>" revisions."""
    same_proposal = _proposal("sqlobject", "Vendor.Data")
    scan = SimpleNamespace(
        contract_proposals=[dict(same_proposal) for _ in range(4)]
    )

    result = run_contract_preflight([scan], selector=None, registry={"contracts": {}})

    assert list(result.formal_registry["contracts"]) == ["sqlobject"]
    assert [item["lifecycle_status"] for item in result.proposals] == ["created"]


def _registry_renamed(registry: dict, old_name: str, new_name: str) -> dict:
    contracts = dict(registry["contracts"])
    contracts[new_name] = contracts.pop(old_name)
    return {**registry, "contracts": contracts}


def _extra_method_proposal(name: str, assembly: str) -> dict:
    proposal = _proposal(name, assembly)
    methods = proposal["implementation_snapshot"]["methods"]
    methods.append(
        {
            **methods[0],
            "method_identity": f"{assembly}.SQLObject.Read(System.String)",
            "method_name": "Read",
            "terminal_sink": "ExecuteReader",
            "branch_rules": [{"mode": "stored_procedure", "sink": "ExecuteReader"}],
        }
    )
    return proposal


def test_matching_fingerprint_reuses_the_entry_despite_name_case() -> None:
    created = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[_proposal("sqlfunc", "Vendor.Data")])],
        registry={"contracts": {}},
    )
    registry = _registry_renamed(created.formal_registry, "sqlfunc", "SQLFunc")

    result = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[_proposal("SQLFunc", "Vendor.Data")])],
        registry=registry,
    )

    assert result.onboarding_status == "reused"
    assert result.proposals[0]["lifecycle_status"] == "reused"
    assert result.formal_selector == "SQLFunc"
    assert list(result.formal_registry["contracts"]) == ["SQLFunc"]


def test_case_different_contract_name_versions_one_entry_without_a_case_twin() -> None:
    created = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[_proposal("sqlfunc", "Vendor.Data")])],
        registry={"contracts": {}},
    )
    registry = _registry_renamed(created.formal_registry, "sqlfunc", "SQLFunc")

    result = run_contract_preflight(
        [
            SimpleNamespace(
                contract_proposals=[_extra_method_proposal("SQLFunc", "Vendor.Data")]
            )
        ],
        registry=registry,
    )

    names = list(result.formal_registry["contracts"])
    assert result.onboarding_status == "created"
    assert len(names) == 2
    assert len({name.casefold() for name in names}) == len(names)
    assert "SQLFunc" in names
    versioned = next(name for name in names if name != "SQLFunc")
    assert versioned.startswith("SQLFunc-")
    assert result.formal_selector == versioned
    for name in names:
        assert (
            normalize_contract_selector(name, result.formal_registry).candidates
            == (name,)
        )


def test_versioned_name_steps_past_an_existing_revision_of_the_same_name() -> None:
    created = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[_proposal("sqlfunc", "Vendor.Data")])],
        registry={"contracts": {}},
    )
    registry = _registry_renamed(created.formal_registry, "sqlfunc", "SQLFunc")
    proposal = _extra_method_proposal("SQLFunc", "Vendor.Data")
    first = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[proposal])],
        registry=registry,
    )
    occupied_name = str(first.formal_selector)

    # Stage the same behavior surface again, with the twelve-character
    # revision name already taken by an unrelated entry.
    registry["contracts"][occupied_name] = {"receiver_types": [], "methods": []}
    result = run_contract_preflight(
        [SimpleNamespace(contract_proposals=[proposal])],
        registry=registry,
    )

    names = list(result.formal_registry["contracts"])
    assert len({name.casefold() for name in names}) == len(names)
    assert result.formal_selector != occupied_name
    assert str(result.formal_selector).startswith("SQLFunc-")
    assert registry["contracts"][occupied_name] == {
        "receiver_types": [],
        "methods": [],
    }


def test_invalid_selector_is_preserved_when_preflight_fails() -> None:
    original = ["alpha", "missing"]
    result = run_contract_preflight(
        [],
        selector=original,
        registry={"contracts": {"alpha": {}}},
    )

    assert result.onboarding_status == "preflight_failed"
    assert result.formal_selector is None
    assert result.to_dict()["selector_original"] == original
    assert result.to_dict()["staged_selector"] == original
    assert result.to_dict()["selector_diagnostic"] == "selector_contract_not_found"


def test_refresh_consumes_staged_contract_for_opaque_wrapper(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.cs"
    root.mkdir()
    proposal = _proposal("vendor", "Vendor.Data")
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
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
    }
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [raw]},
        contract_proposals=[proposal],
    )
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    summary = result["wrapper_summary"]
    observation = summary["observations"][0]
    assert summary["contract_onboarding_status"] == "created"
    assert summary["contract_preflight"]["formal_selector"] == "vendor"
    assert observation["status"] == "explicit_selected"
    assert observation["contract"] == "vendor"
    assert observation["invocation_mode"] == "stored_procedure"
    assert observation["terminal_sink"] == "ExecuteNonQuery"
    assert observation["procedure_name"] == "usp_save"
    assert observation["contract_fingerprint"]
    assert observation["evidence_kind"] == ""


def test_decompiled_provenance_survives_preflight_and_wrapper_summary(
    monkeypatch,
    tmp_path,
) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.cs"
    root.mkdir()
    proposal = _proposal("vendor", "Vendor.Data")
    proposal["evidence_kind"] = "decompiled_auto"
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
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
    }
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [raw]},
        contract_proposals=[proposal],
    )
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    preflight = result["wrapper_summary"]["contract_preflight"]
    entry = preflight["staged_registry"]["contracts"]["vendor"]
    observation = result["wrapper_summary"]["observations"][0]
    assert preflight["proposals"][0]["evidence_kind"] == "decompiled_auto"
    assert entry["evidence_kind"] == "decompiled_auto"
    assert entry["lifecycle"]["status"] == "accepted"
    assert observation["evidence_kind"] == "decompiled_auto"
    assert observation["contract_lifecycle_status"] == "accepted"


def test_direct_inline_invocation_remains_outside_wrapper_preflight(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "direct_sqlclient",
                    "class_name": "OrderPage",
                    "method_name": "Search",
                    "command_text_kind": "literal",
                    "command_text": "SELECT 1",
                    "command_type_stored_procedure": False,
                    "connection_expression": "conn",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert result["wrapper_summary"]["observations"] == []
    assert result["wrapper_summary"]["contract_onboarding_status"] == "not_required"


def test_explicit_selector_array_is_a_sorted_candidate_boundary() -> None:
    gateway = CSharpAnalysisGateway(
        SpCatalog.from_databases({}),
        external_wrapper_contracts={
            "outside": {
                "receiver_types": ["Other.SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            },
            "beta": {
                "receiver_types": ["SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            },
            "alpha": {
                "receiver_types": ["SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            },
        },
    )

    result = gateway.reconcile_wrapper(
        "Page.cs",
        {
            "invocation_kind": "source_wrapper",
            "class_name": "Page",
            "method_name": "Save",
            "wrapper_method_name": "Run",
            "wrapper_receiver_type": "SQLObject",
            "wrapper_source_available": False,
            "wrapper_mode": "stored_procedure",
            "command_text_kind": "literal",
            "command_text": "usp_Save",
            "start_offset": 1,
            "end_offset": 20,
        },
        explicit_contract=["beta", "alpha"],
    )

    assert result.status == "ambiguous_contract"
    assert result.selection_source == "explicit"
    assert result.candidate_contracts == ("alpha", "beta")

    narrowed = gateway.reconcile_wrapper(
        "Page.cs",
        {
            "invocation_kind": "source_wrapper",
            "class_name": "Page",
            "method_name": "Save",
            "wrapper_method_name": "Run",
            "wrapper_receiver_type": "SQLObject",
            "wrapper_source_available": False,
            "wrapper_mode": "stored_procedure",
            "command_text_kind": "literal",
            "command_text": "usp_Save",
            "start_offset": 1,
            "end_offset": 20,
        },
        explicit_contract=["alpha", "outside"],
    )

    assert narrowed.status == "explicit_selected"
    assert narrowed.contract == "alpha"


def test_refresh_passes_valid_selector_boundary_to_reconciliation(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "Run",
                    "wrapper_receiver_type": "SQLObject",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_Save",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )
    registry = {
        "contracts": {
            "outside": {
                "receiver_types": ["SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            },
            "alpha": {
                "receiver_types": ["SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            },
        }
    }
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: registry)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"},
        wrapper_contract=["alpha"],
    )

    observation = result["wrapper_summary"]["observations"][0]
    assert observation["status"] == "explicit_selected"
    assert observation["contract"] == "alpha"
    assert observation["selection_source"] == "explicit"
    assert observation["evidence_kind"] == ""
    assert result["wrapper_summary"]["contract_preflight"]["formal_selector"] == "alpha"


def test_incomplete_preflight_does_not_auto_select_or_promote_opaque_wrapper(
    monkeypatch,
    tmp_path,
) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.cs"
    root.mkdir()
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={
            str(source_file): [
                {
                    "invocation_kind": "source_wrapper",
                    "class_name": "OrderPage",
                    "method_name": "Save",
                    "wrapper_method_name": "Run",
                    "wrapper_receiver_type": "SQLObject",
                    "wrapper_source_available": False,
                    "wrapper_mode": "stored_procedure",
                    "command_text_kind": "literal",
                    "command_text": "usp_Save",
                    "start_offset": 1,
                    "end_offset": 20,
                }
            ]
        },
    )
    registry = {
        "contracts": {
            "sqlobject": {
                "receiver_types": ["SQLObject"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "ExecuteReader"}},
            }
        }
    }
    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: registry)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    summary = result["wrapper_summary"]
    observation = summary["observations"][0]
    assert summary["contract_onboarding_status"] == "preflight_failed"
    assert summary["contract_preflight"]["formal_selector"] is None
    assert summary["contract_preflight"]["staged_contracts"] == ["sqlobject"]
    assert observation["status"] == "unresolved_contract"
    assert observation["evidence_status"] == "unresolved"
    assert observation["contract_preflight_failed"] is True
    assert observation["contract_preflight_reason"] == "contract_preflight_failed"
    assert observation["contract"] == ""


def test_refresh_api_accepts_array_selector_without_string_coercion(monkeypatch) -> None:
    from service import api
    from service.schemas import RefreshRequest

    observed: dict[str, object] = {}

    def fake_refresh_source(source, program_names, wrapper_contract, database):
        observed["wrapper_contract"] = wrapper_contract
        return {"scope": "system", "wrapper_summary": {}}

    monkeypatch.setattr(api.analyze_service, "refresh_source", fake_refresh_source)

    api.refresh(
        RefreshRequest(
            system="Orders",
            wrapper_contract=["beta", "alpha"],
        )
    )

    assert observed["wrapper_contract"] == ["beta", "alpha"]
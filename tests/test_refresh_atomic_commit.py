"""Integration tests: refresh_source atomic commit and program-scope guard."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from code_analyzer.project_scanner import ProjectScanResult
from service import analyze_service


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


def _scan_with_opaque_wrapper(root: Path, proposal: dict) -> ProjectScanResult:
    source_file = root / "OrderPage.cs"
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
        "method_name": "Save",
        "wrapper_method_name": "Run",
        "wrapper_receiver_type": f"{proposal['name']}.SQLObject",
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
    return ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [raw]},
        contract_proposals=[proposal],
    )


def _setup_registry_and_catalog(tmp_path: Path, system_id: str) -> tuple[Path, Path]:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": system_id, "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    return registry_path, catalog_path


def test_full_refresh_commits_staged_contract_to_active_configuration(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    registry_path, catalog_path = _setup_registry_and_catalog(tmp_path, "Orders")
    scan = _scan_with_opaque_wrapper(root, _proposal("vendor", "Vendor.Data"))

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"}, database="Orders")

    assert result["contract_transaction"]["status"] == "committed"
    registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "vendor" in registry_after["contracts"]
    catalog_after = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_after["systems"][0]["wrapper_contract"] == "vendor"

    reference = result["analysis_manifest"]["contract_revision_reference"]
    assert "vendor" in reference
    assert reference["vendor"]["contract_fingerprint"]


def test_program_scoped_refresh_never_commits_even_with_a_complete_proposal(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    registry_path, catalog_path = _setup_registry_and_catalog(tmp_path, "Orders")
    before_registry = registry_path.read_bytes()
    before_catalog = catalog_path.read_bytes()
    scan = _scan_with_opaque_wrapper(root, _proposal("vendor", "Vendor.Data"))

    from service.analyze_service import ProgramRefreshResult

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "_require_current_program_cache", lambda scan_root: None)
    monkeypatch.setattr(
        analyze_service,
        "refresh_programs",
        lambda scan_root, names: ProgramRefreshResult(scan=scan, matched_programs=list(names)),
    )
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.refresh_source(
        {"project": "p", "repo": "r"}, program_names=["OrderPage"], database="Orders"
    )

    assert result["partial"] is True
    assert result["contract_transaction"]["status"] == "not_required"
    assert registry_path.read_bytes() == before_registry
    assert catalog_path.read_bytes() == before_catalog


def test_full_refresh_without_a_system_id_does_not_commit(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    root.mkdir()
    registry_path, catalog_path = _setup_registry_and_catalog(tmp_path, "Orders")
    before_registry = registry_path.read_bytes()
    scan = _scan_with_opaque_wrapper(root, _proposal("vendor", "Vendor.Data"))

    monkeypatch.setattr(analyze_service, "resolve_scan_roots", lambda source, refresh=True: [root])
    monkeypatch.setattr(analyze_service, "get_or_scan", lambda scan_root, refresh=True: scan)
    monkeypatch.setattr(analyze_service, "load_contract_registry", lambda: {"contracts": {}})
    monkeypatch.setattr(analyze_service, "cached_commit", lambda scan_root: "deadbeef")
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(analyze_service, "CONTRACT_TRANSACTION_CATALOG_PATH", catalog_path)

    result = analyze_service.refresh_source({"project": "p", "repo": "r"})

    assert result["contract_transaction"]["status"] == "not_required"
    assert registry_path.read_bytes() == before_registry

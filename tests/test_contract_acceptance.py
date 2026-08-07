"""Focused tests for explicit external-wrapper contract acceptance."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.contract_acceptance import (  # noqa: E402
    ContractAcceptanceError,
    accept_external_wrapper_contract,
    reclassify_cached_scans,
)
import service.contract_acceptance as contract_acceptance_module  # noqa: E402
from service import scan_store as scan_store_module  # noqa: E402
from code_analyzer.project_scanner import ProjectScanResult  # noqa: E402


def test_incomplete_proposal_is_rejected_without_writing_configuration(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteNonQuery",
                            }
                        },
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "system_id": "Orders",
                        "wrapper_contract": "",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    before = {
        registry_path: registry_path.read_bytes(),
        catalog_path: catalog_path.read_bytes(),
    }

    try:
        accept_external_wrapper_contract(
            {
                "name": "orderhelper",
                "receiver_types": ["OrderHelper"],
                "methods": {"Run": {"mode": "", "sink": ""}},
            },
            registry_path=registry_path,
            catalog_path=catalog_path,
            system_id="Orders",
            requested_selector="orderhelper",
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "incomplete_method_semantics"
    else:
        raise AssertionError("incomplete proposals must remain review-only")

    assert registry_path.read_bytes() == before[registry_path]
    assert catalog_path.read_bytes() == before[catalog_path]


def test_existing_sqlobject_contract_is_reused_in_preview(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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
    before = registry_path.read_bytes()

    result = accept_external_wrapper_contract(
        {
            "name": "SQLObject",
            "receiver_types": ["SQLObject"],
            "methods": {
                "CreateTable": {
                    "mode": "call_site",
                    "sink": "ExecuteReader",
                }
            },
        },
        registry_path=registry_path,
        scan_roots=[],
    )

    assert result["status"] == "preview"
    assert result["contract"] == "sqlobject"
    assert result["reused"] is True
    assert result["registry_diff"]["changed"] is True
    assert result["registry_diff"]["after"]["contracts"]["sqlobject"]["methods"][
        "ExeProcNon"
    ]
    assert result["registry_diff"]["after"]["contracts"]["sqlobject"]["methods"][
        "CreateTable"
    ] == {"mode": "call_site", "sink": "ExecuteReader"}
    assert result["written_files"] == []
    assert result["git_commit"] is False
    assert registry_path.read_bytes() == before


def test_sqlobject_receiver_reuse_preserves_existing_auto_select(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": False,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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

    result = accept_external_wrapper_contract(
        {
            "name": "observed_sqlobject",
            "receiver_types": ["SQLObject"],
            "methods": {
                "CreateTable": {
                    "mode": "call_site",
                    "sink": "ExecuteReader",
                }
            },
        },
        registry_path=registry_path,
    )

    contracts = result["registry_diff"]["after"]["contracts"]
    assert result["contract"] == "sqlobject"
    assert result["reused"] is True
    assert result["reuse_reason"] == "existing_contract_reused_by_receiver_type"
    assert set(contracts) == {"sqlobject"}
    assert contracts["sqlobject"]["auto_select"] is False
    assert "CreateTable" in contracts["sqlobject"]["methods"]


def test_reclassification_uses_cached_raw_facts_without_rescanning(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
        "method_name": "Save",
        "wrapper_method_name": "RunProc",
        "wrapper_receiver_type": "OrderHelper",
        "wrapper_source_available": False,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_SaveOrder",
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 30,
    }
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [raw]},
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )
    monkeypatch.setattr(scan_store_module, "cache_status", lambda _: "current")
    monkeypatch.setattr(scan_store_module, "load_cached", lambda _: scan)
    monkeypatch.setattr(
        scan_store_module,
        "get_or_scan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("contract-only acceptance must not rescan C#")
        ),
    )

    result = reclassify_cached_scans(
        [root],
        {
            "orderhelper": {
                "auto_select": True,
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "RunProc": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            }
        },
    )

    assert result["analyzer_calls"] == 0
    assert result["raw_facts_changed"] is False
    assert result["source_snapshots_changed"] is False
    assert result["cache"] == [{"root": str(root), "status": "current", "source_commit": ""}]
    observation = result["wrapper_summary"]["observations"][0]
    assert observation["status"] == "auto_selected"
    assert observation["contract"] == "orderhelper"
    assert scan.db_invocations[str(source_file)] == [raw]


def test_apply_writes_registry_and_requested_system_selector_without_commit(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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
    catalog_path.write_text(
        json.dumps(
            {
                "systems": [
                    {"system_id": "Orders", "name": "Orders", "wrapper_contract": ""}
                ]
            }
        ),
        encoding="utf-8",
    )

    result = accept_external_wrapper_contract(
        {
            "name": "sqlobject",
            "receiver_types": ["SQLObject"],
            "methods": {
                "CreateDataSet": {
                    "mode": "call_site",
                    "sink": "ExecuteReader",
                }
            },
        },
        registry_path=registry_path,
        catalog_path=catalog_path,
        system_id="Orders",
        requested_selector="sqlobject",
        apply=True,
    )

    assert result["status"] == "applied"
    assert result["applied"] is True
    assert result["git_commit"] is False
    assert set(result["written_files"]) == {str(registry_path), str(catalog_path)}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert "CreateDataSet" in registry["contracts"]["sqlobject"]["methods"]
    assert catalog["systems"][0]["wrapper_contract"] == "sqlobject"


def test_apply_write_failure_restores_both_configuration_files(monkeypatch, tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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
    catalog_path.write_text(
        json.dumps(
            {"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}
        ),
        encoding="utf-8",
    )
    before_registry = registry_path.read_bytes()
    before_catalog = catalog_path.read_bytes()
    original_write = contract_acceptance_module._atomic_write_json

    def fail_catalog_write(path, payload):
        if Path(path) == catalog_path:
            raise OSError("simulated catalog write failure")
        return original_write(path, payload)

    monkeypatch.setattr(contract_acceptance_module, "_atomic_write_json", fail_catalog_write)

    try:
        accept_external_wrapper_contract(
            {
                "name": "sqlobject",
                "receiver_types": ["SQLObject"],
                "methods": {
                    "CreateDataSet": {
                        "mode": "call_site",
                        "sink": "ExecuteReader",
                    }
                },
            },
            registry_path=registry_path,
            catalog_path=catalog_path,
            system_id="Orders",
            requested_selector="sqlobject",
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "apply_failed"
    else:
        raise AssertionError("catalog write failure must abort acceptance")

    assert registry_path.read_bytes() == before_registry
    assert catalog_path.read_bytes() == before_catalog


def test_apply_reports_rollback_failure(monkeypatch, tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path = tmp_path / "system_catalog.json"
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders"}]}),
        encoding="utf-8",
    )
    original_write = contract_acceptance_module._atomic_write_json

    def fail_catalog_write(path, payload):
        if Path(path) == catalog_path:
            raise OSError("simulated catalog write failure")
        return original_write(path, payload)

    monkeypatch.setattr(contract_acceptance_module, "_atomic_write_json", fail_catalog_write)
    monkeypatch.setattr(
        contract_acceptance_module,
        "_atomic_write_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("simulated rollback failure")
        ),
    )

    try:
        accept_external_wrapper_contract(
            {
                "name": "orders_contract",
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
            registry_path=registry_path,
            catalog_path=catalog_path,
            system_id="Orders",
            requested_selector="orders_contract",
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "apply_rollback_failed"
        assert str(registry_path) in exc.details[0]
    else:
        raise AssertionError("rollback failures must be reported")


def test_requested_selector_drives_cached_reclassification(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
        "method_name": "Save",
        "wrapper_method_name": "RunProc",
        "wrapper_receiver_type": "SQLObject",
        "wrapper_source_available": False,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_SaveOrder",
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 30,
    }
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [raw]},
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "RunProc": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteReader",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(scan_store_module, "cache_status", lambda _: "current")
    monkeypatch.setattr(scan_store_module, "load_cached", lambda _: scan)
    monkeypatch.setattr(
        scan_store_module,
        "get_or_scan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("acceptance apply must not rescan C#")
        ),
    )

    result = accept_external_wrapper_contract(
        {
            "name": "orders_contract",
            "auto_select": False,
            "receiver_types": ["OrderHelper"],
            "methods": {
                "RunProc": {
                    "mode": "stored_procedure",
                    "sink": "ExecuteReader",
                }
            },
        },
        registry_path=registry_path,
        catalog_path=catalog_path,
        system_id="Orders",
        requested_selector="sqlobject",
        scan_roots=[root],
        apply=True,
    )

    assert result["status"] == "applied"
    assert result["reclassification"]["analyzer_calls"] == 0
    assert result["reclassification"]["raw_facts_changed"] is False
    assert result["reclassification"]["source_snapshots_changed"] is False
    observation = result["reclassification"]["wrapper_summary"]["observations"][0]
    assert observation["status"] == "explicit_selected"
    assert observation["selection_source"] == "explicit"
    assert observation["contract"] == "sqlobject"


def test_unknown_requested_selector_is_rejected_without_writing(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    before_registry = registry_path.read_bytes()
    before_catalog = catalog_path.read_bytes()

    try:
        accept_external_wrapper_contract(
            {
                "name": "orders_contract",
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "RunProc": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
            registry_path=registry_path,
            catalog_path=catalog_path,
            system_id="Orders",
            requested_selector="missing_contract",
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "selector_contract_not_found"
    else:
        raise AssertionError("unknown selectors must be rejected before writes")

    assert registry_path.read_bytes() == before_registry
    assert catalog_path.read_bytes() == before_catalog


def test_updating_contract_cannot_claim_another_contract_receiver(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteNonQuery",
                            }
                        },
                    },
                    "otherhelper": {
                        "auto_select": True,
                        "receiver_types": ["OtherHelper"],
                        "methods": {
                            "Run": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteReader",
                            }
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    before = registry_path.read_bytes()

    try:
        accept_external_wrapper_contract(
            {
                "name": "sqlobject",
                "receiver_types": ["SQLObject", "OtherHelper"],
                "methods": {
                    "CreateTable": {
                        "mode": "call_site",
                        "sink": "ExecuteReader",
                    }
                },
            },
            registry_path=registry_path,
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "duplicate_receiver_contract"
    else:
        raise AssertionError("receiver ownership must remain unique")

    assert registry_path.read_bytes() == before


def test_invalid_semantics_are_rejected(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
                        "auto_select": True,
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
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

    invalid_proposals = [
        (
            {
                "name": "newhelper",
                "receiver_types": ["NewHelper"],
                "methods": {"Run": {"mode": "guessed", "sink": "ExecuteReader"}},
            },
            "invalid_contract_mode",
        ),
        (
            {
                "name": "newhelper",
                "receiver_types": ["NewHelper"],
                "methods": {"Run": {"mode": "stored_procedure", "sink": "Unknown"}},
            },
            "invalid_contract_sink",
        ),
        (
            {
                "name": "invalidmethod",
                "receiver_types": ["InvalidHelper"],
                "methods": {
                    "Run.Method": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
            "invalid_method_identity",
        ),
    ]
    for proposal, expected_code in invalid_proposals:
        try:
            accept_external_wrapper_contract(proposal, registry_path=registry_path, apply=True)
        except ContractAcceptanceError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError(f"expected {expected_code}")


def test_invalid_existing_contract_is_rejected_without_writing(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "broken": {
                        "auto_select": True,
                        "receiver_types": ["BrokenHelper"],
                        "methods": {
                            "Run": {
                                "mode": "guessed",
                                "sink": "ExecuteReader",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    before = registry_path.read_bytes()

    try:
        accept_external_wrapper_contract(
            {
                "name": "newhelper",
                "receiver_types": ["NewHelper"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
            registry_path=registry_path,
            apply=True,
        )
    except ContractAcceptanceError as exc:
        assert exc.code == "invalid_contract_mode"
    else:
        raise AssertionError("invalid active contracts must block acceptance")

    assert registry_path.read_bytes() == before


def test_cached_reclassification_does_not_promote_new_source_facts(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.aspx.cs"
    root.mkdir()
    old_raw = {
        "invocation_kind": "source_wrapper",
        "class_name": "OrderPage",
        "method_name": "Save",
        "wrapper_method_name": "RunProc",
        "wrapper_receiver_type": "OrderHelper",
        "wrapper_source_available": False,
        "wrapper_mode": "stored_procedure",
        "command_text_kind": "literal",
        "command_text": "usp_SaveOrder",
        "connection_expression": "conn",
        "start_offset": 10,
        "end_offset": 30,
    }
    scan = ProjectScanResult(
        project_root=str(root),
        project_name="Orders",
        scan_time=datetime.now(),
        db_invocations={str(source_file): [old_raw]},
        connection_sources={str(source_file): {"conn": "OrdersDb"}},
    )
    monkeypatch.setattr(scan_store_module, "cache_status", lambda _: "current")
    monkeypatch.setattr(scan_store_module, "load_cached", lambda _: scan)
    monkeypatch.setattr(
        scan_store_module,
        "get_or_scan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a source revision requires normal refresh")
        ),
    )

    result = reclassify_cached_scans(
        [root],
        {
            "orders_contract": {
                "auto_select": True,
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "RunProc": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    },
                    "NewMethod": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    },
                },
            }
        },
    )

    assert result["analyzer_calls"] == 0
    assert result["wrapper_summary"]["observed_methods"] == ["RunProc"]
    assert "NewMethod" not in result["wrapper_summary"]["observed_methods"]


def test_acceptance_api_defaults_to_preview_and_forwards_explicit_apply(monkeypatch) -> None:
    from service import api
    from service.schemas import WrapperContractAcceptanceRequest

    observed: dict[str, object] = {}

    def fake_accept(proposal, **kwargs):
        observed["proposal"] = proposal
        observed.update(kwargs)
        return {
            "status": "preview",
            "valid": True,
            "contract": "orderhelper",
            "reused": False,
            "reuse_reason": "new_contract",
            "registry_diff": {"changed": True},
            "catalog_diff": {"changed": False},
            "reclassification": {"analyzer_calls": 0},
            "applied": False,
            "written_files": [],
            "git_commit": False,
        }

    monkeypatch.setattr(api.contract_acceptance, "accept_external_wrapper_contract", fake_accept)

    response = api.accept_wrapper_contract(
        WrapperContractAcceptanceRequest(
            proposal={
                "name": "orderhelper",
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "Run": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
            system_id="Orders",
            requested_selector="orderhelper",
            scan_roots=["C:/scan/Orders"],
        )
    )

    assert observed["proposal"]["name"] == "orderhelper"
    assert observed["system_id"] == "Orders"
    assert observed["requested_selector"] == "orderhelper"
    assert observed["scan_roots"] == ["C:/scan/Orders"]
    assert observed["apply"] is False
    assert response.contract == "orderhelper"
    assert response.applied is False


def test_acceptance_api_rejects_preview_apply_conflict(monkeypatch) -> None:
    from fastapi import HTTPException
    from service import api
    from service.schemas import WrapperContractAcceptanceRequest

    monkeypatch.setattr(
        api.contract_acceptance,
        "accept_external_wrapper_contract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("conflicting operation must be rejected before service call")
        ),
    )

    try:
        api.accept_wrapper_contract(
            WrapperContractAcceptanceRequest(operation="preview", apply=True)
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("preview/apply conflicts must return HTTP 400")


def test_acceptance_api_rejects_unknown_operation() -> None:
    from fastapi import HTTPException
    from service import api
    from service.schemas import WrapperContractAcceptanceRequest

    try:
        api.accept_wrapper_contract(
            WrapperContractAcceptanceRequest(operation="commit")
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("unknown acceptance operations must return HTTP 400")
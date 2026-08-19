"""Focused tests for explicit external-wrapper contract acceptance."""

from __future__ import annotations
import json
import multiprocessing
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
from service.contract_transaction import recover_transaction  # noqa: E402
import service.contract_transaction as contract_transaction_module  # noqa: E402
from service import scan_store as scan_store_module  # noqa: E402
from code_analyzer.external_wrapper_contracts import (  # noqa: E402
    versioned_contract_from_proposal,
)
from code_analyzer.project_scanner import ProjectScanResult  # noqa: E402


def test_incomplete_proposal_is_rejected_without_writing_configuration(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
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


def test_sqlobject_receiver_reuse_merges_methods_by_receiver_type(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
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
    assert "CreateTable" in contracts["sqlobject"]["methods"]


def test_contract_acceptance_preserves_fill_sink_and_default_text_mode(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")

    result = accept_external_wrapper_contract(
        {
            "name": "sqlobject-adapter",
            "receiver_types": ["SQLObject"],
            "methods": {
                "CreateTable": {
                    "mode": "call_site",
                    "default_mode": "inline_sql",
                    "sink": "Fill",
                }
            },
        },
        registry_path=registry_path,
    )

    method = result["registry_diff"]["after"]["contracts"]["sqlobject-adapter"]["methods"][
        "CreateTable"
    ]
    assert method == {
        "mode": "call_site",
        "default_mode": "inline_sql",
        "sink": "Fill",
    }


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
    monkeypatch.setattr(
        contract_acceptance_module.analyze_service.sql_cache_store,
        "load_cached",
        lambda database, schema, server="": {
            "database": "OrdersDb",
            "schema": "dbo",
            "procedures": [{"name": "dbo.usp_SaveOrder"}],
        },
    )

    result = reclassify_cached_scans(
        [root],
        {
            "orderhelper": {
                "receiver_types": ["OrderHelper"],
                "methods": {
                    "RunProc": {
                        "mode": "stored_procedure",
                        "sink": "ExecuteReader",
                    }
                },
            },
        },
        explicit_contract="orderhelper",
        database="OrdersDb",
    )

    assert result["analyzer_calls"] == 0
    assert result["raw_facts_changed"] is False
    assert result["source_snapshots_changed"] is False
    assert result["cache"] == [{"root": str(root), "status": "current", "source_commit": ""}]
    observation = result["wrapper_summary"]["observations"][0]
    assert observation["status"] == "explicit_selected"
    assert observation["contract"] == "orderhelper"
    assert observation["evidence_status"] == "proven"
    assert scan.db_invocations[str(source_file)] == [raw]


def test_registry_only_acceptance_keeps_database_evidence_unresolved(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Orders"
    source_file = root / "OrderPage.aspx.cs"
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    root.mkdir()
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
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
            AssertionError("registry-only acceptance must not rescan C#")
        ),
    )
    monkeypatch.setattr(
        contract_acceptance_module.analyze_service.sql_cache_store,
        "load_cached",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("registry-only acceptance has no database cache scope")
        ),
    )

    result = accept_external_wrapper_contract(
        {
            "name": "orderhelper",
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
        scan_roots=[root],
    )

    assert result["status"] == "preview"
    assert result["reclassification"]["analyzer_calls"] == 0
    observation = result["reclassification"]["wrapper_summary"]["observations"][0]
    assert observation["status"] == "explicit_selected"
    assert observation["evidence_status"] == "unresolved"
    assert observation["evidence_reason"] == "not_in_resolved_catalog"
    assert result["written_files"] == []


def test_apply_writes_registry_and_requested_system_selector_without_commit(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "sqlobject": {
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
    original_write = contract_transaction_module._atomic_write_bytes

    def fail_catalog_write(path, content):
        if Path(path) == catalog_path:
            raise OSError("simulated catalog write failure")
        return original_write(path, content)

    monkeypatch.setattr(contract_transaction_module, "_atomic_write_bytes", fail_catalog_write)

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
        assert exc.code == "commit_failed"
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
    original_write = contract_transaction_module._atomic_write_bytes
    registry_write_calls = {"n": 0}

    def flaky_write(path, content):
        target = Path(path)
        if target == catalog_path:
            raise OSError("simulated catalog write failure")
        if target == registry_path:
            registry_write_calls["n"] += 1
            if registry_write_calls["n"] > 1:
                raise OSError("simulated rollback failure")
        return original_write(path, content)

    monkeypatch.setattr(contract_transaction_module, "_atomic_write_bytes", flaky_write)

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
        assert exc.code == "commit_rollback_failed"
        assert str(registry_path) in exc.details[0]
    else:
        raise AssertionError("rollback failures must be reported")


def test_apply_commits_manifest_with_manual_acceptance_trigger(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )

    result = accept_external_wrapper_contract(
        {
            "name": "orderhelper",
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
        requested_selector="orderhelper",
        apply=True,
    )

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["trigger"] == "manual_acceptance"


def test_transaction_id_and_manifest_path_populated_only_for_real_commits(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )
    proposal = {
        "name": "orderhelper",
        "receiver_types": ["OrderHelper"],
        "methods": {
            "Run": {
                "mode": "stored_procedure",
                "sink": "ExecuteReader",
            }
        },
    }

    preview = accept_external_wrapper_contract(
        proposal,
        registry_path=registry_path,
        catalog_path=catalog_path,
        system_id="Orders",
        requested_selector="orderhelper",
        apply=False,
    )
    assert preview["transaction_id"] == ""
    assert preview["manifest_path"] == ""

    applied = accept_external_wrapper_contract(
        proposal,
        registry_path=registry_path,
        catalog_path=catalog_path,
        system_id="Orders",
        requested_selector="orderhelper",
        apply=True,
    )
    assert applied["transaction_id"]
    assert applied["manifest_path"]
    assert Path(applied["manifest_path"]).exists()

    noop = accept_external_wrapper_contract(
        proposal,
        registry_path=registry_path,
        catalog_path=catalog_path,
        system_id="Orders",
        requested_selector="orderhelper",
        apply=True,
    )
    assert noop["transaction_id"] == ""
    assert noop["manifest_path"] == ""


def test_recover_completes_interrupted_manual_acceptance(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    registry_path.write_text(json.dumps({"contracts": {}}), encoding="utf-8")
    catalog_path.write_text(
        json.dumps({"systems": [{"system_id": "Orders", "wrapper_contract": ""}]}),
        encoding="utf-8",
    )

    result = accept_external_wrapper_contract(
        {
            "name": "orderhelper",
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
        requested_selector="orderhelper",
        apply=True,
    )

    committed_registry_bytes = registry_path.read_bytes()
    committed_catalog_bytes = catalog_path.read_bytes()
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Simulate a crash between the registry replacement and the catalog
    # replacement: restore the catalog to its previous bytes and rewrite the
    # manifest to reflect only the registry step as completed.
    backup_catalog_bytes = Path(manifest["backup_catalog_artifact"]).read_bytes()
    catalog_path.write_bytes(backup_catalog_bytes)
    manifest["commit_progress"] = ["registry_replaced"]
    manifest["final_status"] = "pending"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    recovery = recover_transaction(manifest_path)

    assert recovery["status"] == "recovered_committed"
    assert registry_path.read_bytes() == committed_registry_bytes
    assert catalog_path.read_bytes() == committed_catalog_bytes


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
                        "receiver_types": ["SQLObject"],
                        "methods": {
                            "ExeProcNon": {
                                "mode": "stored_procedure",
                                "sink": "ExecuteNonQuery",
                            }
                        },
                    },
                    "otherhelper": {
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


def _versioned_proposal(assembly: str) -> dict:
    return {
        "name": "orders",
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


def _placeholder_contract(receiver_type: str) -> dict:
    return {
        "receiver_types": [receiver_type],
        "methods": {
            "Run": {"mode": "stored_procedure", "sink": "ExecuteNonQuery"},
        },
    }


def _run_acceptance_into_queue(queue, proposal, registry_path) -> None:
    """Module-level so a spawned child process can import and pickle it."""
    result = accept_external_wrapper_contract(
        proposal,
        registry_path=registry_path,
        scan_roots=[],
    )
    queue.put(result)


def test_three_way_name_collision_returns_promptly_instead_of_hanging(tmp_path) -> None:
    """A proposal whose fingerprint-derived name collides with every already
    taken suffix variant (short, medium, full fingerprint) must still resolve
    to a distinct name instead of oscillating forever between two taken
    names -- the bug this shared algorithm exists to fix.

    Runs the call in a separate, killable process rather than a thread: a
    regression here is a genuine infinite loop, and Python joins non-daemon
    threads at interpreter exit, so a thread-based timeout would still hang
    the whole test process even after "catching" the timeout.
    """
    proposal = _versioned_proposal("Vendor.Orders")
    entry, _report = versioned_contract_from_proposal(proposal)
    fingerprint = str(entry["contract_fingerprint"])

    registry_path = tmp_path / "external_wrapper_contracts.json"
    registry_path.write_text(
        json.dumps(
            {
                "contracts": {
                    "orders": _placeholder_contract("Legacy.Orders.LegacyReceiver"),
                    f"orders-{fingerprint[:12]}": _placeholder_contract(
                        "Collision.A.CollisionReceiverA"
                    ),
                    f"orders-{fingerprint[:16]}": _placeholder_contract(
                        "Collision.B.CollisionReceiverB"
                    ),
                    f"orders-{fingerprint}": _placeholder_contract(
                        "Collision.C.CollisionReceiverC"
                    ),
                }
            }
        ),
        encoding="utf-8",
    )

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(
        target=_run_acceptance_into_queue,
        args=(queue, proposal, registry_path),
    )
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join()
        raise AssertionError(
            "accept_external_wrapper_contract hung on a three-way "
            "contract-name collision instead of returning promptly"
        )

    assert process.exitcode == 0
    result = queue.get_nowait()
    assert result["status"] == "preview"
    assert result["contract"] == f"orders-{fingerprint}-2"
    assert result["contract"] not in {
        "orders",
        f"orders-{fingerprint[:12]}",
        f"orders-{fingerprint[:16]}",
        f"orders-{fingerprint}",
    }
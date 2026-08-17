"""Focused tests for the recoverable two-file contract transaction commit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from service.contract_transaction import (
    ContractTransactionError,
    commit_staged_contract_transaction,
    recover_transaction,
)


def _write_registry(path: Path, contracts: dict) -> None:
    path.write_text(json.dumps({"contracts": contracts}, indent=2), encoding="utf-8")


def _write_catalog(path: Path, system_id: str, selector) -> None:
    path.write_text(
        json.dumps(
            {"systems": [{"system_id": system_id, "wrapper_contract": selector}]},
            indent=2,
        ),
        encoding="utf-8",
    )


def test_commit_records_trigger_in_manifest(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")

    result = commit_staged_contract_transaction(
        staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path,
        catalog_path=catalog_path,
        manifest_dir=tmp_path / ".contract_transactions",
        trigger="refresh",
    )

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["trigger"] == "refresh"


def test_commit_rejects_unknown_trigger_value(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")

    with pytest.raises(ContractTransactionError) as excinfo:
        commit_staged_contract_transaction(
            staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
            staged_selector="vendor",
            system_id="Orders",
            registry_path=registry_path,
            catalog_path=catalog_path,
            manifest_dir=tmp_path / ".contract_transactions",
            trigger="something_else",
        )

    assert excinfo.value.code == "invalid_trigger"


def test_commit_writes_both_files_and_a_manifest(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")

    result = commit_staged_contract_transaction(
        staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path,
        catalog_path=catalog_path,
        manifest_dir=tmp_path / ".contract_transactions",
        trigger="refresh",
    )

    assert result["status"] == "committed"
    assert result["transaction_id"]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["final_status"] == "committed"
    assert manifest["commit_progress"] == [
        "registry_replaced",
        "catalog_replaced",
        "post_commit_validated",
    ]
    assert manifest["recovery_location"] == result["manifest_path"]

    registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "vendor" in registry_after["contracts"]
    catalog_after = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_after["systems"][0]["wrapper_contract"] == "vendor"


def test_commit_is_noop_when_staged_content_matches_active(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {"vendor": {"contract_fingerprint": "abc123"}})
    _write_catalog(catalog_path, "Orders", "vendor")

    result = commit_staged_contract_transaction(
        staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path,
        catalog_path=catalog_path,
        manifest_dir=tmp_path / ".contract_transactions",
        trigger="refresh",
    )

    assert result["status"] == "noop"
    assert not (tmp_path / ".contract_transactions").exists()


def test_commit_without_selector_only_touches_registry(tmp_path) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")

    result = commit_staged_contract_transaction(
        staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
        staged_selector=None,
        system_id="Orders",
        registry_path=registry_path,
        catalog_path=catalog_path,
        manifest_dir=tmp_path / ".contract_transactions",
        trigger="refresh",
    )

    assert result["status"] == "committed"
    catalog_after = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_after["systems"][0]["wrapper_contract"] == ""


def test_failure_between_registry_and_catalog_replacement_rolls_back(
    tmp_path, monkeypatch
) -> None:
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")
    before_registry = registry_path.read_bytes()
    before_catalog = catalog_path.read_bytes()

    import service.contract_transaction as module

    original_write = module._atomic_write_bytes
    call_count = {"n": 0}

    def flaky_write(path, content):
        call_count["n"] += 1
        # Allow manifest + staged/backup artifact writes, then fail exactly
        # when the catalog active file is about to be replaced.
        if Path(path) == catalog_path:
            raise OSError("simulated crash before catalog replacement")
        original_write(path, content)

    monkeypatch.setattr(module, "_atomic_write_bytes", flaky_write)

    with pytest.raises(ContractTransactionError) as excinfo:
        commit_staged_contract_transaction(
            staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
            staged_selector="vendor",
            system_id="Orders",
            registry_path=registry_path,
            catalog_path=catalog_path,
            manifest_dir=tmp_path / ".contract_transactions",
            trigger="refresh",
        )

    assert excinfo.value.code == "commit_failed"
    assert registry_path.read_bytes() == before_registry
    assert catalog_path.read_bytes() == before_catalog


def test_recover_completes_interrupted_commit_to_the_new_pair(tmp_path) -> None:
    # Commit normally first so a manifest and validated staged/backup
    # artifacts exist, then simulate a process crash that happened right
    # after the registry active file was replaced but before the catalog
    # active file was replaced: restore the catalog to its previous bytes
    # and rewrite the manifest to reflect only the registry step completed.
    registry_path = tmp_path / "external_wrapper_contracts.json"
    catalog_path = tmp_path / "system_catalog.json"
    _write_registry(registry_path, {})
    _write_catalog(catalog_path, "Orders", "")

    committed = commit_staged_contract_transaction(
        staged_registry={"contracts": {"vendor": {"contract_fingerprint": "abc123"}}},
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path,
        catalog_path=catalog_path,
        manifest_dir=tmp_path / ".contract_transactions",
        trigger="refresh",
    )
    manifest_path = Path(committed["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _write_catalog(catalog_path, "Orders", "")  # revert as if never replaced
    manifest["commit_progress"] = ["registry_replaced"]
    manifest["final_status"] = "pending"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    recovery = recover_transaction(manifest_path)

    assert recovery["status"] == "recovered_committed"
    registry_after = json.loads(registry_path.read_text(encoding="utf-8"))
    assert "vendor" in registry_after["contracts"]
    catalog_after = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_after["systems"][0]["wrapper_contract"] == "vendor"

    manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_after["final_status"] == "committed"
    assert manifest_after["commit_progress"] == ["registry_replaced", "catalog_replaced"]

    second = recover_transaction(manifest_path)
    assert second["status"] == "already_committed"


def test_deterministic_transaction_identity_for_equivalent_staged_content(tmp_path) -> None:
    registry_path_a = tmp_path / "a" / "external_wrapper_contracts.json"
    catalog_path_a = tmp_path / "a" / "system_catalog.json"
    registry_path_a.parent.mkdir()
    _write_registry(registry_path_a, {})
    _write_catalog(catalog_path_a, "Orders", "")

    registry_path_b = tmp_path / "b" / "external_wrapper_contracts.json"
    catalog_path_b = tmp_path / "b" / "system_catalog.json"
    registry_path_b.parent.mkdir()
    _write_registry(registry_path_b, {})
    _write_catalog(catalog_path_b, "Orders", "")

    staged = {"contracts": {"vendor": {"contract_fingerprint": "abc123"}}}
    result_a = commit_staged_contract_transaction(
        staged_registry=staged,
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path_a,
        catalog_path=catalog_path_a,
        manifest_dir=tmp_path / "a" / ".contract_transactions",
        trigger="refresh",
    )
    result_b = commit_staged_contract_transaction(
        staged_registry=staged,
        staged_selector="vendor",
        system_id="Orders",
        registry_path=registry_path_b,
        catalog_path=catalog_path_b,
        manifest_dir=tmp_path / "b" / ".contract_transactions",
        trigger="refresh",
    )

    assert result_a["transaction_id"] == result_b["transaction_id"]

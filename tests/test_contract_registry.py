"""Unit tests for the shared contract registry loader and naming algorithm."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.contract_registry import (  # noqa: E402
    ContractRegistryError,
    find_casefold,
    load_contract_registry,
    taken_contract_name,
    unused_revision_name,
)


def test_find_casefold_returns_the_stored_spelling() -> None:
    mapping = {"SqlObject": {}, "Other": {}}

    assert find_casefold(mapping, "sqlobject") == "SqlObject"
    assert find_casefold(mapping, "SQLOBJECT") == "SqlObject"


def test_find_casefold_returns_none_when_absent() -> None:
    assert find_casefold({"SqlObject": {}}, "missing") is None


def test_taken_contract_name_checks_entries_then_staged_names() -> None:
    entries = {"alpha": {}}
    staged = {"beta": {}}

    assert taken_contract_name(entries, staged, "ALPHA") == "alpha"
    assert taken_contract_name(entries, staged, "BETA") == "beta"
    assert taken_contract_name(entries, staged, "gamma") is None


def test_unused_revision_name_uses_short_fingerprint_suffix_when_free() -> None:
    fingerprint = "a" * 64
    name = unused_revision_name({}, {}, "orders", fingerprint)

    assert name == f"orders-{fingerprint[:12]}"


def test_unused_revision_name_falls_back_through_longer_suffixes() -> None:
    fingerprint = "b" * 64
    entries = {f"orders-{fingerprint[:12]}": {}}

    name = unused_revision_name(entries, {}, "orders", fingerprint)

    assert name == f"orders-{fingerprint[:16]}"


def test_unused_revision_name_falls_back_to_full_fingerprint() -> None:
    fingerprint = "c" * 64
    entries = {
        f"orders-{fingerprint[:12]}": {},
        f"orders-{fingerprint[:16]}": {},
    }

    name = unused_revision_name(entries, {}, "orders", fingerprint)

    assert name == f"orders-{fingerprint}"


def test_unused_revision_name_three_way_collision_uses_ordinal_fallback_and_returns_promptly() -> None:
    """All three fingerprint-length suffixes are already taken.

    A buggy naming algorithm can oscillate forever between two already-taken
    names in this situation. This must terminate immediately via the
    incrementing ordinal fallback instead of hanging.
    """
    fingerprint = "d" * 64
    entries = {
        f"orders-{fingerprint[:12]}": {},
        f"orders-{fingerprint[:16]}": {},
        f"orders-{fingerprint}": {},
    }

    name = unused_revision_name(entries, {}, "orders", fingerprint)

    assert name == f"orders-{fingerprint}-2"
    assert taken_contract_name(entries, {}, name) is None


def test_unused_revision_name_ordinal_fallback_skips_taken_ordinals() -> None:
    fingerprint = "e" * 64
    entries = {
        f"orders-{fingerprint[:12]}": {},
        f"orders-{fingerprint[:16]}": {},
        f"orders-{fingerprint}": {},
        f"orders-{fingerprint}-2": {},
        f"orders-{fingerprint}-3": {},
    }

    name = unused_revision_name(entries, {}, "orders", fingerprint)

    assert name == f"orders-{fingerprint}-4"


def test_unused_revision_name_considers_staged_names_too() -> None:
    fingerprint = "f" * 64
    staged = {f"orders-{fingerprint[:12]}": {}}

    name = unused_revision_name({}, staged, "orders", fingerprint)

    assert name == f"orders-{fingerprint[:16]}"


# --- load_contract_registry(strict=False) — automatic refresh path behavior ---


def test_non_strict_missing_file_degrades_to_empty_registry(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    registry = load_contract_registry(missing_path, strict=False)

    assert registry == {"contracts": {}}


def test_non_strict_unparseable_json_degrades_to_empty_registry(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{not valid json", encoding="utf-8")

    registry = load_contract_registry(path, strict=False)

    assert registry == {"contracts": {}}


def test_non_strict_malformed_content_passes_through_unvalidated(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"contracts": {"Alpha": {}, "alpha": {}, "beta": "not-an-object"}}),
        encoding="utf-8",
    )

    registry = load_contract_registry(path, strict=False)

    assert registry == {
        "contracts": {"Alpha": {}, "alpha": {}, "beta": "not-an-object"}
    }


def test_non_strict_bare_entry_mapping_is_wrapped_in_contracts_key(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"alpha": {}}), encoding="utf-8")

    registry = load_contract_registry(path, strict=False)

    assert registry == {"contracts": {"alpha": {}}}


def test_non_strict_defaults_to_false() -> None:
    import inspect

    signature = inspect.signature(load_contract_registry)
    assert signature.parameters["strict"].default is False


# --- load_contract_registry(strict=True) — explicit acceptance path behavior ---


def test_strict_missing_file_raises_registry_not_found(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(missing_path, strict=True)

    assert excinfo.value.code == "registry_not_found"


def test_strict_unparseable_json_raises_registry_invalid(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "registry_invalid"


def test_strict_non_object_root_raises_registry_invalid(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "registry_invalid"


def test_strict_missing_contracts_key_raises_registry_invalid(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"not_contracts": {}}), encoding="utf-8")

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "registry_invalid"


def test_strict_empty_contract_name_raises_invalid_contract_name(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"contracts": {" ": {}}}), encoding="utf-8")

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "invalid_contract_name"


def test_strict_casefold_duplicate_names_raise_duplicate_contract_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"contracts": {"Alpha": {}, "alpha": {}}}), encoding="utf-8"
    )

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "duplicate_contract_name"
    assert list(excinfo.value.details) == ["Alpha", "alpha"]


def test_strict_non_object_contract_entry_raises_invalid_contract(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"contracts": {"alpha": "not-an-object"}}), encoding="utf-8"
    )

    with pytest.raises(ContractRegistryError) as excinfo:
        load_contract_registry(path, strict=True)

    assert excinfo.value.code == "invalid_contract"


def test_strict_valid_registry_is_returned_as_is(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    payload = {"contracts": {"alpha": {"receiver_types": ["Foo"]}}}
    path.write_text(json.dumps(payload), encoding="utf-8")

    registry = load_contract_registry(path, strict=True)

    assert registry == payload

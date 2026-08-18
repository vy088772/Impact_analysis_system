"""Unit tests for the shared contract-name collision algorithm."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.contract_registry import (  # noqa: E402
    find_casefold,
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

"""Shared contract-name lookup and collision-avoidance algorithm.

Both the automatic refresh path (``contract_preflight.py``) and the explicit
acceptance path (``contract_acceptance.py``) need to pick a name for a new
contract revision without colliding, case-insensitively, with any name
already registered or staged in the same operation. This module is the one
place that algorithm lives.
"""

from __future__ import annotations

from typing import Any, Mapping


def find_casefold(mapping: Mapping[str, Any], name: str) -> str | None:
    """Return the mapping's own spelling of a name, ignoring letter case."""
    folded = str(name).casefold()
    return next((str(key) for key in mapping if str(key).casefold() == folded), None)


def taken_contract_name(
    entries: Mapping[str, Any],
    staged_names: Mapping[str, Any],
    name: str,
) -> str | None:
    """Return the spelling a registered or staged contract already holds."""
    return find_casefold(entries, name) or find_casefold(staged_names, name)


def unused_revision_name(
    entries: Mapping[str, Any],
    staged_names: Mapping[str, Any],
    taken_name: str,
    fingerprint: str,
) -> str:
    """Name one revision of a taken contract name without overwriting an entry.

    Always terminates: tries three fingerprint-length suffixes first, then
    falls back to an incrementing ordinal so a name is found even when every
    suffixed variant is already taken.
    """
    for suffix in (fingerprint[:12], fingerprint[:16], fingerprint):
        name = f"{taken_name}-{suffix}"
        if taken_contract_name(entries, staged_names, name) is None:
            return name
    ordinal = 2
    while True:
        name = f"{taken_name}-{fingerprint}-{ordinal}"
        if taken_contract_name(entries, staged_names, name) is None:
            return name
        ordinal += 1


__all__ = [
    "find_casefold",
    "taken_contract_name",
    "unused_revision_name",
]

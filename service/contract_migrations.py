"""One-time migration: add missing Delegation Aliases to accepted Contracts.

The decompiler has always recorded a Delegated Method in the decompilation
cache (``data/decompilation_cache/<assembly_identity>.json``); it never wrote
that finding into a Contract already accepted into the registry before this
migration existed. This module reads the cached decompilation result for each
Contract already in the registry and adds the missing ``delegation_aliases``
entry -- it never decompiles an assembly again (ADR-0027; ticket 03).

The alias collection sits outside a Contract's behaviour signature, so this
migration never touches ``behavior_signature`` or ``contract_fingerprint``: a
System that already matched a Contract by fingerprint keeps reusing it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from code_analyzer.external_wrapper_contracts import flatten_delegation_aliases

DEFAULT_DECOMPILATION_CACHE_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "decompilation_cache"
)


def _latest_snapshot(contract: Mapping[str, Any]) -> Mapping[str, Any] | None:
    snapshots = contract.get("implementation_snapshots")
    if not isinstance(snapshots, (list, tuple)) or not snapshots:
        return None
    latest = snapshots[-1]
    return latest if isinstance(latest, Mapping) else None


def _cached_delegated_methods(
    *,
    assembly_identity: str,
    behavior_surface_unit: str,
    decompilation_cache_dir: Path,
) -> tuple[str, list[Mapping[str, Any]] | None]:
    """The decompiler's raw ``delegated_methods`` finding for one receiver type.

    Reads the cache document directly rather than through
    ``DecompilationAttemptCache.load()``: that loader's host-identity gate is
    meant to invalidate a *rerun* decision (would this host produce the same
    result today), which a migration reading history has no business asking.

    Returns ``(status, delegated_methods)``. ``status`` is ``"missing"`` when
    no cached attempt for this receiver type exists at all, ``"stale_schema"``
    when the cached response predates the decompiler recording delegation at
    all (the key itself is absent -- an old cache written before ticket 01/02,
    for example), or ``"found"`` when the field is present, however many
    entries it holds. Only ``"found"`` licenses treating an empty list as a
    confirmed "no delegation" -- an absent key is not evidence of that (the
    same "absence proves nothing" rule ADR-0029 applies elsewhere).
    """
    if not assembly_identity or not behavior_surface_unit:
        return "missing", None
    cache_path = decompilation_cache_dir / f"{assembly_identity}.json"
    try:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "missing", None
    if not isinstance(document, Mapping):
        return "missing", None
    attempts = document.get("attempts")
    if not isinstance(attempts, Mapping):
        return "missing", None
    attempt = attempts.get(behavior_surface_unit)
    if not isinstance(attempt, Mapping):
        return "missing", None
    response = attempt.get("response")
    if not isinstance(response, Mapping) or "delegated_methods" not in response:
        return "stale_schema", None
    delegated_methods = response.get("delegated_methods")
    if not isinstance(delegated_methods, (list, tuple)):
        return "stale_schema", None
    return "found", [item for item in delegated_methods if isinstance(item, Mapping)]


def add_delegation_aliases_from_decompilation_cache(
    registry_payload: Mapping[str, Any],
    *,
    decompilation_cache_dir: Path | str = DEFAULT_DECOMPILATION_CACHE_DIR,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Add the missing Delegation Alias collection to every eligible Contract.

    Pure and read-only with respect to the cache: it never re-decompiles an
    assembly, and it never mutates ``behavior_signature`` or
    ``contract_fingerprint`` on any entry, so a fingerprint-keyed match never
    changes. Walks every Contract in the registry, not one named Contract, so
    a Contract accepted later needs no second migration. Returns the staged
    registry payload (unchanged when nothing needed adding) and a per-contract
    report suitable for a ``--dry-run`` preview.
    """
    cache_dir = Path(decompilation_cache_dir)
    after = copy.deepcopy(dict(registry_payload))
    contracts = after.get("contracts")
    if not isinstance(contracts, Mapping):
        return after, []

    report: list[dict[str, Any]] = []
    for name, contract in contracts.items():
        if not isinstance(contract, Mapping):
            report.append({"contract": str(name), "action": "skipped_invalid_contract"})
            continue
        if contract.get("delegation_aliases"):
            report.append({"contract": str(name), "action": "skipped_already_present"})
            continue
        snapshot = _latest_snapshot(contract)
        if snapshot is None:
            report.append({"contract": str(name), "action": "skipped_no_snapshot"})
            continue
        assembly_identity = str(snapshot.get("assembly_identity") or "").strip()
        behavior_surface_unit = str(snapshot.get("behavior_surface_unit") or "").strip()
        cache_status, delegated_methods = _cached_delegated_methods(
            assembly_identity=assembly_identity,
            behavior_surface_unit=behavior_surface_unit,
            decompilation_cache_dir=cache_dir,
        )
        if cache_status == "missing":
            report.append({"contract": str(name), "action": "skipped_cache_missing"})
            continue
        if cache_status == "stale_schema":
            report.append({"contract": str(name), "action": "skipped_stale_cache_schema"})
            continue
        aliases = flatten_delegation_aliases(delegated_methods)
        if not aliases:
            report.append({"contract": str(name), "action": "skipped_no_delegations"})
            continue
        updated = dict(contract)
        updated["delegation_aliases"] = aliases
        contracts_after = after["contracts"]
        contracts_after[name] = updated
        report.append({"contract": str(name), "action": "added", "aliases": aliases})

    return after, report


__all__ = [
    "DEFAULT_DECOMPILATION_CACHE_DIR",
    "add_delegation_aliases_from_decompilation_cache",
]

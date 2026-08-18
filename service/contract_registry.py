"""Shared external wrapper contract registry loading and naming.

Both the automatic refresh path (``contract_preflight.py``) and the explicit
acceptance path (``contract_acceptance.py``) need to (1) read the external
wrapper contract registry file and (2) pick a name for a new contract
revision without colliding, case-insensitively, with any name already
registered or staged in the same operation. This module is the one place
both concerns live. It owns registry *loading* and *naming* only -- writing
the registry back to disk is ``contract_transaction.py``'s job, and
comparing contract behavior is ``code_analyzer.external_wrapper_contracts``'s
job.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "config" / "external_wrapper_contracts.json"
DEFAULT_CATALOG_PATH = (
    PROJECT_ROOT.parent / "llamaindex-spec-rag" / "catalog" / "system_catalog.json"
)


class ContractRegistryError(ValueError):
    """A registry could not be loaded safely under strict validation."""

    def __init__(self, code: str, message: str, details: Iterable[str] = ()):
        self.code = code
        self.details = tuple(str(item) for item in details)
        super().__init__(message)


def _error(code: str, message: str, details: Iterable[str] = ()) -> NoReturn:
    raise ContractRegistryError(code, message, details)


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


def _registry_entries(registry: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce a registry mapping (or a bare entries mapping) to entries."""
    contracts = registry.get("contracts", registry)
    if not isinstance(contracts, Mapping):
        return {}
    return {str(name): value for name, value in contracts.items()}


def _registry_payload(registry: Mapping[str, Any] | None) -> dict[str, Any]:
    """Coerce any mapping into the ``{"contracts": {...}}`` shape, non-strict."""
    if not isinstance(registry, Mapping):
        return {"contracts": {}}
    payload = copy.deepcopy(dict(registry))
    contracts = payload.get("contracts")
    if isinstance(contracts, Mapping):
        payload["contracts"] = {
            str(name): copy.deepcopy(value) for name, value in contracts.items()
        }
        return payload
    return {"contracts": copy.deepcopy(_registry_entries(registry))}


def _validate_registry_content(payload: Mapping[str, Any]) -> None:
    """Fail-closed structural validation used only in strict mode.

    Non-empty contract names, no casefold-duplicate names, and every
    contract entry is object-shaped -- matching what
    ``contract_acceptance.py`` has always required before this module
    existed.
    """
    contracts = payload.get("contracts")
    if not isinstance(contracts, Mapping):
        _error("registry_invalid", "external wrapper registry 必須包含 contracts object")
    folded_names: dict[str, str] = {}
    for raw_name, raw_contract in contracts.items():
        name = str(raw_name or "").strip()
        if not name:
            _error("invalid_contract_name", "contract name 不可為空")
        folded = name.casefold()
        if folded in folded_names:
            _error(
                "duplicate_contract_name",
                f"contract name 不可重複（不分大小寫）：{name}",
                [folded_names[folded], name],
            )
        if not isinstance(raw_contract, Mapping):
            _error("invalid_contract", f"contract {name!r} 必須是 object")
        folded_names[folded] = name


def load_contract_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Load the active external wrapper contract registry from ``path``.

    ``strict=False`` (the automatic refresh path's behavior) degrades a
    missing or unparseable file to an empty registry (``{"contracts": {}}``)
    and never validates content -- whatever parses is returned as-is.

    ``strict=True`` (the explicit acceptance path's behavior) raises
    ``ContractRegistryError`` on a missing or unparseable file, and on
    structurally invalid content (empty contract names, casefold-duplicate
    names, or non-object contract entries).
    """
    registry_path = Path(path)
    if not strict:
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"contracts": {}}
        return _registry_payload(payload if isinstance(payload, Mapping) else None)

    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _error("registry_not_found", f"registry 不存在：{registry_path}")
    except (OSError, json.JSONDecodeError) as exc:
        _error(
            "registry_invalid",
            f"registry 無法讀取或不是有效 JSON：{registry_path}",
            [str(exc)],
        )
    if not isinstance(payload, dict):
        _error("registry_invalid", f"registry 根節點必須是 JSON object：{registry_path}")
    _validate_registry_content(payload)
    return payload


__all__ = [
    "ContractRegistryError",
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_REGISTRY_PATH",
    "find_casefold",
    "load_contract_registry",
    "taken_contract_name",
    "unused_revision_name",
]

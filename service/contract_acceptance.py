"""Explicit acceptance workflow for external-wrapper contract proposals."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from . import analyze_service, scan_store


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "config" / "external_wrapper_contracts.json"
DEFAULT_CATALOG_PATH = PROJECT_ROOT.parent / "llamaindex-spec-rag" / "catalog" / "system_catalog.json"
ALLOWED_MODES = frozenset({"stored_procedure", "inline_sql", "call_site"})
ALLOWED_SINKS = {
    "executenonquery": "ExecuteNonQuery",
    "executereader": "ExecuteReader",
    "executescalar": "ExecuteScalar",
}
_CONTRACT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_IDENTIFIER_PATH_PATTERN = re.compile(
    r"^@?[A-Za-z_][A-Za-z0-9_]*(?:\.[@A-Za-z_][A-Za-z0-9_]*)*$"
)


class ContractAcceptanceError(ValueError):
    """A proposal cannot be validated or applied safely."""

    def __init__(self, code: str, message: str, details: Optional[Iterable[str]] = None):
        self.code = code
        self.details = tuple(str(item) for item in (details or ()))
        super().__init__(message)


def _error(code: str, message: str, details: Iterable[str] = ()) -> None:
    raise ContractAcceptanceError(code, message, details)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _error(f"{label}_not_found", f"{label} 不存在：{path}")
    except (OSError, json.JSONDecodeError) as exc:
        _error(f"{label}_invalid", f"{label} 無法讀取或不是有效 JSON：{path}", [str(exc)])
    if not isinstance(payload, dict):
        _error(f"{label}_invalid", f"{label} 根節點必須是 JSON object：{path}")
    return payload


def _contract_entries(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    contracts = payload.get("contracts")
    if not isinstance(contracts, Mapping):
        _error("registry_invalid", "external wrapper registry 必須包含 contracts object")
    entries: dict[str, dict[str, Any]] = {}
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
        entries[name] = copy.deepcopy(dict(raw_contract))
        folded_names[folded] = name
    return entries


def load_contract_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    """Load the active registry with fail-closed structural validation."""
    registry_path = Path(path)
    payload = _read_json(registry_path, "registry")
    _contract_entries(payload)
    return payload


def _validate_receiver_types(value: Any, contract_name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        _error(
            "invalid_receiver_types",
            f"contract {contract_name!r} 必須宣告至少一個 receiver_types",
        )
    receivers: list[str] = []
    seen: set[str] = set()
    for raw_receiver in value:
        if not isinstance(raw_receiver, str):
            _error("invalid_receiver_type", f"receiver type 無效：{raw_receiver!r}")
        receiver = raw_receiver.strip()
        if not receiver or not _IDENTIFIER_PATH_PATTERN.fullmatch(receiver):
            _error("invalid_receiver_type", f"receiver type 無效：{receiver!r}")
        folded = receiver.casefold()
        if folded in seen:
            _error("duplicate_receiver_type", f"receiver type 不可重複：{receiver}")
        seen.add(folded)
        receivers.append(receiver)
    return receivers


def _validate_methods(value: Any, contract_name: str) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or not value:
        _error(
            "incomplete_method_semantics",
            f"contract {contract_name!r} 必須宣告含 approved mode 與 sink 的 methods",
        )
    methods: dict[str, dict[str, str]] = {}
    seen: dict[str, str] = {}
    for raw_method, raw_semantics in value.items():
        if not isinstance(raw_method, str):
            _error("invalid_method_identity", f"method identity 無效：{raw_method!r}")
        method = raw_method.strip()
        if not method or not _IDENTIFIER_PATH_PATTERN.fullmatch(method) or "." in method:
            _error("invalid_method_identity", f"method identity 無效：{method!r}")
        folded = method.casefold()
        if folded in seen:
            _error(
                "duplicate_method_identity",
                f"method identity 不可重複（不分大小寫）：{method}",
                [seen[folded], method],
            )
        if not isinstance(raw_semantics, Mapping):
            _error(
                "incomplete_method_semantics",
                f"method {contract_name}.{method} 缺少 approved mode/sink",
            )
        mode = str(
            raw_semantics.get("mode")
            or raw_semantics.get("approved_mode")
            or ""
        ).strip().casefold()
        sink_value = str(
            raw_semantics.get("sink")
            or raw_semantics.get("approved_sink")
            or ""
        ).strip()
        if not mode or not sink_value:
            _error(
                "incomplete_method_semantics",
                f"method {contract_name}.{method} 必須同時提供 approved mode 與 sink",
            )
        if mode not in ALLOWED_MODES:
            _error("invalid_contract_mode", f"不允許的 contract mode：{mode}")
        sink = ALLOWED_SINKS.get(sink_value.casefold())
        if sink is None:
            _error("invalid_contract_sink", f"不允許的 contract sink：{sink_value}")
        methods[method] = {"mode": mode, "sink": sink}
        seen[folded] = method
    return methods


def _normalize_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    candidate: Mapping[str, Any] = proposal
    nested = proposal.get("contract")
    if isinstance(nested, Mapping):
        candidate = nested

    raw_name = candidate.get("name")
    if raw_name is None:
        raw_name = candidate.get("contract_name")
    if not isinstance(raw_name, str):
        _error("invalid_contract_name", f"contract name 無效：{raw_name!r}")
    name = raw_name.strip()
    if not name or not _CONTRACT_NAME_PATTERN.fullmatch(name):
        _error("invalid_contract_name", f"contract name 無效：{name!r}")

    receiver_types = candidate.get("receiver_types")
    if receiver_types is None and candidate.get("receiver_type") is not None:
        receiver_types = [candidate.get("receiver_type")]
    receivers = _validate_receiver_types(receiver_types, name)

    methods = candidate.get("methods")
    if methods is None and candidate.get("observed_method") is not None:
        methods = {
            str(candidate.get("observed_method")): {
                "mode": candidate.get("mode") or candidate.get("approved_mode"),
                "sink": candidate.get("sink") or candidate.get("approved_sink"),
            }
        }
    normalized_methods = _validate_methods(methods, name)
    auto_select_provided = "auto_select" in candidate
    auto_select = candidate.get("auto_select", True)
    if not isinstance(auto_select, bool):
        _error("invalid_auto_select", f"contract {name!r} 的 auto_select 必須是 boolean")
    return {
        "name": name,
        "auto_select": auto_select,
        "auto_select_provided": auto_select_provided,
        "receiver_types": receivers,
        "methods": normalized_methods,
    }


def _find_casefold(mapping: Mapping[str, Any], name: str) -> Optional[str]:
    folded = str(name).casefold()
    return next((key for key in mapping if str(key).casefold() == folded), None)


def _receiver_type_key(receiver_type: str) -> str:
    return str(receiver_type).strip().split(".")[-1].casefold()


def _validated_active_contract(name: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_proposal(
        {
            "name": name,
            "auto_select": contract.get("auto_select", False),
            "receiver_types": contract.get("receiver_types"),
            "methods": contract.get("methods"),
        }
    )
    normalized.pop("name", None)
    normalized.pop("auto_select_provided", None)
    return normalized


def _validate_contract_registry(entries: Mapping[str, Any]) -> None:
    receiver_owners: dict[str, str] = {}
    for name, contract in entries.items():
        normalized = _validated_active_contract(name, contract)
        for receiver in normalized["receiver_types"]:
            receiver_key = _receiver_type_key(receiver)
            owner = receiver_owners.get(receiver_key)
            if owner is not None and owner != name:
                _error(
                    "duplicate_receiver_contract",
                    f"receiver type 不可由多個 contract 擁有：{receiver}",
                    [owner, name],
                )
            receiver_owners[receiver_key] = name


def _prepare_registry(
    registry_payload: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> tuple[dict[str, Any], str, bool, str]:
    before_entries = _contract_entries(registry_payload)
    _validate_contract_registry(before_entries)
    normalized = _normalize_proposal(proposal)
    proposal_name = normalized["name"]
    existing_name = _find_casefold(before_entries, proposal_name)
    receiver_reuse = False

    receiver_keys = {_receiver_type_key(value) for value in normalized["receiver_types"]}
    receiver_matches = []
    for existing_name_candidate, existing_contract in before_entries.items():
        existing_receivers = existing_contract.get("receiver_types", [])
        if not isinstance(existing_receivers, (list, tuple)):
            continue
        if receiver_keys.intersection(
            {_receiver_type_key(value) for value in existing_receivers}
        ):
            receiver_matches.append(existing_name_candidate)

    if existing_name is None and receiver_matches:
        if len(receiver_matches) > 1:
            _error(
                "duplicate_receiver_contract",
                "receiver type 已由多個既有 contract 擁有",
                receiver_matches,
            )
        matched_name = receiver_matches[0]
        matched_receivers = before_entries[matched_name].get("receiver_types", [])
        matched_keys = {
            _receiver_type_key(value)
            for value in matched_receivers
            if isinstance(value, str)
        }
        if not receiver_keys.issubset(matched_keys):
            _error(
                "duplicate_receiver_contract",
                f"receiver type 已由既有 contract 擁有，請重用 {matched_name!r}",
                [matched_name],
            )
        existing_name = matched_name
        receiver_reuse = True

    if existing_name is None:
        active_name = proposal_name
        merged_contract = {
            "auto_select": normalized["auto_select"],
            "receiver_types": normalized["receiver_types"],
            "methods": normalized["methods"],
        }
        reused = False
        reuse_reason = "new_contract"
    else:
        active_name = existing_name
        existing_contract = _validated_active_contract(
            existing_name,
            before_entries[existing_name],
        )
        merged_receivers = list(existing_contract["receiver_types"])
        existing_receiver_keys = {
            _receiver_type_key(value) for value in merged_receivers
        }
        for receiver in normalized["receiver_types"]:
            if _receiver_type_key(receiver) not in existing_receiver_keys:
                merged_receivers.append(receiver)
        merged_methods = dict(existing_contract["methods"])
        merged_methods.update(normalized["methods"])
        merged_contract = {
            "auto_select": (
                normalized["auto_select"]
                if normalized["auto_select_provided"]
                else existing_contract["auto_select"]
            ),
            "receiver_types": merged_receivers,
            "methods": merged_methods,
        }
        _validated_active_contract(active_name, merged_contract)
        reused = True
        reuse_reason = (
            "existing_contract_reused_by_receiver_type"
            if receiver_reuse
            else "existing_contract_reused"
        )

    after_entries = copy.deepcopy(before_entries)
    after_entries[active_name] = merged_contract
    _validate_contract_registry(after_entries)
    after_payload = copy.deepcopy(dict(registry_payload))
    after_payload["contracts"] = after_entries
    return after_payload, active_name, reused, reuse_reason


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _diff(path: Path, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    before_text = _json_text(before)
    after_text = _json_text(after)
    return {
        "path": str(path),
        "changed": before_text != after_text,
        "before": copy.deepcopy(dict(before)),
        "after": copy.deepcopy(dict(after)),
        "unified": "".join(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile=f"{path} (before)",
                tofile=f"{path} (after)",
            )
        ),
    }


def _catalog_after_selector(
    catalog_payload: Mapping[str, Any],
    system_id: str,
    selector: str,
    active_contracts: Mapping[str, Any],
) -> dict[str, Any]:
    systems = catalog_payload.get("systems")
    if not isinstance(systems, list):
        _error("catalog_invalid", "system catalog 必須包含 systems array")
    system = next(
        (
            item
            for item in systems
            if isinstance(item, Mapping)
            and str(item.get("system_id") or "").strip() == system_id
        ),
        None,
    )
    if system is None:
        _error("system_not_found", f"system selector target 不存在：{system_id}")
    contract_name = _find_casefold(active_contracts, selector)
    if contract_name is None:
        _error("selector_contract_not_found", f"requested selector 不存在：{selector}")
    after = copy.deepcopy(dict(catalog_payload))
    after_systems = after["systems"]
    target = next(
        item
        for item in after_systems
        if isinstance(item, Mapping)
        and str(item.get("system_id") or "").strip() == system_id
    )
    target["wrapper_contract"] = contract_name
    return after


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_json_text(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _payload_digest(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _scan_identity(scan: Any) -> tuple[str, str]:
    raw = getattr(scan, "db_invocations", {}) or {}
    snapshots = getattr(scan, "source_snapshots", {}) or {}
    raw_identity = {
        str(path): records
        for path, records in sorted(raw.items(), key=lambda item: str(item[0]))
    }
    snapshot_identity = {
        str(path): {
            "relative_path": str(getattr(snapshot, "relative_path", "")),
            "content_hash": str(getattr(snapshot, "content_hash", "")),
        }
        for path, snapshot in sorted(snapshots.items(), key=lambda item: str(item[0]))
    }
    return _payload_digest(raw_identity), _payload_digest(snapshot_identity)


def reclassify_cached_scans(
    scan_roots: Iterable[Path | str],
    contract_registry: Mapping[str, Any],
    *,
    explicit_contract: str = "",
) -> dict[str, Any]:
    """Classify current cached raw facts without invoking a scanner."""
    unique_roots: list[Path] = []
    seen: set[str] = set()
    for raw_root in scan_roots:
        root = Path(raw_root)
        key = str(root.resolve()).casefold()
        if key and key not in seen:
            unique_roots.append(root)
            seen.add(key)

    cache_entries: list[dict[str, Any]] = []
    scans = []
    before_identities: dict[str, tuple[str, str]] = {}
    for root in unique_roots:
        status = scan_store.cache_status(root)
        if status != "current":
            cache_entries.append({"root": str(root), "status": status})
            continue
        scan = scan_store.load_cached(root)
        if scan is None:
            cache_entries.append({"root": str(root), "status": "invalid"})
            continue
        scans.append(scan)
        before_identities[str(root.resolve())] = _scan_identity(scan)
        cache_entries.append(
            {
                "root": str(root),
                "status": "current",
                "source_commit": scan_store.cached_commit(root) or "",
            }
        )

    wrapper_summary = analyze_service.reconcile_refresh_wrappers(
        scans,
        explicit_contract=explicit_contract,
        contract_registry=contract_registry,
    )
    after_identities = {
        str(scan.project_root): _scan_identity(scan)
        for scan in scans
    }
    return {
        "cache": cache_entries,
        "wrapper_summary": wrapper_summary,
        "analyzer_calls": 0,
        "raw_facts_changed": any(
            before_identities.get(root) != after_identities.get(root)
            for root in set(before_identities) | set(after_identities)
        ),
        "source_snapshots_changed": any(
            before_identities.get(root, ("", ""))[1]
            != after_identities.get(root, ("", ""))[1]
            for root in set(before_identities) | set(after_identities)
        ),
    }


def accept_external_wrapper_contract(
    proposal: Mapping[str, Any],
    *,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    system_id: str = "",
    requested_selector: str = "",
    scan_roots: Iterable[Path | str] = (),
    apply: bool = False,
) -> dict[str, Any]:
    """Validate, preview, or explicitly apply one reviewed contract proposal."""
    registry_file = Path(registry_path)
    catalog_file = Path(catalog_path)
    before_registry = load_contract_registry(registry_file)
    after_registry, active_name, reused, reuse_reason = _prepare_registry(
        before_registry,
        proposal,
    )

    normalized_system_id = str(system_id or "").strip()
    normalized_selector = str(requested_selector or "").strip()
    before_catalog: Optional[dict[str, Any]] = None
    after_catalog: Optional[dict[str, Any]] = None
    selector_contract_name = ""
    catalog_diff: dict[str, Any] = {
        "path": str(catalog_file),
        "changed": False,
        "before": None,
        "after": None,
        "unified": "",
    }
    if normalized_selector:
        if not normalized_system_id:
            _error("system_id_required", "requested selector 必須搭配明確 system_id")
        before_catalog = _read_json(catalog_file, "catalog")
        after_catalog = _catalog_after_selector(
            before_catalog,
            normalized_system_id,
            normalized_selector,
            after_registry["contracts"],
        )
        selector_contract_name = _find_casefold(
            after_registry["contracts"],
            normalized_selector,
        ) or ""
        catalog_diff = _diff(catalog_file, before_catalog, after_catalog)

    registry_diff = _diff(registry_file, before_registry, after_registry)
    reclassification = reclassify_cached_scans(
        scan_roots,
        after_registry["contracts"],
        explicit_contract=selector_contract_name,
    )

    written_files: list[str] = []
    if apply:
        registry_original = registry_file.read_bytes()
        catalog_original = catalog_file.read_bytes() if before_catalog is not None else None
        written_originals: list[tuple[Path, bytes]] = []
        try:
            if registry_diff["changed"]:
                _atomic_write_json(registry_file, after_registry)
                written_files.append(str(registry_file))
                written_originals.append((registry_file, registry_original))
            if catalog_diff["changed"] and after_catalog is not None:
                _atomic_write_json(catalog_file, after_catalog)
                written_files.append(str(catalog_file))
                if catalog_original is not None:
                    written_originals.append((catalog_file, catalog_original))
        except Exception as exc:
            rollback_errors: list[str] = []
            for path, original in reversed(written_originals):
                try:
                    _atomic_write_bytes(path, original)
                except Exception as rollback_exc:
                    rollback_errors.append(f"{path}: {rollback_exc}")
            if rollback_errors:
                _error(
                    "apply_rollback_failed",
                    f"active configuration 寫入失敗且 rollback 不完整：{exc}",
                    rollback_errors,
                )
            _error("apply_failed", f"active configuration 寫入失敗，已完成 rollback：{exc}")

    return {
        "status": "applied" if apply else "preview",
        "valid": True,
        "contract": active_name,
        "reused": reused,
        "reuse_reason": reuse_reason,
        "registry_diff": registry_diff,
        "catalog_diff": catalog_diff,
        "reclassification": reclassification,
        "applied": bool(apply),
        "written_files": written_files,
        "git_commit": False,
    }


accept_contract_proposal = accept_external_wrapper_contract


__all__ = [
    "ALLOWED_MODES",
    "ALLOWED_SINKS",
    "ContractAcceptanceError",
    "accept_contract_proposal",
    "accept_external_wrapper_contract",
    "load_contract_registry",
    "reclassify_cached_scans",
]
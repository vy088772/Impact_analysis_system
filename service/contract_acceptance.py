"""Explicit acceptance workflow for external-wrapper contract proposals."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from code_analyzer.external_wrapper_contracts import (
    ContractSnapshotError,
    compare_implementation_snapshot,
    versioned_contract_from_proposal,
)

from . import analyze_service, scan_store
from .contract_registry import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_REGISTRY_PATH,
    ContractRegistryError,
    _validate_registry_content,
    find_casefold,
    load_contract_registry,
    unused_revision_name,
)
from .contract_transaction import ContractTransactionError, commit_staged_contract_transaction


ALLOWED_MODES = frozenset({"stored_procedure", "inline_sql", "call_site"})
ALLOWED_SINKS = {
    "executenonquery": "ExecuteNonQuery",
    "executenonqueryasync": "ExecuteNonQueryAsync",
    "executereader": "ExecuteReader",
    "executereaderasync": "ExecuteReaderAsync",
    "executescalar": "ExecuteScalar",
    "executescalarasync": "ExecuteScalarAsync",
    "fill": "Fill",
    "fillasync": "FillAsync",
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


def _validated_registry_entries(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Re-validate an already-loaded registry payload and return its entries.

    Structural validation is delegated to the shared module's internal
    validation logic (the same rules ``load_contract_registry(strict=True)``
    enforces), translated to ``ContractAcceptanceError`` at this seam so the
    two validation passes can't drift apart.
    """
    try:
        _validate_registry_content(payload)
    except ContractRegistryError as exc:
        _error(exc.code, str(exc), exc.details)
    contracts = payload.get("contracts", {})
    return {
        str(raw_name).strip(): copy.deepcopy(dict(raw_contract))
        for raw_name, raw_contract in contracts.items()
    }


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


def _validate_methods(value: Any, contract_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        _error(
            "incomplete_method_semantics",
            f"contract {contract_name!r} 必須宣告含 approved mode 與 sink 的 methods",
        )
    methods: dict[str, Any] = {}
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
        overload_values = (
            list(raw_semantics)
            if isinstance(raw_semantics, (list, tuple))
            else [raw_semantics]
        )
        if not overload_values or any(not isinstance(item, Mapping) for item in overload_values):
            _error(
                "incomplete_method_semantics",
                f"method {contract_name}.{method} 缺少 approved mode/sink",
            )
        normalized_overloads: list[dict[str, Any]] = []
        for semantics in overload_values:
            mode = str(
                semantics.get("mode")
                or semantics.get("approved_mode")
                or ""
            ).strip().casefold()
            sink_value = str(
                semantics.get("sink")
                or semantics.get("approved_sink")
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
            raw_default_mode = str(
                semantics.get("default_mode")
                or semantics.get("default_command_type")
                or ""
            ).strip().casefold().replace("-", "_").replace(" ", "_")
            default_mode = {
                "text": "inline_sql",
                "default_text": "inline_sql",
                "inline_sql": "inline_sql",
                "stored_procedure": "stored_procedure",
            }.get(raw_default_mode, "")
            if raw_default_mode and not default_mode:
                _error("invalid_contract_default_mode", f"不允許的 contract default mode：{raw_default_mode}")
            if default_mode and mode != "call_site":
                _error(
                    "invalid_contract_default_mode",
                    f"只有 call_site method 可以宣告 default mode：{contract_name}.{method}",
                )
            normalized_semantics: dict[str, Any] = {"mode": mode, "sink": sink}
            if default_mode:
                normalized_semantics["default_mode"] = default_mode
            for optional_key in (
                "method_identity",
                "method_arity",
                "required_parameter_count",
                "parameter_types",
                "argument_roles",
                "branch_rules",
                "connection_behavior_boundary",
            ):
                if optional_key in semantics:
                    normalized_semantics[optional_key] = copy.deepcopy(semantics[optional_key])
            normalized_overloads.append(normalized_semantics)
        methods[method] = (
            normalized_overloads
            if isinstance(raw_semantics, (list, tuple))
            else normalized_overloads[0]
        )
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
    return {
        "name": name,
        "receiver_types": receivers,
        "methods": normalized_methods,
    }


def _receiver_type_key(receiver_type: str) -> str:
    return str(receiver_type).strip().split(".")[-1].casefold()


def _validated_active_contract(name: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_proposal(
        {
            "name": name,
            "receiver_types": contract.get("receiver_types"),
            "methods": contract.get("methods"),
        }
    )
    normalized.pop("name", None)
    return normalized


def _validate_contract_registry(entries: Mapping[str, Any]) -> None:
    receiver_owners: dict[str, str] = {}
    for name, contract in entries.items():
        normalized = _validated_active_contract(name, contract)
        for receiver in normalized["receiver_types"]:
            receiver_key = _receiver_type_key(receiver)
            owner = receiver_owners.get(receiver_key)
            if owner is not None and owner != name:
                owner_contract = entries.get(owner, {})
                versioned = bool(
                    contract.get("contract_fingerprint")
                    and owner_contract.get("contract_fingerprint")
                )
                if not versioned:
                    _error(
                        "duplicate_receiver_contract",
                        f"receiver type 不可由多個 contract 擁有：{receiver}",
                        [owner, name],
                    )
                continue
            receiver_owners[receiver_key] = name


def _prepare_registry(
    registry_payload: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    allow_legacy_mutation: bool = True,
) -> tuple[dict[str, Any], str, bool, str]:
    before_entries = _validated_registry_entries(registry_payload)
    _validate_contract_registry(before_entries)
    normalized = _normalize_proposal(proposal)
    proposal_name = normalized["name"]
    existing_name = find_casefold(before_entries, proposal_name)
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

    if existing_name is not None and before_entries[existing_name].get("contract_fingerprint"):
        _error(
            "immutable_contract",
            f"accepted contract {existing_name!r} 必須以新的 fingerprint revision 更新",
            [str(before_entries[existing_name].get("contract_fingerprint"))],
        )
    if existing_name is None:
        active_name = proposal_name
        merged_contract = {
            "receiver_types": normalized["receiver_types"],
            "methods": normalized["methods"],
            "status": "legacy_unverified",
            "lifecycle": {"status": "legacy_unverified"},
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
            "receiver_types": merged_receivers,
            "methods": merged_methods,
            "status": str(
                before_entries[existing_name].get("status") or "legacy_unverified"
            ),
            "lifecycle": copy.deepcopy(
                before_entries[existing_name].get(
                    "lifecycle", {"status": "legacy_unverified"}
                )
            ),
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
    if existing_name is not None and not allow_legacy_mutation:
        _error(
            "legacy_contract_requires_explicit_binding",
            f"legacy contract {existing_name!r} 只能在 explicit binding 下相容更新",
            [existing_name],
        )
    after_payload = copy.deepcopy(dict(registry_payload))
    after_payload["contracts"] = after_entries
    return after_payload, active_name, reused, reuse_reason


def _proposal_name(proposal: Mapping[str, Any]) -> str:
    candidate = proposal.get("contract")
    if isinstance(candidate, Mapping):
        proposal = candidate
    raw_name = proposal.get("name")
    if raw_name is None:
        raw_name = proposal.get("contract_name")
    return str(raw_name or "").strip()


def _append_comparison_report(
    payload: Mapping[str, Any],
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    after_payload = copy.deepcopy(dict(payload))
    reports = after_payload.get("comparison_reports")
    if not isinstance(reports, dict):
        reports = {}
    base_reference = str(report.get("comparison_report_reference") or "comparison")
    reference = base_reference
    revision = 2
    while reference in reports:
        reference = f"{base_reference}-{revision}"
        revision += 1
    stored_report = copy.deepcopy(dict(report))
    stored_report["comparison_report_reference"] = reference
    stored_report["latest_reference"] = reference
    stored_report["history_reference"] = reference
    reports[reference] = stored_report
    history = after_payload.get("comparison_report_history")
    if not isinstance(history, list):
        history = []
    history.append(reference)
    after_payload["comparison_reports"] = reports
    after_payload["comparison_report_latest"] = reference
    after_payload["comparison_report_history"] = history
    return after_payload, stored_report


def _prepare_versioned_registry(
    registry_payload: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> tuple[dict[str, Any], str, bool, str, dict[str, Any]]:
    before_entries = _validated_registry_entries(registry_payload)
    _validate_contract_registry(before_entries)
    try:
        versioned_entry, report = versioned_contract_from_proposal(proposal)
    except ContractSnapshotError as exc:
        _error("incomplete_implementation_snapshot", str(exc), exc.reasons)

    fingerprint = str(versioned_entry["contract_fingerprint"])
    existing_fingerprint_name = next(
        (
            name
            for name, contract in before_entries.items()
            if str(contract.get("contract_fingerprint") or "") == fingerprint
        ),
        None,
    )
    if existing_fingerprint_name is not None:
        candidate = (
            proposal.get("contract")
            if isinstance(proposal.get("contract"), Mapping)
            else proposal
        )
        snapshot = next(
            (
                candidate.get(key)
                for key in (
                    "implementation_snapshot",
                    "verified_implementation_snapshot",
                    "snapshot",
                    "source_implementation_snapshot",
                    "source_snapshot",
                )
                if isinstance(candidate.get(key), Mapping)
            ),
            {},
        )
        comparison_report = compare_implementation_snapshot(
            snapshot,
            before_entries[existing_fingerprint_name],
        )
        after_payload, comparison_report = _append_comparison_report(
            registry_payload,
            comparison_report,
        )
        existing_entry = copy.deepcopy(
            after_payload["contracts"][existing_fingerprint_name]
        )
        existing_report_refs = existing_entry.get("comparison_reports")
        existing_history = (
            list(existing_report_refs.get("history", []))
            if isinstance(existing_report_refs, Mapping)
            else []
        )
        if not existing_history and existing_entry.get("comparison_report"):
            existing_history.append(str(existing_entry["comparison_report"]))
        existing_history.append(comparison_report["comparison_report_reference"])
        existing_entry["comparison_report"] = comparison_report[
            "comparison_report_reference"
        ]
        existing_entry["comparison_reports"] = {
            "latest": comparison_report["latest_reference"],
            "history": existing_history,
        }
        after_payload["contracts"][existing_fingerprint_name] = existing_entry
        return (
            after_payload,
            existing_fingerprint_name,
            True,
            "existing_contract_reused_by_fingerprint",
            comparison_report,
        )

    base_name = _proposal_name(proposal)
    if not base_name or not _CONTRACT_NAME_PATTERN.fullmatch(base_name):
        _error("invalid_contract_name", f"contract name 無效：{base_name!r}")
    existing_name = find_casefold(before_entries, base_name)
    if existing_name is None:
        active_name = base_name
    else:
        active_name = unused_revision_name(before_entries, {}, existing_name, fingerprint)

    after_payload, report = _append_comparison_report(registry_payload, report)
    versioned_entry = copy.deepcopy(versioned_entry)
    versioned_entry["comparison_report"] = report["comparison_report_reference"]
    versioned_entry["comparison_reports"] = {
        "latest": report["latest_reference"],
        "history": [report["history_reference"]],
    }
    after_entries = copy.deepcopy(before_entries)
    after_entries[active_name] = versioned_entry
    _validate_contract_registry(after_entries)
    after_payload["contracts"] = after_entries
    return after_payload, active_name, False, "new_immutable_contract_revision", report


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
    contract_name = find_casefold(active_contracts, selector)
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
    database: str = "",
) -> dict[str, Any]:
    """Classify current cached raw facts without invoking a scanner.

    ``database`` is the local SQL-cache key.  Registry-only acceptance may
    omit it; that deliberately keeps database evidence unresolved rather than
    selecting an unknown catalog.
    """
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
        database=database,
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
    try:
        before_registry = load_contract_registry(registry_file, strict=True)
    except ContractRegistryError as exc:
        _error(exc.code, str(exc), exc.details)
    candidate = proposal.get("contract") if isinstance(proposal.get("contract"), Mapping) else proposal
    has_snapshot = any(
        isinstance(candidate.get(key), Mapping)
        for key in (
            "implementation_snapshot",
            "verified_implementation_snapshot",
            "snapshot",
            "source_implementation_snapshot",
            "source_snapshot",
        )
    )
    comparison_report: Optional[dict[str, Any]] = None
    if has_snapshot:
        (
            after_registry,
            active_name,
            reused,
            reuse_reason,
            comparison_report,
        ) = _prepare_versioned_registry(before_registry, proposal)
    else:
        after_registry, active_name, reused, reuse_reason = _prepare_registry(
            before_registry,
            proposal,
            allow_legacy_mutation=(
                not apply or bool(str(requested_selector or "").strip())
            ),
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
        catalog_selector = normalized_selector
        if (
            has_snapshot
            and find_casefold(after_registry["contracts"], catalog_selector) is None
            and catalog_selector.casefold() == _proposal_name(proposal).casefold()
        ):
            catalog_selector = active_name
        after_catalog = _catalog_after_selector(
            before_catalog,
            normalized_system_id,
            catalog_selector,
            after_registry["contracts"],
        )
        selector_contract_name = find_casefold(
            after_registry["contracts"],
            catalog_selector,
        ) or ""
        catalog_diff = _diff(catalog_file, before_catalog, after_catalog)

    registry_diff = _diff(registry_file, before_registry, after_registry)
    # Reclassification preview is always bound to the one candidate contract
    # under review (an explicit binding decision this workflow makes on the
    # maintainer's behalf), never inferred from a receiver type name --
    # auto-select is removed from the contract domain and runtime path.
    reclassification = reclassify_cached_scans(
        scan_roots,
        after_registry["contracts"],
        explicit_contract=selector_contract_name or active_name,
        database=normalized_system_id,
    )

    written_files: list[str] = []
    transaction_id = ""
    manifest_path = ""
    if apply:
        try:
            commit_result = commit_staged_contract_transaction(
                staged_registry=after_registry,
                trigger="manual_acceptance",
                staged_selector=selector_contract_name,
                system_id=normalized_system_id,
                registry_path=registry_file,
                catalog_path=catalog_file,
            )
            written_files = list(commit_result["written_files"])
            transaction_id = str(commit_result["transaction_id"])
            manifest_path = str(commit_result["manifest_path"])
        except ContractTransactionError as exc:
            _error(exc.code, str(exc), exc.details)

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
        "transaction_id": transaction_id,
        "manifest_path": manifest_path,
        "git_commit": False,
        "contract_fingerprint": (
            comparison_report["contract_fingerprint"]
            if comparison_report is not None
            else str(after_registry["contracts"].get(active_name, {}).get("contract_fingerprint") or "")
        ),
        "contract_status": str(
            after_registry["contracts"].get(active_name, {}).get("status") or ""
        ),
        "signature_version": (
            comparison_report["signature_version"]
            if comparison_report is not None
            else str(after_registry["contracts"].get(active_name, {}).get("signature_version") or "")
        ),
        "comparison_report": comparison_report,
    }


accept_contract_proposal = accept_external_wrapper_contract


__all__ = [
    "ALLOWED_MODES",
    "ALLOWED_SINKS",
    "ContractAcceptanceError",
    "accept_contract_proposal",
    "accept_external_wrapper_contract",
    "reclassify_cached_scans",
]
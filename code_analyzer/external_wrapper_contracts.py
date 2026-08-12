"""Immutable identity and comparison helpers for external wrapper contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Optional


CONTRACT_SIGNATURE_SCHEMA_VERSION = "contract-behavior-v1"
SIGNATURE_SCHEMA_VERSION = CONTRACT_SIGNATURE_SCHEMA_VERSION

_MODE_ALIASES = {
    "text": "inline_sql",
    "default_text": "inline_sql",
    "inline": "inline_sql",
    "inline_sql": "inline_sql",
    "fixed_text": "inline_sql",
    "fixed_inline_sql": "inline_sql",
    "storedprocedure": "stored_procedure",
    "stored-procedure": "stored_procedure",
    "stored_procedure": "stored_procedure",
    "fixed_stored_procedure": "stored_procedure",
    "callsite": "call_site",
    "call_site": "call_site",
}
_SINK_ALIASES = {
    "executenonquery": "ExecuteNonQuery",
    "executenonqueryasync": "ExecuteNonQueryAsync",
    "executereader": "ExecuteReader",
    "executereaderasync": "ExecuteReaderAsync",
    "executescalar": "ExecuteScalar",
    "executescalarasync": "ExecuteScalarAsync",
    "fill": "Fill",
    "fillasync": "FillAsync",
}


class ContractSnapshotError(ValueError):
    """A verified implementation snapshot cannot establish a complete surface."""

    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons if reason))
        super().__init__(", ".join(self.reasons) or "incomplete_snapshot")


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _normalized_type(value: object) -> str:
    normalized = _text(value)
    if normalized.startswith("global::"):
        normalized = normalized[8:]
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.casefold()


def _text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_text(value),) if _text(value) else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(_text(item) for item in value if _text(item))


def _parameter_types(value: object) -> tuple[str, ...]:
    return tuple(_normalized_type(item) for item in _text_values(value))


def _mode(value: object) -> str:
    normalized = _normalized_text(value).replace(" ", "_")
    return _MODE_ALIASES.get(normalized, normalized)


def _sink(value: object) -> str:
    normalized = _normalized_text(value).replace("_", "")
    return _SINK_ALIASES.get(normalized, _text(value))


def _first(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            _normalized_text(key): _canonical_value(value[key])
            for key in sorted(value, key=lambda item: _normalized_text(item))
            if _text(key)
        }
    if isinstance(value, (list, tuple, set)):
        values = [_canonical_value(item) for item in value]
        return sorted(values, key=lambda item: _stable_json(item))
    if isinstance(value, str):
        return _normalized_text(value)
    return value


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _is_non_database_operation(operation: Mapping[str, Any]) -> bool:
    if operation.get("database_operation") is False:
        return True
    if operation.get("is_database_operation") is False:
        return True
    return _normalized_text(
        _first(operation, "operation_kind", "kind", "surface_kind")
    ) in {"utility", "non_database", "ui_helper"}


def _operation_name(operation: Mapping[str, Any]) -> str:
    explicit = _text(
        _first(operation, "operation_identity", "method_identity", "overload_identity", "identity")
    )
    method_name = _text(_first(operation, "method_name", "wrapper_method_name", "name"))
    parameter_types = _parameter_types(
        _first(operation, "parameter_types", "parameters", "parameter_type_names")
    )
    arity = _first(operation, "method_arity", "arity")
    if explicit:
        normalized = re.sub(r"\s+", "", explicit)
        normalized = normalized.replace("global::", "")
        return normalized.casefold()
    if method_name and parameter_types:
        return f"{method_name.casefold()}({','.join(parameter_types)})"
    if method_name and arity is not None:
        return f"{method_name.casefold()}/{int(arity)}"
    return method_name.casefold()


def _operation_records(value: object) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        records: list[dict[str, Any]] = []
        for method_name, semantics in value.items():
            values = semantics if isinstance(semantics, (list, tuple)) else (semantics,)
            for item in values:
                if isinstance(item, Mapping):
                    record = dict(item)
                else:
                    record = {}
                record.setdefault("method_name", str(method_name))
                records.append(record)
        return records
    if isinstance(value, (list, tuple, set)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _surface_operations(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    nested = value.get("behavior_surface")
    surface = nested if isinstance(nested, Mapping) else value
    operations = _first(surface, "operations", "methods", "public_database_operations")
    return _operation_records(operations)


def _branch_rules(operation: Mapping[str, Any]) -> object:
    rules = _first(operation, "branch_rules", "branch_scoped_sinks", "branches")
    if rules is None:
        mode = _mode(_first(operation, "effective_command_semantics", "mode", "approved_mode"))
        sink = _sink(_first(operation, "terminal_sink", "sink", "approved_sink"))
        if mode or sink:
            return [{"mode": mode, "sink": sink}]
        return []
    return _canonical_value(rules)


def _canonical_operation(operation: Mapping[str, Any]) -> dict[str, Any]:
    parameters = _parameter_types(
        _first(operation, "parameter_types", "parameters", "parameter_type_names")
    )
    arity_value = _first(operation, "method_arity", "arity")
    arity = int(arity_value) if arity_value is not None else len(parameters)
    mode = _mode(
        _first(
            operation,
            "effective_command_semantics",
            "effective_mode",
            "mode",
            "approved_mode",
            "method_semantics",
        )
    )
    sink = _sink(
        _first(operation, "terminal_sink", "sink", "approved_sink", "effective_terminal_sink")
    )
    identity = _operation_name(operation)
    argument_roles = _canonical_value(
        _first(operation, "argument_roles", "parameter_roles", "roles") or {}
    )
    connection_boundary = _normalized_text(
        _first(
            operation,
            "connection_behavior_boundary",
            "connection_boundary",
            "connection_source_behavior",
        )
    )
    branch_rules = _branch_rules(operation)
    return {
        "operation_identity": identity,
        "method_identity": identity,
        "method_name": _normalized_text(_first(operation, "method_name", "wrapper_method_name", "name")),
        "method_arity": arity,
        "parameter_types": list(parameters),
        "argument_roles": argument_roles,
        "effective_command_semantics": mode,
        "terminal_sink": sink,
        "connection_behavior_boundary": connection_boundary,
        "branch_rules": branch_rules,
    }


def canonical_contract_behavior_signature(
    contract_or_snapshot: Mapping[str, Any],
    *,
    signature_version: str = CONTRACT_SIGNATURE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Return the normalized database behavior surface used for identity."""
    operations = [
        _canonical_operation(operation)
        for operation in _surface_operations(contract_or_snapshot)
        if not _is_non_database_operation(operation)
    ]
    operations.sort(key=lambda item: _stable_json(item))
    return {
        "signature_version": _text(signature_version) or CONTRACT_SIGNATURE_SCHEMA_VERSION,
        "operations": operations,
    }


contract_behavior_signature = canonical_contract_behavior_signature
canonical_behavior_signature = canonical_contract_behavior_signature


def _implementation_boundary_identity(value: Mapping[str, Any]) -> str:
    behavior_surface = value.get("behavior_surface")
    source = behavior_surface if isinstance(behavior_surface, Mapping) else value
    parts = [
        _text(
            _first(
                source,
                "implementation_identity",
                "concrete_implementation",
                "behavior_surface_unit",
            )
        ),
        _text(_first(source, "assembly_identity", "assembly")),
        _text(_first(source, "assembly_revision", "revision", "version")),
    ]
    return "|".join(_normalized_text(part) for part in parts if _text(part))


def compute_contract_fingerprint(
    contract_or_snapshot: Mapping[str, Any],
    *,
    signature_version: str = CONTRACT_SIGNATURE_SCHEMA_VERSION,
) -> str:
    """Return a deterministic SHA-256 fingerprint for a behavior signature."""
    signature = canonical_contract_behavior_signature(
        contract_or_snapshot,
        signature_version=signature_version,
    )
    payload = {
        "signature_version": signature["signature_version"],
        "behavior_signature": signature,
    }
    boundary_identity = _implementation_boundary_identity(contract_or_snapshot)
    if boundary_identity:
        payload["implementation_boundary"] = boundary_identity
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


contract_fingerprint = compute_contract_fingerprint
fingerprint_contract = compute_contract_fingerprint


def _snapshot_identity(snapshot: Mapping[str, Any]) -> str:
    explicit = _text(_first(snapshot, "snapshot_identity", "implementation_snapshot_identity"))
    if explicit:
        return explicit
    return hashlib.sha256(_stable_json(snapshot).encode("utf-8")).hexdigest()


def _snapshot_revisions(snapshot: Mapping[str, Any]) -> set[str]:
    revisions = {_text(snapshot.get("assembly_revision"))}
    revisions.update(_text_values(snapshot.get("assembly_revisions")))
    for operation in _surface_operations(snapshot):
        revision = _text(_first(operation, "assembly_revision", "revision"))
        if revision:
            revisions.add(revision)
    return {revision for revision in revisions if revision}


def validate_implementation_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Validate exact identity and completeness requirements for one snapshot."""
    reasons: list[str] = []
    unresolved_operations: list[str] = []
    required_fields = (
        "artifact_identity",
        "assembly_identity",
        "assembly_revision",
        "behavior_surface_unit",
    )
    missing_fields = [field for field in required_fields if not _text(snapshot.get(field))]
    if missing_fields:
        reasons.append("missing_snapshot_identity")
    if snapshot.get("complete") is False or snapshot.get("surface_complete") is False:
        reasons.append("incomplete_snapshot")
    if snapshot.get("public_database_operations_complete") is False:
        reasons.append("database_behavior_surface_incomplete")
    if snapshot.get("unknown_overloads") or snapshot.get("unresolved_overloads"):
        reasons.append("unknown_overload")
    if snapshot.get("unresolved_helper_operations") or snapshot.get("unresolved_inherited_operations"):
        reasons.append("unresolved_support_operation")
    if snapshot.get("conflicting_operations") or snapshot.get("conflicts"):
        reasons.append("conflicting_semantics")
    if snapshot.get("helper_operations_complete") is not True:
        reasons.append("helper_evidence_incomplete")
    if snapshot.get("inherited_operations_complete") is not True:
        reasons.append("inherited_evidence_incomplete")

    operations = _surface_operations(snapshot)
    if not operations:
        reasons.append("database_behavior_surface_missing")
    revisions = _snapshot_revisions(snapshot)
    if len(revisions) > 1:
        reasons.append("mixed_assembly_revision")

    for operation in operations:
        if _is_non_database_operation(operation):
            continue
        operation_identity = _operation_name(operation) or "<unknown-operation>"
        operation_reasons_before = len(reasons)
        if operation.get("body_complete") is not True:
            reasons.append("method_body_incomplete")
        if operation.get("unresolved") is True or operation.get("semantics_unresolved") is True:
            reasons.append("unresolved_operation")
        has_signature = bool(
            _text(
                _first(
                    operation,
                    "operation_identity",
                    "method_identity",
                    "overload_identity",
                    "identity",
                )
            )
            or _first(operation, "method_arity", "arity") is not None
            or _parameter_types(
                _first(operation, "parameter_types", "parameters", "parameter_type_names")
            )
        )
        if not _operation_name(operation) or not has_signature:
            reasons.append("method_identity_missing")
        if not isinstance(
            _first(operation, "argument_roles", "parameter_roles", "roles"),
            Mapping,
        ):
            reasons.append("argument_roles_missing")
        if not _text(
            _first(
                operation,
                "connection_behavior_boundary",
                "connection_boundary",
                "connection_source_behavior",
            )
        ):
            reasons.append("connection_behavior_boundary_missing")
        if not _mode(
            _first(
                operation,
                "effective_command_semantics",
                "effective_mode",
                "mode",
                "approved_mode",
                "method_semantics",
            )
        ):
            reasons.append("method_semantics_missing")
        if not _sink(
            _first(operation, "terminal_sink", "sink", "approved_sink", "effective_terminal_sink")
        ):
            reasons.append("terminal_sink_missing")
        if len(reasons) != operation_reasons_before:
            unresolved_operations.append(operation_identity)

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "complete": not unique_reasons,
        "status": "accepted" if not unique_reasons else "review",
        "unresolved_reasons": unique_reasons,
        "unresolved_operations": list(dict.fromkeys(unresolved_operations)),
        "missing_fields": missing_fields,
        "snapshot_identity": _snapshot_identity(snapshot),
        "artifact_identity": _text(snapshot.get("artifact_identity")),
        "assembly_identity": _text(snapshot.get("assembly_identity")),
        "assembly_revision": _text(snapshot.get("assembly_revision")),
        "behavior_surface_unit": _text(snapshot.get("behavior_surface_unit")),
        "assembly_revisions": sorted(revisions),
    }


def _signature_operations(signature: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    operations = signature.get("operations")
    if not isinstance(operations, list):
        return {}
    return {
        str(operation.get("operation_identity")): operation
        for operation in operations
        if isinstance(operation, Mapping) and operation.get("operation_identity")
    }


def _surface_differences(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, Any]:
    expected_operations = _signature_operations(expected)
    actual_operations = _signature_operations(actual)
    missing = sorted(set(expected_operations) - set(actual_operations))
    added = sorted(set(actual_operations) - set(expected_operations))
    changed = sorted(
        identity
        for identity in set(expected_operations) & set(actual_operations)
        if expected_operations[identity] != actual_operations[identity]
    )
    return {
        "missing_operations": missing,
        "added_operations": added,
        "changed_operations": changed,
    }


def compare_implementation_snapshot(
    snapshot: Mapping[str, Any],
    existing_contract: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compare one verified snapshot and return a durable onboarding report."""
    validation = validate_implementation_snapshot(snapshot)
    signature = canonical_contract_behavior_signature(snapshot)
    fingerprint = compute_contract_fingerprint(snapshot)
    differences = {
        "missing_operations": [],
        "added_operations": [],
        "changed_operations": [],
    }
    conflict_state = "none"
    if existing_contract is not None:
        existing_signature = existing_contract.get("behavior_signature")
        if not isinstance(existing_signature, Mapping):
            existing_signature = canonical_contract_behavior_signature(existing_contract)
        differences = _surface_differences(existing_signature, signature)
        if any(differences.values()):
            conflict_state = "behavior_changed"

    status = validation["status"]
    if status == "accepted" and conflict_state == "behavior_changed":
        status = "changed"
    report_reference = f"comparison-{fingerprint}"
    return {
        "status": status,
        "comparison_status": status,
        "snapshot_identity": validation["snapshot_identity"],
        "artifact_identity": validation["artifact_identity"],
        "assembly_identity": validation["assembly_identity"],
        "assembly_revision": validation["assembly_revision"],
        "assembly_revisions": validation["assembly_revisions"],
        "behavior_surface_unit": validation["behavior_surface_unit"],
        "signature_version": signature["signature_version"],
        "behavior_signature": signature,
        "contract_fingerprint": fingerprint,
        "method_differences": differences,
        "unresolved_operations": list(validation["unresolved_operations"]),
        "unresolved_reasons": list(validation["unresolved_reasons"]),
        "conflict_state": conflict_state,
        "comparison_report_reference": report_reference,
        "latest_reference": report_reference,
        "history_reference": report_reference,
    }


compare_contract_behavior_surfaces = compare_implementation_snapshot
compare_contract_surfaces = compare_implementation_snapshot


def implementation_snapshot_reference(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Return the exact artifact and revision identity used by a contract."""
    validation = validate_implementation_snapshot(snapshot)
    return {
        "snapshot_identity": validation["snapshot_identity"],
        "artifact_identity": validation["artifact_identity"],
        "assembly_identity": validation["assembly_identity"],
        "assembly_revision": validation["assembly_revision"],
        "behavior_surface_unit": validation["behavior_surface_unit"],
    }


def _normalized_method_projection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    projection: dict[str, Any] = {}
    for raw_name, raw_semantics in value.items():
        overloads = raw_semantics if isinstance(raw_semantics, (list, tuple)) else [raw_semantics]
        normalized_overloads: list[dict[str, Any]] = []
        for semantics in overloads:
            if not isinstance(semantics, Mapping):
                continue
            normalized: dict[str, Any] = {
                "mode": _mode(_first(semantics, "mode", "approved_mode")),
                "sink": _sink(_first(semantics, "sink", "approved_sink")),
            }
            for key in (
                "default_mode",
                "method_identity",
                "method_arity",
                "parameter_types",
                "argument_roles",
                "branch_rules",
                "connection_behavior_boundary",
            ):
                if key in semantics:
                    normalized[key] = copy.deepcopy(semantics[key])
            normalized_overloads.append(normalized)
        if normalized_overloads:
            projection[str(raw_name)] = (
                normalized_overloads
                if isinstance(raw_semantics, (list, tuple))
                else normalized_overloads[0]
            )
    return projection


def _snapshot_method_projection(
    operations: list[dict[str, Any]],
    provided: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for operation in operations:
        method_name = _text(_first(operation, "method_name", "wrapper_method_name", "name"))
        if not method_name:
            continue
        operation_arity = _first(operation, "method_arity", "arity")
        operation_parameters = _parameter_types(
            _first(operation, "parameter_types", "parameters", "parameter_type_names")
        )
        candidates: list[Mapping[str, Any]] = []
        if provided is not None:
            raw_value = next(
                (
                    value
                    for raw_name, value in provided.items()
                    if str(raw_name).strip().casefold() == method_name.casefold()
                ),
                None,
            )
            values = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
            candidates = [value for value in values if isinstance(value, Mapping)]
        matching: Optional[Mapping[str, Any]] = None
        for candidate in candidates:
            candidate_arity = _first(candidate, "method_arity", "arity")
            candidate_parameters = _parameter_types(
                _first(candidate, "parameter_types", "parameters", "parameter_type_names")
            )
            if operation_arity is not None and (
                candidate_arity is None or int(candidate_arity) != int(operation_arity)
            ):
                continue
            if operation_parameters and candidate_parameters != operation_parameters:
                continue
            matching = candidate
            break
        snapshot_mode = _mode(
            _first(
                operation,
                "effective_command_semantics",
                "effective_mode",
                "mode",
                "approved_mode",
                "method_semantics",
            )
        )
        snapshot_sink = _sink(
            _first(operation, "terminal_sink", "sink", "approved_sink", "effective_terminal_sink")
        )
        if provided is not None and matching is None:
            raise ContractSnapshotError(
                ("database_behavior_surface_incomplete", "missing_surface_operation")
            )
        if matching is not None:
            provided_mode = _mode(_first(matching, "mode", "approved_mode"))
            provided_sink = _sink(_first(matching, "sink", "approved_sink"))
            if provided_mode != snapshot_mode or provided_sink != snapshot_sink:
                raise ContractSnapshotError(("conflicting_semantics", "snapshot_method_conflict"))
            normalized = dict(matching)
        else:
            normalized = {}
        normalized.update({"mode": snapshot_mode, "sink": snapshot_sink})
        normalized.setdefault("method_identity", _operation_name(operation))
        normalized.setdefault(
            "method_arity",
            int(operation_arity) if operation_arity is not None else len(operation_parameters),
        )
        normalized.setdefault("parameter_types", list(operation_parameters))
        for key in ("argument_roles", "branch_rules", "connection_behavior_boundary"):
            if key in operation:
                normalized[key] = copy.deepcopy(operation[key])
        projection.setdefault(method_name, []).append(normalized)
    return {
        name: values[0] if len(values) == 1 else values
        for name, values in projection.items()
    }


def versioned_contract_from_proposal(proposal: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an immutable registry entry from a complete snapshot-backed proposal."""
    candidate = proposal.get("contract") if isinstance(proposal.get("contract"), Mapping) else proposal
    snapshot = _first(candidate, "implementation_snapshot", "verified_implementation_snapshot", "snapshot")
    if snapshot is None:
        snapshot = _first(
            candidate,
            "source_implementation_snapshot",
            "source_snapshot",
        )
    if not isinstance(snapshot, Mapping):
        raise ContractSnapshotError(("implementation_snapshot_missing",))
    report = compare_implementation_snapshot(snapshot)
    if report["status"] != "accepted":
        raise ContractSnapshotError(report["unresolved_reasons"])

    receiver_types = _text_values(candidate.get("receiver_types"))
    if not receiver_types:
        receiver_type = _text(candidate.get("receiver_type"))
        receiver_types = (receiver_type,) if receiver_type else ()
    if not receiver_types:
        raise ContractSnapshotError(("receiver_binding_missing",))

    methods = candidate.get("methods")
    provided_methods = methods if isinstance(methods, Mapping) and methods else None
    snapshot_operations = [
        operation
        for operation in _surface_operations(snapshot)
        if not _is_non_database_operation(operation)
    ]
    methods = _snapshot_method_projection(snapshot_operations, provided_methods)

    entry = {
        "auto_select": bool(candidate.get("auto_select", False)),
        "receiver_types": list(receiver_types),
        "methods": _normalized_method_projection(methods),
        "contract_fingerprint": report["contract_fingerprint"],
        "signature_version": report["signature_version"],
        "behavior_signature": report["behavior_signature"],
        "implementation_snapshots": [implementation_snapshot_reference(snapshot)],
        "status": "accepted",
        "lifecycle": {"status": "accepted", "revision": 1},
        "comparison_report": report["comparison_report_reference"],
        "comparison_reports": {
            "latest": report["latest_reference"],
            "history": [report["history_reference"]],
        },
    }
    return entry, report


__all__ = [
    "CONTRACT_SIGNATURE_SCHEMA_VERSION",
    "SIGNATURE_SCHEMA_VERSION",
    "ContractSnapshotError",
    "canonical_contract_behavior_signature",
    "contract_behavior_signature",
    "canonical_behavior_signature",
    "compute_contract_fingerprint",
    "contract_fingerprint",
    "fingerprint_contract",
    "validate_implementation_snapshot",
    "compare_implementation_snapshot",
    "compare_contract_behavior_surfaces",
    "compare_contract_surfaces",
    "implementation_snapshot_reference",
    "versioned_contract_from_proposal",
]
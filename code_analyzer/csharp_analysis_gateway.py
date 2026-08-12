"""CSharpAnalysisGateway: evidence-rated Database Invocations from direct SqlClient use.

Combines raw Roslyn facts (from StaticAnalyzerHost) with a database-scoped SP Catalog
and connection-source resolution. Roslyn only reports what the source contains; all
evidence-rating decisions live here so unresolved names or databases are never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set


class InvocationEvidence(Enum):
    """Confidence level of a detected Database Invocation."""

    PROVEN = "proven"
    LIKELY = "likely"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class InvocationSourceSpan:
    """Identifies the source snapshot region backing one Database Invocation."""

    relative_path: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class WrapperReconciliation:
    """Deterministic classification of one raw wrapper invocation fact."""

    wrapper_kind: str
    status: str
    selection_source: str
    contract: str
    contract_mode: str
    contract_sink: str
    candidate_contracts: tuple[str, ...]
    receiver_type: str
    wrapper_method: str
    source_span: InvocationSourceSpan
    source_available: bool
    scan_root: str = ""
    reason: str = ""
    review_candidate: bool = False
    stored_procedure_mode: bool = False
    mode_reason: str = ""
    implementation_identity: str = ""
    assembly_identity: str = ""
    assembly_revision: str = ""
    method_identity: str = ""
    method_arity: Optional[int] = None
    parameter_types: tuple[str, ...] = ()
    method_semantics: str = ""
    overload_candidates: tuple[str, ...] = ()
    overload_candidate_facts: tuple[Mapping[str, Any], ...] = ()
    receiver_construction_facts: tuple[str, ...] = ()
    receiver_assignment_facts: tuple[str, ...] = ()

    @property
    def active_contract(self) -> bool:
        """Whether this observation has approved contract semantics to use."""
        return bool(self.contract and not self.review_candidate)

    def to_dict(self) -> Dict[str, Any]:
        """Return the machine-readable boundary shape used by audit consumers."""
        return {
            "wrapper_kind": self.wrapper_kind,
            "status": self.status,
            "selection_source": self.selection_source,
            "contract": self.contract,
            "contract_mode": self.contract_mode,
            "contract_sink": self.contract_sink,
            "candidate_contracts": list(self.candidate_contracts),
            "receiver_type": self.receiver_type,
            "wrapper_method": self.wrapper_method,
            "observed_method": self.wrapper_method,
            "source_available": self.source_available,
            "scan_root": self.scan_root,
            "source_span": {
                "relative_path": self.source_span.relative_path,
                "start_offset": self.source_span.start_offset,
                "end_offset": self.source_span.end_offset,
            },
            "reason": self.reason,
            "unresolved_reason": self.reason,
            "review_candidate": self.review_candidate,
            "active_contract": self.active_contract,
            "stored_procedure_mode": self.stored_procedure_mode,
            "mode_reason": self.mode_reason,
            "implementation_identity": self.implementation_identity,
            "assembly_identity": self.assembly_identity,
            "assembly_revision": self.assembly_revision,
            "method_identity": self.method_identity,
            "method_arity": self.method_arity,
            "parameter_types": list(self.parameter_types),
            "method_semantics": self.method_semantics,
            "overload_candidates": list(self.overload_candidates),
            "overload_candidate_facts": [dict(item) for item in self.overload_candidate_facts],
            "receiver_construction_facts": list(self.receiver_construction_facts),
            "receiver_assignment_facts": list(self.receiver_assignment_facts),
        }


@dataclass(frozen=True)
class DbInvocation:
    """One evidence-rated Database Invocation produced by the gateway."""

    class_name: str
    method_name: str
    database: Optional[str]
    procedure_name: Optional[str]
    evidence: InvocationEvidence
    source: InvocationSourceSpan
    reason: str = ""
    procedure_schema: Optional[str] = None
    method_chain: tuple[str, ...] = ()
    branch_context: tuple[str, ...] = ()
    source_snapshot_hash: str = ""
    method_class_chain: tuple[str, ...] = ()
    database_candidates: tuple[str, ...] = ()
    raw_command_text: Optional[str] = None
    external_wrapper_method: str = ""
    wrapper_contract: str = ""
    wrapper_contract_source: str = ""
    wrapper_receiver_type: str = ""
    wrapper_contract_candidates: tuple[str, ...] = ()
    wrapper_kind: str = ""
    wrapper_status: str = ""
    wrapper_selection_source: str = ""
    wrapper_contract_mode: str = ""
    wrapper_contract_sink: str = ""
    wrapper_scan_root: str = ""
    wrapper_review_candidate: bool = False
    wrapper_unresolved_reason: str = ""
    wrapper_mode_reason: str = ""
    wrapper_method: str = ""
    wrapper_source_available: bool = False
    wrapper_stored_procedure_mode: bool = False
    method_semantics: str = ""
    invocation_mode: str = ""
    command_text_kind: str = ""
    command_type_mode: str = ""
    command_text_argument: str = ""
    command_text_literal: Optional[str] = None
    literal_value: Optional[str] = None
    terminal_sink: str = ""
    receiver_type: str = ""
    receiver_name: str = ""
    connection_expression: str = ""
    connection_expression_candidates: tuple[str, ...] = ()
    connection_source: Optional[str] = None
    provenance: str = ""
    implementation_identity: str = ""
    assembly_identity: str = ""
    assembly_revision: str = ""
    method_identity: str = ""
    method_arity: Optional[int] = None
    parameter_types: tuple[str, ...] = ()
    overload_candidates: tuple[str, ...] = ()
    overload_candidate_facts: tuple[Mapping[str, Any], ...] = ()
    receiver_expression: str = ""
    binding_provenance: str = ""
    receiver_construction_facts: tuple[str, ...] = ()
    receiver_assignment_facts: tuple[str, ...] = ()
    wrapper_implementation_identity: str = ""
    wrapper_assembly_identity: str = ""
    wrapper_assembly_revision: str = ""
    wrapper_method_identity: str = ""
    wrapper_method_arity: Optional[int] = None
    wrapper_parameter_types: tuple[str, ...] = ()
    wrapper_method_semantics: str = ""
    wrapper_overload_candidates: tuple[str, ...] = ()
    wrapper_overload_candidate_facts: tuple[Mapping[str, Any], ...] = ()

    @property
    def wrapper_classification_status(self) -> str:
        """Compatibility alias for consumers that use the longer field name."""
        return self.wrapper_status


WRAPPER_EVIDENCE_FIELDS = (
    "wrapper_kind",
    "wrapper_status",
    "wrapper_classification_status",
    "classification_status",
    "status",
    "wrapper_selection_source",
    "selection_source",
    "wrapper_contract",
    "contract",
    "selected_contract",
    "wrapper_contract_source",
    "wrapper_contract_mode",
    "contract_mode",
    "wrapper_contract_sink",
    "contract_sink",
    "wrapper_contract_candidates",
    "candidate_contracts",
    "candidate_contract_names",
    "wrapper_receiver_type",
    "receiver_type",
    "wrapper_scan_root",
    "scan_root",
    "wrapper_source_available",
    "source_available",
    "wrapper_review_candidate",
    "review_candidate",
    "wrapper_unresolved_reason",
    "classification_reason",
    "wrapper_mode_reason",
    "mode_reason",
    "wrapper_method",
    "external_wrapper_method",
    "observed_method",
    "stored_procedure_mode",
    "wrapper_stored_procedure_mode",
    "active_contract",
    "evidence",
    "evidence_status",
    "evidence_reason",
    "source_span",
    "source_snapshot_hash",
    "source_snapshot_identity",
    "source_provenance",
    "method_semantics",
    "invocation_mode",
    "command_text_kind",
    "command_type_mode",
    "command_text_argument",
    "command_text_literal",
    "literal_value",
    "terminal_sink",
    "receiver_name",
    "connection_expression",
    "connection_expression_candidates",
    "connection_source",
    "provenance",
    "implementation_identity",
    "assembly_identity",
    "assembly_revision",
    "method_identity",
    "method_arity",
    "parameter_types",
    "overload_candidates",
    "overload_candidate_facts",
    "receiver_expression",
    "binding_provenance",
    "receiver_construction_facts",
    "receiver_assignment_facts",
    "wrapper_implementation_identity",
    "wrapper_assembly_identity",
    "wrapper_assembly_revision",
    "wrapper_method_identity",
    "wrapper_method_arity",
    "wrapper_parameter_types",
    "wrapper_method_semantics",
    "wrapper_overload_candidates",
    "wrapper_overload_candidate_facts",
)


def wrapper_observation_fields(
    reconciliation: WrapperReconciliation,
    evidence: Optional[DbInvocation] = None,
    *,
    source_snapshot_hash: str = "",
) -> Dict[str, Any]:
    """Project classification and database evidence into one audit shape."""
    classification = reconciliation.to_dict()
    snapshot_hash = str(
        source_snapshot_hash
        or (evidence.source_snapshot_hash if evidence is not None else "")
        or ""
    )
    evidence_status = evidence.evidence.value if evidence is not None else "not_applicable"
    evidence_reason = evidence.reason if evidence is not None else "inline_sql"
    database = evidence.database if evidence is not None else None
    database_candidates = (
        list(evidence.database_candidates) if evidence is not None else []
    )
    procedure_name = evidence.procedure_name if evidence is not None else None
    procedure_schema = evidence.procedure_schema if evidence is not None else None
    source_span = dict(classification["source_span"])
    source_provenance = {
        "selection_source": classification["selection_source"],
        "source_available": classification["source_available"],
        "scan_root": classification["scan_root"],
        "source_span": source_span,
        "source_snapshot_hash": snapshot_hash,
        "source_snapshot_identity": snapshot_hash,
    }
    method_semantics = (
        evidence.method_semantics
        if evidence is not None
        else classification["method_semantics"]
    )
    invocation_mode = (
        evidence.invocation_mode
        if evidence is not None
        else "stored_procedure"
        if classification["stored_procedure_mode"]
        else "inline_sql"
        if classification["mode_reason"] == "inline_sql"
        else "unresolved"
    )
    return {
        "wrapper_kind": classification["wrapper_kind"],
        "wrapper_status": classification["status"],
        "wrapper_classification_status": classification["status"],
        "classification_status": classification["status"],
        "status": classification["status"],
        "wrapper_selection_source": classification["selection_source"],
        "selection_source": classification["selection_source"],
        "wrapper_contract": classification["contract"],
        "contract": classification["contract"],
        "selected_contract": classification["contract"],
        "wrapper_contract_source": (
            "" if classification["source_available"] else classification["selection_source"]
        ),
        "wrapper_contract_mode": classification["contract_mode"],
        "contract_mode": classification["contract_mode"],
        "wrapper_contract_sink": classification["contract_sink"],
        "contract_sink": classification["contract_sink"],
        "wrapper_contract_candidates": list(classification["candidate_contracts"]),
        "candidate_contracts": list(classification["candidate_contracts"]),
        "candidate_contract_names": list(classification["candidate_contracts"]),
        "wrapper_receiver_type": classification["receiver_type"],
        "receiver_type": classification["receiver_type"],
        "wrapper_scan_root": classification["scan_root"],
        "scan_root": classification["scan_root"],
        "wrapper_source_available": classification["source_available"],
        "source_available": classification["source_available"],
        "wrapper_review_candidate": classification["review_candidate"],
        "review_candidate": classification["review_candidate"],
        "wrapper_unresolved_reason": classification["reason"],
        "classification_reason": classification["reason"],
        "wrapper_mode_reason": classification["mode_reason"],
        "mode_reason": classification["mode_reason"],
        "wrapper_method": classification["wrapper_method"],
        "external_wrapper_method": (
            evidence.external_wrapper_method
            if evidence is not None
            else classification["wrapper_method"]
            if classification["wrapper_kind"] == "external_wrapper"
            else ""
        ),
        "observed_method": classification["wrapper_method"],
        "stored_procedure_mode": classification["stored_procedure_mode"],
        "wrapper_stored_procedure_mode": classification["stored_procedure_mode"],
        "active_contract": classification["active_contract"],
        "evidence": evidence_status,
        "evidence_status": evidence_status,
        "evidence_reason": evidence_reason,
        "procedure_name": procedure_name or "",
        "procedure_schema": procedure_schema or "",
        "database": database,
        "database_candidates": database_candidates,
        "database_attribution": (
            "resolved"
            if database
            else "candidate"
            if database_candidates
            else "unresolved"
        ),
        "source_span": source_span,
        "source_snapshot_hash": snapshot_hash,
        "source_snapshot_identity": snapshot_hash,
        "source_provenance": source_provenance,
        "implementation_identity": classification["implementation_identity"],
        "assembly_identity": classification["assembly_identity"],
        "assembly_revision": classification["assembly_revision"],
        "method_identity": classification["method_identity"],
        "method_arity": classification["method_arity"],
        "parameter_types": list(classification["parameter_types"]),
        "overload_candidates": list(classification["overload_candidates"]),
        "overload_candidate_facts": [
            dict(item) for item in classification["overload_candidate_facts"]
        ],
        "receiver_expression": (
            evidence.receiver_expression if evidence is not None else ""
        ),
        "binding_provenance": (
            evidence.binding_provenance if evidence is not None else ""
        ),
        "receiver_construction_facts": (
            list(evidence.receiver_construction_facts)
            if evidence is not None
            else list(classification["receiver_construction_facts"])
        ),
        "receiver_assignment_facts": (
            list(evidence.receiver_assignment_facts)
            if evidence is not None
            else list(classification["receiver_assignment_facts"])
        ),
        "method_semantics": method_semantics,
        "invocation_mode": invocation_mode,
        "command_text_kind": evidence.command_text_kind if evidence is not None else "",
        "command_type_mode": evidence.command_type_mode if evidence is not None else "",
        "command_text_argument": (
            evidence.command_text_argument if evidence is not None else ""
        ),
        "command_text_literal": (
            evidence.command_text_literal if evidence is not None else None
        ),
        "literal_value": evidence.literal_value if evidence is not None else None,
        "raw_command_text": evidence.raw_command_text if evidence is not None else None,
        "terminal_sink": evidence.terminal_sink if evidence is not None else "",
        "receiver_name": evidence.receiver_name if evidence is not None else "",
        "connection_expression": (
            evidence.connection_expression if evidence is not None else ""
        ),
        "connection_expression_candidates": (
            list(evidence.connection_expression_candidates)
            if evidence is not None
            else []
        ),
        "connection_source": (
            evidence.connection_source if evidence is not None else database
        ),
        "branch_context": (
            list(evidence.branch_context) if evidence is not None else []
        ),
        "provenance": evidence.provenance if evidence is not None else "",
    }


def invocation_wrapper_evidence_fields(invocation: DbInvocation) -> Dict[str, Any]:
    """Project one rated invocation using the same shape as wrapper audits."""
    reconciliation = WrapperReconciliation(
        wrapper_kind=invocation.wrapper_kind,
        status=invocation.wrapper_status,
        selection_source=invocation.wrapper_selection_source,
        contract=invocation.wrapper_contract,
        contract_mode=invocation.wrapper_contract_mode,
        contract_sink=invocation.wrapper_contract_sink,
        candidate_contracts=invocation.wrapper_contract_candidates,
        receiver_type=invocation.wrapper_receiver_type,
        wrapper_method=invocation.wrapper_method,
        source_span=invocation.source,
        source_available=invocation.wrapper_source_available,
        scan_root=invocation.wrapper_scan_root,
        reason=invocation.wrapper_unresolved_reason,
        review_candidate=invocation.wrapper_review_candidate,
        stored_procedure_mode=invocation.wrapper_stored_procedure_mode,
        mode_reason=invocation.wrapper_mode_reason,
    )
    fields = wrapper_observation_fields(
        reconciliation,
        invocation,
        source_snapshot_hash=invocation.source_snapshot_hash,
    )
    fields["source_span"] = {
        "relative_path": invocation.source.relative_path,
        "start_offset": invocation.source.start_offset,
        "end_offset": invocation.source.end_offset,
        "content_hash": invocation.source_snapshot_hash,
    }
    fields["external_wrapper_method"] = invocation.external_wrapper_method
    fields.update(
        {
            "method_semantics": invocation.method_semantics,
            "invocation_mode": invocation.invocation_mode,
            "command_text_kind": invocation.command_text_kind,
            "command_type_mode": invocation.command_type_mode,
            "command_text_argument": invocation.command_text_argument,
            "command_text_literal": invocation.command_text_literal,
            "literal_value": invocation.literal_value,
            "terminal_sink": invocation.terminal_sink,
            "receiver_type": (
                invocation.receiver_type
                or fields.get("receiver_type", "")
            ),
            "receiver_name": invocation.receiver_name,
            "connection_expression": invocation.connection_expression,
            "connection_expression_candidates": list(
                invocation.connection_expression_candidates
            ),
            "connection_source": invocation.connection_source or invocation.database,
            "provenance": invocation.provenance,
            "implementation_identity": invocation.implementation_identity,
            "assembly_identity": invocation.assembly_identity,
            "assembly_revision": invocation.assembly_revision,
            "method_identity": invocation.method_identity,
            "method_arity": invocation.method_arity,
            "parameter_types": list(invocation.parameter_types),
            "overload_candidates": list(invocation.overload_candidates),
            "overload_candidate_facts": [
                dict(item) for item in invocation.overload_candidate_facts
            ],
            "receiver_expression": invocation.receiver_expression,
            "binding_provenance": invocation.binding_provenance,
            "receiver_construction_facts": list(invocation.receiver_construction_facts),
            "receiver_assignment_facts": list(invocation.receiver_assignment_facts),
            "wrapper_implementation_identity": invocation.wrapper_implementation_identity,
            "wrapper_assembly_identity": invocation.wrapper_assembly_identity,
            "wrapper_assembly_revision": invocation.wrapper_assembly_revision,
            "wrapper_method_identity": invocation.wrapper_method_identity,
            "wrapper_method_arity": invocation.wrapper_method_arity,
            "wrapper_parameter_types": list(invocation.wrapper_parameter_types),
            "wrapper_method_semantics": invocation.wrapper_method_semantics,
            "wrapper_overload_candidates": list(invocation.wrapper_overload_candidates),
            "wrapper_overload_candidate_facts": [
                dict(item) for item in invocation.wrapper_overload_candidate_facts
            ],
        }
    )
    return fields


def _load_external_wrapper_contracts() -> Dict[str, Dict[str, Any]]:
    """Load the repository-level external wrapper contract registry."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "external_wrapper_contracts.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return _normalize_external_wrapper_contract_registry(payload)


def _normalize_external_wrapper_contract_registry(
    registry: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    contracts = registry.get("contracts", registry)
    if not isinstance(contracts, dict):
        return {}
    loaded_contracts: Dict[str, Dict[str, Any]] = {}
    for name, contract in contracts.items():
        if not isinstance(contract, dict):
            continue
        loaded = dict(contract)
        loaded["name"] = str(name)
        loaded_contracts[str(name)] = loaded
    return loaded_contracts


def load_external_wrapper_contract(contract_name: str) -> Optional[Dict[str, Any]]:
    """Load one named external wrapper contract from repository configuration."""
    normalized_name = str(contract_name or "").strip().casefold()
    if not normalized_name:
        return None
    return next(
        (
            contract
            for name, contract in _load_external_wrapper_contracts().items()
            if name.casefold() == normalized_name
        ),
        None,
    )


def _normalize_type_identity(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("global::"):
        normalized = normalized[len("global::") :]
    return normalized.casefold()


def _receiver_type_matches_contract(
    receiver_type: str,
    receiver_types: object,
) -> bool:
    if not receiver_type or not isinstance(receiver_types, (list, tuple, set)):
        return False
    normalized_receiver = _normalize_type_identity(receiver_type)
    return bool(normalized_receiver) and any(
        normalized_receiver == _normalize_type_identity(candidate)
        for candidate in receiver_types
        if _normalize_type_identity(candidate)
    )


def external_wrapper_contract_candidates(
    receiver_type: str,
) -> List[Dict[str, Any]]:
    """Return auto-selectable contracts matching one receiver type."""
    if not _normalize_type_identity(receiver_type):
        return []

    candidates = []
    for contract in _load_external_wrapper_contracts().values():
        if contract.get("auto_select") is not True:
            continue
        receiver_types = contract.get("receiver_types", [])
        if _receiver_type_matches_contract(receiver_type, receiver_types):
            candidates.append(contract)
    return candidates


def load_external_wrapper_contract_for_receiver(
    receiver_type: str,
) -> Optional[Dict[str, Any]]:
    """Auto-select one contract when a receiver type identifies it uniquely.

    Automatic selection is intentionally conservative: contracts must opt in with
    ``auto_select`` and exactly one contract may match the receiver type.
    """
    candidates = external_wrapper_contract_candidates(receiver_type)
    return candidates[0] if len(candidates) == 1 else None


def _wrapper_contract_method(
    contract: Optional[Mapping[str, Any]],
    method_name: str,
    *,
    method_identity: str = "",
    method_arity: Optional[int] = None,
    parameter_types: Iterable[str] = (),
) -> tuple[Optional[Mapping[str, Any]], str, tuple[Mapping[str, Any], ...]]:
    if contract is None:
        return None, "method_not_in_contract", ()
    methods = contract.get("methods", {})
    folded_name = str(method_name or "").casefold()
    if not folded_name or not isinstance(methods, Mapping):
        return None, "method_not_in_contract", ()

    named_methods: List[Mapping[str, Any]] = []
    for name, value in methods.items():
        if str(name).casefold() != folded_name:
            continue
        values = value if isinstance(value, (list, tuple)) else (value,)
        named_methods.extend(
            dict(candidate)
            for candidate in values
            if isinstance(candidate, Mapping)
        )

    if not named_methods:
        return None, "method_not_in_contract", ()

    observed_identity = _normalize_type_identity(method_identity)
    observed_parameters = tuple(
        _normalize_type_identity(item) for item in parameter_types if str(item).strip()
    )

    def candidate_matches(candidate: Mapping[str, Any]) -> bool:
        candidate_identity = _normalize_type_identity(
            _first_fact(candidate, "method_identity", "identity")
        )
        if observed_identity and candidate_identity:
            if observed_identity == candidate_identity:
                return True
            return False
        if observed_identity and not candidate_identity:
            candidate_parameters = tuple(
                _normalize_type_identity(item)
                for item in _text_facts(
                    _first_fact(candidate, "parameter_types", "parameters")
                )
            )
            candidate_arity = _optional_int_fact(
                _first_fact(candidate, "method_arity", "arity")
            )
            if candidate_arity is None and candidate_parameters:
                candidate_arity = len(candidate_parameters)
            if method_arity is not None and candidate_arity != method_arity:
                return False
            if observed_parameters and candidate_parameters != observed_parameters:
                return False
            return bool(method_arity is not None or observed_parameters)

        candidate_arity = _optional_int_fact(
            _first_fact(candidate, "method_arity", "arity")
        )
        candidate_parameters = tuple(
            _normalize_type_identity(item)
            for item in _text_facts(
                _first_fact(candidate, "parameter_types", "parameters")
            )
        )
        if candidate_arity is None and candidate_parameters:
            candidate_arity = len(candidate_parameters)
        if method_arity is not None:
            if candidate_arity is None or candidate_arity != method_arity:
                return False
        if observed_parameters:
            if not candidate_parameters or candidate_parameters != observed_parameters:
                return False
        return method_arity is not None or bool(observed_parameters)

    if len(named_methods) == 1:
        candidate = named_methods[0]
        has_signature = bool(
            _text_fact(_first_fact(candidate, "method_identity", "identity"))
            or _optional_int_fact(_first_fact(candidate, "method_arity", "arity"))
            is not None
            or _text_facts(_first_fact(candidate, "parameter_types", "parameters"))
        )
        observed_signature = bool(
            observed_identity or method_arity is not None or observed_parameters
        )
        if not has_signature:
            # A signature-less contract entry can't confirm it is the observed overload.
            if observed_signature:
                return None, "ambiguous_overload", tuple(named_methods)
            return candidate, "", tuple(named_methods)
        if candidate_matches(candidate):
            return candidate, "", tuple(named_methods)
        return None, "overload_not_found", tuple(named_methods)

    if not observed_identity and method_arity is None and not observed_parameters:
        return None, "ambiguous_overload", tuple(named_methods)

    matching = tuple(candidate for candidate in named_methods if candidate_matches(candidate))
    if len(matching) == 1:
        return matching[0], "", tuple(named_methods)
    if len(matching) > 1:
        return None, "ambiguous_overload", tuple(named_methods)
    return None, "overload_not_found", tuple(named_methods)


def _wrapper_contract_method_identity(
    candidate: Mapping[str, Any],
    method_name: str,
) -> str:
    explicit_identity = _text_fact(
        _first_fact(candidate, "method_identity", "wrapper_method_identity", "identity")
    )
    if explicit_identity:
        return explicit_identity
    parameter_types = _text_facts(
        _first_fact(candidate, "parameter_types", "parameters")
    )
    if parameter_types:
        return f"{method_name}({', '.join(parameter_types)})"
    method_arity = _optional_int_fact(
        _first_fact(candidate, "method_arity", "arity")
    )
    if method_arity is not None:
        return f"{method_name}/{method_arity}"
    return method_name


def _wrapper_contract_receiver_matches(
    contract: Mapping[str, Any],
    receiver_type: str,
) -> bool:
    receiver_types = contract.get("receiver_types", [])
    return _receiver_type_matches_contract(receiver_type, receiver_types)


def _text_fact(value: object) -> str:
    return str(value or "").strip()


def _text_facts(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


_KNOWN_TERMINAL_SINKS = {
    "executenonquery": "ExecuteNonQuery",
    "executenonqueryasync": "ExecuteNonQueryAsync",
    "executereader": "ExecuteReader",
    "executereaderasync": "ExecuteReaderAsync",
    "executescalar": "ExecuteScalar",
    "executescalarasync": "ExecuteScalarAsync",
    "fill": "Fill",
    "fillasync": "FillAsync",
}


def _known_terminal_sink(value: object) -> str:
    sink = _text_fact(value)
    return _KNOWN_TERMINAL_SINKS.get(sink.casefold(), "")


def _optional_int_fact(value: object) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def wrapper_observation_identity(observation: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the source/method identity that must remain distinct in reports."""
    return (
        _text_fact(
            observation.get("implementation_identity")
            or observation.get("wrapper_implementation_identity")
        ),
        _text_fact(observation.get("assembly_identity") or observation.get("wrapper_assembly_identity")),
        _text_fact(observation.get("assembly_revision") or observation.get("wrapper_assembly_revision")),
        _text_fact(observation.get("receiver_type") or observation.get("wrapper_receiver_type")),
        _text_fact(observation.get("receiver_expression")),
        _text_fact(observation.get("binding_provenance")),
        _text_fact(observation.get("method_identity") or observation.get("wrapper_method_identity")),
        _optional_int_fact(
            observation.get("method_arity")
            if observation.get("method_arity") is not None
            else observation.get("wrapper_method_arity")
        ),
        _text_facts(
            observation.get("parameter_types")
            or observation.get("wrapper_parameter_types")
        ),
        _text_fact(
            observation.get("method_semantics")
            or observation.get("wrapper_method_semantics")
        ),
        _text_fact(observation.get("connection_expression")),
        _text_fact(
            observation.get("connection_source")
            or observation.get("database")
        ),
        _text_facts(observation.get("connection_expression_candidates")),
        _text_facts(observation.get("database_candidates")),
        _text_facts(
            observation.get("overload_candidates")
            or observation.get("wrapper_overload_candidates")
        ),
        _text_fact(observation.get("invocation_mode")),
        _text_fact(observation.get("terminal_sink")),
        _text_facts(observation.get("receiver_construction_facts")),
        _text_facts(observation.get("receiver_assignment_facts")),
    )


def _first_fact(source: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value
    return None


def _receiver_binding_facts(raw: Mapping[str, Any]) -> Dict[str, Any]:
    binding_value = _first_fact(
        raw,
        "receiver_binding",
        "implementation_binding",
        "bound_implementation",
    )
    if isinstance(binding_value, Mapping):
        binding = binding_value
    elif binding_value is not None:
        binding = {"implementation_identity": binding_value}
    else:
        binding = {}

    return {
        "expression": _text_fact(
            _first_fact(binding, "expression", "receiver_expression")
            or _first_fact(raw, "receiver_expression", "receiver_name", "receiver")
        ),
        "implementation_identity": _text_fact(
            _first_fact(
                binding,
                "implementation_identity",
                "concrete_implementation",
                "type_identity",
                "concrete_type",
                "type",
            )
            or _first_fact(
                raw,
                "receiver_implementation_identity",
                "wrapper_implementation_identity",
                "implementation_identity",
                "concrete_implementation",
                "wrapper_class_identity",
            )
        ),
        "assembly_identity": _text_fact(
            _first_fact(binding, "assembly_identity", "assembly")
            or _first_fact(raw, "wrapper_assembly_identity", "assembly_identity")
        ),
        "assembly_revision": _text_fact(
            _first_fact(binding, "assembly_revision", "revision", "version")
            or _first_fact(raw, "wrapper_assembly_revision", "assembly_revision")
        ),
        "provenance": _text_fact(
            _first_fact(binding, "provenance", "source_provenance")
            or _first_fact(raw, "binding_provenance", "receiver_binding_provenance")
        ),
        "construction_facts": _text_facts(
            _first_fact(
                binding,
                "construction_facts",
                "receiver_construction_facts",
            )
            or _first_fact(raw, "receiver_construction_facts")
        ),
        "assignment_facts": _text_facts(
            _first_fact(
                binding,
                "assignment_facts",
                "receiver_assignment_facts",
            )
            or _first_fact(raw, "receiver_assignment_facts")
        ),
    }


def _normalize_wrapper_method_semantics(value: object) -> str:
    normalized = _text_fact(value).casefold().replace("-", "_").replace(" ", "_")
    if normalized in {
        "fixed_text",
        "text",
        "inline_sql",
        "fixed_inline_sql",
        "commandtype_text",
        "fixed_commandtype_text",
    }:
        return "fixed_inline_sql"
    if normalized in {
        "fixed_stored_procedure",
        "stored_procedure",
        "storedprocedure",
        "commandtype_stored_procedure",
        "fixed_commandtype_stored_procedure",
    }:
        return "fixed_stored_procedure"
    if normalized in {"call_site", "callsite", "call_site_selected"}:
        return "call_site"
    if normalized in {"", "unknown", "unresolved", "wrapper_mode_unresolved"}:
        return "unresolved"
    return normalized


def _wrapper_method_identity(candidate: Mapping[str, Any]) -> str:
    explicit = _text_fact(
        _first_fact(candidate, "method_identity", "wrapper_method_identity", "identity")
    )
    if explicit:
        return explicit
    method_name = _text_fact(_first_fact(candidate, "method_name", "wrapper_method_name"))
    implementation = _text_fact(
        _first_fact(
            candidate,
            "implementation_identity",
            "wrapper_implementation_identity",
            "type_identity",
        )
    )
    parameter_types = _text_facts(
        _first_fact(candidate, "parameter_types", "wrapper_parameter_types", "parameters")
    )
    if method_name and implementation:
        return f"{implementation}.{method_name}({', '.join(parameter_types)})"
    if method_name:
        return f"{method_name}({', '.join(parameter_types)})"
    return ""


def _wrapper_candidate_fact(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize one overload candidate's bound-implementation/signature facts.

    Kept structured (not collapsed into an identity string) so an ambiguous
    overload still exposes each candidate's arity and parameter types.
    """
    parameter_types = _text_facts(
        _first_fact(candidate, "parameter_types", "wrapper_parameter_types", "parameters")
    )
    method_arity = _optional_int_fact(_first_fact(candidate, "method_arity", "arity"))
    if method_arity is None and parameter_types:
        method_arity = len(parameter_types)
    return {
        "method_identity": _wrapper_method_identity(candidate),
        "implementation_identity": _text_fact(
            _first_fact(
                candidate,
                "implementation_identity",
                "wrapper_implementation_identity",
                "type_identity",
            )
        ),
        "receiver_type": _text_fact(
            _first_fact(candidate, "receiver_type", "wrapper_receiver_type")
        ),
        "method_name": _text_fact(_first_fact(candidate, "method_name", "wrapper_method_name")),
        "method_arity": method_arity,
        "parameter_types": parameter_types,
    }


def _wrapper_method_facts(raw: Mapping[str, Any]) -> Dict[str, Any]:
    raw_candidates = _first_fact(
        raw,
        "wrapper_method_candidates",
        "wrapper_overload_candidates",
        "method_candidates",
        "overload_candidates",
    )
    candidates = []
    if isinstance(raw_candidates, (list, tuple)):
        for candidate in raw_candidates:
            if isinstance(candidate, Mapping):
                candidates.append(dict(candidate))
            elif isinstance(candidate, str) and candidate.strip():
                candidates.append({"method_identity": candidate.strip()})
    candidate_names = tuple(
        identity
        for identity in (_wrapper_method_identity(candidate) for candidate in candidates)
        if identity
    )
    candidate_facts = tuple(_wrapper_candidate_fact(candidate) for candidate in candidates)

    method_name = _text_fact(_first_fact(raw, "wrapper_method_name", "method_name"))
    method_arity = _optional_int_fact(
        _first_fact(raw, "wrapper_method_arity", "method_arity", "arity")
    )
    parameter_types = _text_facts(
        _first_fact(raw, "wrapper_parameter_types", "parameter_types", "parameter_type_names")
    )
    matching = [
        candidate
        for candidate in candidates
        if not _text_fact(_first_fact(candidate, "method_name", "wrapper_method_name"))
        or _text_fact(_first_fact(candidate, "method_name", "wrapper_method_name")).casefold()
        == method_name.casefold()
    ]
    if method_arity is not None and matching:
        exact_arity = [
            candidate
            for candidate in matching
            if (
                _optional_int_fact(_first_fact(candidate, "method_arity", "arity"))
                == method_arity
                or (
                    _optional_int_fact(_first_fact(candidate, "method_arity", "arity")) is None
                    and len(_text_facts(_first_fact(candidate, "parameter_types", "parameters")))
                    == method_arity
                )
            )
        ]
        if exact_arity:
            matching = exact_arity
    if parameter_types and matching:
        normalized_parameters = tuple(item.casefold() for item in parameter_types)
        exact_parameters = [
            candidate
            for candidate in matching
            if tuple(
                item.casefold()
                for item in _text_facts(
                    _first_fact(candidate, "parameter_types", "wrapper_parameter_types", "parameters")
                )
            )
            == normalized_parameters
        ]
        if exact_parameters:
            matching = exact_parameters

    selected = matching[0] if len(matching) == 1 else None
    reason = ""
    if raw.get("wrapper_overload_ambiguous") is True:
        reason = "ambiguous_overload"
    elif candidates and len(matching) > 1:
        reason = "ambiguous_overload"
    elif candidates and not matching:
        reason = "overload_not_found"

    selected_or_raw: Mapping[str, Any] = selected or raw
    selected_arity = _optional_int_fact(
        _first_fact(selected_or_raw, "wrapper_method_arity", "method_arity", "arity")
    )
    selected_parameters = _text_facts(
        _first_fact(
            selected_or_raw,
            "wrapper_parameter_types",
            "parameter_types",
            "parameter_type_names",
            "parameters",
        )
    )
    if selected_arity is None and selected_parameters:
        selected_arity = len(selected_parameters)
    selected_identity = _wrapper_method_identity(selected_or_raw)
    selected_semantics = _normalize_wrapper_method_semantics(
        _first_fact(selected_or_raw, "wrapper_method_semantics", "method_semantics", "semantics")
    )
    selected_sink = _text_fact(
        _first_fact(selected_or_raw, "wrapper_terminal_sink", "terminal_sink", "sink")
    )
    explicit_reason = _text_fact(raw.get("wrapper_unresolved_reason"))
    if explicit_reason:
        reason = explicit_reason
    return {
        "method_identity": selected_identity,
        "method_arity": selected_arity,
        "parameter_types": selected_parameters,
        "method_semantics": selected_semantics,
        "terminal_sink": selected_sink,
        "candidate_names": candidate_names,
        "candidate_facts": candidate_facts,
        "reason": reason,
        "selected": selected,
    }


def normalize_procedure_name(raw_name: str) -> str:
    """Normalize a candidate SP name to its bare, case-insensitive identity."""
    cleaned = raw_name.strip().replace("[", "").replace("]", "")
    bare = cleaned.split(".")[-1]
    return bare.strip().lower()


@dataclass(frozen=True)
class SpCatalog:
    """Database-scoped set of normalized stored procedure identities."""

    procedures_by_database: Dict[str, Set[str]]
    qualified_procedures_by_database: Dict[str, Set[str]] = field(default_factory=dict)

    @classmethod
    def from_databases(
        cls,
        procedures_by_database: Dict[str, Iterable[str]],
        default_schema: Optional[str] = "dbo",
    ) -> "SpCatalog":
        bare_names: Dict[str, Set[str]] = {}
        qualified_names: Dict[str, Set[str]] = {}
        canonical_databases: Dict[str, str] = {}
        normalized_default_schema = normalize_schema_name(default_schema or "")
        for database, names in procedures_by_database.items():
            database_name = str(database).strip()
            database_key = database_name.casefold()
            canonical_database = canonical_databases.setdefault(database_key, database_name)
            bare_names.setdefault(canonical_database, set())
            qualified_names.setdefault(canonical_database, set())
            for name in names:
                normalized_name = normalize_procedure_name(name)
                bare_names[canonical_database].add(normalized_name)
                schema = normalize_procedure_schema(name)
                schema = schema or normalized_default_schema
                if schema:
                    qualified_names[canonical_database].add(f"{schema}.{normalized_name}")
        return cls(bare_names, qualified_names)

    def contains(
        self,
        database: str,
        normalized_name: str,
        schema: Optional[str] = None,
    ) -> bool:
        database_key = self._database_key(database)
        bare_names = self.procedures_by_database.get(database_key, set())
        if not schema:
            return normalized_name in bare_names
        qualified_names = self.qualified_procedures_by_database.get(database_key, set())
        qualified_identity = f"{schema}.{normalized_name}"
        return qualified_identity in qualified_names

    def databases_containing(
        self,
        normalized_name: str,
        schema: Optional[str] = None,
    ) -> List[str]:
        return sorted(
            database
            for database, names in self.procedures_by_database.items()
            if self.contains(database, normalized_name, schema)
        )

    def _database_key(self, database: str) -> str:
        if database in self.procedures_by_database:
            return database
        folded = database.casefold()
        return next(
            (candidate for candidate in self.procedures_by_database if candidate.casefold() == folded),
            database,
        )


class CSharpAnalysisGateway:
    """Validates direct SqlClient invocations against a database-scoped SP Catalog."""

    def __init__(
        self,
        catalog: SpCatalog,
        connection_sources: Optional[Dict[str, str]] = None,
        external_wrapper_contract: Optional[Mapping[str, Any]] = None,
        external_wrapper_contracts: Optional[Mapping[str, Any]] = None,
    ):
        self._catalog = catalog
        self._connection_sources = connection_sources or {}
        self._external_wrapper_contract = dict(external_wrapper_contract or {})
        self._wrapper_contract_name = str(self._external_wrapper_contract.get("name") or "")
        self._external_wrapper_contracts = (
            None
            if external_wrapper_contracts is None
            else _normalize_external_wrapper_contract_registry(external_wrapper_contracts)
        )

    def _load_contract(self, contract_name: str) -> Optional[Dict[str, Any]]:
        if self._external_wrapper_contracts is None:
            return load_external_wrapper_contract(contract_name)
        normalized_name = str(contract_name or "").strip().casefold()
        if not normalized_name:
            return None
        return next(
            (
                contract
                for name, contract in self._external_wrapper_contracts.items()
                if name.casefold() == normalized_name
            ),
            None,
        )

    def _contract_candidates(self, receiver_type: str) -> List[Dict[str, Any]]:
        if self._external_wrapper_contracts is None:
            return external_wrapper_contract_candidates(receiver_type)
        if not _normalize_type_identity(receiver_type):
            return []
        return [
            contract
            for contract in self._external_wrapper_contracts.values()
            if contract.get("auto_select") is True
            and _receiver_type_matches_contract(
                receiver_type,
                contract.get("receiver_types", []),
            )
        ]

    def reconcile_wrapper(
        self,
        relative_path: str,
        raw: Mapping[str, Any],
        *,
        scan_root: str = "",
        source_wrapper_available: Optional[bool] = None,
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
        receiver_type_contract_candidates: Optional[Iterable[Mapping[str, Any]]] = None,
    ) -> WrapperReconciliation:
        """Classify one raw wrapper fact before rating its database evidence.

        This is the single contract/source boundary shared by Gateway consumers.
        Contract selection is deliberately separate from the later SP Catalog
        check: a selected contract does not by itself prove a procedure exists.
        """
        receiver_type = str(raw.get("wrapper_receiver_type") or "").strip()
        wrapper_method = str(raw.get("wrapper_method_name") or "").strip()
        binding = _receiver_binding_facts(raw)
        method_facts = _wrapper_method_facts(raw)
        method_semantics = method_facts["method_semantics"]
        source_available = (
            raw.get("wrapper_source_available") is True
            if source_wrapper_available is None
            else bool(source_wrapper_available)
        )
        source = InvocationSourceSpan(
            str(relative_path or raw.get("relative_path") or raw.get("source_file") or ""),
            int(raw.get("start_offset") or 0),
            int(raw.get("end_offset") or 0),
        )
        raw_mode = str(raw.get("wrapper_mode") or "").strip().casefold()
        root = str(scan_root or "")
        source_sink = method_facts["terminal_sink"] or _text_fact(
            _first_fact(raw, "wrapper_terminal_sink", "terminal_sink", "sink")
        )

        def result(
            *,
            wrapper_kind: str,
            status: str,
            selection_source: str,
            contract: str = "",
            contract_mode: str = "",
            contract_sink: str = "",
            candidate_contracts: Iterable[str] = (),
            overload_candidates: Optional[Iterable[str]] = None,
            overload_candidate_facts: Optional[Iterable[Mapping[str, Any]]] = None,
            reason: str = "",
            review_candidate: bool = False,
            stored_procedure_mode: bool = False,
            mode_reason: str = "",
        ) -> WrapperReconciliation:
            return WrapperReconciliation(
                wrapper_kind=wrapper_kind,
                status=status,
                selection_source=selection_source,
                contract=contract,
                contract_mode=contract_mode,
                contract_sink=contract_sink,
                candidate_contracts=tuple(
                    name for name in (str(item).strip() for item in candidate_contracts) if name
                ),
                receiver_type=receiver_type,
                wrapper_method=wrapper_method,
                source_span=source,
                source_available=source_available,
                scan_root=root,
                reason=reason,
                review_candidate=review_candidate,
                stored_procedure_mode=stored_procedure_mode,
                mode_reason=mode_reason,
                implementation_identity=binding["implementation_identity"],
                assembly_identity=binding["assembly_identity"],
                assembly_revision=binding["assembly_revision"],
                method_identity=method_facts["method_identity"],
                method_arity=method_facts["method_arity"],
                parameter_types=method_facts["parameter_types"],
                method_semantics=method_semantics,
                overload_candidates=tuple(
                    method_facts["candidate_names"]
                    if overload_candidates is None
                    else (
                        str(item).strip()
                        for item in overload_candidates
                        if str(item).strip()
                    )
                ),
                overload_candidate_facts=tuple(
                    method_facts["candidate_facts"]
                    if overload_candidate_facts is None
                    else (
                        dict(item)
                        for item in overload_candidate_facts
                        if isinstance(item, Mapping)
                    )
                ),
                receiver_construction_facts=binding["construction_facts"],
                receiver_assignment_facts=binding["assignment_facts"],
            )

        def source_mode() -> tuple[bool, str]:
            if method_semantics == "fixed_inline_sql":
                return False, "inline_sql"
            if method_semantics == "fixed_stored_procedure":
                return True, ""
            if method_semantics == "call_site" and raw_mode == "inline_sql":
                return False, "inline_sql"
            if method_semantics == "call_site" and raw_mode == "stored_procedure":
                return True, ""
            return False, "wrapper_mode_unresolved"

        if source_available:
            if method_facts["reason"]:
                return result(
                    wrapper_kind="source_wrapper",
                    status=(
                        "ambiguous_overload"
                        if method_facts["reason"] == "ambiguous_overload"
                        else "unresolved_method"
                    ),
                    selection_source="source_code",
                    contract_mode=str(raw.get("wrapper_mode") or ""),
                    contract_sink=source_sink,
                    candidate_contracts=(),
                    reason=method_facts["reason"],
                    review_candidate=True,
                    mode_reason="wrapper_mode_unresolved",
                )
            if not binding["implementation_identity"]:
                return result(
                    wrapper_kind="source_wrapper",
                    status="unresolved_method",
                    selection_source="source_code",
                    contract_mode=str(raw.get("wrapper_mode") or ""),
                    contract_sink=source_sink,
                    candidate_contracts=(),
                    reason="receiver_binding_unresolved",
                    review_candidate=True,
                    mode_reason="wrapper_mode_unresolved",
                )
            stored_procedure_mode, mode_reason = source_mode()
            return result(
                wrapper_kind="source_wrapper",
                status="source_wrapper",
                selection_source="source_code",
                contract_mode=str(raw.get("wrapper_mode") or ""),
                contract_sink=source_sink,
                stored_procedure_mode=stored_procedure_mode,
                mode_reason=mode_reason,
            )

        explicit_name = ""
        explicit_selected = False
        selected_contract: Optional[Mapping[str, Any]] = None
        if explicit_contract is None:
            selected_contract = self._external_wrapper_contract or None
            explicit_name = self._wrapper_contract_name
            explicit_selected = selected_contract is not None
        elif isinstance(explicit_contract, str):
            explicit_name = explicit_contract.strip()
            explicit_selected = bool(explicit_name)
            selected_contract = self._load_contract(explicit_name)
        elif isinstance(explicit_contract, Mapping):
            selected_contract = explicit_contract
            explicit_name = str(explicit_contract.get("name") or "").strip()
            explicit_selected = True

        attempted_sp_mode = raw_mode == "stored_procedure"
        if explicit_selected and selected_contract is None:
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_contract",
                selection_source="explicit",
                candidate_contracts=(explicit_name,),
                reason="configured_contract_not_found",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        if explicit_selected:
            candidates = [
                candidate
                for candidate in (selected_contract,)
                if candidate is not None
            ]
            selection_source = "explicit"
        elif receiver_type_contract_candidates is None:
            candidates = list(self._contract_candidates(receiver_type))
            selection_source = "auto_receiver_type"
        else:
            candidates = [
                candidate
                for candidate in receiver_type_contract_candidates
                if isinstance(candidate, Mapping)
            ]
            selection_source = "auto_receiver_type"

        candidate_names = tuple(
            str(candidate.get("name") or "").strip()
            for candidate in candidates
            if str(candidate.get("name") or "").strip()
        )
        if len(candidates) > 1:
            return result(
                wrapper_kind="external_wrapper",
                status="ambiguous_contract",
                selection_source="ambiguous_receiver_type",
                candidate_contracts=candidate_names,
                reason="multiple_contracts_match_receiver_type",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )
        if not candidates:
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_contract",
                selection_source="unresolved_receiver_type",
                reason=(
                    "receiver_type_missing"
                    if not receiver_type
                    else "no_contract_matches_receiver_type"
                ),
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        contract = candidates[0]
        contract_name = str(contract.get("name") or explicit_name).strip()
        if not _wrapper_contract_receiver_matches(contract, receiver_type):
            return result(
                wrapper_kind="external_wrapper",
                status="receiver_mismatch",
                selection_source=selection_source,
                contract=contract_name,
                candidate_contracts=candidate_names,
                reason="receiver_type_does_not_match_contract",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        observed_method_identity = _text_fact(
            _first_fact(raw, "wrapper_method_identity", "method_identity")
        )
        method_contract, method_reason, method_candidates = _wrapper_contract_method(
            contract,
            wrapper_method,
            method_identity=observed_method_identity,
            method_arity=method_facts["method_arity"],
            parameter_types=method_facts["parameter_types"],
        )
        method_candidate_names = tuple(
            _wrapper_contract_method_identity(candidate, wrapper_method)
            for candidate in method_candidates
        )
        if method_contract is None:
            return result(
                wrapper_kind="external_wrapper",
                status=(
                    "ambiguous_overload"
                    if method_reason == "ambiguous_overload"
                    else "unresolved_method"
                ),
                selection_source=selection_source,
                contract=contract_name,
                candidate_contracts=candidate_names,
                overload_candidates=method_candidate_names,
                overload_candidate_facts=tuple(
                    _wrapper_candidate_fact(candidate) for candidate in method_candidates
                ),
                reason=method_reason,
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        contract_mode = str(method_contract.get("mode") or "")
        contract_mode_key = contract_mode.casefold()
        if contract_mode_key == "inline_sql":
            stored_procedure_mode = False
            mode_reason = "inline_sql"
        elif contract_mode_key == "stored_procedure":
            stored_procedure_mode = True
            mode_reason = ""
        elif contract_mode_key == "call_site" and raw_mode == "inline_sql":
            stored_procedure_mode = False
            mode_reason = "inline_sql"
        elif contract_mode_key == "call_site" and raw_mode == "stored_procedure":
            stored_procedure_mode = True
            mode_reason = ""
        elif contract_mode_key == "call_site":
            stored_procedure_mode = False
            mode_reason = "call_site_requires_explicit_stored_procedure_mode"
        else:
            stored_procedure_mode = False
            mode_reason = "wrapper_mode_unresolved"

        method_semantics = {
            "inline_sql": "fixed_inline_sql",
            "stored_procedure": "fixed_stored_procedure",
            "call_site": "call_site",
        }.get(contract_mode_key, method_semantics)

        return result(
            wrapper_kind="external_wrapper",
            status="explicit_selected" if explicit_selected else "auto_selected",
            selection_source=selection_source,
            contract=contract_name,
            contract_mode=contract_mode,
            contract_sink=str(method_contract.get("sink") or ""),
            candidate_contracts=candidate_names,
            stored_procedure_mode=stored_procedure_mode,
            mode_reason=mode_reason,
        )

    def resolve_direct_invocations(
        self,
        relative_path: str,
        raw_invocations: List[dict],
        *,
        scan_root: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
    ) -> List[DbInvocation]:
        """Turn raw Roslyn direct-SqlClient facts into evidence-rated Database Invocations."""
        results: List[DbInvocation] = []
        for raw in raw_invocations:
            invocation = self._resolve_one(
                relative_path,
                raw,
                scan_root=scan_root,
                explicit_contract=explicit_contract,
            )
            if invocation is not None:
                results.append(invocation)
        return results

    def reconcile_wrapper_observation(
        self,
        relative_path: str,
        raw: Mapping[str, Any],
        *,
        scan_root: str = "",
        source_snapshot_hash: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
    ) -> Dict[str, Any]:
        """Return one wrapper observation with classification and evidence parity."""
        classification = self.reconcile_wrapper(
            relative_path,
            raw,
            scan_root=scan_root,
            explicit_contract=explicit_contract,
        )
        rated = self.resolve_direct_invocations(
            relative_path,
            [dict(raw)],
            scan_root=scan_root,
            explicit_contract=explicit_contract,
        )
        return wrapper_observation_fields(
            classification,
            rated[0] if rated else None,
            source_snapshot_hash=source_snapshot_hash,
        )

    def _resolve_one(
        self,
        relative_path: str,
        raw: dict,
        *,
        scan_root: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
    ) -> Optional[DbInvocation]:
        invocation_kind = str(raw.get("invocation_kind") or "").casefold()
        if invocation_kind == "source_wrapper":
            return self._resolve_wrapper_invocation(
                relative_path,
                raw,
                scan_root=scan_root,
                explicit_contract=explicit_contract,
            )
        if invocation_kind in {"dapper", "entity_framework", "entityframework", "ef"}:
            return self._resolve_adapter_invocation(relative_path, raw)

        if not raw.get("command_type_stored_procedure"):
            if invocation_kind not in {"", "direct_sqlclient"}:
                return None
            if invocation_kind == "" and not raw.get("command_text_kind"):
                return None
            return self._resolve_inline_direct_invocation(relative_path, raw)

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)

        connection_expression = raw.get("connection_expression")
        database = self._resolve_database(connection_expression)
        metadata = self._invocation_metadata(
            raw,
            database=database,
            method_semantics="fixed_stored_procedure",
            invocation_mode="stored_procedure",
        )
        if str(raw.get("command_type_mode") or "").casefold() == "unknown":
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "command_type_unresolved",
                branch_context=branch_context,
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
            )
        if not metadata["terminal_sink"]:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "terminal_sink_unresolved",
                branch_context=branch_context,
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
            )

        if (
            raw.get("command_text_kind") != "literal"
            or not str(raw.get("command_text") or "").strip()
        ):
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                branch_context=branch_context,
                **metadata,
            )

        return self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            branch_context=branch_context,
            connection_resolution_reason=self._connection_source_unresolved_reason(raw),
            metadata=metadata,
        )

    def _resolve_inline_direct_invocation(
        self,
        relative_path: str,
        raw: dict,
    ) -> Optional[DbInvocation]:
        command_text_kind = str(raw.get("command_text_kind") or "").casefold()
        command_text = raw.get("command_text")
        if command_text_kind in {"", "none", "unknown"} and not command_text:
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        database = self._resolve_database(raw.get("connection_expression"))
        command_type_mode = str(raw.get("command_type_mode") or "").casefold()
        metadata = self._invocation_metadata(
            raw,
            database=database,
            method_semantics=(
                "unresolved" if command_type_mode == "unknown" else "fixed_inline_sql"
            ),
            invocation_mode=(
                "unresolved" if command_type_mode == "unknown" else "inline_sql"
            ),
        )
        if command_type_mode == "unknown":
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "command_type_unresolved",
                branch_context=branch_context,
                raw_command_text=(
                    str(command_text)
                    if command_text_kind == "literal" and command_text
                    else None
                ),
                **metadata,
            )
        if not metadata["terminal_sink"]:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "terminal_sink_unresolved",
                branch_context=branch_context,
                raw_command_text=(
                    str(command_text)
                    if command_text_kind == "literal" and command_text
                    else None
                ),
                **metadata,
            )

        if command_text_kind != "literal" or not command_text:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                branch_context=branch_context,
                **metadata,
            )

        return DbInvocation(
            class_name,
            method_name,
            database,
            None,
            InvocationEvidence.PROVEN,
            source,
            "inline_sql",
            branch_context=branch_context,
            raw_command_text=str(command_text),
            **metadata,
        )

    def _invocation_metadata(
        self,
        raw: Mapping[str, Any],
        *,
        database: Optional[str],
        method_semantics: str,
        invocation_mode: str,
    ) -> Dict[str, Any]:
        command_text_argument = raw.get("command_text_argument")
        if command_text_argument is None:
            command_text_argument = raw.get("argument_expression")
        if command_text_argument is None:
            command_text_argument = raw.get("argument")

        command_text_literal = raw.get("command_text_literal")
        if command_text_literal is None:
            command_text_literal = raw.get("literal_value")
        if command_text_literal is None and raw.get("command_text_kind") == "literal":
            command_text_literal = raw.get("command_text")

        return {
            "method_semantics": str(raw.get("method_semantics") or method_semantics),
            "invocation_mode": str(raw.get("invocation_mode") or invocation_mode),
            "command_text_kind": str(raw.get("command_text_kind") or ""),
            "command_type_mode": str(raw.get("command_type_mode") or ""),
            "command_text_argument": str(command_text_argument or ""),
            "command_text_literal": (
                str(command_text_literal)
                if command_text_literal is not None
                else None
            ),
            "literal_value": (
                str(command_text_literal)
                if command_text_literal is not None
                else None
            ),
            "terminal_sink": str(
                raw.get("terminal_sink")
                or raw.get("wrapper_terminal_sink")
                or ""
            ).strip(),
            "receiver_type": str(
                raw.get("receiver_type")
                or raw.get("wrapper_receiver_type")
                or ""
            ),
            "receiver_name": str(
                raw.get("receiver_name")
                or raw.get("receiver")
                or ""
            ),
            "receiver_construction_facts": _text_facts(
                raw.get("receiver_construction_facts")
            ),
            "receiver_assignment_facts": _text_facts(
                raw.get("receiver_assignment_facts")
            ),
            "connection_expression": str(
                raw.get("connection_expression")
                or raw.get("connection_variable")
                or ""
            ),
            "connection_expression_candidates": _text_facts(
                raw.get("connection_expression_candidates")
            ),
            "connection_source": database,
            "provenance": str(raw.get("provenance") or "static_analyzer_host"),
        }

    def _resolve_adapter_invocation(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        mode = str(raw.get("adapter_mode") or raw.get("wrapper_mode") or "").casefold()
        if mode == "inline_sql":
            return None

        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        database = self._resolve_database(raw.get("connection_expression"))
        if mode != "stored_procedure" and raw.get("command_type_stored_procedure") is not True:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "adapter_mode_unresolved",
                method_chain=tuple(raw.get("method_chain") or ()),
                branch_context=branch_context,
            )
        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                method_chain=tuple(raw.get("method_chain") or ()),
                branch_context=branch_context,
            )
        return self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            method_chain=tuple(raw.get("method_chain") or ()),
            branch_context=branch_context,
            connection_resolution_reason=self._connection_source_unresolved_reason(raw),
        )

    def _resolve_wrapper_invocation(
        self,
        relative_path: str,
        raw: dict,
        *,
        scan_root: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str] = None,
    ) -> Optional[DbInvocation]:
        reconciliation = self.reconcile_wrapper(
            relative_path,
            raw,
            scan_root=scan_root,
            explicit_contract=explicit_contract,
        )
        raw = dict(raw)
        if not _text_fact(raw.get("terminal_sink")):
            raw["terminal_sink"] = _text_fact(
                raw.get("wrapper_terminal_sink") or reconciliation.contract_sink
            )

        source = reconciliation.source_span
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        method_class_chain = tuple(
            value
            for value in (class_name, raw.get("wrapper_class_name"))
            if value
        )
        database = self._resolve_database(raw.get("connection_expression"))
        source_available = reconciliation.source_available
        external_wrapper_method = (
            reconciliation.wrapper_method if not source_available else ""
        )

        def annotate(invocation: DbInvocation) -> DbInvocation:
            return replace(
                invocation,
                wrapper_kind=reconciliation.wrapper_kind,
                wrapper_status=reconciliation.status,
                wrapper_selection_source=reconciliation.selection_source,
                wrapper_contract=reconciliation.contract,
                wrapper_contract_source=(
                    "" if source_available else reconciliation.selection_source
                ),
                wrapper_contract_mode=reconciliation.contract_mode,
                wrapper_contract_sink=reconciliation.contract_sink,
                wrapper_receiver_type=reconciliation.receiver_type,
                wrapper_contract_candidates=reconciliation.candidate_contracts,
                wrapper_scan_root=reconciliation.scan_root,
                wrapper_review_candidate=reconciliation.review_candidate,
                wrapper_unresolved_reason=reconciliation.reason,
                wrapper_mode_reason=reconciliation.mode_reason,
                wrapper_method=reconciliation.wrapper_method,
                wrapper_source_available=reconciliation.source_available,
                wrapper_stored_procedure_mode=reconciliation.stored_procedure_mode,
                external_wrapper_method=external_wrapper_method,
                implementation_identity=reconciliation.implementation_identity,
                assembly_identity=reconciliation.assembly_identity,
                assembly_revision=reconciliation.assembly_revision,
                method_identity=reconciliation.method_identity,
                method_arity=reconciliation.method_arity,
                parameter_types=reconciliation.parameter_types,
                overload_candidates=reconciliation.overload_candidates,
                overload_candidate_facts=reconciliation.overload_candidate_facts,
                receiver_construction_facts=reconciliation.receiver_construction_facts,
                receiver_assignment_facts=reconciliation.receiver_assignment_facts,
                receiver_expression=str(
                    raw.get("receiver_expression")
                    or raw.get("receiver_name")
                    or raw.get("receiver")
                    or ""
                ),
                binding_provenance=str(
                    raw.get("binding_provenance")
                    or raw.get("receiver_binding_provenance")
                    or ""
                ),
                wrapper_implementation_identity=reconciliation.implementation_identity,
                wrapper_assembly_identity=reconciliation.assembly_identity,
                wrapper_assembly_revision=reconciliation.assembly_revision,
                wrapper_method_identity=reconciliation.method_identity,
                wrapper_method_arity=reconciliation.method_arity,
                wrapper_parameter_types=reconciliation.parameter_types,
                wrapper_method_semantics=reconciliation.method_semantics,
                wrapper_overload_candidates=reconciliation.overload_candidates,
                wrapper_overload_candidate_facts=reconciliation.overload_candidate_facts,
            )

        common = {
            "method_chain": tuple(raw.get("method_chain") or ()),
            "method_class_chain": method_class_chain,
            "branch_context": branch_context,
        }

        if not source_available:
            if reconciliation.status == "ambiguous_overload":
                metadata = self._invocation_metadata(
                    raw,
                    database=database,
                    method_semantics=reconciliation.method_semantics or "unresolved",
                    invocation_mode="unresolved",
                )
                return annotate(DbInvocation(
                    class_name,
                    method_name,
                    database,
                    None,
                    InvocationEvidence.UNRESOLVED,
                    source,
                    "ambiguous_overload",
                    raw_command_text=(
                        str(raw["command_text"])
                        if raw.get("command_text_kind") == "literal"
                        and raw.get("command_text")
                        else None
                    ),
                    **metadata,
                    **common,
                ))
            if reconciliation.status in {"explicit_selected", "auto_selected"}:
                if not _known_terminal_sink(raw.get("terminal_sink")):
                    metadata = self._invocation_metadata(
                        raw,
                        database=database,
                        method_semantics=reconciliation.method_semantics,
                        invocation_mode="unresolved",
                    )
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_contract_sink_unresolved",
                        **metadata,
                        **common,
                    ))
                if not reconciliation.stored_procedure_mode:
                    if reconciliation.mode_reason != "inline_sql":
                        metadata = self._invocation_metadata(
                            raw,
                            database=database,
                            method_semantics=reconciliation.method_semantics,
                            invocation_mode="unresolved",
                        )
                        return annotate(DbInvocation(
                            class_name,
                            method_name,
                            database,
                            None,
                            InvocationEvidence.UNRESOLVED,
                            source,
                            "wrapper_mode_unresolved",
                            **metadata,
                            **common,
                        ))
                    metadata = self._invocation_metadata(
                        raw,
                        database=database,
                        method_semantics=reconciliation.method_semantics,
                        invocation_mode="inline_sql",
                    )
                    if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
                        return annotate(DbInvocation(
                            class_name,
                            method_name,
                            database,
                            None,
                            InvocationEvidence.UNRESOLVED,
                            source,
                            "dynamic_command_text",
                            **metadata,
                            **common,
                        ))
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.PROVEN,
                        source,
                        "inline_sql",
                        raw_command_text=str(raw["command_text"]),
                        **metadata,
                        **common,
                    ))
                if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
                    metadata = self._invocation_metadata(
                        raw,
                        database=database,
                        method_semantics=reconciliation.method_semantics,
                        invocation_mode="stored_procedure",
                    )
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "dynamic_command_text",
                        **metadata,
                        **common,
                    ))

                rated = self._rate_literal_candidate(
                    class_name,
                    method_name,
                    database,
                    raw["command_text"],
                    source,
                    connection_resolution_reason=self._connection_source_unresolved_reason(raw),
                    metadata=self._invocation_metadata(
                        raw,
                        database=database,
                        method_semantics=reconciliation.method_semantics,
                        invocation_mode="stored_procedure",
                    ),
                    **common,
                )
                return annotate(rated)

            procedure_name = None
            procedure_schema = None
            if (
                reconciliation.stored_procedure_mode
                and raw.get("command_text_kind") == "literal"
                and raw.get("command_text")
            ):
                procedure_name = normalize_procedure_name(raw["command_text"])
                procedure_schema = normalize_procedure_schema(raw["command_text"])
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                procedure_name,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_source_unavailable",
                procedure_schema,
                raw_command_text=raw.get("command_text") if procedure_name else None,
                **self._invocation_metadata(
                    raw,
                    database=database,
                    method_semantics=reconciliation.method_semantics,
                    invocation_mode=(
                        "stored_procedure"
                        if reconciliation.stored_procedure_mode
                        else "unresolved"
                    ),
                ),
                **common,
            ))

        if reconciliation.review_candidate and reconciliation.reason:
            metadata = self._invocation_metadata(
                raw,
                database=database,
                method_semantics=reconciliation.method_semantics or "unresolved",
                invocation_mode="unresolved",
            )
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                reconciliation.reason,
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
                **common,
            ))

        if not _known_terminal_sink(raw.get("terminal_sink")):
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_sink_unresolved",
                **self._invocation_metadata(
                    raw,
                    database=database,
                    method_semantics=reconciliation.method_semantics,
                    invocation_mode="unresolved",
                ),
                **common,
            ))
        if reconciliation.mode_reason == "wrapper_mode_unresolved":
            metadata = self._invocation_metadata(
                raw,
                database=database,
                method_semantics=reconciliation.method_semantics,
                invocation_mode="unresolved",
            )
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "wrapper_mode_unresolved",
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
                **common,
            ))
        if not reconciliation.stored_procedure_mode:
            metadata = self._invocation_metadata(
                raw,
                database=database,
                method_semantics=reconciliation.method_semantics,
                invocation_mode="inline_sql",
            )
            if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
                return annotate(DbInvocation(
                    class_name,
                    method_name,
                    database,
                    None,
                    InvocationEvidence.UNRESOLVED,
                    source,
                    "dynamic_command_text",
                    **metadata,
                    **common,
                ))
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.PROVEN,
                source,
                "inline_sql",
                raw_command_text=str(raw["command_text"]),
                **metadata,
                **common,
            ))

        if raw.get("command_text_kind") != "literal" or not raw.get("command_text"):
            metadata = self._invocation_metadata(
                raw,
                database=database,
                method_semantics=reconciliation.method_semantics,
                invocation_mode="stored_procedure",
            )
            return annotate(DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "dynamic_command_text",
                **metadata,
                **common,
            ))

        return annotate(self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            connection_resolution_reason=self._connection_source_unresolved_reason(raw),
            metadata=self._invocation_metadata(
                raw,
                database=database,
                method_semantics=reconciliation.method_semantics,
                invocation_mode="stored_procedure",
            ),
            **common,
        ))

    def _rate_literal_candidate(
        self,
        class_name: str,
        method_name: str,
        database: Optional[str],
        command_text: str,
        source: InvocationSourceSpan,
        method_chain: tuple[str, ...] = (),
        branch_context: tuple[str, ...] = (),
        method_class_chain: tuple[str, ...] = (),
        connection_resolution_reason: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> DbInvocation:
        metadata = dict(metadata or {})
        normalized_name = normalize_procedure_name(command_text)
        procedure_schema = normalize_procedure_schema(command_text)

        if database:
            if self._catalog.contains(database, normalized_name, procedure_schema):
                return DbInvocation(
                    class_name,
                    method_name,
                    database,
                    normalized_name,
                    InvocationEvidence.PROVEN,
                    source,
                    procedure_schema=procedure_schema,
                    method_chain=method_chain,
                    branch_context=branch_context,
                    method_class_chain=method_class_chain,
                    raw_command_text=command_text,
                    **metadata,
                )
            return DbInvocation(
                class_name,
                method_name,
                database,
                normalized_name,
                InvocationEvidence.UNRESOLVED,
                source,
                "not_in_resolved_catalog",
                procedure_schema,
                method_chain,
                branch_context,
                method_class_chain=method_class_chain,
                raw_command_text=command_text,
                **metadata,
            )

        matches = self._catalog.databases_containing(normalized_name, procedure_schema)
        if connection_resolution_reason:
            return DbInvocation(
                class_name,
                method_name,
                None,
                normalized_name,
                InvocationEvidence.UNRESOLVED,
                source,
                connection_resolution_reason,
                procedure_schema,
                method_chain,
                branch_context,
                method_class_chain=method_class_chain,
                database_candidates=tuple(matches),
                raw_command_text=command_text,
                **metadata,
            )
        if len(matches) == 1:
            return DbInvocation(
                class_name,
                method_name,
                None,
                normalized_name,
                InvocationEvidence.LIKELY,
                source,
                "unique_across_catalogs",
                procedure_schema,
                method_chain,
                branch_context,
                method_class_chain=method_class_chain,
                database_candidates=tuple(matches),
                raw_command_text=command_text,
                **metadata,
            )
        reason = "unknown_database_source" if len(matches) == 0 else "ambiguous_cross_database"
        return DbInvocation(
            class_name,
            method_name,
            None,
            normalized_name,
            InvocationEvidence.UNRESOLVED,
            source,
            reason,
            procedure_schema,
            method_chain,
            branch_context,
            method_class_chain=method_class_chain,
            database_candidates=tuple(matches),
            raw_command_text=command_text,
            **metadata,
        )

    @staticmethod
    def _connection_source_unresolved_reason(raw: Mapping[str, Any]) -> str:
        candidates = _text_facts(raw.get("connection_expression_candidates"))
        if len(candidates) > 1:
            return "ambiguous_connection_source"
        if candidates:
            return "connection_source_unresolved"
        if "connection_expression" in raw and not str(
            raw.get("connection_expression") or ""
        ).strip():
            return "connection_source_unresolved"
        return ""

    def _resolve_database(self, connection_expression: object) -> Optional[str]:
        if not connection_expression:
            return None
        expression = str(connection_expression).strip()
        if not expression:
            return None
        if expression in self._connection_sources:
            database = self._connection_sources[expression]
        else:
            folded = expression.casefold()
            database = next(
                (
                    value
                    for key, value in self._connection_sources.items()
                    if str(key).casefold() == folded
                ),
                None,
            )
        if not database or str(database).strip().casefold() in {"unknown", "unresolved"}:
            return None
        return str(database).strip()

    @staticmethod
    def _branch_context(raw: dict) -> tuple[str, ...]:
        value = raw.get("branch_context")
        if value is None:
            value = raw.get("branch_path")
        if isinstance(value, str):
            value = [value]
        return tuple(str(item) for item in (value or ()) if str(item).strip())


def normalize_procedure_schema(raw_name: str) -> Optional[str]:
    """Return the explicit schema from a qualified procedure name, when present."""
    cleaned = raw_name.strip().replace("[", "").replace("]", "")
    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if len(parts) < 2:
        return None
    return normalize_schema_name(parts[-2])


def normalize_schema_name(raw_schema: str) -> str:
    return raw_schema.strip().replace("[", "").replace("]", "").casefold()

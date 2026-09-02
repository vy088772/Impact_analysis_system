"""CSharpAnalysisGateway: evidence-rated Database Invocations from direct SqlClient use.

Combines raw Roslyn facts (from StaticAnalyzerHost) with a database-scoped SP Catalog
and connection-source resolution. Roslyn only reports what the source contains; all
evidence-rating decisions live here so unresolved names or databases are never guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .external_wrapper_contracts import (
    CONTRACT_SIGNATURE_SCHEMA_VERSION,
    compute_contract_fingerprint,
)


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
class EmbeddedProcedureTarget:
    """Catalog evidence for a procedure named by inline SQL text.

    ``target_source`` says how the text named it: ``exec_keyword`` for an
    explicit ``EXEC``/``EXECUTE``, ``implicit_exec`` for a command text that is
    nothing but the procedure name, which T-SQL executes just the same. Both
    answer `DbInvocation.executed_procedure_name` identically, so this field is
    the only place the difference between them survives. It is a plain string
    beside ``reason``, which is one too.
    """

    procedure_name: Optional[str]
    procedure_schema: Optional[str]
    database: Optional[str]
    evidence: InvocationEvidence
    reason: str = ""
    database_candidates: tuple[str, ...] = ()
    raw_target: str = ""
    target_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procedure_name": self.procedure_name,
            "procedure_schema": self.procedure_schema,
            "database": self.database,
            "database_candidates": list(self.database_candidates),
            "evidence": self.evidence.value,
            "evidence_status": self.evidence.value,
            "reason": self.reason,
            "raw_target": self.raw_target,
            "target_source": self.target_source,
        }


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
    semantic_binding_accepted: bool = False
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
    contract_fingerprint: str = ""
    contract_signature_version: str = ""
    contract_lifecycle_status: str = ""
    evidence_kind: str = ""
    implementation_snapshot_reference: str = ""
    comparison_report_reference: str = ""
    source_contract_conflict: bool = False
    source_contract_conflict_reason: str = ""
    source_contract_semantics: str = ""
    source_contract_sink: str = ""

    @property
    def active_contract(self) -> bool:
        """Whether this observation has approved contract semantics to use."""
        return bool(self.contract and not self.review_candidate)


def project_wrapper_evidence(reconciliation: WrapperReconciliation) -> Dict[str, Any]:
    """Return the machine-readable boundary shape used by audit consumers.

    Emits exactly one canonical key per fact. The dropped aliases
    (``observed_method``, ``signature_version``, ``contract_status``, and
    friends) never appear here -- see ``.scratch/collapse-wrapper-evidence-
    aliases/spec.md`` for the canonical-name table.
    """
    return {
        "wrapper_kind": reconciliation.wrapper_kind,
        "status": reconciliation.status,
        "selection_source": reconciliation.selection_source,
        "contract": reconciliation.contract,
        "contract_mode": reconciliation.contract_mode,
        "contract_sink": reconciliation.contract_sink,
        "candidate_contracts": list(reconciliation.candidate_contracts),
        "receiver_type": reconciliation.receiver_type,
        "wrapper_method": reconciliation.wrapper_method,
        "source_available": reconciliation.source_available,
        "scan_root": reconciliation.scan_root,
        "source_span": {
            "relative_path": reconciliation.source_span.relative_path,
            "start_offset": reconciliation.source_span.start_offset,
            "end_offset": reconciliation.source_span.end_offset,
        },
        "reason": reconciliation.reason,
        "unresolved_reason": reconciliation.reason,
        "review_candidate": reconciliation.review_candidate,
        "active_contract": reconciliation.active_contract,
        "semantic_binding_accepted": reconciliation.semantic_binding_accepted,
        "stored_procedure_mode": reconciliation.stored_procedure_mode,
        "mode_reason": reconciliation.mode_reason,
        "implementation_identity": reconciliation.implementation_identity,
        "assembly_identity": reconciliation.assembly_identity,
        "assembly_revision": reconciliation.assembly_revision,
        "method_identity": reconciliation.method_identity,
        "method_arity": reconciliation.method_arity,
        "parameter_types": list(reconciliation.parameter_types),
        "method_semantics": reconciliation.method_semantics,
        "overload_candidates": list(reconciliation.overload_candidates),
        "overload_candidate_facts": [
            dict(item) for item in reconciliation.overload_candidate_facts
        ],
        "receiver_construction_facts": list(reconciliation.receiver_construction_facts),
        "receiver_assignment_facts": list(reconciliation.receiver_assignment_facts),
        "contract_fingerprint": reconciliation.contract_fingerprint,
        "contract_signature_version": reconciliation.contract_signature_version,
        "contract_lifecycle_status": reconciliation.contract_lifecycle_status,
        "evidence_kind": reconciliation.evidence_kind,
        "implementation_snapshot_reference": reconciliation.implementation_snapshot_reference,
        "comparison_report_reference": reconciliation.comparison_report_reference,
        "source_contract_conflict": reconciliation.source_contract_conflict,
        "source_contract_conflict_reason": reconciliation.source_contract_conflict_reason,
        "source_contract_semantics": reconciliation.source_contract_semantics,
        "source_contract_sink": reconciliation.source_contract_sink,
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
    contract_fingerprint: str = ""
    contract_signature_version: str = ""
    contract_lifecycle_status: str = ""
    evidence_kind: str = ""
    implementation_snapshot_reference: str = ""
    comparison_report_reference: str = ""
    source_contract_conflict: bool = False
    source_contract_conflict_reason: str = ""
    source_contract_semantics: str = ""
    source_contract_sink: str = ""
    embedded_target: Optional[EmbeddedProcedureTarget] = None
    procedure_name_hint: Optional[str] = None
    command_text_source: Optional[InvocationSourceSpan] = None
    command_text_provenance: str = ""
    server: Optional[str] = None

    @property
    def embedded_procedure_target(self) -> Optional[EmbeddedProcedureTarget]:
        """Compatibility name for the optional inline EXEC target evidence."""
        return self.embedded_target

    @property
    def embedded_procedure_name(self) -> Optional[str]:
        return self.embedded_target.procedure_name if self.embedded_target else None

    @property
    def embedded_procedure_schema(self) -> Optional[str]:
        return self.embedded_target.procedure_schema if self.embedded_target else None

    @property
    def embedded_procedure_evidence(self) -> Optional[InvocationEvidence]:
        return self.embedded_target.evidence if self.embedded_target else None

    def _answering_embedded_target(self) -> Optional[EmbeddedProcedureTarget]:
        """The Embedded Procedure Target that answers for this invocation, if any.

        Only when the call declared no procedure of its own, and only at
        ``proven`` -- a candidate is not a call.
        """
        if self.procedure_name:
            return None
        target = self.embedded_target
        if target is not None and target.evidence is InvocationEvidence.PROVEN:
            return target
        return None

    @property
    def executed_procedure_name(self) -> Optional[str]:
        """The stored procedure this invocation runs, however the call names it.

        Usually that is ``procedure_name``: the call selected stored-procedure
        mode and named its procedure directly. It can also be a proven Embedded
        Procedure Target -- inline SQL text that executes a procedure, whether it
        says ``EXEC`` or relies on T-SQL running a bare procedure name. Both are
        calls the database really makes, and a reverse lookup that reads only the
        first answers "no callers" for the second.

        The two stay separate fields on purpose: ``procedure_name`` records what
        the call itself declared, and the target records what its text turned out
        to name, with the raw text and rating behind it. This property is the one
        place that asks the question both answer. Nothing below ``proven`` is
        offered -- a candidate is not a call.

        The answer is the normalized bare identity either way. A declared name
        arrives however the call wrote it and a target's arrives already
        normalized, and a property whose job is comparison must not hand back two
        shapes for the same procedure.
        """
        target = self._answering_embedded_target()
        raw_name = target.procedure_name if target is not None else self.procedure_name
        return normalize_procedure_name(raw_name) if raw_name else None

    @property
    def executed_procedure_schema(self) -> Optional[str]:
        """The schema of `executed_procedure_name`, from whichever field named it."""
        target = self._answering_embedded_target()
        return target.procedure_schema if target is not None else self.procedure_schema

    @property
    def executed_procedure_name_source(self) -> str:
        """Where `executed_procedure_name` came from: ``declared`` when the call
        named its own procedure, else the target's ``target_source``."""
        target = self._answering_embedded_target()
        return target.target_source if target is not None else "declared"

    @property
    def wrapper_classification_status(self) -> str:
        """Compatibility alias for consumers that use the longer field name."""
        return self.wrapper_status


WRAPPER_EVIDENCE_FIELDS = (
    "wrapper_kind",
    "status",
    "selection_source",
    "contract",
    "wrapper_contract_source",
    "contract_mode",
    "contract_sink",
    "candidate_contracts",
    "wrapper_receiver_type",
    "receiver_type",
    "scan_root",
    "source_available",
    "review_candidate",
    "classification_reason",
    "mode_reason",
    "wrapper_method",
    "external_wrapper_method",
    "stored_procedure_mode",
    "active_contract",
    "evidence_status",
    "evidence_reason",
    "source_span",
    "source_snapshot_hash",
    "source_provenance",
    "method_semantics",
    "invocation_mode",
    "command_text_kind",
    "command_type_mode",
    "command_text_argument",
    "command_text_literal",
    "command_text_source_span",
    "command_text_provenance",
    "literal_value",
    "terminal_sink",
    "embedded_target",
    "embedded_targets",
    "embedded_procedure_name",
    "embedded_procedure_schema",
    "embedded_procedure_evidence",
    "procedure_name_hint",
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
    "contract_fingerprint",
    "contract_signature_version",
    "contract_lifecycle_status",
    "evidence_kind",
    "implementation_snapshot_reference",
    "comparison_report_reference",
    "source_contract_conflict",
    "source_contract_conflict_reason",
    "source_contract_semantics",
    "source_contract_sink",
)


def wrapper_observation_fields(
    reconciliation: WrapperReconciliation,
    evidence: Optional[DbInvocation] = None,
    *,
    source_snapshot_hash: str = "",
) -> Dict[str, Any]:
    """Project classification and database evidence into one audit shape."""
    classification = project_wrapper_evidence(reconciliation)
    snapshot_hash = str(
        source_snapshot_hash
        or (evidence.source_snapshot_hash if evidence is not None else "")
        or ""
    )
    reviewed_exclusion = evidence is None and classification["status"] == "not_applicable"
    evidence_status = (
        "not_applicable"
        if reviewed_exclusion
        else evidence.evidence.value if evidence is not None else "not_applicable"
    )
    evidence_reason = (
        classification["reason"]
        if reviewed_exclusion
        else evidence.reason if evidence is not None else "inline_sql"
    )
    database = evidence.database if evidence is not None else None
    server = evidence.server if evidence is not None else None
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
        "semantic_binding_accepted": classification["semantic_binding_accepted"],
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
        "evidence_status": evidence_status,
        "evidence_reason": evidence_reason,
        "procedure_name": procedure_name or "",
        "procedure_schema": procedure_schema or "",
        "procedure_name_hint": (
            evidence.procedure_name_hint if evidence is not None else None
        ),
        "database": database,
        "server": server,
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
        "contract_fingerprint": classification["contract_fingerprint"],
        "contract_signature_version": classification["contract_signature_version"],
        "signature_version": classification["contract_signature_version"],
        "contract_lifecycle_status": classification["contract_lifecycle_status"],
        "contract_status": classification["contract_lifecycle_status"],
        "evidence_kind": classification["evidence_kind"],
        "implementation_snapshot_reference": classification[
            "implementation_snapshot_reference"
        ],
        "comparison_report_reference": classification["comparison_report_reference"],
        "source_contract_conflict": classification["source_contract_conflict"],
        "source_contract_conflict_reason": classification[
            "source_contract_conflict_reason"
        ],
        "source_contract_semantics": classification["source_contract_semantics"],
        "source_contract_sink": classification["source_contract_sink"],
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
        "command_text_source_span": (
            {
                "relative_path": evidence.command_text_source.relative_path,
                "start_offset": evidence.command_text_source.start_offset,
                "end_offset": evidence.command_text_source.end_offset,
            }
            if evidence is not None and evidence.command_text_source is not None
            else None
        ),
        "command_text_provenance": (
            evidence.command_text_provenance if evidence is not None else ""
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
        "embedded_target": (
            evidence.embedded_target.to_dict()
            if evidence is not None and evidence.embedded_target is not None
            else None
        ),
        "embedded_targets": (
            [evidence.embedded_target.to_dict()]
            if evidence is not None and evidence.embedded_target is not None
            else []
        ),
        "embedded_procedure_name": (
            evidence.embedded_procedure_name if evidence is not None else None
        ),
        "embedded_procedure_schema": (
            evidence.embedded_procedure_schema if evidence is not None else None
        ),
        "embedded_procedure_evidence": (
            evidence.embedded_procedure_evidence.value
            if evidence is not None and evidence.embedded_procedure_evidence is not None
            else None
        ),
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
        evidence_kind=invocation.evidence_kind,
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
            "command_text_source_span": (
                {
                    "relative_path": invocation.command_text_source.relative_path,
                    "start_offset": invocation.command_text_source.start_offset,
                    "end_offset": invocation.command_text_source.end_offset,
                }
                if invocation.command_text_source is not None
                else None
            ),
            "command_text_provenance": invocation.command_text_provenance,
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
            "embedded_target": (
                invocation.embedded_target.to_dict()
                if invocation.embedded_target is not None
                else None
            ),
            "embedded_targets": (
                [invocation.embedded_target.to_dict()]
                if invocation.embedded_target is not None
                else []
            ),
            "embedded_procedure_name": invocation.embedded_procedure_name,
            "embedded_procedure_schema": invocation.embedded_procedure_schema,
            "embedded_procedure_evidence": (
                invocation.embedded_procedure_evidence.value
                if invocation.embedded_procedure_evidence is not None
                else None
            ),
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
            "contract_fingerprint": invocation.contract_fingerprint,
            "contract_signature_version": invocation.contract_signature_version,
            "signature_version": invocation.contract_signature_version,
            "contract_lifecycle_status": invocation.contract_lifecycle_status,
            "contract_status": invocation.contract_lifecycle_status,
            "evidence_kind": invocation.evidence_kind,
            "implementation_snapshot_reference": invocation.implementation_snapshot_reference,
            "comparison_report_reference": invocation.comparison_report_reference,
            "source_contract_conflict": invocation.source_contract_conflict,
            "source_contract_conflict_reason": invocation.source_contract_conflict_reason,
            "source_contract_semantics": invocation.source_contract_semantics,
            "source_contract_sink": invocation.source_contract_sink,
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


def _normalize_wrapper_review_exclusions(
    exclusions: Optional[Iterable[Mapping[str, Any]]],
) -> Dict[tuple[str, str], str]:
    """Fold a curated review-triage list into an exact (receiver, method) lookup.

    Each entry records a human decision that one exact observed receiver/method
    pair is confirmed not to be a database wrapper call (e.g. ``String.Format``
    surfaced only because its receiver type could not be resolved locally).
    Matching is exact, not a method-name wildcard, so a triage decision never
    silently swallows an unrelated call that happens to share a method name.
    """
    normalized: Dict[tuple[str, str], str] = {}
    for entry in exclusions or ():
        if not isinstance(entry, Mapping):
            continue
        method_name = _text_fact(entry.get("method_name") or entry.get("wrapper_method"))
        if not method_name:
            continue
        receiver_type = _text_fact(entry.get("receiver_type"))
        reason = _text_fact(entry.get("reason")) or "reviewed_non_wrapper_method"
        normalized[(receiver_type.casefold(), method_name.casefold())] = reason
    return normalized


def _load_wrapper_review_exclusions_registry() -> Dict[str, tuple[Dict[str, Any], ...]]:
    """Load the repository-level per-system wrapper review exclusion registry."""
    config_path = (
        Path(__file__).resolve().parent.parent / "config" / "wrapper_review_exclusions.json"
    )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    systems = payload.get("systems", payload) if isinstance(payload, dict) else {}
    if not isinstance(systems, dict):
        return {}
    registry: Dict[str, tuple[Dict[str, Any], ...]] = {}
    for system_id, entries in systems.items():
        if not isinstance(entries, list):
            continue
        rules = tuple(entry for entry in entries if isinstance(entry, dict))
        if rules:
            registry[str(system_id)] = rules
    return registry


def load_wrapper_review_exclusions(system: str) -> tuple[Dict[str, Any], ...]:
    """Load the reviewed wrapper-review exclusion list for one system id.

    Each entry is a human triage decision, recorded once a maintainer has
    confirmed one exact receiver/method pair surfaced only because its
    receiver type could not be resolved locally and is not actually a
    database wrapper call. Scoped per system so the same method name can be
    treated differently across unrelated codebases.
    """
    normalized_system = str(system or "").strip().casefold()
    if not normalized_system:
        return ()
    registry = _load_wrapper_review_exclusions_registry()
    return next(
        (
            rules
            for key, rules in registry.items()
            if str(key).strip().casefold() == normalized_system
        ),
        (),
    )


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


def _candidate_arity(candidate: Mapping[str, Any]) -> Optional[int]:
    arity = _optional_int_fact(_first_fact(candidate, "method_arity", "arity"))
    if arity is not None:
        return arity
    parameters = _text_facts(_first_fact(candidate, "parameter_types", "parameters"))
    return len(parameters) if parameters else None


def _candidate_admits_arity(
    candidate: Mapping[str, Any], method_arity: Optional[int]
) -> bool:
    """Whether a call with ``method_arity`` arguments can bind to ``candidate``.

    An exact count always binds. A shorter call binds only when the candidate says
    how many parameters it actually requires -- C# lets a caller leave trailing
    optional parameters out, and an overload set that differs only by such a
    parameter is exactly where comparing counts alone picks the wrong sibling. A
    candidate that reports no Required Parameter Count keeps the strict equality it
    has today, so a registry written before the count existed selects unchanged.
    A call can never pass more arguments than the overload declares.

    An unobserved argument count (``None``) admits every candidate: there is
    nothing to compare, which is not the same as a mismatch. The analyzer host
    applies this same rule to a wrapper it can read the source of, in
    ``CSharpAnalyzer.ResolveWrapperOverload``; the two tie-break differently
    afterwards, because only the host has the call site's argument types.
    """
    if method_arity is None:
        return True
    candidate_arity = _candidate_arity(candidate)
    if candidate_arity is None:
        return False
    if candidate_arity == method_arity:
        return True
    required = _optional_int_fact(
        _first_fact(candidate, "required_parameter_count", "required_parameters")
    )
    return required is not None and required <= method_arity < candidate_arity


_STRING_PARAMETER_TYPES = {"string", "system.string"}


def _is_string_parameter(parameter_type: str) -> bool:
    return _normalize_type_identity(parameter_type).rstrip("?") in _STRING_PARAMETER_TYPES


def _carries_mode_argument(
    candidate: Mapping[str, Any], method_arity: Optional[int]
) -> Optional[bool]:
    """Whether ``candidate`` has a parameter that could have received the call
    site's command-type mode argument, or ``None`` when it does not say.

    A mode argument is a string. An overload that declares a ``command_type``
    argument role carries it when that role sits inside the observed argument
    count and the parameter there is a string. An overload that declares no such
    role carries it only if some other string parameter, inside the observed count
    and not the command-text parameter, was free to take it. This is C# binding,
    not a preference: a string literal has no conversion to an ``int`` parameter,
    so an overload whose only spare parameter is numeric cannot be the overload
    the compiler chose.

    ``None`` is the answer for a candidate that does not declare enough to be
    judged -- no observed argument count, no parameter types, no argument roles,
    or roles that never name the command-text parameter, which is the one this
    rule has to set aside. It is not the same as "carries nothing": a legacy
    entry excluded for saying too little could hand the tie to its sibling on
    evidence it was never asked for.
    """
    if method_arity is None:
        return None
    parameters = _text_facts(_first_fact(candidate, "parameter_types", "parameters"))
    if not parameters:
        return None
    visible = parameters[:method_arity]
    roles = _first_fact(candidate, "argument_roles", "parameter_roles", "roles")
    if not isinstance(roles, Mapping):
        return None
    mode_index = _optional_int_fact(roles.get("command_type"))
    if mode_index is not None:
        return 0 <= mode_index < len(visible) and _is_string_parameter(visible[mode_index])
    command_text_index = _optional_int_fact(roles.get("command_text"))
    if command_text_index is None:
        return None
    return any(
        index != command_text_index and _is_string_parameter(parameter)
        for index, parameter in enumerate(visible)
    )


def _narrow_by_mode_argument_carriage(
    matching: tuple[Mapping[str, Any], ...], method_arity: Optional[int]
) -> tuple[Mapping[str, Any], ...]:
    """Break a tie by which overload could have carried the observed mode argument.

    Only a narrowing to exactly one candidate is taken. Zero survivors means the
    observation explains none of them, several means it separates none of them --
    either way the tie is left exactly as it was, for the shared-mode merge and
    the ambiguity report downstream to handle as they do today. One candidate
    that cannot be judged at all abandons the narrowing outright: a survivor
    picked because a sibling said too little would be a decision made on missing
    evidence, not on the observation.
    """
    carriage = [_carries_mode_argument(candidate, method_arity) for candidate in matching]
    if any(carried is None for carried in carriage):
        return matching
    carriers = tuple(
        candidate for candidate, carried in zip(matching, carriage) if carried
    )
    return carriers if len(carriers) == 1 else matching


def _wrapper_contract_method(
    contract: Optional[Mapping[str, Any]],
    method_name: str,
    *,
    method_identity: str = "",
    method_arity: Optional[int] = None,
    parameter_types: Iterable[str] = (),
    command_type_mode_observed: bool = False,
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
        candidate_parameters = tuple(
            _normalize_type_identity(item)
            for item in _text_facts(
                _first_fact(candidate, "parameter_types", "parameters")
            )
        )
        if observed_identity and not candidate_identity:
            if not _candidate_admits_arity(candidate, method_arity):
                return False
            if observed_parameters and candidate_parameters != observed_parameters:
                return False
            return bool(method_arity is not None or observed_parameters)

        if not _candidate_admits_arity(candidate, method_arity):
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
    if len(matching) > 1 and command_type_mode_observed:
        matching = _narrow_by_mode_argument_carriage(matching, method_arity)
    if len(matching) == 1:
        return matching[0], "", tuple(named_methods)
    if len(matching) > 1:
        merged = _merge_ambiguous_candidates_by_shared_mode(matching)
        if merged is not None:
            return merged, "ambiguous_overload_mode_resolved", tuple(named_methods)
        return None, "ambiguous_overload", tuple(named_methods)
    return None, "overload_not_found", tuple(named_methods)


def _merge_ambiguous_candidates_by_shared_mode(
    matching: tuple[Mapping[str, Any], ...],
) -> Optional[Dict[str, Any]]:
    """Rate database evidence for a tied overload set when every remaining
    candidate agrees on ``mode`` and ``sink``.

    Two sibling overloads (e.g. ``CreateReader(string, SqlParameter)`` vs.
    ``CreateReader(string, SqlParameter[])``) can be indistinguishable from
    call-site facts alone -- the scanner only sees an argument count, not the
    exact parameter type -- yet both run the exact same command text through
    the exact same terminal sink. In that case the *method identity* stays
    ambiguous (kept out of the merged result, and callers must keep surfacing
    that as a review-worthy fact) but the *database evidence* does not have
    to.  A signature-less candidate never participates: it does not declare
    enough to even confirm it describes the observed call, so folding it in
    would be exactly the kind of guess this module refuses to make.
    """
    modes: Set[str] = set()
    sinks: Set[str] = set()
    for candidate in matching:
        has_signature = bool(
            _text_fact(_first_fact(candidate, "method_identity", "identity"))
            or _optional_int_fact(_first_fact(candidate, "method_arity", "arity"))
            is not None
            or _text_facts(_first_fact(candidate, "parameter_types", "parameters"))
        )
        if not has_signature:
            return None
        mode = str(candidate.get("mode") or "").strip()
        sink = str(candidate.get("sink") or "").strip()
        if not mode or not sink:
            return None
        modes.add(mode.casefold())
        sinks.add(sink.casefold())
    if len(modes) != 1 or len(sinks) != 1:
        return None
    representative = dict(matching[0])
    for ambiguous_key in ("method_identity", "identity", "parameter_types", "parameters"):
        representative.pop(ambiguous_key, None)
    return representative


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


def _contract_snapshot_field(contract: Mapping[str, Any], *field_names: str) -> str:
    """Read a field from a contract's Implementation Snapshot: from the singular
    `implementation_snapshot` (the pre-acceptance proposal shape) if it carries the field,
    else from the first entry of `implementation_snapshots` (the accepted-contract shape).
    Checks each field name in `field_names` in priority order, mirroring `_first_fact`."""
    snapshot = contract.get("implementation_snapshot")
    if isinstance(snapshot, Mapping):
        value = _text_fact(_first_fact(snapshot, *field_names))
        if value:
            return value
    snapshots = contract.get("implementation_snapshots")
    if isinstance(snapshots, (list, tuple)) and snapshots:
        first_snapshot = snapshots[0]
        if isinstance(first_snapshot, Mapping):
            return _text_fact(_first_fact(first_snapshot, *field_names))
        return _text_fact(first_snapshot)
    return ""


def _contract_assembly_identity(contract: Mapping[str, Any]) -> str:
    """The assembly identity a contract was built from -- a top-level field on a hand-authored
    contract, or the field of the same name on its Implementation Snapshot for a decompiled
    one. Contract Onboarding never records this at the top level, only on the snapshot, so
    both places must be checked."""
    explicit = _text_fact(contract.get("assembly_identity"))
    if explicit:
        return explicit
    return _contract_snapshot_field(contract, "assembly_identity")


def _semantic_bound_method_facts(
    raw: Mapping[str, Any],
    method_facts: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[str, tuple[str, ...], bool]:
    """The bound method identity/parameter types to trust when matching a call against one
    specific contract candidate, and whether the compiler's binding was accepted for it.

    Symbol acceptance rule (ticket 06): a bound identity is trusted only when the call site
    carries a bound symbol *and* that symbol's own containing assembly identity equals the
    assembly identity this contract was actually built from. A rejected identity is discarded
    entirely -- both the method identity and its parameter types -- so contract matching falls
    back to the argument-count path exactly as if the compiler had not resolved a symbol at
    all. Never adopt a bound identity from an assembly the contract does not describe.
    """
    observed_method_identity = _text_fact(
        _first_fact(raw, "wrapper_method_identity", "method_identity")
    )
    if not observed_method_identity:
        return "", (), False
    bound_assembly_identity = _text_fact(
        _first_fact(raw, "wrapper_assembly_identity", "assembly_identity")
    )
    contract_assembly_identity = _contract_assembly_identity(contract)
    if (
        bound_assembly_identity
        and contract_assembly_identity
        and bound_assembly_identity.casefold() != contract_assembly_identity.casefold()
    ):
        return "", (), False
    return observed_method_identity, method_facts["parameter_types"], True


def _contract_identity_facts(contract: Mapping[str, Any]) -> Dict[str, str]:
    explicit_fingerprint = _text_fact(contract.get("contract_fingerprint"))
    fingerprint = explicit_fingerprint
    if not fingerprint:
        try:
            fingerprint = compute_contract_fingerprint(contract)
        except (TypeError, ValueError):
            fingerprint = ""
    signature_version = _text_fact(
        contract.get("signature_version")
        or contract.get("contract_signature_version")
        or CONTRACT_SIGNATURE_SCHEMA_VERSION
    )
    lifecycle = contract.get("lifecycle")
    lifecycle_status = _text_fact(contract.get("status"))
    if not lifecycle_status and isinstance(lifecycle, Mapping):
        lifecycle_status = _text_fact(lifecycle.get("status"))
    if not lifecycle_status:
        lifecycle_status = "accepted" if explicit_fingerprint else "legacy_unverified"
    snapshot_reference = _text_fact(
        contract.get("implementation_snapshot_reference")
        or contract.get("snapshot_reference")
    )
    if not snapshot_reference:
        snapshot_reference = _contract_snapshot_field(
            contract, "snapshot_identity", "artifact_identity"
        )
    report = contract.get("comparison_report")
    report_reference = _text_fact(
        contract.get("comparison_report_reference")
        or contract.get("comparison_report_ref")
    )
    if not report_reference:
        if isinstance(report, Mapping):
            report_reference = _text_fact(
                report.get("comparison_report_reference") or report.get("latest_reference")
            )
        else:
            report_reference = _text_fact(report)
    return {
        "contract_fingerprint": fingerprint,
        "signature_version": signature_version,
        "contract_lifecycle_status": lifecycle_status,
        "evidence_kind": _text_fact(contract.get("evidence_kind")),
        "implementation_snapshot_reference": snapshot_reference,
        "comparison_report_reference": report_reference,
    }


def _source_contract_conflict_facts(
    contract: Optional[Mapping[str, Any]],
    *,
    receiver_type: str,
    implementation_identity: str,
    wrapper_method: str,
    method_facts: Mapping[str, Any],
    source_semantics: str,
    source_sink: str,
) -> Dict[str, Any]:
    contract_receiver_identity = implementation_identity or receiver_type
    if not contract or not _wrapper_contract_receiver_matches(
        contract,
        contract_receiver_identity,
    ):
        return {}
    method_contract, _, _ = _wrapper_contract_method(
        contract,
        wrapper_method,
        method_identity=_text_fact(method_facts.get("method_identity")),
        method_arity=method_facts.get("method_arity"),
        parameter_types=method_facts.get("parameter_types", ()),
    )
    if method_contract is None:
        return {}
    contract_mode = _text_fact(method_contract.get("mode")).casefold()
    contract_semantics = {
        "inline_sql": "fixed_inline_sql",
        "stored_procedure": "fixed_stored_procedure",
        "call_site": "call_site",
    }.get(contract_mode, _normalize_wrapper_method_semantics(contract_mode))
    contract_sink = _known_terminal_sink(
        method_contract.get("sink") or method_contract.get("terminal_sink")
    ) or _text_fact(method_contract.get("sink") or method_contract.get("terminal_sink"))
    reasons: list[str] = []
    if source_semantics and contract_semantics and source_semantics != contract_semantics:
        reasons.append("method_semantics_conflict")
    if source_sink and contract_sink and _known_terminal_sink(source_sink) != contract_sink:
        reasons.append("terminal_sink_conflict")
    identity = _contract_identity_facts(contract)
    return {
        **identity,
        "source_contract_conflict": bool(reasons),
        "source_contract_conflict_reason": ";".join(reasons),
        "source_contract_semantics": contract_semantics,
        "source_contract_sink": contract_sink,
    }


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
        _text_fact(observation.get("contract_fingerprint")),
        _text_fact(
            observation.get("contract_signature_version")
            or observation.get("signature_version")
        ),
        _text_fact(
            observation.get("contract_lifecycle_status")
            or observation.get("contract_status")
        ),
        _text_fact(observation.get("implementation_snapshot_reference")),
        _text_fact(observation.get("comparison_report_reference")),
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


def _wrapper_contract_default_mode(candidate: Mapping[str, Any]) -> str:
    normalized = _text_fact(
        _first_fact(candidate, "default_mode", "default_command_type")
    ).casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"inline_sql", "text", "default_text"}:
        return "inline_sql"
    if normalized in {"stored_procedure", "storedprocedure"}:
        return "stored_procedure"
    return ""


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


_SQL_IDENTIFIER = r"(?:\[[^\]]+\]|[A-Za-z_][\w$]*)"
_EMBEDDED_EXEC_KEYWORD = re.compile(r"^EXEC(?:UTE)?\b", re.IGNORECASE)
_EMBEDDED_EXEC_TARGET = re.compile(
    rf"^(?P<target>{_SQL_IDENTIFIER}(?:\s*\.\s*{_SQL_IDENTIFIER})*)",
    re.IGNORECASE,
)


def _skip_sql_leading_trivia(text: str, start: int = 0) -> int:
    index = start
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            index = len(text) if comment_end < 0 else comment_end + 2
            continue
        break
    return index


def _iter_sql_exec_offsets(text: str) -> Iterable[int]:
    index = 0
    while index < len(text):
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            index = len(text) if comment_end < 0 else comment_end + 2
            continue
        if text[index] in {"'", '"'}:
            quote = text[index]
            index += 1
            while index < len(text):
                if text[index] == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if text[index] == "[":
            closing = text.find("]", index + 1)
            index = len(text) if closing < 0 else closing + 1
            continue
        keyword_match = _EMBEDDED_EXEC_KEYWORD.match(text[index:])
        if keyword_match is not None and (
            index == 0 or not (text[index - 1].isalnum() or text[index - 1] in "_$")
        ):
            yield index
            index += keyword_match.end()
            continue
        index += 1


def _parse_embedded_exec_target_at(
    raw_text: str,
    start: int,
) -> tuple[Optional[str], str]:
    keyword_match = _EMBEDDED_EXEC_KEYWORD.match(raw_text[start:])
    if keyword_match is None:
        return None, ""
    remainder = raw_text[start + keyword_match.end() :]
    remainder_start = _skip_sql_leading_trivia(remainder)
    remainder = remainder[remainder_start:]
    if re.match(r"AS\b", remainder, re.IGNORECASE):
        return None, "embedded_exec_as"
    target_match = _EMBEDDED_EXEC_TARGET.match(remainder)
    if target_match is None:
        return "", "embedded_exec_target_dynamic"
    return target_match.group("target"), ""


def _embedded_procedure_target(raw_text: str) -> tuple[Optional[str], str, str]:
    """The procedure name this inline SQL text executes, and how it named it.

    Returns ``(target, reason, target_source)``. ``target`` is ``None`` when the
    text names no procedure, ``""`` when it executes one it cannot name.
    """
    for start in _iter_sql_exec_offsets(raw_text):
        target, reason = _parse_embedded_exec_target_at(raw_text, start)
        if reason == "embedded_exec_as":
            continue
        return target, reason, "exec_keyword"
    implicit = _implicit_exec_target(raw_text)
    if implicit is not None:
        return implicit, "", "implicit_exec"
    return None, "", ""


def _implicit_exec_target(raw_text: str) -> Optional[str]:
    """The procedure name a command text executes without saying ``EXECUTE``.

    T-SQL runs a batch whose first statement is a bare procedure call with the
    keyword omitted, so a command text that is one possibly-qualified identifier
    and nothing else executes that identifier. Whitespace, comments, and one
    optional statement terminator surround it without changing that.

    "Nothing else" is the whole guard, and it is what keeps ordinary inline SQL
    untouched: a second token -- an argument, an operator, another statement --
    means this is not that shape, and no target is named.

    A lone word that is really a statement (`COMMIT`, `GO`) does fit the
    identifier shape, and is deliberately left to the catalog rating that every
    candidate goes through: no database defines a procedure called `commit`, so
    it rates `not_in_resolved_catalog` and answers nothing. A denylist here would
    be a second rule competing with the catalog, and one that could never be
    complete.
    """
    body = raw_text[_skip_sql_leading_trivia(raw_text) :]
    match = _EMBEDDED_EXEC_TARGET.match(body)
    if match is None:
        return None
    remainder = body[match.end() :]
    remainder = remainder[_skip_sql_leading_trivia(remainder) :]
    if remainder.startswith(";"):
        remainder = remainder[1:]
        remainder = remainder[_skip_sql_leading_trivia(remainder) :]
    if remainder.strip():
        return None
    return match.group("target")


def _leading_sql_statement(raw_text: str) -> str:
    start = _skip_sql_leading_trivia(raw_text)
    match = re.match(r"([A-Za-z]+)\b", raw_text[start:])
    return match.group(1).casefold() if match else ""


def _procedure_name_hint(raw_text: str) -> Optional[str]:
    normalized = normalize_procedure_name(raw_text)
    bare = raw_text.strip().replace("[", "").replace("]", "").split(".")[-1]
    if bare.casefold().startswith(("sp", "usp", "proc")):
        return normalized
    return None


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
        connection_sources: Optional[Dict[str, Any]] = None,
        external_wrapper_contract: Optional[Mapping[str, Any]] = None,
        external_wrapper_contracts: Optional[Mapping[str, Any]] = None,
        wrapper_review_exclusions: Optional[Iterable[Mapping[str, Any]]] = None,
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
        self._wrapper_review_exclusions = _normalize_wrapper_review_exclusions(
            wrapper_review_exclusions
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

    def _wrapper_review_exclusion_reason(self, receiver_type: str, wrapper_method: str) -> str:
        return self._wrapper_review_exclusions.get(
            (
                str(receiver_type or "").strip().casefold(),
                str(wrapper_method or "").strip().casefold(),
            ),
            "",
        )

    def reconcile_wrapper(
        self,
        relative_path: str,
        raw: Mapping[str, Any],
        *,
        scan_root: str = "",
        source_wrapper_available: Optional[bool] = None,
        explicit_contract: Optional[Mapping[str, Any] | str | List[str] | tuple[str, ...]] = None,
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
        source_contract: Optional[Mapping[str, Any]] = None
        if explicit_contract is None:
            source_contract = self._external_wrapper_contract or None
        elif isinstance(explicit_contract, str):
            source_contract = self._load_contract(explicit_contract)
        elif isinstance(explicit_contract, Mapping):
            source_contract = explicit_contract
        source_contract_facts = _source_contract_conflict_facts(
            source_contract,
            receiver_type=receiver_type,
            implementation_identity=binding["implementation_identity"],
            wrapper_method=wrapper_method,
            method_facts=method_facts,
            source_semantics=method_semantics,
            source_sink=source_sink,
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
            semantic_binding_accepted: bool = False,
            stored_procedure_mode: bool = False,
            mode_reason: str = "",
            contract_identity_facts: Optional[Mapping[str, Any]] = None,
        ) -> WrapperReconciliation:
            identity = dict(contract_identity_facts or {})
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
                semantic_binding_accepted=semantic_binding_accepted,
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
                contract_fingerprint=_text_fact(identity.get("contract_fingerprint")),
                contract_signature_version=_text_fact(
                    identity.get("signature_version")
                    or identity.get("contract_signature_version")
                ),
                contract_lifecycle_status=_text_fact(
                    identity.get("contract_lifecycle_status")
                    or identity.get("contract_status")
                ),
                evidence_kind=_text_fact(identity.get("evidence_kind")),
                implementation_snapshot_reference=_text_fact(
                    identity.get("implementation_snapshot_reference")
                ),
                comparison_report_reference=_text_fact(
                    identity.get("comparison_report_reference")
                ),
                source_contract_conflict=bool(identity.get("source_contract_conflict")),
                source_contract_conflict_reason=_text_fact(
                    identity.get("source_contract_conflict_reason")
                ),
                source_contract_semantics=_text_fact(
                    identity.get("source_contract_semantics")
                ),
                source_contract_sink=_text_fact(identity.get("source_contract_sink")),
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

        exclusion_reason = self._wrapper_review_exclusion_reason(receiver_type, wrapper_method)
        if exclusion_reason:
            return result(
                wrapper_kind="external_wrapper",
                status="not_applicable",
                selection_source="reviewed_exclusion",
                reason=exclusion_reason,
                review_candidate=False,
            )

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
                    contract_identity_facts=source_contract_facts,
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
                    contract_identity_facts=source_contract_facts,
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
                contract_identity_facts=source_contract_facts,
            )

        explicit_name = ""
        explicit_names: tuple[str, ...] = ()
        explicit_selected = False
        explicit_missing = False
        selected_contract: Optional[Mapping[str, Any]] = None
        selected_contracts: list[Mapping[str, Any]] = []
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
        elif isinstance(explicit_contract, (list, tuple)):
            names = sorted(
                {
                    str(item).strip()
                    for item in explicit_contract
                    if isinstance(item, str) and str(item).strip()
                },
                key=str.casefold,
            )
            explicit_names = tuple(names)
            explicit_selected = bool(explicit_names)
            for name in explicit_names:
                contract = self._load_contract(name)
                if contract is None:
                    explicit_missing = True
                else:
                    selected_contracts.append(contract)

        attempted_sp_mode = raw_mode == "stored_procedure"
        if explicit_selected and (
            selected_contract is None and not selected_contracts
            or explicit_missing
        ):
            return result(
                wrapper_kind="external_wrapper",
                status="unresolved_contract",
                selection_source="explicit",
                candidate_contracts=explicit_names or (explicit_name,),
                reason="configured_contract_not_found",
                review_candidate=True,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
            )

        # Contract selection has one legitimate source: an explicit system
        # selector. Receiver implementation binding remains provenance and
        # cannot define a registry-wide candidate boundary.
        if explicit_selected:
            candidates = selected_contracts or [
                candidate for candidate in (selected_contract,) if candidate is not None
            ]
            selection_source = "explicit"
        else:
            candidates = []
            selection_source = "unresolved_receiver_type"

        selected_candidate_names = tuple(
            str(candidate.get("name") or "").strip()
            for candidate in candidates
            if str(candidate.get("name") or "").strip()
        )
        if explicit_names and len(candidates) > 1:
            contract_receiver_identity = binding["implementation_identity"] or receiver_type
            receiver_matches = [
                candidate
                for candidate in candidates
                if _wrapper_contract_receiver_matches(
                    candidate,
                    contract_receiver_identity,
                )
            ]
            if not receiver_matches:
                return result(
                    wrapper_kind="external_wrapper",
                    status="receiver_mismatch",
                    selection_source="explicit",
                    candidate_contracts=selected_candidate_names,
                    reason="receiver_type_does_not_match_contract",
                    review_candidate=True,
                    stored_procedure_mode=attempted_sp_mode,
                    mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
                )
            if len(receiver_matches) > 1:
                method_matches: list[Mapping[str, Any]] = []
                for candidate in receiver_matches:
                    candidate_identity, candidate_parameter_types, _ = (
                        _semantic_bound_method_facts(raw, method_facts, candidate)
                    )
                    method_contract, _, _ = _wrapper_contract_method(
                        candidate,
                        wrapper_method,
                        method_identity=candidate_identity,
                        method_arity=method_facts["method_arity"],
                        parameter_types=candidate_parameter_types,
                    )
                    if method_contract is not None:
                        method_matches.append(candidate)
                if method_matches:
                    candidates = method_matches
                else:
                    return result(
                        wrapper_kind="external_wrapper",
                        status="unresolved_method",
                        selection_source="explicit",
                        candidate_contracts=tuple(
                            str(candidate.get("name") or "").strip()
                            for candidate in receiver_matches
                            if str(candidate.get("name") or "").strip()
                        ),
                        reason="method_not_in_contract",
                        review_candidate=True,
                        stored_procedure_mode=attempted_sp_mode,
                        mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
                    )
            else:
                candidates = receiver_matches
        candidate_names = tuple(
            str(candidate.get("name") or "").strip()
            for candidate in candidates
            if str(candidate.get("name") or "").strip()
        )
        if len(candidates) > 1:
            return result(
                wrapper_kind="external_wrapper",
                status="ambiguous_contract",
                selection_source=(
                    "explicit" if explicit_selected else "ambiguous_receiver_type"
                ),
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
        contract_identity_facts = _contract_identity_facts(contract)
        contract_receiver_identity = binding["implementation_identity"] or receiver_type
        if not _wrapper_contract_receiver_matches(contract, contract_receiver_identity):
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
                contract_identity_facts=contract_identity_facts,
            )

        observed_method_identity, observed_parameter_types, semantic_binding_accepted = (
            _semantic_bound_method_facts(raw, method_facts, contract)
        )
        method_contract, method_reason, method_candidates = _wrapper_contract_method(
            contract,
            wrapper_method,
            method_identity=observed_method_identity,
            method_arity=method_facts["method_arity"],
            parameter_types=observed_parameter_types,
            command_type_mode_observed=bool(raw.get("command_type_argument_observed")),
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
                semantic_binding_accepted=semantic_binding_accepted,
                stored_procedure_mode=attempted_sp_mode,
                mode_reason="" if attempted_sp_mode else "wrapper_mode_unresolved",
                contract_identity_facts=contract_identity_facts,
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
        elif contract_mode_key == "call_site" and raw_mode in {"", "default_text"}:
            default_mode = _wrapper_contract_default_mode(method_contract)
            if default_mode == "inline_sql":
                stored_procedure_mode = False
                mode_reason = "inline_sql"
            elif default_mode == "stored_procedure":
                stored_procedure_mode = True
                mode_reason = ""
            else:
                stored_procedure_mode = False
                mode_reason = "call_site_requires_explicit_stored_procedure_mode"
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

        # Every remaining candidate agreed on mode/sink (e.g. CreateReader's
        # SqlParameter vs SqlParameter[] siblings), so database evidence can
        # still be rated -- but the exact overload identity was never
        # confirmed, so this must stay a visible review candidate, not a
        # silent "explicit_selected" match.
        overload_identity_ambiguous = method_reason == "ambiguous_overload_mode_resolved"
        return result(
            wrapper_kind="external_wrapper",
            status="ambiguous_overload" if overload_identity_ambiguous else "explicit_selected",
            selection_source=selection_source,
            contract=contract_name,
            contract_mode=contract_mode,
            contract_sink=str(method_contract.get("sink") or ""),
            candidate_contracts=candidate_names,
            overload_candidates=method_candidate_names if overload_identity_ambiguous else None,
            overload_candidate_facts=(
                tuple(_wrapper_candidate_fact(candidate) for candidate in method_candidates)
                if overload_identity_ambiguous
                else None
            ),
            stored_procedure_mode=stored_procedure_mode,
            mode_reason=mode_reason,
            reason="ambiguous_overload_mode_resolved" if overload_identity_ambiguous else "",
            review_candidate=overload_identity_ambiguous,
            semantic_binding_accepted=semantic_binding_accepted,
            contract_identity_facts=contract_identity_facts,
        )

    def resolve_direct_invocations(
        self,
        relative_path: str,
        raw_invocations: List[dict],
        *,
        scan_root: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str | List[str] | tuple[str, ...]] = None,
    ) -> List[DbInvocation]:
        """Turn raw Roslyn direct-SqlClient facts into evidence-rated Database Invocations."""
        results: List[DbInvocation] = []
        for raw in raw_invocations:
            for candidate_raw in self._expand_command_text_candidates(raw):
                candidate_raw.setdefault("relative_path", relative_path)
                invocation = self._resolve_one(
                    relative_path,
                    candidate_raw,
                    scan_root=scan_root,
                    explicit_contract=explicit_contract,
                )
                if invocation is not None:
                    results.append(invocation)
        return results

    @staticmethod
    def _expand_command_text_candidates(raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
        base = dict(raw)
        candidate_values = None
        for key in (
            "command_text_candidates",
            "command_text_assignments",
            "value_candidates",
        ):
            if key in base:
                candidate_values = base.get(key)
                break
        if not isinstance(candidate_values, (list, tuple)) or not candidate_values:
            return [base]

        expanded: List[Dict[str, Any]] = []
        for candidate in candidate_values:
            merged = dict(base)
            for key in (
                "command_text_candidates",
                "command_text_assignments",
                "value_candidates",
            ):
                merged.pop(key, None)
            if isinstance(candidate, Mapping):
                candidate_values_map = dict(candidate)
                if "command_text" not in candidate_values_map:
                    candidate_values_map["command_text"] = candidate_values_map.get(
                        "value"
                    )
                if "command_text_kind" not in candidate_values_map:
                    candidate_values_map["command_text_kind"] = (
                        "literal"
                        if candidate_values_map.get("command_text") is not None
                        else "dynamic"
                    )
                if "branch_context" not in candidate_values_map:
                    predicate = candidate_values_map.get(
                        "predicate", candidate_values_map.get("branch_predicate")
                    )
                    if predicate is not None:
                        candidate_values_map["branch_context"] = [predicate]
                if "command_text_source_span" not in candidate_values_map:
                    source_span = candidate_values_map.get("source_span")
                    if source_span is not None:
                        candidate_values_map["command_text_source_span"] = source_span
                if "command_text_provenance" not in candidate_values_map:
                    provenance = candidate_values_map.get("provenance")
                    if provenance is not None:
                        candidate_values_map["command_text_provenance"] = provenance
                merged.update(candidate_values_map)
            else:
                merged["command_text_kind"] = "literal"
                merged["command_text"] = candidate
            has_source_span = any(
                key in merged
                for key in (
                    "command_text_source_span",
                    "value_source_span",
                    "source_span",
                    "command_text_source_start_offset",
                )
            )
            has_provenance = any(
                str(merged.get(key) or "").strip()
                for key in (
                    "command_text_provenance",
                    "value_provenance",
                    "command_text_value_provenance",
                )
            )
            if not has_source_span or not has_provenance:
                merged["command_text_kind"] = "dynamic"
                merged["command_text"] = None
                merged["command_text_provenance"] = "candidate_provenance_incomplete"
                merged["command_text_source_span"] = {
                    "relative_path": merged.get("relative_path") or merged.get("source_file") or "",
                    "start_offset": merged.get("start_offset") or 0,
                    "end_offset": merged.get("end_offset") or 0,
                }
            expanded.append(merged)
        return expanded

    def reconcile_wrapper_observation(
        self,
        relative_path: str,
        raw: Mapping[str, Any],
        *,
        scan_root: str = "",
        source_snapshot_hash: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str | List[str] | tuple[str, ...]] = None,
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
        explicit_contract: Optional[Mapping[str, Any] | str | List[str] | tuple[str, ...]] = None,
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
        database, server = self._resolve_database(connection_expression)
        metadata = self._invocation_metadata(
            raw,
            database=database,
            server=server,
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
        if not _known_terminal_sink(metadata["terminal_sink"]):
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
        database, server = self._resolve_database(raw.get("connection_expression"))
        command_type_mode = str(raw.get("command_type_mode") or "").casefold()
        command_text_value = str(command_text or "")
        explicit_text_mode = (
            command_type_mode in {"text", "default_text", "inline_sql"}
            or raw.get("command_type_stored_procedure") is False
            or str(raw.get("method_semantics") or "").casefold()
            in {"fixed_inline_sql", "inline_sql", "text"}
        )
        known_inline_text = command_type_mode != "unknown" and (
            explicit_text_mode
            or _leading_sql_statement(command_text_value)
            in {"select", "insert", "update", "delete", "merge", "exec", "execute"}
        )
        inline_method_semantics = "fixed_inline_sql" if known_inline_text else "unresolved"
        inline_invocation_mode = "inline_sql" if known_inline_text else "unresolved"
        metadata = self._invocation_metadata(
            raw,
            database=database,
            server=server,
            method_semantics=inline_method_semantics,
            invocation_mode=inline_invocation_mode,
        )
        embedded_target = (
            self._rate_embedded_target(
                command_text_value,
                database,
                self._connection_source_unresolved_reason(raw),
            )
            if known_inline_text
            and command_text_kind == "literal"
            and command_text_value.strip()
            else None
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
                embedded_target=embedded_target,
                **metadata,
            )
        if not _known_terminal_sink(metadata["terminal_sink"]):
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
                embedded_target=embedded_target,
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

        if not known_inline_text:
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "procedure_prefix_without_mode"
                if _procedure_name_hint(command_text_value)
                else "command_type_unresolved",
                branch_context=branch_context,
                raw_command_text=command_text_value,
                procedure_name_hint=_procedure_name_hint(command_text_value),
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
            embedded_target=embedded_target,
            **metadata,
        )

    def _rate_embedded_target(
        self,
        command_text: str,
        database: Optional[str],
        connection_resolution_reason: str = "",
    ) -> Optional[EmbeddedProcedureTarget]:
        raw_target, extraction_reason, target_source = _embedded_procedure_target(command_text)
        if raw_target is None:
            return None
        if not raw_target:
            return EmbeddedProcedureTarget(
                None,
                None,
                database,
                InvocationEvidence.UNRESOLVED,
                extraction_reason,
                target_source=target_source,
            )

        normalized_name = normalize_procedure_name(raw_target)
        procedure_schema = normalize_procedure_schema(raw_target)
        if database:
            if self._catalog.contains(database, normalized_name, procedure_schema):
                return EmbeddedProcedureTarget(
                    normalized_name,
                    procedure_schema,
                    database,
                    InvocationEvidence.PROVEN,
                    "catalog_match",
                    raw_target=raw_target,
                    target_source=target_source,
                )
            return EmbeddedProcedureTarget(
                normalized_name,
                procedure_schema,
                database,
                InvocationEvidence.UNRESOLVED,
                "not_in_resolved_catalog",
                raw_target=raw_target,
                target_source=target_source,
            )

        matches = self._catalog.databases_containing(normalized_name, procedure_schema)
        if connection_resolution_reason:
            return EmbeddedProcedureTarget(
                normalized_name,
                procedure_schema,
                None,
                InvocationEvidence.UNRESOLVED,
                connection_resolution_reason,
                database_candidates=tuple(matches),
                raw_target=raw_target,
                target_source=target_source,
            )
        if len(matches) == 1:
            return EmbeddedProcedureTarget(
                normalized_name,
                procedure_schema,
                None,
                InvocationEvidence.LIKELY,
                "unique_across_catalogs",
                database_candidates=tuple(matches),
                raw_target=raw_target,
                target_source=target_source,
            )
        return EmbeddedProcedureTarget(
            normalized_name,
            procedure_schema,
            None,
            InvocationEvidence.UNRESOLVED,
            "unknown_database_source" if not matches else "ambiguous_cross_database",
            database_candidates=tuple(matches),
            raw_target=raw_target,
            target_source=target_source,
        )

    def _invocation_metadata(
        self,
        raw: Mapping[str, Any],
        *,
        database: Optional[str],
        method_semantics: str,
        invocation_mode: str,
        server: Optional[str] = None,
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

        command_text_source = raw.get("command_text_source_span")
        if command_text_source is None:
            command_text_source = raw.get("value_source_span")
        if command_text_source is None and (
            raw.get("command_text_source_start_offset") is not None
            or raw.get("command_text_source_end_offset") is not None
        ):
            command_text_source = {
                "relative_path": raw.get("relative_path") or raw.get("source_file") or "",
                "start_offset": raw.get("command_text_source_start_offset"),
                "end_offset": raw.get("command_text_source_end_offset"),
            }
        if isinstance(command_text_source, Mapping):
            command_text_source_span = InvocationSourceSpan(
                str(
                    command_text_source.get("relative_path")
                    or command_text_source.get("path")
                    or raw.get("relative_path")
                    or raw.get("source_file")
                    or ""
                ),
                int(
                    command_text_source.get("start_offset")
                    or command_text_source.get("start")
                    or 0
                ),
                int(
                    command_text_source.get("end_offset")
                    or command_text_source.get("end")
                    or 0
                ),
            )
        else:
            command_text_source_span = None
        command_text_provenance = str(
            raw.get("command_text_provenance")
            or raw.get("value_provenance")
            or raw.get("command_text_value_provenance")
            or raw.get("provenance")
            or ""
        )

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
            "terminal_sink": (
                _known_terminal_sink(
                    raw.get("terminal_sink")
                    or raw.get("wrapper_terminal_sink")
                    or ""
                )
                or str(
                    raw.get("terminal_sink")
                    or raw.get("wrapper_terminal_sink")
                    or ""
                ).strip()
            ),
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
            "server": server,
            "provenance": str(raw.get("provenance") or "static_analyzer_host"),
            "command_text_source": command_text_source_span,
            "command_text_provenance": command_text_provenance,
        }

    def _resolve_adapter_invocation(self, relative_path: str, raw: dict) -> Optional[DbInvocation]:
        mode = str(raw.get("adapter_mode") or raw.get("wrapper_mode") or "").casefold()
        source = InvocationSourceSpan(relative_path, raw["start_offset"], raw["end_offset"])
        class_name = raw["class_name"]
        method_name = raw["method_name"]
        branch_context = self._branch_context(raw)
        database, server = self._resolve_database(raw.get("connection_expression"))
        method_chain = tuple(raw.get("method_chain") or ())
        metadata_raw = dict(raw)
        if not _text_fact(metadata_raw.get("command_type_mode")):
            metadata_raw["command_type_mode"] = {
                "inline_sql": "text",
                "stored_procedure": "stored_procedure",
            }.get(mode, "unknown")
        if mode == "inline_sql":
            metadata = self._invocation_metadata(
                metadata_raw,
                database=database,
                server=server,
                method_semantics="fixed_inline_sql",
                invocation_mode="inline_sql",
            )
            embedded_target = (
                self._rate_embedded_target(
                    str(raw["command_text"]),
                    database,
                    self._connection_source_unresolved_reason(raw),
                )
                if raw.get("command_text_kind") == "literal"
                and raw.get("command_text")
                else None
            )
            if not _known_terminal_sink(metadata["terminal_sink"]):
                return DbInvocation(
                    class_name,
                    method_name,
                    database,
                    None,
                    InvocationEvidence.UNRESOLVED,
                    source,
                    "terminal_sink_unresolved",
                    method_chain=method_chain,
                    branch_context=branch_context,
                    embedded_target=embedded_target,
                    **metadata,
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
                    method_chain=method_chain,
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
                method_chain=method_chain,
                branch_context=branch_context,
                raw_command_text=str(raw["command_text"]),
                embedded_target=embedded_target,
                **metadata,
            )
        if mode != "stored_procedure":
            metadata = self._invocation_metadata(
                metadata_raw,
                database=database,
                server=server,
                method_semantics="unresolved",
                invocation_mode="unresolved",
            )
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "adapter_mode_unresolved",
                method_chain=method_chain,
                branch_context=branch_context,
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
            )
        metadata = self._invocation_metadata(
            metadata_raw,
            database=database,
            server=server,
            method_semantics="fixed_stored_procedure",
            invocation_mode="stored_procedure",
        )
        if not _known_terminal_sink(metadata["terminal_sink"]):
            return DbInvocation(
                class_name,
                method_name,
                database,
                None,
                InvocationEvidence.UNRESOLVED,
                source,
                "terminal_sink_unresolved",
                method_chain=method_chain,
                branch_context=branch_context,
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **metadata,
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
                method_chain=method_chain,
                branch_context=branch_context,
                **metadata,
            )
        return self._rate_literal_candidate(
            class_name,
            method_name,
            database,
            raw["command_text"],
            source,
            method_chain=method_chain,
            branch_context=branch_context,
            connection_resolution_reason=self._connection_source_unresolved_reason(raw),
            metadata=metadata,
        )

    def _resolve_wrapper_invocation(
        self,
        relative_path: str,
        raw: dict,
        *,
        scan_root: str = "",
        explicit_contract: Optional[Mapping[str, Any] | str | List[str] | tuple[str, ...]] = None,
    ) -> Optional[DbInvocation]:
        reconciliation = self.reconcile_wrapper(
            relative_path,
            raw,
            scan_root=scan_root,
            explicit_contract=explicit_contract,
        )
        if reconciliation.status == "not_applicable":
            return None
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
        database, server = self._resolve_database(raw.get("connection_expression"))
        source_available = reconciliation.source_available
        external_wrapper_method = (
            reconciliation.wrapper_method if not source_available else ""
        )

        def annotate(invocation: DbInvocation) -> DbInvocation:
            embedded_target = invocation.embedded_target
            if (
                embedded_target is None
                and (
                    invocation.invocation_mode == "inline_sql"
                    or reconciliation.mode_reason == "inline_sql"
                )
                and invocation.raw_command_text
            ):
                embedded_target = self._rate_embedded_target(
                    invocation.raw_command_text,
                    database,
                    self._connection_source_unresolved_reason(raw),
                )
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
                contract_fingerprint=reconciliation.contract_fingerprint,
                contract_signature_version=reconciliation.contract_signature_version,
                contract_lifecycle_status=reconciliation.contract_lifecycle_status,
                evidence_kind=reconciliation.evidence_kind,
                implementation_snapshot_reference=reconciliation.implementation_snapshot_reference,
                comparison_report_reference=reconciliation.comparison_report_reference,
                source_contract_conflict=reconciliation.source_contract_conflict,
                source_contract_conflict_reason=reconciliation.source_contract_conflict_reason,
                source_contract_semantics=reconciliation.source_contract_semantics,
                source_contract_sink=reconciliation.source_contract_sink,
                embedded_target=embedded_target,
            )

        common = {
            "method_chain": tuple(raw.get("method_chain") or ()),
            "method_class_chain": method_class_chain,
            "branch_context": branch_context,
        }

        if not source_available:
            overload_identity_ambiguous = reconciliation.reason == "ambiguous_overload_mode_resolved"
            if reconciliation.status == "ambiguous_overload" and not overload_identity_ambiguous:
                metadata = self._invocation_metadata(
                    raw,
                    database=database,
                    server=server,
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
            if reconciliation.status == "explicit_selected" or overload_identity_ambiguous:
                if not _known_terminal_sink(raw.get("terminal_sink")):
                    metadata = self._invocation_metadata(
                        raw,
                        database=database,
                        server=server,
                        method_semantics=reconciliation.method_semantics,
                        invocation_mode=(
                            "inline_sql"
                            if reconciliation.mode_reason == "inline_sql"
                            else "unresolved"
                        ),
                    )
                    return annotate(DbInvocation(
                        class_name,
                        method_name,
                        database,
                        None,
                        InvocationEvidence.UNRESOLVED,
                        source,
                        "wrapper_contract_sink_unresolved",
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
                    if reconciliation.mode_reason != "inline_sql":
                        metadata = self._invocation_metadata(
                            raw,
                            database=database,
                            server=server,
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
                    metadata = self._invocation_metadata(
                        raw,
                        database=database,
                        server=server,
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
                        server=server,
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
                        server=server,
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
                    server=server,
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
                server=server,
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
                raw_command_text=(
                    str(raw["command_text"])
                    if raw.get("command_text_kind") == "literal"
                    and raw.get("command_text")
                    else None
                ),
                **self._invocation_metadata(
                    raw,
                    database=database,
                    server=server,
                    method_semantics=reconciliation.method_semantics,
                    invocation_mode="unresolved",
                ),
                **common,
            ))
        if reconciliation.mode_reason == "wrapper_mode_unresolved":
            metadata = self._invocation_metadata(
                raw,
                database=database,
                server=server,
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
                server=server,
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
                server=server,
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
                server=server,
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

    def _resolve_database(
        self, connection_expression: object
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve a connection expression to its (database, server) pair.

        ``self._connection_sources`` values may be a plain database-name string
        (the legacy shape, still accepted so every existing caller keeps
        working unchanged) or a ``{"database": ..., "server": ...}`` mapping
        produced by the Web.config connection-string resolver -- in which case
        the server travels alongside the database instead of being dropped.
        """
        if not connection_expression:
            return None, None
        expression = str(connection_expression).strip()
        if not expression:
            return None, None
        if expression in self._connection_sources:
            entry = self._connection_sources[expression]
        else:
            folded = expression.casefold()
            entry = next(
                (
                    value
                    for key, value in self._connection_sources.items()
                    if str(key).casefold() == folded
                ),
                None,
            )
        if isinstance(entry, Mapping):
            database = entry.get("database")
            server = entry.get("server")
        else:
            database = entry
            server = None
        if not database or str(database).strip().casefold() in {"unknown", "unresolved"}:
            return None, None
        server_text = str(server).strip() if server else None
        return str(database).strip(), (server_text or None)

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

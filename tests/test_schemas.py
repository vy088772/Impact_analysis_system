"""Regression guard for the shared wrapper-evidence base model (ticket 04 of
`.scratch/collapse-wrapper-evidence-aliases/`).
"""

from __future__ import annotations

from service.schemas import (
    PathEvidenceResponse,
    SPMatchProgram,
    TableMatchProgram,
    WrapperEvidenceFields,
)

# The 20 wrapper-evidence alias names ticket 02 dropped, plus the `evidence`
# key ticket 03 dropped.
_DROPPED_WRAPPER_EVIDENCE_ALIASES = {
    "wrapper_status",
    "wrapper_classification_status",
    "classification_status",
    "wrapper_selection_source",
    "wrapper_contract",
    "selected_contract",
    "wrapper_contract_mode",
    "wrapper_contract_sink",
    "wrapper_contract_candidates",
    "candidate_contract_names",
    "wrapper_scan_root",
    "wrapper_source_available",
    "wrapper_review_candidate",
    "wrapper_unresolved_reason",
    "wrapper_mode_reason",
    "observed_method",
    "wrapper_stored_procedure_mode",
    "signature_version",
    "contract_status",
    "source_snapshot_identity",
    "evidence",
}

_RESPONSE_SCHEMAS = (PathEvidenceResponse, SPMatchProgram, TableMatchProgram)

# The 17 canonical fields the spec's table collapses the alias groups to.
_CANONICAL_WRAPPER_EVIDENCE_FIELDS = {
    "status",
    "selection_source",
    "contract",
    "contract_mode",
    "contract_sink",
    "candidate_contracts",
    "scan_root",
    "source_available",
    "review_candidate",
    "classification_reason",
    "mode_reason",
    "wrapper_method",
    "stored_procedure_mode",
    "evidence_status",
    "contract_signature_version",
    "contract_lifecycle_status",
    "source_snapshot_hash",
}


def test_response_schemas_inherit_shared_wrapper_evidence_base() -> None:
    for schema in _RESPONSE_SCHEMAS:
        assert issubclass(schema, WrapperEvidenceFields)


def test_wrapper_evidence_fields_declares_all_17_canonical_names_once() -> None:
    assert _CANONICAL_WRAPPER_EVIDENCE_FIELDS <= set(WrapperEvidenceFields.model_fields)


def test_response_schemas_drop_all_20_wrapper_evidence_aliases() -> None:
    for schema in _RESPONSE_SCHEMAS:
        assert _DROPPED_WRAPPER_EVIDENCE_ALIASES.isdisjoint(schema.model_fields)


def test_response_schemas_keep_declared_dual_fact_pairs() -> None:
    # receiver_type/wrapper_receiver_type and external_wrapper_method/
    # wrapper_method are two independent facts, not aliases — both names
    # must remain declared on every response schema that had them before.
    for schema in _RESPONSE_SCHEMAS:
        fields = set(schema.model_fields)
        assert {"receiver_type", "wrapper_receiver_type"} <= fields
        assert {"external_wrapper_method", "wrapper_method"} <= fields


def test_dual_fact_pairs_hold_independent_values_on_the_same_response() -> None:
    response = SPMatchProgram(
        receiver_type="SQLObject",
        wrapper_receiver_type="LegacyWrapper",
        external_wrapper_method="Save",
        wrapper_method="ExeProcNon",
    )

    assert response.receiver_type == "SQLObject"
    assert response.wrapper_receiver_type == "LegacyWrapper"
    assert response.external_wrapper_method == "Save"
    assert response.wrapper_method == "ExeProcNon"

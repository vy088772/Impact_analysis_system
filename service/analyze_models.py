"""The structured records emitted by Analyze, independent of other endpoints."""

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_serializer

InvocationRating = Literal["proven", "likely", "unresolved"]
WrapperRating = Literal["proven", "likely", "unresolved", "not_applicable"]


class AnalyzeRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", serialize_by_alias=True)


class OmissibleRecord(AnalyzeRecord):
    @model_serializer(mode="wrap")
    def serialize_present_fields(self, handler):
        data = handler(self)
        for name, field in type(self).model_fields.items():
            if name not in self.model_fields_set:
                data.pop(field.serialization_alias or field.alias or name, None)
        return data


class Method(OmissibleRecord):
    name: str
    class_: str = Field(alias="class")
    strength: Literal["determined", "likely"] = "determined"


class Snippet(AnalyzeRecord):
    model_config = ConfigDict(from_attributes=True)

    file: str
    label: str
    lines: str
    text: str


class Definition(AnalyzeRecord):
    name: str
    exists: bool
    definition: str
    truncated: bool


class ProcedureDefinition(Definition):
    parameters: list[str]
    tables: list[str]
    dependency_source: str
    complexity: str


class FunctionDefinition(Definition):
    parameters: list[str]
    return_type: str


class RelatedProgram(OmissibleRecord):
    file: str
    class_: str = Field(alias="class")
    method: str
    called_by: str
    depth: int
    lines: str = ""
    snippet: str = ""


class SourceSpan(OmissibleRecord):
    relative_path: str
    start_offset: int
    end_offset: int
    content_hash: str = ""


class SourceProvenance(AnalyzeRecord):
    selection_source: str
    source_available: bool
    scan_root: str
    source_span: SourceSpan
    source_snapshot_hash: str
    source_snapshot_identity: str


class OverloadCandidate(OmissibleRecord):
    method_name: str
    method_identity: str = ""
    implementation_identity: str = ""
    receiver_type: str = ""
    method_arity: int | None = None
    parameter_types: list[str] = Field(default_factory=list, strict=False)


class EmbeddedTarget(AnalyzeRecord):
    procedure_name: str | None
    procedure_schema: str | None
    database: str | None
    database_candidates: list[str]
    evidence: InvocationRating
    evidence_status: InvocationRating
    reason: str
    raw_target: str
    target_source: str


class WrapperEvidence(AnalyzeRecord):
    wrapper_kind: str
    status: str
    selection_source: str
    contract: str
    wrapper_contract_source: str
    contract_mode: str
    contract_sink: str
    candidate_contracts: list[str]
    wrapper_receiver_type: str
    receiver_type: str
    scan_root: str
    source_available: bool
    review_candidate: bool
    classification_reason: str
    mode_reason: str
    wrapper_method: str
    external_wrapper_method: str
    stored_procedure_mode: bool
    active_contract: bool
    evidence_status: WrapperRating
    evidence_reason: str
    source_span: SourceSpan
    source_snapshot_hash: str
    source_provenance: SourceProvenance
    method_semantics: str
    invocation_mode: str
    command_text_kind: str
    command_type_mode: str
    command_text_argument: str
    command_text_literal: str | None
    command_text_source_span: SourceSpan | None
    command_text_provenance: str
    literal_value: str | None
    terminal_sink: str
    embedded_target: EmbeddedTarget | None
    embedded_targets: list[EmbeddedTarget]
    embedded_procedure_name: str | None
    embedded_procedure_schema: str | None
    embedded_procedure_evidence: InvocationRating | None
    procedure_name_hint: str | None
    receiver_name: str
    connection_expression: str
    connection_expression_candidates: list[str]
    connection_source: str | None
    provenance: str
    implementation_identity: str
    assembly_identity: str
    assembly_revision: str
    method_identity: str
    method_arity: int | None
    parameter_types: list[str]
    overload_candidates: list[str]
    overload_candidate_facts: list[OverloadCandidate]
    receiver_expression: str
    binding_provenance: str
    receiver_construction_facts: list[str]
    receiver_assignment_facts: list[str]
    wrapper_implementation_identity: str
    wrapper_assembly_identity: str
    wrapper_assembly_revision: str
    wrapper_method_identity: str
    wrapper_method_arity: int | None
    wrapper_parameter_types: list[str]
    wrapper_method_semantics: str
    wrapper_overload_candidates: list[str]
    wrapper_overload_candidate_facts: list[OverloadCandidate]
    contract_fingerprint: str
    contract_signature_version: str
    contract_lifecycle_status: str
    evidence_kind: str
    implementation_snapshot_reference: str
    comparison_report_reference: str
    source_contract_conflict: bool
    source_contract_conflict_reason: str
    source_contract_semantics: str
    source_contract_sink: str
    contract_delegation_alias: str


class SharedComponentLabel(AnalyzeRecord):
    kind: Literal["view_component"]
    name: str


class FullWrapperEvidence(WrapperEvidence):
    wrapper_status: str
    wrapper_classification_status: str
    classification_status: str
    wrapper_selection_source: str
    selected_contract: str
    wrapper_contract_mode: str
    wrapper_contract_sink: str
    wrapper_contract_delegation_alias: str
    candidate_contract_names: list[str]
    wrapper_scan_root: str
    wrapper_source_available: bool
    wrapper_review_candidate: bool
    semantic_binding_accepted: bool
    wrapper_unresolved_reason: str
    wrapper_mode_reason: str
    observed_method: str
    wrapper_stored_procedure_mode: bool
    server: str | None
    source_snapshot_identity: str
    signature_version: str
    contract_status: str
    raw_command_text: str | None


class DatabaseInvocation(FullWrapperEvidence, OmissibleRecord):
    class_name: str
    method_name: str
    database: str | None
    database_candidates: list[str]
    database_attribution: str
    procedure_name: str | None
    procedure_schema: str | None
    raw_command_text: str | None
    evidence: InvocationRating
    reason: str
    caller: str
    caller_class: str
    caller_method: str
    method_chain: list[str]
    method_class_chain: list[str]
    wrapper_contract: str
    wrapper_contract_candidates: list[str]
    branch_context: list[str]
    unresolved_reason: str
    shared_component: SharedComponentLabel = Field(
        default_factory=lambda: SharedComponentLabel(kind="view_component", name="")
    )


class Diagnostic(DatabaseInvocation):
    diagnostic: Literal[True]


class ObjectReference(AnalyzeRecord):
    database: str
    schema_: str = Field(alias="schema")
    name: str
    schema_source: str


class ExecutionPath(FullWrapperEvidence):
    path_id: str
    method_class_chain: list[str]
    wrapper_contract: str
    wrapper_contract_candidates: list[str]
    entry_method: str
    method_chain: list[str]
    database: str
    database_candidates: list[str]
    database_attribution: str
    caller: str
    caller_class: str
    caller_method: str
    procedure_name: str
    procedure_schema: str
    branch_context: list[str]
    sp_chain: list[str]
    module_chain_ids: list[str]
    terminal_operation_id: str
    terminal_operation: str | None
    target: str
    written_columns: list[str]
    conditions: list[str]
    reads: list[str]
    writes: list[str]
    read_full_keys: list[ObjectReference]
    write_full_keys: list[ObjectReference]
    risk_flags: list[str]
    evidence: InvocationRating
    reason: str
    confirmed: bool
    unresolved_reason: str
    unresolved_targets: list[str]


class CompactPath(OmissibleRecord):
    path_id: str
    relevance_key: list[Union[int, str]]
    entry_method: str
    method_chain: list[str]
    sp_chain: list[str]
    terminal_operation_id: str
    terminal_operation: str | None
    target: str
    written_columns: list[str]
    conditions: list[str]
    reads: list[str]
    writes: list[str]
    risk_flags: list[str]
    evidence: InvocationRating
    unresolved_targets: list[str]
    unresolved_reason: str = ""


class PathCounts(AnalyzeRecord):
    total_paths: int
    returned_paths: int
    omitted_paths: int


class EmptyPathCounts(AnalyzeRecord):
    pass


class DisplayField(OmissibleRecord):
    kind: Literal["header", "label", "input", "value"]
    control: str = ""
    id: str = ""
    text: str = ""
    data_field: str = ""
    events: dict[str, str] = Field(default_factory=dict)
    navigate_to: str = ""
    unresolved_reason: str = ""


class GridField(AnalyzeRecord):
    kind: Literal["grid"]
    control: str
    id: str
    events: dict[str, str]
    fields: list[DisplayField]


class InputField(OmissibleRecord):
    control: str
    id: str
    css_class: str = ""
    max_length: str = ""
    js_binding: str = ""


class FormItem(AnalyzeRecord):
    label: str
    fields: list[InputField]


class FormField(FormItem):
    kind: Literal["form"]


class FormGroup(AnalyzeRecord):
    kind: Literal["form_group"]
    container: str
    id: str
    items: list[FormItem]


class ScriptField(AnalyzeRecord):
    kind: Literal["script"]
    index: int
    text: str


class ViewLayer(AnalyzeRecord):
    file: str
    type: str
    framework: str
    summary: list[str]
    fields: list[Union[DisplayField, GridField, FormField, FormGroup, ScriptField]]
    warnings: list[str]


class SharedComponentContribution(SharedComponentLabel):
    file: str
    class_: str = Field(alias="class")
    method: str
    stored_procedures: list[str]
    tables: list[str]
---
status: ready-for-agent
triage: ready-for-agent
---

# Collapse Wrapper Evidence Alias Sprawl

## Problem Statement

`WrapperReconciliation.to_dict()` (`code_analyzer/csharp_analysis_gateway.py`), `analyze_service.py`'s `_wrapper_projection_fields`/`invocation_wrapper_evidence_fields`, and the three response schemas `PathEvidenceResponse`, `SPMatchProgram`, `TableMatchProgram` (`service/schemas.py`) each independently declare the same ~90-entry field list. Roughly 20 of those entries are genuine duplicates — one underlying value exposed under two or three different JSON key names in the same response object (for example `"signature_version"` and `"contract_signature_version"` both mirror `self.contract_signature_version` inside `to_dict()`). A caller or test consuming "wrapper evidence" has to learn nearly as large an interface as the domain logic that produces it, and every future field addition or rename has to be hand-copied into three separate schema classes to stay in sync.

This is consumed outside this repository: `llamaindex-spec-rag`'s `impact_orch` package calls `/analyze`, `/refresh`, and `/path_evidence` over HTTP and reads the JSON response with loose `dict.get(...)` calls — there is no typed model or contract test on that side, so a field rename does not fail a build, it silently returns `None`/default wherever a consumer still asks for a dropped key.

## Solution

Collapse the genuine duplicates to one canonical field name each, chosen from `CONTEXT.md`'s controlled vocabulary where a term already exists there, or from whichever name `llamaindex-spec-rag` already reads when `CONTEXT.md` is silent (this minimizes cross-repo churn and, in practice, means only one of the six alias groups `llamaindex-spec-rag` actually reads needs a change on that side at all — see Implementation Decisions).

Critically, not everything that looks like a wrapper-evidence alias is a duplicate. `DbInvocation` deliberately stores two independent facts for several of these concepts: the invocation's own identity (if it is itself a direct call or a local, source-backed wrapper) and the identity of the external wrapper it resolved through, when one applies. These are stored as separate dataclass fields today (e.g. `implementation_identity` and `wrapper_implementation_identity` are both real, independently-populated fields — not one field exposed under two names), and at least one of them (`receiver_type`/`wrapper_receiver_type`) is merged with explicit fallback logic (`invocation.receiver_type or fields.get("receiver_type", "")`) precisely because the two can differ. This whole family stays untouched by this spec — collapsing it would silently discard the external wrapper's own identity whenever it differs from the invocation's own, which is exactly the audit trail Contract Fingerprint and Contract Preflight (ADR 0004/0005/0006) depend on.

The seam for this collapse is `WrapperReconciliation.to_dict()` itself — already the one place every consumer of wrapper evidence (three schema classes, `analyze_service.py`, and three existing test files) goes through today. It is replaced in place by a standalone function, `project_wrapper_evidence(reconciliation) -> dict`, living alongside `WrapperReconciliation` in `code_analyzer/csharp_analysis_gateway.py`. `WrapperReconciliation` itself keeps only typed attributes; nothing about wire-format field naming lives on the dataclass anymore. The three response schemas stop hand-declaring the ~90 fields independently and instead inherit a single shared base model that declares the canonical field set once; the JSON shape stays flat (no nested `wrapper_evidence` object) so this is a field-count reduction, not a shape change.

## User Stories

1. As a developer reading `service/schemas.py`, I want the wrapper-evidence fields declared once, so that I don't have to diff three ~90-field classes by eye to confirm they still agree.
2. As a developer adding a new wrapper-evidence field, I want to add it in one place, so that I can't forget to add it to one of the three response schemas.
3. As a developer removing or renaming a wrapper-evidence field, I want exactly one call site to change, so that I don't have to grep three files and a dataclass method to find every place the old name is still emitted.
4. As a developer reading `WRAPPER_EVIDENCE_FIELDS`, I want the list to contain one entry per fact, so that its length reflects the actual number of distinct things being reported, not the number of names each fact has.
5. As a developer writing a test against `WrapperReconciliation`, I want to call one projection function and assert on canonical keys, so that my test doesn't silently pass by asserting on a dead alias nobody reads.
6. As a developer extending the `implementation_identity`/`wrapper_implementation_identity`-style dual-fact fields, I want them explicitly documented as two independent facts, so that a future contributor doesn't "clean them up" into one field and quietly drop the external wrapper's identity when it differs from the invocation's own.
7. As a maintainer of `llamaindex-spec-rag`, I want the collapsed field names to match what `impact_orch` already reads wherever `CONTEXT.md` doesn't mandate a specific name, so that most of the six alias groups it consumes require no change on the spec-rag side at all.
8. As a maintainer of `llamaindex-spec-rag`, I want the one alias group that does require a spec-rag-side change (`evidence`/`evidence_status`, collapsing to `evidence_status`) called out explicitly, so that `impact_orch/context_builder.py` and `impact_orch/path_selection.py`'s reads of the inner `evidence` key on a `/path_evidence` response are updated in the same change, not discovered later as a silent missing-field bug.
9. As an operator reading a `/refresh` wrapper summary or a `/path_evidence` response, I want one field name per fact regardless of which endpoint produced it, so that I don't have to remember that the same concept is called `evidence` on one endpoint and `evidence_status` on another.
10. As a developer reading `CONTEXT.md`, I want the "Wrapper Resolution Status" concept (the `status` field's own controlled vocabulary — `source_wrapper`, `explicit_selected`, `unresolved_contract`, `ambiguous_contract`, `receiver_mismatch`, `unresolved_method`, `not_applicable`) named and defined, so that the canonical `status` field has a documented meaning distinct from Evidence Status.
11. As a code reviewer, I want the response schema change to be additive-safe for every consumer this repo already tests (`tests/test_path_evidence_api.py` and friends), so that this refactor doesn't require touching unrelated response fields like `unresolved_reason`, `evidence_reason`, `invocation_mode`, `terminal_sink`, `procedure_name`, `connection_source`, or the `wrapper_summary.totals`/`contract_preflight` sub-objects, none of which are part of this alias collapse.
12. As a developer, I want `WrapperReconciliation`'s own attribute names left unchanged, so that this refactor touches only wire-format dict construction, never the domain dataclass's internal field names.
13. As a developer running the existing test suite, I want the three tests that currently call `.to_dict()` directly (`tests/test_external_wrapper_contract_identity.py`, `tests/test_external_wrapper_discovery.py`, `tests/test_csharp_analysis_gateway.py`) to keep passing after switching to `project_wrapper_evidence`, so that this refactor has no unintended behavior change for anything already covered.
14. As a developer, I want a regression test asserting that the dropped alias keys (e.g. `selected_contract`, `wrapper_classification_status`, `signature_version`) never reappear in a real response payload, so that a future contributor can't silently reintroduce the sprawl by copy-pasting an old snippet.
15. As a developer, I want a regression test proving the dual-fact identity pairs (`implementation_identity` vs `wrapper_implementation_identity`, `receiver_type` vs `wrapper_receiver_type`, etc.) can hold different values on the same invocation, so that this collapse — or any future one — can't accidentally merge them.
16. As a system maintainer coordinating both repos, I want both repos' changes committed (not pushed) in the same working session, so that neither repo is left temporarily inconsistent with the other's field names.

## Implementation Decisions

- **Seam**: `WrapperReconciliation.to_dict()` in `code_analyzer/csharp_analysis_gateway.py` is replaced by a standalone function `project_wrapper_evidence(reconciliation: WrapperReconciliation) -> Dict[str, Any]`, defined next to `WrapperReconciliation` in the same module. This is the only place that maps `WrapperReconciliation`/`DbInvocation` attributes to wrapper-evidence wire-format keys. `WrapperReconciliation` itself keeps only typed attributes — no `to_dict` method remains on the class.
- `WRAPPER_EVIDENCE_FIELDS` shrinks to exactly the canonical key set `project_wrapper_evidence` and `invocation_wrapper_evidence_fields` actually emit — one entry per fact, no alias entries. `analyze_service.py`'s `_wrapper_projection_fields` and `invocation_wrapper_evidence_fields` keep their current shape (they still filter/merge a source mapping by this list); only the list's contents shrink.
- `service/schemas.py` gains one shared base model (e.g. `WrapperEvidenceFields(BaseModel)`) declaring the canonical wrapper-evidence field set once. `PathEvidenceResponse`, `SPMatchProgram`, and `TableMatchProgram` inherit from it instead of independently redeclaring every field. The JSON shape stays flat — no nested `wrapper_evidence` sub-object; this changes field count, not response shape.
- **Canonical names for true duplicates** (one value, multiple keys today — collapse to the first column, drop the rest):

  | Canonical | Dropped aliases |
  |---|---|
  | `status` | `wrapper_status`, `wrapper_classification_status`, `classification_status` |
  | `selection_source` | `wrapper_selection_source` |
  | `contract` | `wrapper_contract` (response-level only — the distinct request-level `AnalyzeRequest.wrapper_contract`/`PathEvidenceRequest.wrapper_contract` selector field is untouched), `selected_contract` |
  | `contract_mode` | `wrapper_contract_mode` |
  | `contract_sink` | `wrapper_contract_sink` |
  | `candidate_contracts` | `wrapper_contract_candidates`, `candidate_contract_names` |
  | `scan_root` | `wrapper_scan_root` |
  | `source_available` | `wrapper_source_available` |
  | `review_candidate` | `wrapper_review_candidate` |
  | `classification_reason` | `wrapper_unresolved_reason` (distinct from the separate, already-single-named `unresolved_reason` field, which reports the *invocation's* evidence-unresolved reason, not the wrapper's — that field is untouched) |
  | `mode_reason` | `wrapper_mode_reason` |
  | `wrapper_method` | `observed_method` (distinct from the separate, already-single-named `external_wrapper_method` field — untouched, see dual-fact list below) |
  | `stored_procedure_mode` | `wrapper_stored_procedure_mode` |
  | `evidence_status` | `evidence` (this alias exists only inside the wrapper-evidence bag on `PathEvidenceResponse`/`SPMatchProgram`/`TableMatchProgram`; `DbInvocation`'s own top-level `evidence: InvocationEvidence` field and its serialized `evidence` key are a different, core field and are untouched) |
  | `contract_signature_version` | `signature_version` |
  | `contract_lifecycle_status` | `contract_status` |
  | `source_snapshot_hash` | `source_snapshot_identity` (both where it appears at the top level and nested inside the `source_provenance` object) |

  Every other entry currently in `WRAPPER_EVIDENCE_FIELDS` (`wrapper_kind`, `wrapper_contract_source`, `active_contract`, `evidence_reason`, `source_span`, `source_provenance`, `invocation_mode`, `command_text_*`, `literal_value`, `terminal_sink`, `embedded_*`, `procedure_name_hint`, `receiver_name`, `connection_*`, `provenance`, `receiver_expression`, `binding_provenance`, `receiver_construction_facts`, `receiver_assignment_facts`, `contract_fingerprint`, `evidence_kind`, `implementation_snapshot_reference`, `comparison_report_reference`, `source_contract_conflict*`, `source_contract_semantics`, `source_contract_sink`) already has exactly one name today and is unaffected.

- **Explicitly out of scope — dual-fact pairs, not aliases** (both names stay, both keep being populated from their own independent `DbInvocation` field):
  `implementation_identity`/`wrapper_implementation_identity`, `assembly_identity`/`wrapper_assembly_identity`, `assembly_revision`/`wrapper_assembly_revision`, `method_identity`/`wrapper_method_identity`, `method_arity`/`wrapper_method_arity`, `parameter_types`/`wrapper_parameter_types`, `method_semantics`/`wrapper_method_semantics`, `overload_candidates`/`wrapper_overload_candidates`, `overload_candidate_facts`/`wrapper_overload_candidate_facts`, `receiver_type`/`wrapper_receiver_type`, `external_wrapper_method`/`wrapper_method`.
- **`llamaindex-spec-rag` coordination**: of the six alias groups `impact_orch` actually reads (`status`; `contract`/`selected_contract`; `receiver_type` — out of scope, dual-fact, untouched; `classification_reason`; `wrapper_method`; `evidence`/`evidence_status`), only `evidence`/`evidence_status` requires a change on the spec-rag side, because every other one already reads the name this spec keeps as canonical. `impact_orch`'s `/path_evidence` consumers (`context_builder.py`, `path_selection.py`) that currently read the inner `evidence` key off a `PathEvidenceResponse`-shaped payload switch to `evidence_status`. `impact_orch`'s `/refresh` consumer (`refresh_cli.py`) already reads `evidence_status` from `wrapper_summary.review_items` and needs no change. `impact_orch`'s redundant `item.get("contract") or item.get("selected_contract")` fallback may be simplified to `item.get("contract")` as a cleanup, but is not required to change (a missing key returns `None` from `.get()` harmlessly).
- `CONTEXT.md` gains a "Wrapper Resolution Status" term for the `status` field's controlled vocabulary (`source_wrapper`, `explicit_selected`, `unresolved_contract`, `ambiguous_contract`, `receiver_mismatch`, `unresolved_method`, `not_applicable`, and any other value `WrapperReconciliation.status` is assigned). This has already been added during the design discussion that produced this spec.
- Both repos' changes (this repo and `llamaindex-spec-rag`) land as part of the same piece of work; both are committed locally, neither is pushed as part of this spec.

## Testing Decisions

- A good test here asserts the externally observable dict/JSON shape `project_wrapper_evidence` and the collapsed schemas produce — key presence, key absence, and value — never the internal call sequence used to build that dict.
- `tests/test_external_wrapper_contract_identity.py`, `tests/test_external_wrapper_discovery.py`, and `tests/test_csharp_analysis_gateway.py`'s existing calls to `.to_dict()` are updated to call `project_wrapper_evidence(...)` instead; their existing assertions on canonical keys (e.g. `payload["staged_selector"]`) are unaffected, and any assertion on a now-dropped alias key is rewritten to assert the canonical key instead.
- A new focused test constructs a `WrapperReconciliation` and asserts `project_wrapper_evidence(...)` contains none of the dropped alias keys listed above (`selected_contract`, `wrapper_classification_status`, `classification_status`, `signature_version`, `contract_status`, `source_snapshot_identity`, `wrapper_unresolved_reason`, `observed_method`, `evidence` inside the wrapper-evidence bag, etc.) — this is the regression guard against the sprawl reappearing.
- A new focused test constructs a `DbInvocation` where the invocation's own identity fields (`implementation_identity`, `receiver_type`, etc.) differ from the wrapper's (`wrapper_implementation_identity`, `wrapper_receiver_type`, etc.) and asserts both values survive independently in the serialized output — the regression guard against the dual-fact pairs being merged by mistake, following the existing fixture-construction pattern already used in `tests/test_csharp_analysis_gateway.py`.
- `tests/test_path_evidence_api.py` (existing pattern for hitting the HTTP layer) gains an assertion that a `/path_evidence` response contains `evidence_status` and not `evidence` inside the wrapper-evidence fields, and that `SPMatchProgram`/`TableMatchProgram`-shaped entries in a `/refresh` response likewise expose exactly one name per collapsed concept.
- No test should assert on `WrapperReconciliation.to_dict` remaining callable — any such test is rewritten against `project_wrapper_evidence`.

## Out of Scope

- The ten dual-fact identity/receiver/method pairs listed above — they are two independent facts, not aliases, and are not touched by this spec.
- Changing the shape of `source_provenance` (still a nested object) or any other already-single-named field.
- Introducing a nested `wrapper_evidence` sub-object on the response schemas — the collapse stays flat.
- Renaming any `WrapperReconciliation` or `DbInvocation` dataclass attribute — only wire-format dict/JSON key construction changes.
- Building a typed response model, client SDK, or cross-repo contract test for `llamaindex-spec-rag` — `impact_orch` keeps its existing loose `dict.get(...)` style; only the two field names it reads for the `evidence`/`evidence_status` concept change.
- Candidate "one seam for the two-file atomic commit" (registry/catalog commit unification) — already specified separately in `.scratch/unify-contract-acceptance-transaction/spec.md` and unrelated to this change.
- Any ADR — this is interior interface cleanup behind seams ADR 0002/0004 already established; no ADR decision is being revisited.

## Further Notes

This spec was produced from a grilling session (using the `codebase-design`/`grilling` skills) over architecture-review candidate #1 ("collapse the wrapper-evidence alias sprawl"). Mid-session fact-finding into `llamaindex-spec-rag`'s actual field reads, followed by direct tracing of `DbInvocation`'s dataclass fields and `invocation_wrapper_evidence_fields`'s construction logic, corrected the original candidate's scope: roughly a third of the ~90 fields the architecture review flagged as "duplicate" turned out to be two independently-populated facts (invocation-level vs. external-wrapper-level) rather than one value under two names. That correction is now load-bearing for this spec — see the "Explicitly out of scope" list in Implementation Decisions. `CONTEXT.md` gained a "Wrapper Resolution Status" glossary term during this session; no further glossary or ADR work is expected for this spec.

# 04 — Collapse the three response schemas onto one shared canonical base model

**What to build:** `PathEvidenceResponse`, `SPMatchProgram`, and `TableMatchProgram` in `service/schemas.py` stop independently redeclaring the ~90-field wrapper-evidence bag and instead inherit a single shared base model declaring the canonical field set once. The JSON response shape stays flat (no nested `wrapper_evidence` object) — this is a field-count reduction, not a shape change.

**Blocked by:** 01 (dropping the `evidence` field specifically requires spec-rag to have already migrated off it; the other 16 canonicalized field names are safe to drop from the schema regardless of domain-side timing, since Pydantic ignores extra dict keys it doesn't declare).

**Status:** ready-for-agent

- [ ] `service/schemas.py` gains one shared base model (e.g. `WrapperEvidenceFields(BaseModel)`) declaring exactly the 17 canonical wrapper-evidence fields from the spec's table (`status`, `selection_source`, `contract`, `contract_mode`, `contract_sink`, `candidate_contracts`, `scan_root`, `source_available`, `review_candidate`, `classification_reason`, `mode_reason`, `wrapper_method`, `stored_procedure_mode`, `evidence_status`, `contract_signature_version`, `contract_lifecycle_status`, `source_snapshot_hash`) plus every already-single-named field currently shared across all three classes.
- [ ] `PathEvidenceResponse`, `SPMatchProgram`, and `TableMatchProgram` inherit from the shared base model instead of independently redeclaring these fields.
- [ ] None of the 20 dropped aliases from ticket 02, nor the `evidence` field from ticket 03, remain declared on any of the three response schemas.
- [ ] The ten dual-fact pairs (`implementation_identity`/`wrapper_implementation_identity` and friends, `receiver_type`/`wrapper_receiver_type`, `external_wrapper_method`/`wrapper_method`) and every already-single-named field remain declared exactly as today — this ticket does not touch response shape for anything outside the 17-group canonical collapse.
- [ ] `tests/test_path_evidence_api.py` gains an assertion that a `/path_evidence` response contains `evidence_status` and not `evidence` inside the wrapper-evidence fields, and that it contains no other dropped alias key.
- [ ] An equivalent assertion is added for `/refresh`'s `wrapper_summary` entries (`SPMatchProgram`/`TableMatchProgram`-shaped) — exactly one name per collapsed concept, no dropped alias key present.
- [ ] Full existing test suite passes, including any existing test that constructs a `PathEvidenceResponse`/`SPMatchProgram`/`TableMatchProgram` by keyword argument using a now-dropped field name — those call sites are updated to the canonical name.

# 03 — Collapse `evidence`/`evidence_status` to `evidence_status` at the domain seam

**What to build:** `project_wrapper_evidence` (introduced in ticket 02) and `WRAPPER_EVIDENCE_FIELDS` stop emitting the `evidence` key inside the wrapper-evidence bag, keeping only `evidence_status`. This is the one alias group in this spec with real cross-repo risk, so it lands only after `llamaindex-spec-rag` no longer depends on the old name.

**Blocked by:** 01 (spec-rag must have already migrated off `evidence`), 02 (builds on the `project_wrapper_evidence` seam and shrunk `WRAPPER_EVIDENCE_FIELDS` that ticket introduces).

**Status:** ready-for-agent

- [ ] `project_wrapper_evidence`'s output no longer includes an `evidence` key inside the wrapper-evidence bag; `evidence_status` remains and continues to carry the same value `evidence` used to.
- [ ] `WRAPPER_EVIDENCE_FIELDS` drops the `evidence` entry, keeping `evidence_status`.
- [ ] `DbInvocation`'s own top-level `evidence: InvocationEvidence` field, and the top-level `evidence` key `_serialize_db_invocation` emits for it in `analyze_service.py`, are untouched — this ticket only removes the duplicate `evidence` key inside the wrapper-evidence bag on `PathEvidenceResponse`/`SPMatchProgram`/`TableMatchProgram`, not the invocation's own core evidence field.
- [ ] Any existing test asserting `evidence` inside the wrapper-evidence bag (as opposed to the invocation's own top-level `evidence`) is rewritten to assert `evidence_status`.
- [ ] Full existing test suite passes.

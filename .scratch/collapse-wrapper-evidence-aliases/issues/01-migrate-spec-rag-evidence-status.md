# 01 — Migrate llamaindex-spec-rag off the `evidence` field

**What to build:** `llamaindex-spec-rag`'s `/path_evidence` consumers stop reading the `evidence` key on a `PathEvidenceResponse`-shaped payload and read `evidence_status` instead — the same fact, already present in today's response under a second name, so this can land with zero coordination with the Impact_analysis_system side.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `impact_orch/context_builder.py`'s reads of the inner `evidence` key (the `PathEvidenceResponse.evidence` field nested inside spec-rag's own `{"path": ..., "evidence": ...}` wrapper — not spec-rag's own outer `"evidence"` wrapper key, which is unrelated and stays as-is) are changed to read `evidence_status`.
- [ ] `impact_orch/path_selection.py`'s equivalent reads of the same inner `evidence` key are changed to read `evidence_status`.
- [ ] `impact_orch/refresh_cli.py` is left unchanged — it already reads `evidence_status` from `wrapper_summary.review_items` for `/refresh`.
- [ ] Existing spec-rag tests covering `context_builder.py`/`path_selection.py` pass against a `/path_evidence` fixture response that has both `evidence` and `evidence_status` present with the same value (matching today's actual Impact_analysis_system behavior).
- [ ] Change is committed in the `llamaindex-spec-rag` repository, not pushed.

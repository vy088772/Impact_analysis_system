# 06 — Wire rag_client and migrate context_builder / path_selection

**What to build:** `rag_client.py`'s `analyze()` and `path_evidence()` call the new `evidence_status` module at their existing return points, so they return already-typed evidence values instead of raw JSON. `context_builder.py` and `path_selection.py` — the two real consumers of that data — switch to reading evidence exclusively through these typed values, replacing their current ad hoc, inconsistent dict-reading. Because `rag_client.py`'s return shape changes, these two consumers must migrate in the same ticket — landing the seam without its consumers (or vice versa) leaves the code broken, not just incomplete.

**Blocked by:** 04 (the module must exist), 05 (fixture rewrite needs the validation helper).

**Status:** done

- [x] `rag_client.py`'s `analyze()` and `path_evidence()` return typed evidence values via the `evidence_status` module instead of raw JSON
- [x] `rag_client.py`'s other five HTTP functions (`refresh`, `find_by_sp`, `find_by_table`, `flow_chain`) are unmodified
- [x] `context_builder.py` reads evidence data exclusively through the new typed values; its previous ad hoc `evidence`/`evidence_status` dict-reading is removed
- [x] `path_selection.py` reads evidence data exclusively through the new typed values; its previous ad hoc `evidence`/`evidence_status` dict-reading is removed
- [x] `tests/test_path_selection.py` and `tests/test_path_evidence_wiring.py` fixtures are rewritten using the schema-validation helper (ticket 05) instead of hand-written dicts
- [x] Existing assertions on rendered output pass unchanged — this is a parsing-path change, not a behavior change

`llamaindex-spec-rag/impact_orch/rag_client.py`'s `analyze()`/`path_evidence()` now parse every Evidence Status they carry through `evidence_status.parse_db_invocation_evidence()`/`parse_wrapper_evidence_status()` before returning — a validation pass, not a reshape (the raw JSON dict shape is unchanged, so every other existing caller of these two functions keeps working). It fails loudly (`UnknownEvidenceStatusError`) on an unrecognized value right at this HTTP seam.

`context_builder.py` (`_format_program`'s database-invocation/execution-path verified-vs-unresolved split, and `render_selected_path_evidence`/`_render_one_path_evidence`) and `path_selection.py` (`_result`'s new `_wrapper_evidence_status()` helper, `_evidence_summary()`, `make_deterministic_path_decision_provider().decide()`'s compact-path ranking, and `_fallback_evidence_for_path()`'s literal-SP-candidate filter) now branch on `parse_db_invocation_evidence()`/`parse_wrapper_evidence_status()` + `is_verified()` calls instead of ad hoc `"evidence" in {"proven","likely"}` / `.get("evidence_status")` string comparisons.

One constraint drove the design: `finalization.py` still `json.dumps()`s `selected_path_evidence` (and `path_selection.py` still `json.dumps()`s the LLM selector prompt), so no `Enum` instance from `evidence_status.py` is ever stored into a dict that flows through those — the typed values are computed transiently at each read/branch site (never persisted as a new dict key), keeping every existing JSON-serialization path intact. Rendered markdown output is byte-for-byte unchanged (verified by the full existing test suite).

`tests/test_path_selection.py` and `tests/test_path_evidence_wiring.py` gained a local `_path_evidence_response(**overrides)` helper that builds a `/path_evidence`-response-shaped fixture and validates it via ticket 05's `assert_matches_schema(fixture, "PathEvidenceResponse")`; every hand-written wrapper-evidence-bag fixture in both files now goes through it. (Compact-execution-path/database-invocation fixtures stay hand-written — Impact_analysis_system's OpenAPI export has no component schema for those, since `ProgramAnalysis.database_invocations`/`compact_execution_paths` are untyped `List[Dict]` on that side.) Full suite: 71 passed, 1 pre-existing unrelated failure (`test_refresh_client_uses_catalog_contract_without_discovery_request`, fails identically on the pre-migration code — depends on local catalog data, not this change).

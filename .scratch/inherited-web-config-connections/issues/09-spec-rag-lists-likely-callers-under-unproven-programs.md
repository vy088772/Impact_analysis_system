# 09 — spec-rag lists likely callers under `unproven_programs`

**What to build:** In `llamaindex-spec-rag`, the routing-expectation lookup
shows each `likely` caller of a stored procedure under `unproven_programs`. No
real caller disappears with no trace. See the spec, section
"`llamaindex-spec-rag`".

**Blocked by:** 08 — `/find_by_sp` returns likely callers in `likely_matches`

**Status:** done (2026-09-30)

- [x] The stored-procedure lookup reads `likely_matches` beside `matches`.
- [x] The partition by Evidence Status puts each `likely` caller in the
      unproven half. `unproven_programs` lists it, and the proven list does
      not.
- [x] A response with no `likely_matches` field, from an older service, still
      works.
- [x] Seam C test: a fake `/find_by_sp` response with one entry in
      `likely_matches`.

## Comments

### 2026-09-30 — implementation notes

- Repository: `llamaindex-spec-rag`, branch `spec_extend_20260701`. Two
  commits: a feature commit and a fix commit after code review.
- Files of this ticket: `impact_orch/rag_client.py`
  (`_merge_match_responses` and the `find_by_sp` docstring),
  `impact_orch/cross_system_lookup.py` (`find_cached_program_matches`),
  `evaluation/Impact_analysis/cache_derived_lookup.py` (`_raw_sp_result`
  only), and `tests/test_cache_derived_lookup.py`.
- The merge across databases kept only `matches`. It now also keeps
  `likely_matches`. The merged answer has the field only when a response
  carries it.
- `find_cached_program_matches` gains `include_likely` (default `False`).
  Only the evaluation lookup sets it. `find_programs_by_sp` does not split by
  Evidence Status. With the option on there, a `likely` caller would show as
  a plain program. The code review found this. A test now guards it.
- An entry in `likely_matches` with no `evidence_status` reads as `likely`.
  An entry with an explicit status keeps it.
- Tests: two Seam C tests, one merge test, one runtime guard test. The full
  suite has two failures in `test_table_lookup_write_access_types.py`. They
  fail on a clean copy of HEAD too.
- Not done: the glossary (`CONTEXT.md`) has no entry for the status `likely`.
  This is a gap for a domain-modeling session. Ticket 10 (regeneration of the
  routing expectations) stays open.

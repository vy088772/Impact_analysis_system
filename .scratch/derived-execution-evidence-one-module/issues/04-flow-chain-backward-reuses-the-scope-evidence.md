# 04 — `/flow_chain` backward reuses the scope evidence

**What to build:** `/flow_chain` in the backward direction asks the module for the evidence of the whole scope. A second backward request on one scope does not rate again. A backward request after `/find_by_table` on one scope does not rate again. The chains do not change. See the spec, section "Endpoints".

**Blocked by:** 02 — `/path_evidence` gets its evidence from the module and finds a path by its path_id.

**Status:** resolved (2026-10-02)

- [x] The backward direction calls the entry point with no needed files.
- [x] The backward direction uses the paths of the evidence and does not build paths again.
- [x] `/flow_chain` takes an optional evidence source.
- [x] An endpoint-seam test gives fixed evidence and checks the backward chains and the diagnostics.
- [x] The present backward tests pass with no change in expected answers.

## Comments

### Implementation Notes (2026-10-02)

- Affected functions: `flow_chain` and `build_backward_chains`.
- User-visible change: repeated backward requests reuse the scope evidence. A backward request after `/find_by_table` also reuses it.
- Every backward request calls the evidence source without needed files. Requests without a Database keep their previous inline SQL chains and empty diagnostics.
- The builder accepts supplied Execution Paths. The endpoint supplies the evidence paths, so the builder does not build them again.
- Fixed-evidence tests check the path identifier, column filter, diagnostics, refresh flag, and requests without a Database.
- Reuse tests give different scan content with the same recorded state. The retained answer proves reuse without private counters or object-identity assertions.
- Focused tests: 79 passed across the table lookup, inline flow, graph reverse lookup, and evidence module test files. Existing expected answers are unchanged.
- Full suite: 1621 passed; two existing collection errors remain in `test_search_roles.py` and `test_sp_tables.py` (`KeyError: 'PUR'`).
- The collection errors follow a failed SQL connection because this environment lacks ODBC Driver 17 for SQL Server.
- Typecheck: the two changed service modules have the same 58 existing mypy errors as `c25f723`. No new errors were added.
- Standards and Spec reviews found two issues. Both were fixed, and both focused reviews then reported no remaining findings.
- Forward behavior remains outside this ticket. The unrelated `.scratch/request-context-one-module/` directory was not changed.

# 06 — Remove the old forms and verify the whole change

**What to build:** All five handlers use the request context. This ticket removes what no caller needs, then checks the whole change against the baseline. The user of the API sees no change.

**Blocked by:** 02 — Move `/find_by_table` onto the request context; 03 — Move `/flow_chain` onto the request context; 04 — Move `/analyze` onto the request context; 05 — Move `/path_evidence` onto the request context.

**Status:** resolved

- [x] No test of the five handlers patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] The tests of the two refresh functions keep their patches. The service keeps the names those tests need.
- [x] Imports and helpers that no caller uses are removed from the service. A helper that a refresh function still uses stays.
- [x] The shared test fixtures keep only the style that tests still use.
- [x] The full test suite runs in the main directory. The result matches the baseline from before this work. The path-dependent tests that differ in a worktree are compared in the main directory only.
- [x] Candidates 8 and 9 do not change how the scope is built. If they do, the owner of this spec reviews decision Q8 first.
- [x] A diff stat shows that no file changed its line endings (CRLF or LF) by mistake.
- [x] A search of the service shows one `cache_only` skip rule only.
- [x] No API response changes.

## Comments

Completed on 2026-10-02 against `bc0b01b`.

- Affected functions: the five handlers retain the request context. The unused service functions `resolve_source` and `_get_scan` are removed.
- User-visible change: none. API requests, responses, errors, and HTTP status codes stay the same.
- The unused `settings` and `AzureDevOpsFetcher` imports are removed.
- The unused `RequestStores.install_legacy` method and its SQL cache import are removed.
- Refresh retains `resolve_scan_roots`, `get_or_scan`, `cache_status`, `cached_commit`, `repo_dir`, and `_merge_scans`.
- The service retains the two method-chain helpers used by integration tests.
- The remaining old patches test refresh or other evidence boundaries, not the five handler preludes.
- `service/request_context.py` has the only `cache_only` skip rule.
- Candidates 8 and 9 are not changed. The scope construction remains unchanged, so Q8 needs no new decision.
- Focused tests: 109 passed after helper removal. Review fixes passed 26 cases. Final import cleanup passed 75 cases.
- Full suite in the main directory: 1,671 passed with the same two collection errors as the preceding ticket.
- The recorded pre-refactor baseline at `ad31993` is 1,631 passed with those same errors. Tickets 01 to 05 add 40 cases.
- The earlier saved evidence-module report has 1,627 passes. It precedes the four regression cases in `ad31993`.
- The two collection errors remain in `tests/test_search_roles.py` and `tests/test_sp_tables.py`. Both need the missing ODBC Driver 17.
- Scoped type check: six files checked. All 29 existing diagnostics match after line-number normalization and sorting.
- The service keeps CRLF. The three changed test files keep LF. The diff stat shows no whole-file rewrite.
- Standards review found two assertions tied to internal call records. The tests now check refusal errors and refresh-specific responses.
- Final Standards review: zero findings. Final Spec review: zero findings. The review covers the change from `ad31993` through this ticket.

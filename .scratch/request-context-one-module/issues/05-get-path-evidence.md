# 05 — Move `/path_evidence` onto the request context

**What to build:** `/path_evidence` calls the request context module. The handler keeps its own check for an empty root list. The user of the API sees no change, including the `source_not_found` error.

**Blocked by:** 01 — Build the request context and move `/find_by_sp` onto it.

**Status:** resolved

- [x] `/path_evidence` calls the module.
- [x] A source with no roots still raises the same `source_not_found` error. The check stays in the handler, and it runs before any scan call.
- [x] A Database on several hosts with no host named still answers "not scanned".
- [x] The handler keeps its own SQL execution graph requirement.
- [x] The `/path_evidence` tests use in-memory adapters through the handler call. No `/path_evidence` test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] A test covers the empty-roots error.
- [x] No API response changes.

## Comments

Completed on 2026-10-02 against `f98127f`.

- `get_path_evidence` accepts optional stores and uses `build_request_context`.
- The handler checks the SQL execution graph through its identity callback before source resolution.
- The handler checks for empty roots through its roots callback before scan retrieval.
- Tests use in-memory adapters through the handler, including the HTTP test injection helper.
- New cases cover empty roots with both refresh values, unnamed hosts, blank hosts, and the SQL graph error before source resolution.
- User-visible change: none. The response, error code, error message, and HTTP status stay the same.
- Focused tests: 79 passed.
- Full suite: 1,671 passed. Two existing collection errors remain in `test_search_roles.py` and `test_sp_tables.py`.
- Both collection errors need the missing ODBC Driver 17 for SQL Server.
- Scoped type check: seven files checked. The 27 existing service diagnostics match the baseline after line-number normalization and sorting.
- Standards review: zero findings. Spec review: zero findings.

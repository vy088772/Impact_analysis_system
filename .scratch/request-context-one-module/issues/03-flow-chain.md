# 03 — Move `/flow_chain` onto the request context

**What to build:** `/flow_chain` calls the request context module. The third copy of the `cache_only` rule disappears. After this ticket, the rule exists in one place. The user of the API sees no change.

`/flow_chain` does not refuse an Ambiguous Database. It reads the answer as "not scanned". The ticket keeps that behavior.

**Blocked by:** 01 — Build the request context and move `/find_by_sp` onto it.

**Status:** resolved

- [x] `/flow_chain` calls the module and builds its own skipped response.
- [x] A Database on several hosts with no host named still answers "not scanned". The handler does not raise `AmbiguousDatabaseError`.
- [x] The `/flow_chain` copy of the `cache_only` rule is deleted.
- [x] A search of the service shows one `cache_only` skip rule only.
- [x] The `/flow_chain` tests use in-memory adapters through the handler call. No `/flow_chain` test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] A test covers a skip, and a test covers the "not scanned" answer for an Ambiguous Database.
- [x] Both directions (forward and backward) keep their existing tests, and they pass.
- [x] No API response changes.

## Comments

### 2026-10-02 - Implementation Note

The request context prepares the scans and the evidence scope for `/flow_chain`.
The handler creates its own skipped response.
The service now holds one `cache_only` skip rule.
The API responses do not change.

Both directions keep the "not scanned" error for an Ambiguous Database.
The handler raises `SqlExecutionGraphRequiredError`, not `AmbiguousDatabaseError`.
New tests cover a partly cached source, the ambiguous answer, and the refresh bypass in both directions.

Handler tests pass in-memory scan and cache stores.
HTTP tests inject an in-memory scan store and keep real SQL cache files to check the 409 response.
No flow test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
Other handlers keep their old test adapters until their own tickets migrate them.

The focused checks pass 80 tests.
The final full suite passes 1659 tests with two existing collection errors.
Those errors need ODBC Driver 17, the SQL Server connection driver that this environment lacks.

The shared context, adapters, test stores, and new test file pass mypy, the Python type checker.
The wider check keeps the same 52 type errors as the starting revision, including 27 in the service.
The error messages match after line-number changes.

The code review uses `257670d` as its starting revision.
The Standards review finds no rule violations or design issues.
The Spec review finds no missing requirements or extra behavior.

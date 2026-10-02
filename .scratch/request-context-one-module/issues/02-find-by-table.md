# 02 — Move `/find_by_table` onto the request context

**What to build:** `/find_by_table` calls the request context module. The second copy of the `cache_only` rule disappears. The user of the API sees no change: the skipped response and the 409 `ambiguous_database` refusal stay the same.

**Blocked by:** 01 — Build the request context and move `/find_by_sp` onto it.

**Status:** resolved

- [x] `/find_by_table` calls the module and builds its own skipped response.
- [x] `/find_by_table` keeps its own `AmbiguousDatabaseError` raise.
- [x] The `/find_by_table` copy of the `cache_only` rule is deleted.
- [x] The `/find_by_table` tests use in-memory adapters through the handler call. No `/find_by_table` test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] A test covers a skip, and a test covers a refusal before any scan call.
- [x] The blending rule for inline table matches keeps its existing tests, and they pass.
- [x] No API response changes.

## Comments

### 2026-10-02 - Implementation Note

The request context prepares the scans and the evidence scope for `/find_by_table`.
The handler still creates its skipped response and raises `AmbiguousDatabaseError`.
The API responses do not change.

The handler tests pass in-memory scan and cache stores.
The HTTP tests use an in-memory scan store with real SQL cache files to check host selection.
Cross-handler tests limit old scan patches to calls of handlers that still need them.
The table handler does not use those patches.

The focused checks pass all 167 tests.
The full suite passes 1653 tests with two existing collection errors.
The two errors need ODBC Driver 17, the SQL Server connection driver that this environment lacks.

The new tests and the shared test stores pass mypy, the Python type checker.
The service keeps the same 27 type errors as the starting revision.
The error messages match after line-number changes.

The code review uses `2dcd9e8` as its starting revision.
The Standards review finds no rule violations or design issues.
The Spec review finds no missing requirements or extra behavior.

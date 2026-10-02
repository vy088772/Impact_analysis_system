# 01 — Build the request context and move `/find_by_sp` onto it

**What to build:** One module turns a request into a ready context or a `Skipped` marker. The module owns the `cache_only` rule. `/find_by_sp` is the first handler to use the module. This ticket is the tracer bullet for the whole spec. It proves the skip rule, the `refresh` bypass, and the order of the steps.

The module needs two ports. The scan store port covers source resolution, root resolution, scan retrieval, and the scan cache check. The cache store port covers the SQL Cache Identity lookup. Each port has a real adapter that wraps the existing functions. Each port also has an in-memory adapter for tests. The handler takes both stores as optional arguments. The default is the real adapter.

The user of the API sees no change. `/find_by_sp` returns the same response as before, including the skipped response and the 409 `ambiguous_database` refusal.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] The request context module exists. It returns a ready context or a `Skipped` marker. The ready context holds the roots, the Scan of each root, the merged Scan, the chosen root, the raw SQL Cache Identity result, and the scope.
- [x] The step order is: identity lookup, `cache_only` check, root resolution, scans. An Ambiguous Database refuses before any scan call.
- [x] The `cache_only` check runs only when `cache_only` is set and `refresh` is not set. It checks every candidate root. It does not clone or pull.
- [x] Both ports have a real adapter and an in-memory adapter. Both adapters sit together in one adapters module.
- [x] `/find_by_sp` calls the module. The handler keeps its own `AmbiguousDatabaseError` raise and builds its own skipped response.
- [x] The `/find_by_sp` copy of the `cache_only` rule is deleted.
- [x] The `/find_by_sp` tests use in-memory adapters through the handler call. No `/find_by_sp` test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] New handler tests cover: a skip, a skip when one root of a multi-folder source has no cache, no skip when `refresh` is set, and an Ambiguous Database refusal before any scan call.
- [x] The shared test fixtures work for the new style and for the old patch style. The handlers that have not moved yet keep passing.
- [x] No API response changes.

## Comments

- 2026-10-02: Started implementation. The agreed test boundary is the handler call with in-memory stores. The review baseline is `ad31993dd2b48efa6b7352ef6ec5a12fdfdf207e`.
- 2026-10-02: Completed the request context and the `/find_by_sp` migration. The affected function is `find_by_sp`. The user-visible change is none.
- The handler supplies its identity check to the context builder. It raises `AmbiguousDatabaseError` before any scan-store call.
- The shared fixtures pass in-memory stores to the handler. They keep the old wiring for the handlers that have not moved.
- The HTTP SQL Cache Identity integration tests keep the real cache adapter. This preserves their host-selection and directory-listing checks.
- Validation: 13 new handler cases passed. The changed handler and HTTP test files passed all 86 cases.
- Full suite: 1644 passed. Two existing collection errors remain in `test_search_roles.py` and `test_sp_tables.py`. The environment lacks ODBC Driver 17.
- Type check: the two new modules, the shared fixture, and the new tests passed. The service's 27 errors match the baseline after line-number normalization.
- Standards review: no accepted findings. Spec review: no accepted findings. Both reviews incorrectly called `_merge_scans` unused; six existing call sites still use it.
- The original CRLF files retain their line endings. The diff check passed with `cr-at-eol` enabled.

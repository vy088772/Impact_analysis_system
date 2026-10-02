# 04 — Move `/analyze` onto the request context

**What to build:** `/analyze` calls the request context module. This handler has no `cache_only` rule. The ticket proves that the module works for a handler that never skips. The user of the API sees no change.

`/analyze` reads `refresh` with a default of false, because its request may not carry the field. The module must give the same result.

**Blocked by:** 01 — Build the request context and move `/find_by_sp` onto it.

**Status:** resolved

- [x] `/analyze` calls the module. The handler never receives a `Skipped` marker, because the handler sets no `cache_only` rule.
- [x] A request without a `refresh` field behaves as `refresh` set to false.
- [x] A Database on several hosts with no host named still answers "not scanned".
- [x] The scope comes from the module and equals the scope that the handler built before.
- [x] The `/analyze` tests use in-memory adapters through the handler call. No `/analyze` test patches `resolve_scan_roots`, `_get_scan`, or `find_cache_identity`.
- [x] A multi-folder source gives the same merged Scan and the same chosen root as before.
- [x] No API response changes.

## Comments

- Affected function: `service.analyze_service.analyze()`.
- User-visible change: none. The API responses stay unchanged.
- Pass the scan and cache adapters through the handler call.
- Keep the real cache adapter in the HTTP cache-listing integration tests.
- Keep the refresh and `/path_evidence` tests unchanged for their separate tickets.
- Verify 117 affected tests, including seven new regression cases.
- Verify the final full suite: 1666 tests pass.
- Record two existing collection errors: `test_search_roles.py` and `test_sp_tables.py` require ODBC Driver 17 for SQL Server.
- Compare type diagnostics with `19156ae`: all 64 existing diagnostics match, including 27 in the service.
- Resolve the Standards review finding by testing merge results through the handler response, not scan-object identity.
- Record zero remaining findings for the Standards and Spec reviews.
- Note the final reviews used current files because their temporary diff snapshot was unavailable.
- Retain the initial full-diff review and the final current-file review as the review record.

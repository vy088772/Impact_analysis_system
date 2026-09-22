# Retire the Legacy Dependency-Dictionary Pipeline

**Status:** Accepted
**Date:** 2026-09-22

## Context

[ADR-0001](0001-sql-execution-graph.md) replaced the SQL cache's untyped `dependencies` / `depends_on` / `depended_by` model with the AST-backed SQL Execution Graph as the sole source of SQL relationship and flow evidence. `CONTEXT.md`'s SQL Execution Graph glossary entry already lists `dependencies`, `depends_on`, and `depended_by` under _Avoid_. What ADR-0001 did not do is remove the old model's code. Three pieces stayed in the codebase after the graph replaced it, each with zero production callers, but none of them look dead:

- `SQLAnalyzer.get_all_dependencies()` (`code_analyzer/sql_analyzer.py`) queries `sys.sql_expression_dependencies` and builds the old `depends_on`/`depended_by` dict, with a full docstring describing what it does. `SQLAnalyzer.dump_all_sql_objects()` — the method that actually assembles a SQL cache payload — never calls it. It has had no production caller since the graph replaced it, not because some caller was later removed.
- `service/dependency_fetcher.py`'s `fetch_dependencies()` is not a reader of the old dict. Its own docstring says formal callers must query the SQL Execution Graph directly, and that it "never turns those legacy indexes into formal lineage." It takes a `graph` argument and recomputes the old `depends_on`/`depended_by` shape from graph nodes and relationships, purely as a migration-comparison adapter. Its only caller was a test asserting that formal output consumers no longer depend on legacy relations — the adapter was already graph-backed, and nothing in the codebase needs the legacy shape it produced.
- `_without_legacy_dependency_fields()` (`service/sql_cache_store.py`) runs inside `get_or_dump(..., refresh=True)`, right after `dump_all_sql_objects()` builds the payload and before that payload is persisted. It pops `dependencies` and `write_dependencies` from the payload. Since `dump_all_sql_objects()` never sets those keys, this call strips fields that are never present in current production output — but a dedicated test proves its purpose is real: it is a defense-in-depth guard. If whatever assembles the cache payload is ever swapped or changed and reintroduces those field names, this is the check that stops them from reaching the persisted cache. It was not incidental dead code swept up alongside the other two; it is a guard whose triggering condition just happens not to hold today.

Reading this code gives no signal that all three are unreachable from the graph-only pipeline. One has a full docstring, one has a dedicated regression test with a hand-built graph fixture, and one is exercised by an integration test that builds a fake payload specifically to prove it works.

A related claim needs correcting here, not repeated: this retirement does **not** "drop one live schema query per refresh." `get_all_dependencies()`'s `sys.sql_expression_dependencies` query was already unreachable from the refresh path before this decision — `dump_all_sql_objects()` never called it. Removing unreachable code removes no query that was running.

## Decision

Delete all three pieces:

- `SQLAnalyzer.get_all_dependencies()` and its docstring.
- `service/dependency_fetcher.py` in full. Do not preserve any part of its graph-walking logic elsewhere — nothing in the codebase needs the legacy `depends_on`/`depended_by` result shape, and the SQL Execution Graph is the sole source callers should query directly.
- `_without_legacy_dependency_fields()` and its one call site in `get_or_dump()`.

The regression coverage for the invariant the scrubber protected — a SQL refresh never persists the old `dependencies`/`write_dependencies` field names — stays at the same seam, `sql_cache_store.get_or_dump()`'s refresh/dump integration test, so a future change to the cache-writing path is still caught if it reintroduces those field names. The test no longer names the deleted scrubber function; it asserts on the persisted payload's shape instead.

No `_SQL_CACHE_VERSION` bump accompanies this change. The shape `dump_all_sql_objects()` produces is unchanged — the scrubber removed here was already a no-op against that shape in production, so this is not a cache-format change. The version-history comment's v3/v4 entries (which introduced the now-fully-removed `dependencies` and `write_dependencies` fields) are condensed into one line pointing at this ADR, so a reader debugging a cache file stamped v3 or v4 can still find out what those versions once held and why they were removed. The version numbering sequence stays intact and unbroken.

## Consequences

- `code_analyzer/sql_analyzer.py` and `service/sql_cache_store.py` now expose only methods with live production callers. An engineer reading either file no longer has to trace call graphs to find out whether a documented, test-covered method is actually reachable.
- The codebase has exactly one producer of SQL relationship evidence: the SQL Execution Graph. `service/dependency_fetcher.py`'s removal closes off the one place an engineer could otherwise reach for the superseded `depends_on`/`depended_by` shape.
- The defense-in-depth guard this decision removes is a real trade-off, not a pure cleanup. If a future change to the cache-writing path reintroduces `dependencies` or `write_dependencies` field names into a payload, nothing at the `sql_cache_store` layer strips them before they reach disk anymore. The integration test at `get_or_dump()`'s refresh/dump seam is what now carries that invariant — it is expected to fail loudly if a future payload producer regresses this.
- This retirement drops no live schema query. `get_all_dependencies()`'s `sys.sql_expression_dependencies` query was already unreachable from the refresh path before this decision; nothing about `/refresh_sql`'s live-query behavior changes.
- A future reader who finds `get_all_dependencies`, `dependency_fetcher`, or `_without_legacy_dependency_fields` in git history should conclude: these were already unreachable from the graph-only pipeline by the time they were deleted, not victims of a caller being removed elsewhere. The scrubber in particular was a working guard against a scenario that never occurred in production — its removal is a decision to accept that risk at this layer, made in favor of keeping equivalent coverage at the integration-test seam instead of in production code with no reachable trigger.
- This decision does not touch the FK resolver, `sp_fetcher`'s live-query fallback removal, or any other decision recorded in [ADR-0011](0011-remove-live-query-fallbacks.md) — those are unrelated code paths. It also does not touch `quick_analyze_sp`'s regex-based table-guessing fallback or `_get_native_referenced_tables()`, which remain a different, still-live fallback mechanism for single-object analysis.

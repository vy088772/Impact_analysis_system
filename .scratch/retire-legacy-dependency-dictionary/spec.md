# Retire the Legacy Dependency-Dictionary Pipeline

Status: ready-for-agent

## Problem Statement

The SQL Execution Graph (ADR-0001) replaced the untyped `dependencies` / `depends_on` / `depended_by` model as the sole source of SQL relationship evidence. The project's glossary already reflects this: `CONTEXT.md`'s SQL Execution Graph entry lists `dependencies`, `depends_on`, and `depended_by` under Avoid.

The old model's producer, a compatibility adapter, and a scrubber that used to run against its output all stayed in the codebase after the replacement, each with zero production callers:

- The producer queries `sys.sql_expression_dependencies` and builds the old `depends_on`/`depended_by` dict. The code that assembles a SQL cache payload never calls it.
- The compatibility adapter is not a reader of the old dict — its own docstring says formal callers must query the graph and that it never turns the old indexes into formal lineage. It takes a graph argument and computes the old result shape from graph nodes and relationships. Its only caller was a test asserting that formal output consumers no longer depend on legacy relations.
- The scrubber stripped the old dict's field names from a freshly-produced cache payload before it reached disk. Since the producer step it ran after never sets those field names, it strips fields that were never present in current production output — but a dedicated test proves it as a defense-in-depth guard: if whatever assembles the cache payload is ever swapped or changed and reintroduces those field names, the scrubber is what stops them from reaching the persisted cache.

An engineer reading this code today has no way to tell, from the code alone, that all three pieces are already unreachable from the graph-only pipeline. They look alive: one has a full docstring, one has a dedicated regression test with a hand-built graph fixture, and one is exercised by an integration test that builds a fake payload specifically to prove it works.

## Solution

Delete the producer, the compatibility adapter, and the scrubber. Update every test that currently exercises them so the suite continues to pass and continues to guard the invariants that still matter — the old field names and shape must never reach a caller or a persisted cache — without needing the deleted code, and without keeping tests that only prove a scenario no code path can produce anymore. Record the decision as an ADR, since the deletion is a real trade-off (removing a defensive guard, not just dead code) that a future reader could reasonably question.

## User Stories

1. As a maintainer reading `code_analyzer/sql_analyzer.py`, I want the class to expose only methods with live production callers, so that I don't have to trace call graphs to find out whether a well-documented method is actually reachable.
2. As a maintainer reading `service/sql_cache_store.py`, I want the module to hold only the logic the current cache-writing path actually needs, so that the file reflects what the pipeline does today.
3. As an engineer onboarding onto the SQL Execution Graph, I want the codebase to have exactly one producer of SQL relationship evidence, so that I don't find a second, unreachable producer and wonder which one is authoritative.
4. As an engineer who might otherwise reach for the old `depends_on`/`depended_by` shape, I want that compatibility adapter removed, so that I'm not tempted to build against a shape the graph has already superseded.
5. As a code reviewer looking at this deletion later, I want an ADR that explains why a documented, test-covered method and a defensively-guarded scrubber were removed together, so that I don't assume the deletion was careless and try to revert it.
6. As an engineer debugging a SQL cache file stamped with an old `cache_version` of 3 or 4, I want the version-history comment in `sql_cache_store.py` to still tell me what those versions once held, so that I'm not left guessing what changed.
7. As a maintainer running the test suite after this change, I want no test to assert that a scrubbing step removes fields from a payload, when no code in the repository can produce a payload with those fields anymore, so that the suite doesn't carry an assertion with no real scenario behind it.
8. As a maintainer running the test suite after this change, I want the existing regression coverage for "a SQL refresh never persists the legacy dependency fields" to still exist at the same seam it runs at today (`sql_cache_store.get_or_dump()`), so that a future change to the cache-writing path is still caught if it reintroduces those field names.
9. As an engineer who reads `docs/進階手冊.md`'s architecture map, I want it to list only files that exist, so that the map doesn't send me looking for a module that was deleted.
10. As an engineer reviewing the PR/commit for this change, I want the stated benefits (line count, dropped query) to be accurate, so that I can trust the rationale without re-verifying it myself.
11. As a future maintainer of `code_analyzer/sql_analyzer.py`'s `dump_all_sql_objects()`, I want no vestigial test stub referring to a method that no longer exists on the class, so that I'm not misled into thinking that method is still part of the object's contract.
12. As an engineer who searches the codebase for `dependencies`, `depends_on`, or `depended_by` as SQL relationship terms, I want zero production code matches, so that the glossary's Avoid list (already true in `CONTEXT.md`) is also true of the code.

## Implementation Decisions

- Delete the producer method on the SQL analyzer class that queries `sys.sql_expression_dependencies` and builds the old `depends_on`/`depended_by` dict. It has zero production callers; the code that assembles a SQL cache payload does not call it.
- Delete the `dependency_fetcher` compatibility-adapter module in full. It has zero production callers. Do not preserve any part of its graph-walking logic elsewhere — nothing currently needs the old `depends_on`/`depended_by` result shape, and the SQL Execution Graph is the sole source callers should query directly.
- Delete the scrubber function in `sql_cache_store` that strips the old field names from a freshly-produced cache payload before it's persisted, and its one call site in the refresh/dump path.
- No `_SQL_CACHE_VERSION` bump is needed. The shape `dump_all_sql_objects()` currently produces is unchanged by this deletion — the scrubber it removes was already a no-op against that shape in production. Do not treat this as a cache-format change.
- In the `_SQL_CACHE_VERSION` history comment, condense the two lines documenting versions 3 and 4 (which introduced the now-fully-removed `dependencies` and `write_dependencies` fields) into a single line. Keep the version numbering sequence (v2 through v10) intact and unbroken — do not delete the v3/v4 entries outright. Point the condensed line at the ADR this spec asks for, so a reader debugging a cache file stamped v3 or v4 can still find out what those versions held and why they were removed.
- Update the architecture-map documentation (`docs/進階手冊.md`) to remove the line describing the deleted compatibility-adapter module.
- Write an ADR recording this decision. Base it on the existing ADR that removed the two live-query fallbacks in `sp_fetcher`/`fk_resolver` (same repo, same shape of decision: identify an already-unreachable path, remove it, document why non-obviously). Reference the ADR that originally introduced the SQL Execution Graph as the replacement this decision completes. The ADR should correct, not repeat, the claim that this change drops a live schema query per refresh — verify against `dump_all_sql_objects()` first; that query is not running today regardless of this change.
- The commit/PR description for this change should not claim it "drops one live schema query per refresh." That claim does not hold: the query in question is already unreachable from the refresh path before this change, independent of whether the deletion happens.

## Testing Decisions

A good test here proves an external behavior of the cache-writing or cache-reading path, not the internal existence of a helper function. Prefer the highest existing seam over inspecting removed internals directly.

- **`service/sql_cache_store.py`'s refresh/dump integration test** (prior art: the existing test that builds a fake SQL-analyzer-like object, calls `get_or_dump(..., refresh=True)`, and asserts on the returned/persisted payload) is the seam for proving "a SQL refresh never persists the old dependency field names." Update the fake payload this test builds so it no longer includes the old `dependencies`/`write_dependencies` fields, and drop the assertions that check for their absence — asserting the absence of fields no code path can produce anymore tests nothing. Keep the rest of this test (graph construction, node/relationship shape) unchanged; it doesn't depend on the deleted fields.
- **The existing test that exercises `SQLAnalyzer.dump_all_sql_objects()` directly** (prior art: the test asserting later `SQLAnalyzer` methods stay on the class after progress-reporting was added) is the seam for the deleted producer method. It never needed to call the producer — remove only the now-pointless stub line that assigned a replacement for it; the test's own assertions are unaffected.
- **The formal-output-migration test file** (prior art: `tests/test_formal_output_migration.py`, whose stated purpose is checking that formal output consumers no longer depend on legacy relations) is the seam for the deleted compatibility adapter. Delete the one test function that imported and exercised it, and its now-dangling import. Do not touch the file's other tests — they exercise unrelated modules (`sp_fetcher`, `DependencyGraphGenerator`) and don't import the deleted adapter.
- No new test seam is needed anywhere in this change. All four touch points above are modifications to existing seams, not new ones.

## Out of Scope

- Any change to the FK resolver, `sp_fetcher`'s live-query fallback removal, or any other decision already recorded in ADR-0011 — unrelated code paths.
- Any change to `quick_analyze_sp`'s regex-based table-guessing fallback, or to `_get_native_referenced_tables()` — these are a different, still-live fallback mechanism for single-object analysis, not part of the retired whole-schema dependency-dictionary pipeline.
- Verifying against a live database that the retired producer's query was in fact never reachable in production outside of this repository's own code paths (e.g., no external script or notebook calling it). This spec covers only what's reachable from within this repository.
- Any new consumer of the SQL Execution Graph, or any change to what the graph itself covers.
- A pre-existing, unrelated test failure in `tests/test_formal_output_migration.py::test_dependency_graph_renderer_ignores_legacy_sp_relations` (an `edges` key-shape mismatch: `source`/`target` vs. `from`/`to`/`weight`). Confirmed present before this change too — do not fix it as part of this work.

## Further Notes

- This is an internal dead-code/tech-debt removal with no user-facing (API, CLI, or output-format) behavior change. Every consumer-visible behavior — what a SQL cache refresh persists, what a cache read returns — is unchanged; only unreachable code and the tests that (accurately or not) exercised it are removed.
- Two claims in the originating proposal needed correction against the actual code, not just against intent, before this spec was written:
  1. "Drops one live schema query per refresh" — false. The query was already unreachable from the refresh path.
  2. "The old producer, reader, and scrubber all stayed" (implying the compatibility adapter reads the old dict) — imprecise. The compatibility adapter was already graph-backed; it read the graph, not the old dict, and refused to fall back to it. It was dead by lack of callers, not by reading stale data.
- The scrubber's true role (a defense-in-depth guard against a future/alternate producer reintroducing the old field names, not a no-op against today's producer) was discovered only after an initial implementation pass got flagged by its dedicated test. Whoever implements this spec should keep the guard's intent alive at the seam named in Testing Decisions, even though the guard's implementation is deleted — the invariant it protects ("the persisted cache never carries the old field names") should stay provable from the test suite.

# 04 — Delete the cache-write scrubber and condense the v3/v4 cache-version history

**What to build:** Remove the function in `sql_cache_store` that strips the legacy `dependencies`/`write_dependencies` field names from a freshly-produced cache payload before it's persisted, and its one call site in the refresh/dump path. This scrubber is a defense-in-depth guard, not a pure no-op: a dedicated integration test proves it by feeding a fake payload that still carries the legacy fields and asserting they never reach the persisted cache. That test's intent — the persisted cache must never carry the legacy field names — must survive this change even though the scrubber implementation doesn't; update the test's fake payload and its two legacy-field assertions accordingly rather than deleting the coverage outright.

Also condense the `_SQL_CACHE_VERSION` history comment's two lines documenting versions 3 and 4 (which introduced the now-fully-removed fields) into a single line pointing at ADR-0031, keeping the v2-through-v10 numbering sequence unbroken.

**Blocked by:** 01 — Write ADR-0031 retiring the legacy dependency-dictionary pipeline (the condensed v3/v4 comment line cites this ADR by number; it needs to exist first so the citation resolves).

**Status:** done

- [x] The scrubber function and its one call site in the refresh/dump path are deleted.
- [x] No `_SQL_CACHE_VERSION` bump is made — the payload shape the current producer emits is unchanged by this deletion.
- [x] The refresh/dump integration test's fake payload no longer includes the legacy `dependencies`/`write_dependencies` fields; the four assertions checking their absence are replaced with two payload-shape assertions per ADR-0031 (see Note — this ticket's literal checklist wording ["...are removed"] conflicts with the ADR's decision text, which wins); the rest of that test (graph construction, node/relationship shape) is unchanged.
- [x] The `_SQL_CACHE_VERSION` history comment's v3 and v4 entries are condensed into one line referencing ADR-0031, with the v2-through-v10 numbering sequence still intact and unbroken.
- [x] The affected test file passes.

**Note:** Deleted `_without_legacy_dependency_fields()` (was
`service/sql_cache_store.py:352-356`) and its one call site inside
`get_or_dump(..., refresh=True)`, right before `build_sql_execution_graph()` is
invoked. `_SQL_CACHE_VERSION` stayed at 10 — the current producer
(`dump_all_sql_objects()`) never emits the legacy fields, so the deletion changes
no payload shape.

**Contradicts this ticket's own checklist item 13 — corrected in favor of
ADR-0031, per AGENTS.md's "Flag ADR conflicts" rule.** The ticket text above says
to remove the two legacy-field assertions outright. ADR-0031's Decision section
says the opposite: "The regression coverage for the invariant the scrubber
protected ... stays at the same seam ... The test no longer names the deleted
scrubber function; it asserts on the persisted payload's shape instead." A first
pass here followed the ticket text literally and deleted the coverage with no
replacement — a Standards-axis review (`/code-review`) caught the gap before
commit. Fixed to match the ADR:

The dedicated integration test is
`test_sql_refresh_builds_and_reloads_typed_execution_graph` in
`tests/test_sql_execution_graph.py`. `FakeSqlAnalyzer.dump_all_sql_objects()`'s
payload dropped the `dependencies`/`write_dependencies` entries (matching what
the real producer emits post ticket 02/03). In place of the four
`assert "..." not in ...` lines, two positive shape assertions now stand: right
after `get_or_dump()`, `assert set(data.keys()) == {expected 7 top-level keys}`,
and after the mem-cache-cleared reload, `assert set(reloaded.keys()) ==
set(data.keys())`. Either would fail if a future payload producer reintroduces
`dependencies`/`write_dependencies` (or any other unexpected top-level key) into
what gets persisted — which is the invariant the deleted scrubber used to
enforce directly. Graph construction and node/relationship assertions in that
test are untouched.

Condensed the `_SQL_CACHE_VERSION` history comment's v3/v4 lines (in
`service/sql_cache_store.py`, above the version constant) into one line pointing
at ADR-0031; v2 and v5-through-v10 lines are unchanged and the sequence stays
unbroken.

Ran `tests/test_sql_execution_graph.py` (11 passed) and
`tests/test_sql_cache_store.py` (62 passed) individually, then the full suite.
16 pre-existing failures remain (ODBC-driver-dependent and live-DB-dependent
tests under `test_csharp_analysis_gateway.py`, `test_external_wrapper_discovery.py`,
`test_formal_output_migration.py`, `test_graph_reverse_lookup.py`,
`test_program_refresh.py`, `test_raw_sql_execution_command_source.py`,
`test_sqldbcontext_real_calls_resolve.py`, plus two collection errors in
`test_search_roles.py`/`test_sp_tables.py` from a missing "ODBC Driver 17 for SQL
Server" driver) — confirmed identical on the pre-change tree via `git stash`, so
none of them trace to this change.

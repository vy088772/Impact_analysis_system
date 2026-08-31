# 03 — Backfill an Object Location Index for caches already on disk

**What to build:** An operator runs one command and every SQL cache already on disk gains an Object Location Index, without re-scanning any Database over the network. The command needs no scan credentials and puts no load on any SQL Server.

This matters because of where the cost actually sits: of the five caches on disk, `PUR` is 105 MB and the other four together are under 2.5 MB. `PUR` is declared by both Systems that declare anything, so it is opened on nearly every Reverse Lookup. Without a backfill, the one cache that most needs an index is the last to get one, and the feature delivers almost nothing until somebody re-scans a 105 MB Database.

**Blocked by:** 01.

**Status:** resolved

- [x] The tool builds each index with the same shared build function the refresh path uses. There is no second way to build an index.
- [x] The tool opens no SQL Server connection.
- [x] The tool does not modify any cache content — only writes the index beside it.
- [x] The tool reports which caches it indexed and which it skipped, so an operator can confirm the rollout is complete.
- [x] Re-running the tool is safe and rebuilds the index.
- [x] Deleting an index by hand afterwards breaks nothing: the affected Database falls back to being read in full.
- [x] Tested following the prior art of the repo's existing cache-repair tool and its test.

## Implementation notes

- New `tools/backfill_object_location_indexes.py`, modeled on the existing
  `tools/repair_sql_execution_graphs.py` (same per-row result-dict shape,
  same `--dry-run`/`--cache-root` CLI flags).
- Enumeration reuses `sql_cache_store.list_caches()` (the same read-only
  directory listing `/locate_object` and `GET /scan_records` already use)
  instead of a second, hand-rolled glob — this is also what keeps the
  identity round-trip correct: `CacheIdentity.of(row.server, row.database,
  row.schema)` reproduces exactly the filename `_save()` would have written,
  the same pattern `analyze_service.locate_object()` already uses.
- Content is read via `sql_cache_store.load_cached(...)`, not a raw
  `json.loads()` of the file — this applies the exact same validity gate
  (`_load`/`_is_valid_cache`: meta present, `cache_version` current,
  `sql_execution_graph` version/scope matching) that `find_by_sp`/
  `find_by_table` already apply. A cache the query path would refuse to read
  is reported as `invalid_cache` and skipped, rather than silently indexed —
  otherwise `/locate_object` could report a Database as `matched` that the
  live read path would never actually search, breaking the "identical
  results with/without the index" guarantee (spec.md user story 5).
- A row whose `(server, database, schema)` can't even build a
  `CacheIdentity` (blank server/database) is reported as `bad_identity` and
  skipped, rather than raising and aborting the whole run — same defensive
  posture ticket 02's code review already established for `locate_object`.
- The index itself carries no independent version to compare against
  (`cache_version` only tracks the *cache* format, per ticket 01) — so
  re-running always rebuilds and overwrites; there is no "already current"
  skip branch like the graph-repair tool has, by design.
- Both the identity enumeration and the index build/write are functions
  `sql_cache_store` already exported from ticket 01/02
  (`CacheIdentity.of`, `load_cached`, `build_object_location_index`,
  `write_object_location_index`) — no new function was added to
  `sql_cache_store.py` for this ticket.
- Tests: new `tests/test_backfill_object_location_indexes.py` (9 cases),
  mirroring `tests/test_repair_sql_execution_graphs.py`'s shape: writes a
  cache via `write_cache()` (never `_save()`, so no index exists yet),
  backfills, and asserts the index matches `build_object_location_index()`'s
  own output byte-for-byte; a dedicated case monkeypatches `pyodbc.connect`
  to raise, proving the tool never opens a SQL Server connection.
- Full suite: 571 passed / 12 failed (same pre-existing baseline as ticket
  02, confirmed unchanged), up from 562/12 before this ticket.
- Code review (Standards + Spec sub-agents): no hard violations on either
  axis. Standards flagged two minor judgement-call smells, left as-is: (1)
  the CLI's result-printing loop duplicates `repair_sql_execution_graphs.py`'s
  shape (only two instances so far, not worth extracting yet); (2)
  `--cache-root` is applied by mutating `settings.SQL_CACHE_ROOT` rather than
  threading a `cache_root` parameter through — this matches how
  `tests/sql_cache_fixtures.py`'s `CacheRoot` fixture already overrides the
  same setting, not a new pattern in this codebase.

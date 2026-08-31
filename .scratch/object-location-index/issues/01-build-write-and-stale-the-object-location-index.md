# 01 — Object Location Index: build, write, and staleness

**What to build:** After a SQL cache refresh, that cache carries an Object Location Index — a small record, held under the same SQL Cache Identity, naming every object the cache can answer for. An operator who runs the existing refresh command gets the index without running a second command. A reader can decide whether an index is trustworthy without opening the cache it describes.

The index has two buckets. The stored-procedure bucket holds procedure, function, and view names, normalized by the same function `/find_by_sp` uses to compare an invocation. The table bucket holds the cache's declared table names **and** every table-like node name in the SQL Execution Graph, normalized by the same function `/find_by_table` uses. The union in the table bucket is the point: a table reached only inside a stored-procedure body is exactly what the table Reverse Lookup exists to find.

The governing rule is that the index may over-report a name but must never under-report one. A wrong inclusion costs one extra cache read; a wrong exclusion loses an answer.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] One shared build function turns a SQL cache into its Object Location Index. Ticket 03 calls the same function; there is no second implementation.
- [x] The index carries its SQL Cache Identity and the SQL cache format version.
- [x] The index is stored beside its cache, not merged into the cache metadata record — that record is the Scan Record and must keep one meaning.
- [x] A refresh writes the cache first and the index second, so an interrupted refresh leaves the index detectably older rather than quietly wrong.
- [x] One staleness rule, defined in one place: an index is absent when it is missing, unreadable, older than its cache by modification time, or built against a different cache format version.
- [x] The staleness check never reads the cache body. Hashing a 105 MB cache at query time would spend exactly what the index saves.
- [x] The table bucket includes table names that appear only as SQL Execution Graph nodes, proven by a fixture whose table is referenced only inside a stored-procedure body.
- [x] Table name normalization drops the schema, so two schemas with the same table name collapse to one key. This matches today's matching behaviour and is stated in the index's own documentation so nobody later assumes otherwise.
- [x] Tests live at the SQL cache store seam, following the prior art already used for that module.

## Implementation notes

- All new code lives in `service/sql_cache_store.py`: `ObjectLocationIndex`
  (dataclass), `build_object_location_index(identity, data)` (the one shared
  build function — ticket 03's backfill tool must call this same function,
  not reimplement it), `write_object_location_index`,
  `load_object_location_index` (the single staleness check), plus a new
  `CacheIdentity.index_filename` property (`{key}.index.json`, beside the
  cache's `.json`/`.meta.json`, never merged into the Scan Record).
- Stored-procedure bucket: `procedures`/`views`/`functions` names normalized
  by `code_analyzer.csharp_analysis_gateway.normalize_procedure_name` — the
  same function `find_by_sp` calls.
- Table bucket: declared `data["tables"]` names **union** every
  `sql_execution_graph["nodes"]` entry whose `type == "table"`, both
  normalized by `service.graph_queries._normalize_table` (imported as
  `normalize_table_name`) — the function `find_by_table` uses (via
  `query_table_accesses`) to match graph table names, so a name the index
  keeps can never be a name the endpoint would have pruned. Reused directly
  rather than duplicated: `analyze_service.py`'s own near-identical private
  `_normalize_table` could not be imported here without a circular import
  (`analyze_service.py` already imports `sql_cache_store` at module level).
- Staleness (`load_object_location_index`, one place): absent when the index
  or cache file is missing, the index is unreadable, the index's mtime is
  older than the cache's, `cache_version` doesn't match today's
  `_SQL_CACHE_VERSION`, or the index's own recorded `(server, database,
  schema)` doesn't match the identity being asked for (catches a file moved
  or renamed by hand). Only `Path.stat().st_mtime` is read on the cache file
  — its body is never opened here.
- `_save()` writes the cache + meta first, then builds and writes the index
  in a second, independent `try/except` — an index build/write failure can
  never roll back or block the already-successful cache write, and prints a
  non-fatal warning exactly like the existing cache-write failure path.
- Tests: 14 new cases added to `tests/test_sql_cache_store.py` (the file's
  existing seam), covering both buckets' normalization, the graph-only-table
  union fixture, identity/version carriage, write placement, write order, and
  every staleness branch (missing/unreadable/stale-by-mtime/version-mismatch/
  identity-mismatch) plus a dedicated test proving the cache body is never
  parsed. 48/48 passing in the file; full suite 548 passed / 12 failed, same
  pre-existing baseline failures as before this change (confirmed via `git
  stash`), see `/memories/repo/impact-analysis-system.md`.

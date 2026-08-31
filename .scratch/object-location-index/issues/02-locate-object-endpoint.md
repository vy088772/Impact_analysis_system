# 02 — `/locate_object` answers from the indexes alone

**What to build:** A caller asks one question — "which Databases could hold this name?" — and gets an answer without any SQL cache being opened. The caller sends an object name and a kind of `sp` or `table`; the kind selects which bucket to read, and therefore which name normalization applies.

The reply separates two different facts. `matched` names the Databases whose index is fresh and holds the name. `unindexed` names the Databases whose cache exists but whose index is absent by the staleness rule — the caller must read those in full, because the service cannot say. A Database with a fresh index that does not hold the name appears in neither list; that omission is the pruning, and it is authoritative.

Both lists name each Database by its full `(server, database)` identity, so a caller can match them against a Declared Database Dependency without resolving a bare name.

**Blocked by:** 01.

**Status:** resolved

- [x] The endpoint opens no SQL cache. A request that would require opening one is a bug, not a fallback.
- [x] The endpoint reads every index on disk in one request, so one call answers for every System in the catalog.
- [x] `matched` and `unindexed` are separate lists, each carrying full `(server, database)` identities.
- [x] The reply reports how many indexes were consulted, so a caller can assert the cost.
- [x] A missing, unreadable, or stale index puts its Database in `unindexed` — never in neither list, and never in `matched`.
- [x] An unknown `kind` is rejected as a bad request rather than guessed.
- [x] `/find_by_sp` and `/find_by_table` request and response shapes are unchanged, and their existing tests pass untouched.
- [x] Behaviour is tested at the analysis-service seam, following the prior art that already drives the Reverse Lookup functions directly against a fixture cache directory. The route itself gets only the thin error-translation test its prior art uses.
- [x] An ADR in this repo records the decision to treat a matching Object Location Index as authoritative and skip that cache unopened, and states why a stale index degrades to slow rather than wrong.

## Implementation notes

- `service/schemas.py`: `LocateObjectRequest` (`object_name`, `kind`),
  `LocatedDatabase` (`server`, `database` — no `schema`, matching the caller-side
  `(server, database)` identity used everywhere else, e.g. `databases_read` in
  `llamaindex-spec-rag`'s coverage report), `LocateObjectResponse` (`matched`,
  `unindexed`, `indexes_consulted`).
- `service/analyze_service.py`: `locate_object(req)`, placed beside
  `find_by_sp`/`find_by_table`. Bad `kind` (anything other than `sp`/`table`,
  case-insensitive) raises `ValueError`, translated to HTTP 400 by the route —
  the same `ValueError` → 400 pattern every other route in `api.py` already
  uses, so the route needed no new error-translation shape. Iterates
  `sql_cache_store.list_caches()` (already a read-only directory listing, no
  cache body ever opened) and calls `sql_cache_store.load_object_location_index`
  per identity; `kind="sp"` normalizes with the same
  `code_analyzer.csharp_analysis_gateway.normalize_procedure_name` `find_by_sp`
  uses, `kind="table"` with the same `sql_cache_store.normalize_table_name`
  (`= graph_queries._normalize_table`) the table bucket was built with in
  ticket 01 — reusing both rather than re-deriving them is what keeps the
  index's completeness guarantee from ticket 01 intact here.
- `service/api.py`: `POST /locate_object` route, same try/except shape as
  `/find_by_sp`/`/find_by_table` (`ValueError` → 400, anything else → 500).
- **Bug found and fixed, in scope:** `sql_cache_store.list_caches()` globbed
  `*.json` and only excluded names ending in `.meta.json` — it did not exclude
  `.index.json` (ticket 01's new suffix), which also ends in `.json`. Once a
  cache has an index (every cache saved through `_save()` since ticket 01
  does), `list_caches()` silently double-counted it as a second, malformed
  "cache" (stem parsed as `...__dbo.index`, no sibling meta file). This broke
  `locate_object`'s `indexes_consulted` count and its matched/unindexed split
  outright (discovered via a failing acceptance test in this ticket, not
  anticipated by ticket 01's own tests, which never built a real index file
  and then called `list_caches()` in the same test). It would also have
  quietly corrupted `GET /scan_records`'s listing for any cache with an index
  attached. Fixed by adding `.index.json` to `list_caches()`'s existing skip
  check alongside `.meta.json`; regression test added to
  `tests/test_sql_cache_store.py`
  (`test_list_caches_never_lists_an_object_location_index_file_as_a_cache`).
- Tests: new `tests/test_locate_object.py` (13 cases) using the existing
  `tests/sql_cache_fixtures.py` `CacheRoot`/`write_cache` helpers (prior art:
  `tests/test_sql_cache_store.py`, `tests/test_repair_sql_execution_graphs.py`)
  to build real on-disk cache+index pairs — matched, pruned (fresh index, no
  match), missing index, stale index (backdated mtime), multi-cache single-call
  coverage, `sp` and `table` kind normalization (including the graph-only-table
  union case from ticket 01), case-insensitive `kind` matching, bad `kind`
  rejection, a stray file with an incomplete cache identity (tolerated, not a
  crash — a code-review finding, see below), and a dedicated test that
  monkeypatches `sql_cache_store._load` to raise if ever called, proving the
  endpoint never opens a cache body. Route gets 2 thin tests (bad `kind` →
  400, pass-through), matching `tests/test_path_evidence_api.py`'s pattern.
  Plus 1 new regression test for the `list_caches()` fix below.
  `docs/openapi/openapi.json` regenerated via
  `python -m tools.export_openapi_schema` to include the new route (existing
  `tests/test_export_openapi_schema.py` guards this).
  Full suite: 562 passed / 12 failed (same pre-existing baseline names as
  before this change, confirmed unchanged), up from 548/12 before this ticket.
- **Code-review finding, fixed:** `CacheIdentity.of()` raises `ValueError` on
  an empty server/database — but `list_caches()`'s own docstring guarantees it
  lists even a file whose name doesn't fit the `{server}__{database}__{schema}`
  shape (an incomplete/malformed cache identity), rather than silently
  omitting it. The first draft of `locate_object` let that `ValueError`
  propagate uncaught, so one stray malformed file anywhere in the cache
  directory turned the *entire* `/locate_object` request into an HTTP 400 for
  every object name, indistinguishable from an actual bad-`kind` error. Fixed
  by skipping (not counting, not listing) a row whose identity can't be
  constructed — it isn't a cache this endpoint can answer for in either
  direction — instead of crashing the whole request.

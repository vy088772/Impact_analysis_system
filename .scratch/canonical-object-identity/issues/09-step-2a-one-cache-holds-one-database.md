# 09 — Step 2a: one SQL cache holds one Database

**Spec issue:** 5, the identity commit

**What to build:** The SQL Cache Identity becomes server and database, and the
cache filename has two parts. An operator runs one refresh per Database with no
schema option. Every cache written before this change invalidates itself.

See "One SQL cache holds one Database" in the spec. It lists every site this
commit changes.

**Blocked by:** 08

**Status:** done (2026-09-29), except the operator gate in the last item

- [x] The identity loses its schema field. Its filename compose and its reverse parse change in one edit.
- [x] Every site in the spec's list changes: the meta writer's `schema` field and its comparison, the Object Location Index's `schema` field and its comparison, the cache listing row and its sort key, the `db_schema` field on `/scan_records`, the backfill tool's report field, the data status tool's presence check, and the object location lookup's loop.
- [x] The refresh entry point loses its schema parameter. `db_schema` leaves the refresh request and the refresh response.
- [x] The refresh CLI loses its schema option.
- [x] The SQL cache format version rises.
- [x] The grep check passes: a search of the service code and the tool code for a schema read from an identity or a cache listing row returns nothing.
- [x] The three object location tests that state two caches for one Database are deleted.
- [x] The `sql_cache_identity` list states two-part filenames. The `__` case uses a two-part filename and keeps its assertion.
- [x] The advanced manual example that sends the removed request field changes.
- [x] The `CONTEXT.md` SQL Cache Identity entry states a two-part identity.
- [x] The `sample_cache` entry is regenerated.
- [x] The whole suite of this repository passes.
- [x] After this ticket, an operator refreshes `EFNETDB` on another machine and copies the file here. The Step 2a gate is met when that file holds an object whose schema is not `dbo`. No agent runs a refresh. (Met: the code review after issue 13 opened `data/sql_cache/vmsystest07.topmost.com.tw__EFNETDB.json`, cache version 11, saved 2026-09-29 14:07. It holds tables in `HR` (11), `COMMON` (3), and `Finance` (1). The file holds no procedure, View, or Function.)

## Notes

- **Refresh CLI.** The refresh CLI is in `llamaindex-spec-rag`, not in this
  repository. Its `--schema` option and the orchestration client's `db_schema`
  belong to ticket 10. This repository has no schema option to remove. The
  service still accepts an old client body, because the request model ignores
  the unknown `db_schema` key.
- **Old caches.** A cache under a three-part filename never loads: the format
  version is 11, and the meta file has no `schema`. The files stay on disk.
  `list_caches()` still lists them by their meta content, and the object
  location lookup reports such a Database as unindexed. A new test states that
  a three-part file is not the cache of its Database. An operator may delete
  the old files after the refresh.
- **Object location lookup.** The merge by server and Database stays as dead
  code. Ticket 11 removes it. The docstring says so.
- **Documents.** ADR-0009 still says `(server, database, schema)`. Ticket 12
  does not list it yet. Add it there.
- **Other documents changed here.** `CONTEXT.md` entry, the advanced manual
  example, the two lines of the advanced flow chart, `openapi.json`.
- **sample_cache.** Only the meta file changed: version 11, no `schema`.
- **Suite.** `pytest tests/ --ignore=tests/test_search_roles.py
  --ignore=tests/test_sp_tables.py`: 1109 passed, 16 failed. The same 16 as ticket
  08. In a worktree at `c563b7e`, 12 of them fail; the four path-dependent ids
  fail in the main tree only. No new failure.
- **mypy.** No error in `sql_cache_store.py`, `schemas.py`, or the two tools.
- **Review.** No hard finding. The `CacheIdentity.of(...) if db_server else
  find_cache_identity(...)` ternary repeats four times, as before. Left as is.

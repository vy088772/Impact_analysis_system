# 03 — The SQL Cache Identity is the only way to name a SQL cache

**Spec issue:** 2

**What to build:** Every cache-store function takes a SQL Cache Identity, and
the cache store alone decides which files in the cache directory are caches.
The graph repair tool then runs to the end over the cache directory as it
stands. Today it raises on its first file. That is the one behaviour change.
After this ticket, Step 2a removes the schema part in one value type.

See "The SQL Cache Identity module" and "The SQL Cache Identity, over a
temporary cache root" in the spec.

**Blocked by:** 02 (the whole ticket, not one commit)

**Status:** done

- [x] Commit 1 adds the one directory listing. It returns one row per candidate file: the data file's path and the identity that names it. The two sibling suffixes produce no row. A file whose name states no identity produces a row with an empty identity.
- [x] The listing decides an identity by a round trip: parse the stem, build an identity, compose its data filename, and compare.
- [x] Commit 1 moves the repair tool, the cache listing, and the server reverse-derivation onto that listing. The repair tool keeps no suffix list, loses its cache-root argument, and reports and skips a row with an empty identity.
- [x] Commit 2 makes every public cache-store function take an identity. The reader, the saved-at reader, the presence check, and the whole-database dump lose their loose arguments.
- [x] A caller that knows no server gets one from a separately named function. It returns nothing when no cache names that Database, and the ambiguous-server case is a returned value.
- [x] The identity's constructor stays pure. The identity's `dbo` default is removed.
- [x] The reverse parse is a method of the identity, beside the forward compose. It returns nothing for a stem that names no identity.
- [x] The server reverse-derivation matches on the identity's Database field and composes no suffix.
- [x] The in-memory cache is keyed by the identity. The meta writer loses its path argument.
- [x] `/scan_records` reports exactly the fields it reports today. A file with no identity stays listed under its stem. A hand-edited Scan Record still produces a row.
- [x] The index backfill tool, the data status tool, and the object location lookup move onto the identity.
- [x] The one-off key-migration tool, its test, and its two manual entries are deleted.
- [x] `CONTEXT.md`'s SQL Cache Identity entry gains the sentence that the identity owns its three filenames and that the cache store alone answers which files are caches.
- [x] New cases: the ambiguous server; the reverse parse of a three-part stem and of a stem that names none; the directory listing over all three files; a Database name that holds `__`; a repair run beside an index written by the real index writer.
- [x] The repair tool's test file uses the shared cache-root helper. Setup literals move to the identity, and assertion literals stay.
- [x] Every existing test returns the same result before and after. The only new behaviour is the repair run that now finishes.

## Notes (implementation)

- Commit 1 `fix(sql-cache): one directory listing decides which files are caches`
  touched `service/sql_cache_store.py`, `tools/repair_sql_execution_graphs.py`,
  `tests/test_sql_cache_store.py`, `tests/test_repair_sql_execution_graphs.py`.
- The directory listing is `sql_cache_store.list_cache_files()`. Each row is a
  `CacheFile(data_path, identity)`. The reverse parse is
  `CacheIdentity.from_key(stem)`.
- A `list_caches()` row for a file with no identity lists `server=""`,
  `database=<stem>`, `schema=""`. The Scan Record fields still override those
  values as written. (Commit 1 also added an `identity` field to the row. The
  review commit removed it, because no caller needs it.)
- The server reverse-derivation compares the safe-named Database and schema
  parts without case. The cache directory sits on a Windows file system, and the
  old glob matched without case there.
- The repair tool reports an unrecognised file as `bad_identity`, with the label
  the backfill tool prints (`⚠️  身分無法辨識，略過`).
- Commit 2 `refactor(sql-cache): every cache-store function takes a SQL Cache Identity`
  touched the store, `service/analyze_service.py`, the three fetchers
  (`sp_fetcher`, `view_fetcher`, `udf_fetcher`), the backfill and data status
  tools, `CONTEXT.md`, `docs/進階手冊.md`, `tests/sql_cache_fixtures.py`, and 22
  test files. It deleted `tools/migrate_sql_cache_keys.py`.
- `get_or_dump(identity, *, connection_server, ...)` keeps the raw connection
  server. `normalize_server()` drops a named-instance suffix, and the connection
  needs that suffix.
- The server-less lookup is `find_cache_identity(database, schema)`. It returns
  `None`, a `CacheIdentity`, or an `AmbiguousServer(database, schema, servers)`.
  Each of the seven reader sites states the branch
  (`CacheIdentity.of(...) if db_server else find_cache_identity(...)`).
- The object location lookup and the backfill tool still build an identity from
  the cache listing row (the Scan Record fields). Commit 2 moved them onto the
  filename identity, and the review commit moved them back (see below).
- `tests/sql_cache_fixtures.write_legacy_cache` is deleted (only the migration
  tests used it). The new helper `one_server_holds_every_database` stands in for
  the server lookup in the tests that stub the reader.
- Suite proof: full-suite pass/fail lists before and after are the same, except
  the new cases and the deleted dbo-default and migration tests. The 16 failures
  and 2 collection errors exist in the baseline too.
- Review commit `fix(sql-cache): keep the caller's Database name in the server lookup`:
  - `find_cache_identity()` takes only the server from the filename. It builds
    the identity from the caller's own database and schema. The filename holds
    a `_safe_name()` Database (`Y Docs` becomes `Y_Docs`), and the loader
    compares the cache's own Database name. Before the fix, a server-less read
    of `Y Docs` found no cache. The new case
    `test_a_caller_without_a_server_reads_a_database_whose_name_the_filename_rewrites`
    covers it.
  - The object location lookup and the backfill tool are back on
    `CacheIdentity.of(row.server, row.database, row.schema)`, so their answers
    stay as they were for such names.
  - `write_cache` asserts that its `cache_root` is the settings root, because
    the meta writer now writes there.
- Decision (user, 2026-09-24): `get_or_dump` keeps a separate
  `connection_server`, and no check compares it with `identity.server`. The only
  caller (`refresh_sql_source`) builds both from one `server` value, so the two
  cannot disagree today.

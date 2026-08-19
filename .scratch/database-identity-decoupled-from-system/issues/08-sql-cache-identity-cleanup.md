# 08 — Tidy Up the Cache-Identity Module After Its Reviews

**Repo:** `Impact_analysis_system`
**Spec:** `.scratch/database-identity-decoupled-from-system/spec.md`
**ADR:** `docs/adr/0009-sql-cache-identity-decoupled-from-system.md`

**What to build:** The follow-ups the ticket 02 code review raised and ticket 02 did not act on. No behaviour the analyst sees changes here, with one exception called out below — this is the module's shape, its documentation, and one leftover transitional crutch.

**Blocked by:** 03 (it is actively editing the same public functions; changing their signatures underneath it would conflict)

**Status:** done

## Decide first

- [x] `normalize_server()` lowercases its result, but ticket 02's criterion says "a hostname that already contains `.` is unchanged" — the code and the written rule disagree, and a test currently locks the lowercasing in. Settle it one way and make code, test, and ADR-0009 agree. **Recommended: keep the lowercasing and amend the wording**, because hostnames are case-insensitive and a `VMSYSTEST07` in one Web.config must not produce a second cache file beside `vmsystest07`'s. The alternative is dropping `.lower()`, which makes the rule literally true but lets one server hold two cache identities.
      **Settled:** kept the lowercasing. ADR-0009's Decision now states it, and `test_hostname_case_does_not_change_the_normalized_server` keeps locking it.

## Correctness of what the code says about itself

- [x] `get_or_dump()`'s docstring claims "`database`：顯示用簡稱；不參與快取鍵計算", but `db = str(db_name or database or "")` then keys the cache by `db` — when `db_name` is omitted, `database` *is* the key. Either drop the fallback (the `/refresh_sql` endpoint already rejects an empty `db_name`, so nothing relies on it) or correct the docstring. Prefer dropping the fallback.
      **Done:** fallback dropped; an empty `db_name` now raises before any connection attempt, so the docstring is true.
- [x] `CONTEXT.md` gains the term for the cache identity itself — the normalized `(server, database, schema)` triple. Today the concept exists in ADR-0009 and in code (`normalize_server`, `cache_key`, `resolve_server`) but has no glossary entry; `Uncataloged Database` only links the ADR.

## Retire the transitional crutch

- [x] `resolve_server()` back-resolves a server by globbing the cache directory, which makes one lookup's result depend on what *other* files sit in that directory. It exists because callers had no server to pass. `/analyze` and `/path_evidence` requests already carry `db_server`, so thread it through `analyze_service.py`'s read path (`_execution_sql_context`, `_require_sql_execution_graph`) and the fetchers into `load_cached(..., server=...)`.
- [x] Once every in-repo caller passes a server, decide whether `resolve_server()` still earns its place. If it stays, it stays for a named caller, not "in case someone needs it".
      **Settled: it stays**, for three callers whose requests carry no server and which this ticket does not widen: `/find_by_sp` and `/find_by_table` (`FindBySPRequest`/`FindByTableRequest` have no `db_server` field) and the refresh path's `reconcile_refresh_wrappers()` → `load_sp_catalog()` (plus `tools/discover_external_wrappers.py`). Its docstring names them; every other call site now passes a server.

## Shape

- [x] The triple travels as three loose strings through `cache_key`, `cache_filename`, `_paths`, `_load`, `_save`, `_is_valid_cache`, and `LEGACY_CACHE_SCOPES`, in three different argument orders (`(server, database, schema)`, `(database, schema, server="")`, `(server, database, schema)`). Give it one type and one order.
      **Done:** `sql_cache_store.CacheIdentity` (frozen, built by `CacheIdentity.of()`, which normalizes and validates). Every internal function now takes that one value; `LEGACY_CACHE_SCOPES` entries are a `Scope` NamedTuple that hands one out. The public `load_cached`/`has_cache`/`get_or_dump` signatures are unchanged — they were not among the offenders.
- [x] The cache filename shape is spelled three times — `cache_filename()`, `_paths()`, and `resolve_server()`'s glob suffix each rebuild it. One of them should be the source of truth.
      **Done:** `_KEY_SEPARATOR`/`_DATA_SUFFIX`/`_META_SUFFIX` plus `_key_of()` are the one spelling; `CacheIdentity.filename`, `_paths()`, and `resolve_server()`'s suffix all derive from them.
- [x] `cache_filename()` has no caller outside its own test. Either give it the callers that justify it or delete it.
      **Done:** deleted as a free function; it lives on as `CacheIdentity.filename`/`.meta_filename`, called by `_paths()` and by the migration script.
- [x] `tools/migrate_sql_cache_keys.py` rebuilds `_save()`'s meta-file dict by hand and reads the private `sql_cache_store._SQL_CACHE_VERSION`. Expose one meta-writing seam in `sql_cache_store` and have the migration use it, so the meta format lives in one place.
      **Done:** `sql_cache_store.write_meta()` (backed by the private `_meta_payload()` helper, which has no caller outside it); `_save()` and the migration both go through `write_meta()`, and the migration keeps the legacy file's `saved_at` because a rename is not a re-scan.

## Tests

- [x] `tests/test_sql_cache_store.py`'s `_write_legacy_cache()` is used to write *new-key* caches too; rename it for what it does.
      **Done:** now `write_cache(cache_root, key, payload, cache_version=None)` in the shared fixture module.
- [x] `tests/test_sql_execution_graph.py` still hand-rolls the cache-root/mem-cache save-and-restore boilerplate five times, which `tests/test_sql_cache_store.py`'s `_CacheRoot` context manager already does. Share one.
      **Done:** both files now import `CacheRoot` and `write_cache` from the new `tests/sql_cache_fixtures.py`.
- [x] `tests/test_sql_cache_store.py`'s two `try/except ValueError` + `raise AssertionError` blocks become `pytest.raises`, matching the rest of `tests/`.

## Deliberate deviations

Two things this ticket asked for that the work knowingly did not do, both settled by the code review of this ticket:

- **`load_cached()`/`has_cache()` keep the `(database, schema, server="")` order**, which the Shape bullet lists as one of the three. `CacheIdentity` and the one order `(server, database, schema)` govern everything where all three parts are required. On the public read API the server is genuinely optional — it is the one parameter a caller may not have — so it stays last with a default. Moving it first would force ~40 call sites and test doubles to pass `""` positionally to say "I don't know".
- **A `db_server` that does not normalize to the cached server is now a miss, not a rescue.** Before, `resolve_server()` would still find the single cache on disk. That is the directory-dependence the ticket set out to retire, so the stricter lookup is the point rather than a regression — but it is a behaviour change beyond the `get_or_dump` exception the ticket called out. `normalize_server()` already folds case, the named-instance suffix, and the bare/FQDN split, so only a genuinely different spelling (an IP, say) reaches it.

## Comments

Raised by the two-axis review of ticket 02 (`6732c30`). Two findings from that review are deliberately **not** in this ticket: the PUR cache's identity-string rewrite (a documented, necessary deviation from "byte-for-byte" — the old file stored a `system_id`, so the reader would have rejected it), and the migration script's `--dry-run`/`--cache-root`/idempotency extras (beyond what the spec asked for, but they cost nothing to keep and the script is one-off).

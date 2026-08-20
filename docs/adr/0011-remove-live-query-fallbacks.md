# Remove the Live-Query Fallbacks from the Stored-Procedure Fetcher and the FK Resolver

**Status:** Accepted
**Date:** 2026-08-20

## Context

A SQL cache (`sql_cache_store.py`) is a copy of one Database, built by `/refresh_sql`. Two components treated a gap in that copy as a reason to open a live database connection instead of reporting the gap:

- `service/sp_fetcher.py`'s `_from_live_query()` queried the live database for any stored-procedure name the cache didn't hold.
- `service/fk_resolver.py`'s `_fetch_fk_pairs()` queried `sys.foreign_keys` on the live database whenever no SQL cache existed at all.

Both fallbacks hid a stale or missing cache behind a best-effort live answer instead of surfacing that the cache needs a new `/refresh_sql` scan. Neither fallback could run today: `sp_fetcher.fetch_sp_definitions()` is only ever asked for names the SQL Execution Graph already proved exist in the cache (measured 1489/1489 for `PUR`, 53/53 for `STC`), and `fk_resolver.resolve_fk_related()` is called with `fk_depth = 0`, plus `_require_sql_execution_graph()` already refuses a Database with no SQL cache before either path is reached.

The FK fallback also held a trap: eight of the catalog's ten systems declare no Database and send an empty `database` field. `_fetch_fk_pairs()` would then fall through to `SQLAnalyzer`'s environment fallback (`DB_DATABASES`/`DB_DEFAULT_DATABASE` in `config/settings.py`), silently merging that default Database's tables into an unrelated system's result with no marker that this had happened.

## Decision

Remove both live-query fallbacks. `fetch_sp_definitions()` returns only what the SQL cache holds; a name the cache doesn't have returns no definition for that name. `resolve_fk_related()` returns an empty list when it finds no SQL cache; it never queries `sys.foreign_keys`, so the environment-fallback trap above cannot be reached from this path.

The PK-naming-convention inference over cached tables in `_build_pk_naming_adjacency()` is unchanged — it is the route that produces this project's FK results today, since this project's databases use only primary keys, not FK constraints.

## Consequences

- A caller that asks for a stored-procedure definition or FK-related tables the cache doesn't cover now gets a smaller (possibly empty) result instead of a best-effort live answer. The fix is to run `/refresh_sql`, not to retry — a stale copy needs a new scan, not a second read path.
- **Known gap, not resolved by this decision:** the scanner does not collect actual FK constraints, and the SQL cache has no field for them. The claim that this project's databases hold no FK constraints — only primary keys — comes from a code comment in the removed fallback, and nobody has verified it against the live databases. If that claim is wrong, the PK-naming inference this ADR keeps is the only FK-adjacent signal available, and it can both miss real constraints and infer relationships that don't exist.
- `code_analyzer/sql_analyzer.py`'s `SQLAnalyzer` class and its environment-based database fallback (`DB_DATABASES`/`DB_DEFAULT_DATABASE`) are unchanged — they still back `/refresh_sql` itself and other live-connection call sites outside `sp_fetcher.py`/`fk_resolver.py`. This decision only removes the two call sites that reached them as a silent fallback from a cache-first path.

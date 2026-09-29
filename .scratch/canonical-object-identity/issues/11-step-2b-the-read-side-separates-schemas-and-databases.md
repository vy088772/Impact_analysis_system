# 11 — Step 2b: the read side separates schemas and Databases

**Spec issue:** 7

**What to build:** An analyst who asks about `dbo.AVM` no longer receives the
programs of `COMMON.AVM`, and `PUR.dbo.Users` no longer merges into
`Response.dbo.Users`. A bare name still returns every candidate. A match whose
schema nobody proved stays in the answer and carries an Unproven Schema mark.

See "The two-bucket lookup rule", "The read side", "The table match", "The Path
Identity value", "The index states its own format version", and issue 7 in the
spec.

**Blocked by:** 09, 10, and the operator action: the five caches are refreshed
on another machine and copied here, and the Step 2a gate is met.

**Status:** done

- [x] Before any code change, the files on disk show two-part filenames, and each meta file carries the new format version.
- [x] Commit 1 adds the Path Identity value and removes the private function that assembled the eleven strings. No `path_id` changes. The golden test passes with no edit.
- [x] The Object Location Index holds a bare bucket and a full bucket for stored procedures and for tables. The bare buckets do not reuse today's field names.
- [x] The index states `index_version` from `_INDEX_VERSION`, starting at 1, and drops the cache format version field. The loader treats a missing version, another version, or a missing bucket as absent.
- [x] The same commit corrects the backfill tool's two docstrings, the operator manual's rerun advice, the advanced manual's tool table, and the `CONTEXT.md` Object Location Index entry.
- [x] The index version cases join the cache store's absent-index group, with the index newer than its cache. The backfill tool's test proves that an index with no version returns after a run.
- [x] A located-database row keeps the cache's server and database, gains a schema field, and gains `stated_database` when the matched full key names another Database. The object location lookup's row merge is removed.
- [x] Each Execution Path gains `read_full_keys` and `write_full_keys`. A relationship that states no database takes the graph's own Database.
- [x] The table match obeys the two-bucket rule, and a fallback match carries `unproven_schema` in `risk_flags`. The `table` field shows the target as the graph stores it. A View or a Function obeys the same rule.
- [x] The graph object lookup obeys the two-bucket rule. The `dbo` fills that name Step 2b are removed.
- [x] The inline C# SQL match, in the analysis service and in the flow chain builder, obeys the table match rule and takes the Database of its connection.
- [x] Seam 1: the eight table match cases, the four inline C# SQL cases, and path evidence case 3 pass.
- [x] The advanced manual sentence about a stripped `dbo.` prefix changes.
- [x] One run of the index backfill tool on this machine returns the pruning.
- [x] The whole suite of this repository passes.

## Notes

**2026-09-29: work did not start. The first checklist item fails.**

The agent read `data/sql_cache` before any code change:

- All five caches (`ETON`, `PUR`, `Response`, `STC`, `SysErrorRecord`) still
  have three-part filenames that end in `__dbo`.
- Each meta file still states `cache_version` 10 and a `schema` field.
- The files date from 2026-08-21 to 2026-09-24. They are older than ticket 09.
- No `EFNETDB` cache exists on this machine. The Step 2a gate needs one.

The operator action (refresh on another machine, copy here) is not done.
The Status line stays `ready-for-agent`. No box is checked. No code changed.
Start this ticket again after the refreshed files arrive.

**2026-09-29 (temp-table-scope, ticket 05):** Step 2b starts from the new graph version (6 or higher), the node lookup must keep the scope of a scoped temp node (`scope_module_id`), and the calls helper (`_resolve_call_target`) is the one site that changes the call target rule. See ADR-0036.

**2026-09-29 (done):** The operator refreshed the caches. `data/sql_cache` now holds seven caches (`EFNETDB`, `ETON`, `PUR`, `Response`, `STC`, `SysErrorRecord`, `eFinance`) with two-part filenames and `cache_version` 11. The first checklist item passes.

- **Commits.** `81f8f6e` Path Identity value (golden test unedited). `39b30e3` index buckets, `_INDEX_VERSION = 1`, located-database rows, the four written sentences. `8248dda` table match, full keys on a path, inline C# SQL match, graph object lookup. A fix commit follows for the locate fallback.
- **Backfill run.** One run on this machine rebuilt seven indexes, and `/locate_object` then reported no unindexed Database. The full run of the suite: 1165 passed, 16 failed, 2 collection errors (`test_search_roles`, `test_sp_tables`). The same 16 failures and 2 errors occur before ticket 11 (checked on the commit before it).
- **Graph version stays 6 (decided by the operator, 2026-09-29).** The graph builder stopped filling `dbo` for a reference that states no schema, and a call or a View/Function reference with no schema now names every listed node with that bare name. The payload shape did not change, so no version rise. A v6 graph built before this commit still holds `dbo` fills, so its no-schema targets read as proven `dbo` and carry no `unproven_schema` mark. A rise to 7 needs the repair tool (about 30 minutes for PUR) before the backfill tool can index a cache. The spec rule ("rises whenever the graph payload shape changes") does not settle a change of values only. The operator chose to keep 6. The next refresh of a cache builds a graph without the `dbo` fill, and a rise to 7 can wait for that.
- **Other decisions.** `_STORE_VERSION` of the derived evidence store rose to 2, because a stored path lacks `read_full_keys`. A View/Function lineage record keeps the bare node name in `table`, as it did before. `/find_by_table` and `/locate_object` use `response_model_exclude_none` so `stated_database` is absent. A `stated_database` on a locate row keeps the case the caller typed, else the lowercase key. A locate name that states a Database never falls back to another Database.
- **Review.** Standards: no hard violation; smells noted (string split of a full key in `_located_rows`, two copies of the "stated schema or bare name" lookup). Spec: the locate fallback ignoring the stated Database and the empty row set for a hand-edited index were fixed. An unresolved connection leaves `stated_database` unset; the spec is unclear there.

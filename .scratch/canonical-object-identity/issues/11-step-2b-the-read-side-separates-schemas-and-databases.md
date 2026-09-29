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

**Status:** ready-for-agent

- [ ] Before any code change, the files on disk show two-part filenames, and each meta file carries the new format version.
- [ ] Commit 1 adds the Path Identity value and removes the private function that assembled the eleven strings. No `path_id` changes. The golden test passes with no edit.
- [ ] The Object Location Index holds a bare bucket and a full bucket for stored procedures and for tables. The bare buckets do not reuse today's field names.
- [ ] The index states `index_version` from `_INDEX_VERSION`, starting at 1, and drops the cache format version field. The loader treats a missing version, another version, or a missing bucket as absent.
- [ ] The same commit corrects the backfill tool's two docstrings, the operator manual's rerun advice, the advanced manual's tool table, and the `CONTEXT.md` Object Location Index entry.
- [ ] The index version cases join the cache store's absent-index group, with the index newer than its cache. The backfill tool's test proves that an index with no version returns after a run.
- [ ] A located-database row keeps the cache's server and database, gains a schema field, and gains `stated_database` when the matched full key names another Database. The object location lookup's row merge is removed.
- [ ] Each Execution Path gains `read_full_keys` and `write_full_keys`. A relationship that states no database takes the graph's own Database.
- [ ] The table match obeys the two-bucket rule, and a fallback match carries `unproven_schema` in `risk_flags`. The `table` field shows the target as the graph stores it. A View or a Function obeys the same rule.
- [ ] The graph object lookup obeys the two-bucket rule. The `dbo` fills that name Step 2b are removed.
- [ ] The inline C# SQL match, in the analysis service and in the flow chain builder, obeys the table match rule and takes the Database of its connection.
- [ ] Seam 1: the eight table match cases, the four inline C# SQL cases, and path evidence case 3 pass.
- [ ] The advanced manual sentence about a stripped `dbo.` prefix changes.
- [ ] One run of the index backfill tool on this machine returns the pruning.
- [ ] The whole suite of this repository passes.

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

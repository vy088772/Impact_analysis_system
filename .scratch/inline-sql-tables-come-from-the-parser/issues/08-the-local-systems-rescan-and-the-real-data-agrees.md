# 08 — The local Systems rescan, and the real data agrees

**What to build:** An operator rescans the ten local Systems, and the answers show the fix on real data. Before the rescan, count the table relations of each C# Scan Result by reason and by access type, and record the written tables of the companion repository's routing expectations. Rescan each System locally. Regenerate the routing expectations. Count again, and record both counts and both lists in this ticket.

See "Rollout" and "Testing Decisions" (acceptance) and user stories 11, 30 to 32, and 51 in the spec.

**Blocked by:** 03, 04, 05, 06.

**Status:** done (2026-10-01). Item 3 first failed, because its premise was false. The spec corrected user story 11 and item 3 on 2026-10-01. See "Item 3" in the Notes, and ticket 09.

- [x] The one-time check of ticket 02 has its result on record. That check needs the scans of the old format, so it cannot run after this rescan.
- [x] Each old C# Scan Result reports `scan_cache_stale` before the rescan.
- [x] `/find_by_table ManifestNew write_only=True` on ATV returns no ATV program, and its excluded count is one. (Corrected item. The first text asked for the ATV program with the type `INSERT`. That failed, because the insert is commented-out C# code. See the Notes.)
- [x] At least 545 relations carry the reason `inline_sql_parsed`. (637)
- [x] The ticket records the counts per reason and per access type, before and after.
- [x] The ticket records three spot checks: one parsed relation, one fallback relation, and one relation whose access type changed.
- [x] The ticket records the written tables of the routing expectations, before and after. A table whose only write evidence is a fallback relation leaves the list. The companion repository does not change.
- [x] An unexpected change becomes its own ticket, not a silent edit. (tickets 09 and 10)

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `.scratch/inline-sql-tables-come-from-the-parser/issues/08-the-local-systems-rescan-and-the-real-data-agrees.md` (this file)
- `.scratch/inline-sql-tables-come-from-the-parser/issues/09-the-csharp-parser-reads-no-sql-from-a-csharp-comment.md` (new)
- `.scratch/inline-sql-tables-come-from-the-parser/issues/10-a-table-valued-function-in-a-from-clause-is-not-a-table.md` (new)

No product code and no test changed. In `data/`, the live `data/scan_cache` did not change (see "The rescan"). The companion repository did not change.

### The data sources

- An earlier session already rescanned the ten Systems on 2026-09-30: from version 40 to 42 (this spec, tickets 03 and 04), then from 42 to 43 (inherited-web-config-connections, ticket 10). The backups `data/scan_cache_backup_v40_20260930` and `data/scan_cache_backup_v42_20260930` hold the older scans.
- "Before" in this ticket is the v40 backup: the last scans of the old format, before ticket 03.
- After that rescan, HEAD gained `22433c2` (the host: `INSERT ... EXEC`) and `14dfa75` (connection inheritance). So this ticket rescanned again with HEAD (`f57d6cb`).

### The rescan

- Each System was rescanned with `scan_store.get_or_scan(root, refresh=True)` into a staging directory, with no pull. The ten Systems took about 16 minutes (TOPCSCY 334 s, TTPUR 354 s).
- The staging result equals the live `data/scan_cache` (version 43) in each of these fields: `table_relations` (every field of every relation), `sp_relations`, `db_invocations`, `connection_sources`, `unresolved_connections`, `databases_used`, `unique_tables`, and `unique_sps` (the last two as sets). So the live caches already describe HEAD. They stay in place, and the staging directory is deleted.
- Stale check: with `SCAN_CACHE_ROOT` set to the v40 backup, `system_targets.scan_cache_state(root)` gives `(False, "scan_cache_stale")` for each of the ten roots.

### Counts, before and after

| | Relations | Reason | Access type |
|---|---|---|---|
| Before (v40) | 641 | none stored (old format) | `SELECT` 641 |
| After (v43 = HEAD) | 681 | `inline_sql_parsed` 637, `inline_sql_regex` 44 | `SELECT` 637, `UNRESOLVED` 44 |

Each parsed relation is `SELECT`, and each fallback relation is `UNRESOLVED`. No local relation has `INSERT`, `UPDATE`, `DELETE`, or `SELECT_INTO`.

Per System (the five Systems with relations; the other five have none):

| System | Before | After: parsed | After: fallback |
|---|---|---|---|
| Response | 11 | 11 | 0 |
| TTRDQ | 219 | 204 | 39 |
| ATV | 5 | 5 | 1 |
| TTPUR | 382 | 391 | 4 |
| STC | 24 | 26 | 0 |

Relation by relation, keyed by System, file, line, and table:

- 598 relations went from `SELECT` to `inline_sql_parsed` / `SELECT`.
- 43 relations went from `SELECT` to `inline_sql_regex` / `UNRESOLVED`.
- 24 relations are new: 23 parsed and 1 fallback (`ManifestNew`). No relation was lost.
- 6 of the 23 new parsed relations name a table-valued function. See ticket 10.

### Spot checks

1. Parsed: ATV `ManifestQry.aspx.cs` line 39, method `BindMOT`, `obj.CreateReader("SELECT ... FROM [PUR].[dbo].[MOT] Where ...")`. The relation is `PUR.dbo.MOT`, `inline_sql_parsed`, `SELECT`, Database `PUR`, `invocation_span` (1402, 1531). Before, it was `SELECT` with no reason.
2. Fallback: TTRDQ `SC/T2Qry_Pur.aspx.cs` line 149, `string sql = @"SELECT county FROM zipcode WHERE county IN (SELECT DISTINCT county FROM T2Suppliers)"`, and the code then appends to `sql`. The host rates the text `dynamic`. Two relations, `zipcode` and `T2Suppliers`, are `inline_sql_regex`, `UNRESOLVED`, Database `unknown`, with an empty span.
3. Access type changed: TTRDQ `Homepage_DevV3.aspx.cs` line 468, `cmd = new SqlCommand("select * from View_HomePageDev_getPicArea", cn)`. Before: `SELECT`. After: `inline_sql_regex` / `UNRESOLVED`. The command is a new value of a variable that `new SqlCommand()` made on the line before, and the host records no literal text at that site. The text is static, so a later host change can parse it.

### Item 3: `ManifestNew` on ATV

- The text `insert into ManifestNew (R_ID,data) values('...` is on line 131 of `ATV/PO_ManifastUploadV3.aspx.cs`, and the line is a C# comment: `//this.DbCon.Edit_Data("insert into ManifestNew ...")`. The program never runs it. The host correctly records no Database Invocation for it. The C# parser reads it from the comment, so it becomes a fallback relation (ticket 09).
- `/find_by_table ManifestNew` on ATV, after the rescan, with no Database, with `PUR`, and with `ETON`:
  - `write_only=True`: no match, `excluded_count` 1.
  - `write_only=False`: one match, `po_manifastuploadv3`, `inline_sql_regex`, `UNRESOLVED`, `via_sp` false.
- The live code calls `usp_PO_ManifaseUpload_AddData` in place of the insert. In the ETON SQL cache, that procedure has `INSERT` operations on `ManifestTemp` and `ManifestNew`. `/find_by_sp usp_PO_ManifaseUpload_AddData` (ATV, `ETON`) gives no proven match. It lists `po_manifastuploadv3` under `likely_matches`: Database candidates `["ETON"]`, attribution `candidate`, reason `unique_across_catalogs`. The connection of that call does not resolve, so the write is not proven. A `write_only` answer correctly leaves it out (ADR-0015).
- So user story 11 and its acceptance item rested on a false premise: the insert is not "the real writer".
- Correction (2026-10-01, a separate step after this ticket): the spec now states story 11 and item 3 as the behaviour above. The guess stays out of a `write_only` answer and adds one to the excluded count. ADR-0039 also no longer calls the insert a lost write. The measurement above meets the corrected item, so no new run was needed.

### Routing expectations

- The written tables are `CacheObjectInventory.write_table_names`, which `load_cache_object_inventory` derives from the scan relations whose access type is a write. Computed with the companion repository's own loader and its restricted unpickler:
  - Before (v40): empty. Each v40 relation is `SELECT`.
  - After (v43): empty. Each parsed relation is `SELECT`, and each fallback relation is `UNRESOLVED`.
  - The v42 backup gives empty too.
- No table left the list, because no table was in it. Before the rescan, `ManifestNew` was not a relation at all. After, it is a fallback relation, so it stays out of the list, as the spec requires.
- Regeneration: `routing_expectations --seeds-from evaluation/Impact_analysis/results/routing_expectations.json`, written to a scratch path, against an Impact service of this worktree on port 8808. All 42 rows equal the reviewed file in each target field (0 differences). The companion repository did not change.
- The regeneration printed the known warning for `Y-DOCs_TTRDQ` (`find_by_sp needs database`). Inherited-web-config-connections ticket 10 records it too. It does not change a target.

### Other observations

- The fallback holds a relation to a table named `{tableName}` (TTRDQ `SC/SCAddSupplierType.aspx.cs` line 200, an interpolated C# string). It existed before as `SELECT`. It is now `UNRESOLVED`, so it no longer reads as a proven read. It is not a new change, so it has no ticket.
- 14 of the 44 fallback relations come from a line that starts a C# comment (ticket 09).

Verification: this ticket changed no code, so it ran no test suite. The checks above ran on the live data with HEAD `f57d6cb`.

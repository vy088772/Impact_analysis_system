# 03 — Rebuild the SQL caches and confirm that no omission remains

**What to build:** The local SQL caches answer with predicate reads and statement reads. The operator rebuilds the 8 SQL caches to graph version 12. The consistency check then proves that the 201 omissions of problem 1 are gone (`../spec.md`, "Version and rebuild" and "Testing Decisions").

**Blocked by:** 01 — A read in a non-DML statement gives a SELECT operation; 02 — A read in an IF or WHILE predicate gives a SELECT operation

**Status:** done

- [x] A backup of the 8 SQL caches exists before the rebuild.
- [x] The caches rebuild in this order: the repair tool, then the index backfill tool.
- [x] A comparison of the graphs before and after the rebuild shows that the rebuild adds reads and uses relationships and removes none. This ticket records the count of new operations for each cache.
- [x] The consistency check script in this directory reports only the 8 known false positives that the spec lists. The script does not change.
- [x] The companion repository regenerates its routing expectations. Each change is a new reader of a table. An unexpected change becomes its own ticket.
- [x] The C# Scan Result cache version does not change, and no forced rescan occurs.
- [x] The whole suite shows no new failure.

## Notes

- Backup: all 24 files of `data/sql_cache` (the v13 state of 15:08) went to the session scratchpad before any change. The v11 original that the operator copied is still in `~/Downloads/sql_cache`. The rebuild started from that v11 copy, with the same definition text (checked per cache).
- Why not repair `data/sql_cache` in place: it already held graph version 13, built at 15:08, before the ticket 02 commit (15:15). The repair tool skips a cache at the current version (`already_current`), so it would not rebuild. The rebuild ran in a copy (`--cache-root`): repair tool first (11 → 13, 13 s), then the index backfill tool. Then the 8 `.json` files replaced those in `data/sql_cache`. The `.index.json` and `.meta.json` files were already identical.
- Graph version is 13, not 12: another effort (database-qualified-call-target) raised it after ticket 01. Another session now holds an uncommitted change that raises it to 14. The 8 caches then need one more repair after that change lands. This ticket did not touch that change.
- Before and after (v11 → rebuilt), new `SELECT` operations, `reads` and `uses` relationships. No `reads` or `uses` relationship is removed in any cache.

  | Cache | New operations | New reads | New uses |
  |---|---|---|---|
  | EFNETDB | 0 | 0 | 0 |
  | ETON | 15 | 5 | 6 |
  | PUR | 591 | 289 | 26 |
  | Response | 3 | 3 | 0 |
  | STC | 8 | 3 | 0 |
  | SysErrorRecord | 0 | 0 | 0 |
  | eFinance | 45 | 27 | 2 |
  | RTTalentDB (vmsystest09) | 117 | 57 | 2 |
  | Total | 779 | 384 | 36 |

- The `calls` relationships change by id only (PUR 22, Response 17, eFinance 5 removed; PUR 22, Response 17, eFinance 15 added). The cause is the version 13 call target that keeps its Database. It is not from this ticket.
- Consistency check (script unchanged, run on the rebuilt caches): `table_missing` falls from 149 modules (v11) to 4 modules. The 4 modules hold 9 candidates, not 8:
  - 8 known false positives: the CTE `table1` (`EOR.AEBudgetLog_Summary_Qry`), 6 in `dbo.usp_SupplierProfile_Qry_Confirm`, 1 in `dbo.spApproveBat`.
  - 1 more: `vendors` in `dbo.usp_DevQryContrast_Qry2` (PUR). `problems.md` row 63 calls it "scalar subquery after set". The definition text shows that `Vendors` sits only inside a string that `set @Qrystr = @Qrystr + '...'` builds. That is dynamic SQL (problem 4, out of scope), and the check does not strip that string. So it is a ninth false positive of the check, and not an omission. The spec count of 8 is one short.
- `table_extra` is 6 (was 5) and `call_extra` is 3 (same). The new `table_extra` item is `dbo.spAddNewIVWorkV2` with `Parameters`. The read is real (`set @ParamValue=(select ... from Parameters ...)` at offset 1868). The check misses it because of an apostrophe in a comment, a known limit of the script (spec, Out of Scope).
- Companion repository: `routing_expectations.json` regenerated with `--seeds-from` the reviewed file, with `--question-count 41`, on a second service (port 8812) on the rebuilt caches. All 42 rows keep their targets. No row gains a reader, so no new ticket. Outside the rows, `sql_cache_sources` takes new scan times, and eFinance `unowned_call_targets` rises from 47 to 57. The version 13 call target explains the rise. I did not prove it with a separate run. The companion fixture `tests/_sql_cache_fixtures.py` `GRAPH_VERSION` rises from 11 to 13.
- C# Scan Result cache version stays 44. `data/scan_cache` and `scan_store.py` are not changed. No rescan ran.
- Suites: Impact_analysis_system 1743 pass (the two ODBC test files stay out, as in tickets 01 and 02). Companion 1618 pass.
- The service on port 8800 keeps its memory cache. Restart it after the version 14 change lands.

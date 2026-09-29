# 06: The PUR refresh finishes on real data

**What to build:** The operator refreshes PUR on the refresh machine with the
new code. The refresh ends, and the lineage answers make sense. After this
ticket, the canonical-object-identity operator action can continue.

See "Further Notes" in the spec.

**Repositories:** this repository and `llamaindex-spec-rag`, deployed together.

**Blocked by:** 04, 05.

**Status:** done (2026-09-29)

- [x] Both repositories are deployed to the refresh machine.
- [x] `refresh_sql_cli PUR` reaches the cache write stage and prints its result.
- [x] The `lineage` stage on PUR ends in 30 seconds or less.
- [x] The new PUR cache holds the new graph version.
- [x] From the new PUR cache, the two or three temp table names that the most procedures share are picked. For each, a `/find_by_table` answer lists no unrelated procedure.
- [x] A "parent creates, child fills" pattern in PUR keeps its base tables in the `/find_by_table` answer.

## Notes

Measured on 2026-09-29. The operator confirmed that this machine is the refresh machine, so the deployment checkbox is closed.

- `refresh_sql_cli PUR` ended with exit code 0: SP 1496, View 145, Function 58, tables 404. The cache file is `data/sql_cache/vmsystest07.topmost.com.tw__PUR.json` (`cache_version` 11, `graph_version` 6, the same as `GRAPH_VERSION`).
- Total refresh time was about 14 minutes. The `SP 定義` stage took 3:12. The `SQL Execution Graph` stage took 10:51 (1698 modules).
- The `lineage` stage did not show in the progress output because it ended between two polls. I timed it on the cached graph: I removed the lineage relations and ran `_expand_temp_table_lineage` again. It took 0.05 seconds. The relation count returned to 24645, the same as the cache.
- The three most shared temp table names are `#List` (84 procedures), `#tmp` (72), and `#Data` (43). `/find_by_table` with `database=PUR` and the Y-Docs_TTPUR source returned 375, 50, and 195 matches. Each `sp_chain` holds at least one procedure that owns that temp table: 0 unrelated chains for all three.

- Read-by-read check on the cached graph (2026-09-29): a separate script did not use the build code. For each read of `#List` (190 reads in 81 procedures), `#tmp` (190 in 68), and `#Data` (106 in 43), it walked the call edges up or down from the reading procedure. It compared the base tables it found with the lineage reads in the cache. Result: 0 differences, and 0 base tables whose writer is outside the reading procedure, its callers, and its callees. The old shared-name rule would have given 7961, 9734, and 5236 more base reads for the three names. The procedure counts differ from the 84, 72, and 43 above because this check counts procedures that read the name, not procedures that only write it.
- "Parent creates, child fills" example: `usp_CDCU_RMPriceCount_Delete` reads `#List` after the call to `usp_CDCU_RMPriceCount`. The graph links the read to `MaterialType` and `RMPriceMaster`. `/find_by_table` for both tables lists chains that hold `usp_CDCU_RMPriceCount` and `usp_CDCU_RMPriceCount_Delete` (53 chains for each table).
- Side effects: the first `/find_by_table` call with `cache_only=false` rebuilt the C# scan cache (`cache_version` 29 was old). It took 793 seconds.
- Not in this ticket: the graph stage is slow because `build_sql_execution_graph` starts one `dotnet` process for each module (about 0.38 seconds each). A batch mode in the SQL analyzer, like `analyze_csharp_files`, would cut it. Also, `refresh_sql_cli` crashes on a cp950 terminal when it prints the error mark in its first error message.

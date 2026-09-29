# 02: The PUR refresh proves the batch speed on real data

**What to build:** The operator refreshes PUR on the refresh machine with the
batch code. The SQL Execution Graph stage ends in 2 minutes or less, and the
new graph is the same as the old graph for every module whose definition did
not change.

See "Further Notes" in the spec.

**Blocked by:** 01.

**Status:** done (2026-09-29)

The Impact service must run, and the refresh machine must reach the PUR SQL
Server. After the operator starts the service, an agent can run the steps.

- [x] The current PUR cache is copied to a backup location before the refresh.
- [x] `refresh_sql_cli PUR` with the batch code reaches the cache write stage and prints its result.
- [x] The SQL Execution Graph stage on PUR ends in 2 minutes or less.
- [x] The definition text of each module in the new cache is compared with the backup. The modules whose definition changed are listed.
- [x] Without the changed modules, the new graph is equal to the backup graph: `nodes`, `relationships`, and `parse_errors`.
- [x] The Notes of this ticket record the stage times, the list of changed modules, and the comparison result.

## Notes

Measured on 2026-09-29 on the refresh machine. The Impact service ran with `--reload`, so it used the batch code.

- Backup: the old PUR cache (`.json`, `.index.json`, `.meta.json`) is in `data/sql_cache_backup_pur_20260929/`. The folder is git-ignored.
- `refresh_sql_cli PUR` ended with exit code 0: SP 1496, View 145, Function 58, tables 404. The cache write stage ran and printed its result.
- Stage times: the whole refresh took 263 seconds (about 4:23). The `SP 定義` stage took about 2:40. The `SQL Execution Graph` stage took about 30 seconds for 1698 modules (the bar showed 0:30 at 1600/1698; the first 100 modules took 5 seconds). Before the change: 14 minutes in total and 10:51 for the graph stage. The graph target (2 minutes or less) is met.
- Changed modules: none. All 1699 definitions (1496 + 145 + 58) are equal to the backup, so no module was excluded from the comparison.
- Comparison result: `graph_version` is 6 in both caches. `nodes` (9769), `relationships` (24645), and `parse_errors` (0) are equal to the backup, entry by entry and in the same order.
- **1698 modules against 1699 definitions.** The cache holds 1699 module definitions, but the graph stage analyzed 1698 modules. The function `fnDecrypt` has an empty definition. The graph builder keeps its node and skips the analysis of an empty definition. This rule exists before the batch change, so the batch change did not cause the difference of 1.
- **Compare script.** The script is now in the repository: `tools/compare_sql_cache_graphs.py OLD.json NEW.json`. It follows steps 4 to 6 of the spec. A run on the backup and the new PUR cache gives 1699 modules, 0 changed definitions, and equal `graph_version`, `nodes` (9769), `relationships` (24645), and `parse_errors` (0). `tests/test_compare_sql_cache_graphs.py` covers the removal of changed modules.
- **Progress report at 0.** The graph stage still sends one report `(0, total, "")` before the first batch. This report exists before the batch change. After it, the stage reports once for each batch.

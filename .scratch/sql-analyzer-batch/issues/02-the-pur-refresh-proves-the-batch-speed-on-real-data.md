# 02: The PUR refresh proves the batch speed on real data

**What to build:** The operator refreshes PUR on the refresh machine with the
batch code. The SQL Execution Graph stage ends in 2 minutes or less, and the
new graph is the same as the old graph for every module whose definition did
not change.

See "Further Notes" in the spec.

**Blocked by:** 01.

**Status:** ready-for-human

The Impact service must run, and the refresh machine must reach the PUR SQL
Server. After the operator starts the service, an agent can run the steps.

- [ ] The current PUR cache is copied to a backup location before the refresh.
- [ ] `refresh_sql_cli PUR` with the batch code reaches the cache write stage and prints its result.
- [ ] The SQL Execution Graph stage on PUR ends in 2 minutes or less.
- [ ] The definition text of each module in the new cache is compared with the backup. The modules whose definition changed are listed.
- [ ] Without the changed modules, the new graph is equal to the backup graph: `nodes`, `relationships`, and `parse_errors`.
- [ ] The Notes of this ticket record the stage times, the list of changed modules, and the comparison result.

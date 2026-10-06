# Report CREATE TABLE for a Temp Table

The analyzer does not report `CREATE TABLE #name`. A module that makes its temp table with `CREATE TABLE` and fills it with `INSERT` does not get Temp Table Shadowing. This agrees with [ADR-0036](../docs/adr/0036-a-temp-table-belongs-to-the-procedure-that-uses-it.md) and [ADR-0043](../docs/adr/0043-a-select-into-temp-table-shadows-the-callers-temp-table.md).

## Why this is out of scope

The change needs an analyzer change, a new SQL cache refresh for every Database, and a new graph fact. The gain is small.

In October 2026, a scan of the 8 SQL caches found 4360 temp table lineage reads. Only 8 of them cross a call. All 8 are the `SELECT ... INTO #name` case, and ADR-0043 now handles them. The scan found no wrong lineage read from a `CREATE TABLE #name` across a call.

The worst result of the gap is one extra base table in a read. [ADR-0012](../docs/adr/0012-object-location-index-authoritative-pruning.md) prefers an over-report to a lost read.

## Known cost of this decision

A callee that makes its temp table with `CREATE TABLE` still receives the base tables of the caller's temp table with the same name.

Reconsider this decision if a new cache scan shows a wrong lineage read across a call from a `CREATE TABLE #name`.

## Prior requests

- `.scratch/temp-table-scope-indirect-reads/issues/02-report-create-table-for-a-temp-table.md` — "Report CREATE TABLE for a temp table" (from issue 01 of the same directory)

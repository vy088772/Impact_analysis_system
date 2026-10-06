# Mark a Temp Table Lineage Read as Indirect

`/find_by_table` lists a temp table lineage read as a direct read. The read gets no `is_indirect: true` and no `read_through`. The `lineage` field keeps the chain in the graph only. This agrees with [ADR-0036](../docs/adr/0036-a-temp-table-belongs-to-the-procedure-that-uses-it.md) and [ADR-0043](../docs/adr/0043-a-select-into-temp-table-shadows-the-callers-temp-table.md).

## Why this is out of scope

The mark does not change the module-level answer. After ADR-0043, no temp table lineage read crosses a call to a shadowing module. A writer of the temp table reads the base table with its own direct read.

In October 2026, a scan of the 8 SQL caches found 1161 pairs of a module and a base table that a lineage read gives. Every pair has a direct read of the same base table in the same module. So the mark adds no module and removes no module from an answer.

The mark changes only the label of one operation record. It needs a new response format for the temp table name and a new version of the derived Execution Path evidence.

Example: `dbo.usp_DevQryContrast_Qry2` reads `#tmpCus`. Its op 1 (`INSERT ... SELECT`) reads `Customers`, `DevPart`, and `Part` directly. Its op 2 gets the same three tables by lineage through `#tmpCus`.

## Known cost of this decision

The answer does not show that op 2 reaches a base table through a temp table.

Reconsider this decision if a new cache scan finds a lineage read with no direct read of the same base table in the same module.

## Prior requests

- `.scratch/temp-table-scope-indirect-reads/issues/03-mark-a-temp-table-lineage-read-as-indirect.md` — "Mark a temp table lineage read as indirect" (from issue 01 of the same directory)

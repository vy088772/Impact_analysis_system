# A SELECT INTO Temp Table Shadows the Caller's Temp Table

**Status:** Accepted
**Date:** 2026-10-06

## Context

[ADR-0036](0036-a-temp-table-belongs-to-the-procedure-that-uses-it.md) lets a temp table read resolve through the writers of callers and callees. It does not detect shadowing, so it takes the union of the visible writers. ADR-0036 rejected shadowing detection because the analyzer does not report `CREATE TABLE #name`.

The graph already holds a different create fact. A `SELECT ... INTO #name` statement always creates a new temp table, and the graph gives its operation the type `SELECT_INTO`.

In the PUR cache, `dbo.usp_CDCU_RMPriceCount` calls `dbo.usp_CDCU_RMPriceCount_Delete`. Both procedures use `#List`. The callee fills its own `#List` with `SELECT ... INTO #List FROM dbo.fun_GetStatusForRMCD(...)`. The caller makes its `#List` from `dbo.MaterialType` after the call. The expansion went up from the callee's `#List` to the caller's `#List`. So `/find_by_table MaterialType` listed the callee, but the callee never refers to `MaterialType`. The callee also received a lineage read of `RMPriceMaster` from the caller.

A scan of the 8 caches found 4360 lineage reads. Only 8 of them crossed a call, and all 8 were this case.

## Decision

### Temp Table Shadowing

A module shadows a temp table when the module has a `SELECT_INTO` operation that writes that temp table and the operation is in no branch (its `branch_path` is empty). Such a module always creates its own table. The caller's table with the same name is a different table.

A shadowing module does not share that temp table across its calls to callers:

- A resolution does not go up from a shadowing module to its callers.
- A resolution does not go down from a caller into a shadowing callee.
- A resolution can go up from a callee into a shadowing module, and it can go down from a shadowing module into its callees. The callees of the shadowing module see the table that the module created.

The rule applies to each temp table name separately. A `##name` global temp table does not change.

### Only an unconditional SELECT INTO

A `SELECT_INTO` in an IF, ELSE, or WHILE branch does not shadow. Another branch can read the caller's table. [ADR-0012](0012-object-location-index-authoritative-pruning.md) prefers an over-report to a lost read, so the expansion keeps the union for that module.

### No statement order

The rule does not compare the sequence of the read and the `SELECT_INTO`. A read in a shadowing module that comes before its `SELECT_INTO` reads the caller's table at run time. The expansion loses that caller lineage. This is a known cost. A rule that uses the order would need one state for each read, and a WHILE loop makes the text order differ from the run order.

### CREATE TABLE stays undetected

The analyzer still does not report `CREATE TABLE #name`. A callee that creates its table with `CREATE TABLE` and fills it with `INSERT` still receives the caller's base tables. An analyzer change for this fact is a separate issue.

### Graph version

`GRAPH_VERSION` rises from 13 to 14. The read path rejects a v13 graph until an operator rebuilds it.

## Considered Options

- **Keep the over-report and mark the read as indirect.** The answer would name the temp table that the read passes through. This mark does not make a wrong read correct. The `MaterialType` read of the callee does not occur at run time. A mark for a correct lineage read stays a separate question.
- **Edit ADR-0036 in place.** This record keeps why ADR-0036 chose no detection and why this decision changes it.

## Consequences

- ADR-0036 "No shadowing detection" and its "Rejected alternative" no longer apply to a `SELECT ... INTO #name`. They still apply to `CREATE TABLE #name`.
- `/find_by_table MaterialType` does not list `dbo.usp_CDCU_RMPriceCount_Delete`. The callee keeps its own lineage read of `dbo.fun_GetStatusForRMCD`.
- An operator rebuilds each graph after the version rise.

# Parse Concatenated Dynamic SQL

The SQL Execution Graph does not parse the string that a module builds and runs with `EXEC(@variable)`. The graph keeps each such operation as an `unresolved_dynamic_sql` node with an `unresolved` edge. It does not give a target object for the operation. This agrees with [ADR-0001](../docs/adr/0001-sql-execution-graph.md).

## Why this is out of scope

In October 2026, a check of the PUR and Response SQL caches found 15 dynamic SQL operations. The operations use four concatenation patterns:

| Pattern | Operations | Object names in string literals |
|---|---|---|
| P1: The full SQL text comes from a parameter | `dt_checkinobject` `exec(@txStream1/2/3)`, 3 in each database | No. The legacy Visual SourceSafe procedure runs DDL text that the caller supplies. |
| P2: A fixed SQL template with appended filter values | `usp_InitialControlEnquiry_Approve_Check`, `spMyQuestionQry`, `spQuestionQry` | Yes |
| P3: A cursor loop builds pivot columns before a fixed `FROM` clause | `usp_SupplierProfile_MT1_Qry2`, `usp_SupplierProfile_MT1_Qry3`, `usp_SupplierProfile_P1_Qry2`, `spQuesStaticCrossTable` | Yes |
| P4: `CONCAT()` builds a `PIVOT` query | `usp_Orders_OrderVariance_Report`, 2 operations | Yes |

No parse can find a target for P1. The other 9 operations are `SELECT` statements only. None of them writes to a table. Thus, the gap does not hide a write path.

A parse of P2 to P4 cannot give a `proven` target. A variable fragment can hold a further object name. For example, `usp_InitialControlEnquiry_Approve_Check` puts `@PONO nvarchar(max)` inside a `not in (...)` clause. A parse must thus add a new confidence value. It must also replace ADR-0001 and change the graph format. The Impact tool accepts an operation that it cannot parse when the graph marks that operation clearly. The current mark does this.

## Known cost of this decision

A reverse lookup on a table does not find the dynamic SQL that reads it. For example, a change to a column of `Revenue` does not list `usp_SupplierProfile_P1_Qry2`. The Execution Path keeps the `dynamic_sql` risk flag, so a reader of the path can see the gap.

Reconsider this decision if a new database shows dynamic SQL that writes to tables, or if a missed read causes a real failure.

## Prior requests

- `.scratch/dynamic-sql-concatenation-patterns/issues/01-decide-whether-to-parse-concatenated-dynamic-sql.md` — "Decide whether to parse concatenated dynamic SQL" (from problem 4 of `.scratch/sql-graph-consistency/problems.md`)

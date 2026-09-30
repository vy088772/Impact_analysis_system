# 02 — A CTE name never becomes a table

**What to build:** An analyst asks which programs read a table, and a common table expression (CTE) no longer counts as that table. The analyzer host collects the CTE names of a statement from the whole statement, including its `WITH` clause, and skips them in the main query, the `INSERT` source, and the `UPDATE` and `DELETE` `FROM` clauses. `/find_by_table test.Table1` no longer reports `EOR.AEBudgetLog_Summary_Qry`.

See "The analyzer host" and user stories 23 to 27 in the spec.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing analyzer host test comes first for each statement kind: `SELECT`, `SELECT ... INTO`, `INSERT`, `UPDATE`, and `DELETE` that read a CTE in the main part.
- [x] A recursive CTE and a statement with several CTEs (one reading another) give no CTE read.
- [x] A CTE name wins over a real table with the same name inside its statement.
- [x] The tables that a CTE body reads stay reads.
- [x] A test uses the `EOR.AEBudgetLog_Summary_Qry` statement, trimmed to the `WITH Table1 ... SELECT ... INTO #table FROM Table1` statement, and finds no read of `Table1`.
- [x] The graph format version does not change here; ticket 09 raises it once.
- [x] The whole suite shows no new failure.

## Implementation note

Changed files (this ticket only):

- `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: `CreateCandidate` reads the CTE names of the whole statement once (`ReadCteNames`). Every `CollectReferences` call receives them. `CollectReferences` no longer reads CTE names from the fragment it walks. `AddObjectName` skips a name only when it states no server, database, or schema.
- `tests/test_static_analyzer_host.py`: new tests for each statement kind, recursive and chained CTEs, name precedence, and the `EOR.AEBudgetLog_Summary_Qry` case. The old test that recorded the `dbo.X` loss as a defect now asserts the corrected result (`dbo.X` stays a read).

Decisions:

- A schema-qualified name is never a CTE, because T-SQL cannot qualify a CTE name. So `WITH X AS (...) ... FROM dbo.X` keeps `dbo.X` as a read.
- The graph format version did not change. Ticket 09 raises it once.

Verification: the analyzer host test file passes (26 tests). The whole suite gives 1199 passed and 16 failed. The same 16 fail without this change. `tests/test_search_roles.py` and `tests/test_sp_tables.py` need a live database and fail at collection, so the run skipped them.

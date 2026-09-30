# 02 — A CTE name never becomes a table

**What to build:** An analyst asks which programs read a table, and a common table expression (CTE) no longer counts as that table. The analyzer host collects the CTE names of a statement from the whole statement, including its `WITH` clause, and skips them in the main query, the `INSERT` source, and the `UPDATE` and `DELETE` `FROM` clauses. `/find_by_table test.Table1` no longer reports `EOR.AEBudgetLog_Summary_Qry`.

See "The analyzer host" and user stories 23 to 27 in the spec.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A failing analyzer host test comes first for each statement kind: `SELECT`, `SELECT ... INTO`, `INSERT`, `UPDATE`, and `DELETE` that read a CTE in the main part.
- [ ] A recursive CTE and a statement with several CTEs (one reading another) give no CTE read.
- [ ] A CTE name wins over a real table with the same name inside its statement.
- [ ] The tables that a CTE body reads stay reads.
- [ ] A test uses the `EOR.AEBudgetLog_Summary_Qry` statement, trimmed to the `WITH Table1 ... SELECT ... INTO #table FROM Table1` statement, and finds no read of `Table1`.
- [ ] The graph format version does not change here; ticket 09 raises it once.
- [ ] The whole suite shows no new failure.

# 01 — A read in a non-DML statement gives a SELECT operation

**What to build:** An analyst asks which procedures read a table. A procedure that reads the table only in a SET, DECLARE, RETURN, PRINT, or other non-DML statement is in the answer. Today the analyzer host makes an operation only for a DML statement or an EXEC statement. A subquery in `SET @x = (SELECT ... FROM T)` is not a SELECT statement, so the host makes no operation for it.

This ticket sets the general rule of the spec (`../spec.md`, "The rule" and "The operation"). It does not change IF predicates or WHILE predicates. Ticket 02 does that.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing analyzer host test comes first: `SET @n = (SELECT COUNT(*) FROM dbo.POrder WHERE id = @id);` gives one `SELECT` operation that reads `dbo.POrder`.
- [x] A non-DML statement that refers to at least one table, view, or user-defined function gives one `SELECT` operation. The rule is general and does not list statement types.
- [x] Analyzer host tests cover SET, DECLARE with a value, RETURN in a scalar function, and PRINT, each with a subquery.
- [x] A direct function call in a non-DML statement, for example `SET @ok = dbo.fnCheck(@id)`, gives the same relationships as a function call in a SELECT statement.
- [x] One statement with two subqueries gives one operation that reads the tables of both subqueries.
- [x] `SET @x = GETDATE()` and `SET @x = (SELECT 1)` give no operation.
- [x] A CTE name and a table variable in the statement give no table read.
- [x] The source location covers the full statement. The branch path is the branch path outside the statement.
- [x] DML statements, EXEC statements, and the bodies of IF, WHILE, and TRY/CATCH give the same operations as before.
- [x] A graph regression test with the real definition of `dbo.sp_SO_UpdateInvFlag` (PUR) shows a reads relationship to `POrder`.
- [x] The graph format version rises from 11 to 12, and its comment states why a v11 graph is rejected. This is the one rise for the whole effort. Ticket 02 does not rise it again.
- [x] ADR-0041 records the rule, the choice of the `SELECT` operation type, and the rejected separate operation type. Its consequences state that the C# Scan Result cache keeps old relations until a rescan.
- [x] The graph design document states that a `dml_operation` of type `SELECT` can come from a non-DML statement.
- [x] The whole suite shows no new failure.

## Notes

- Rule lives in `Visit` of `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: a `TSqlStatement` that holds no other statement is a leaf. `CreateNonDmlCandidate` collects tables, columns, and functions of the whole statement, and gives no operation when it finds no table, view, or function.
- A statement that holds statements (block, procedure body) is not a leaf, so DML, EXEC, IF, WHILE, and TRY/CATCH behave as before. IF and WHILE predicates stay for ticket 02 (their own `IfStatement` and `WhileStatement` branches return before the leaf rule).
- The graph regression test lists `dbo.POrder` and `dbo.SOrder` as tables in the fixture. Without them the node id is `table:.POrder` (ADR-0037, unstated schema stays unresolved).
- `tests/cross_repository_agreement.json` holds `graph_version`. It rose from 11 to 12. The companion repository needs the same change.
- Full suite: 1712 pass. `tests/test_search_roles.py` and `tests/test_sp_tables.py` fail at collection because no ODBC driver exists here. They do not relate to this ticket.


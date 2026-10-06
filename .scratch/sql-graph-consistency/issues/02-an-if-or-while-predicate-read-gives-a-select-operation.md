# 02 — A read in an IF or WHILE predicate gives a SELECT operation

**What to build:** An analyst asks which procedures read a table. A procedure that reads the table only in an IF predicate or a WHILE predicate is in the answer. Examples are `IF EXISTS (SELECT ... FROM T)` and `IF (SELECT ... FROM T) <> ''`. Today the analyzer host keeps the predicate only as text in the branch path. Problem 1 of `../problems.md` groups about 107 of the 201 omissions as an EXISTS predicate or a scalar subquery after `if`.

This ticket applies the rule of ticket 01 to predicates (`../spec.md`, "The operation").

**Blocked by:** 01 — A read in a non-DML statement gives a SELECT operation

**Status:** done

- [x] A failing analyzer host test comes first: `IF EXISTS (SELECT 1 FROM dbo.UserProgram WHERE id = @id) UPDATE dbo.T SET a = 1;` gives a `SELECT` operation that reads `dbo.UserProgram`, then the `UPDATE` operation.
- [x] An IF predicate and a WHILE predicate that refer to at least one object give one `SELECT` operation each.
- [x] Analyzer host tests cover an EXISTS predicate, a scalar subquery predicate, a WHILE predicate, and a direct function call in an IF predicate.
- [x] The source location of a predicate read covers the predicate only, not the THEN body or the ELSE body.
- [x] A predicate read does not carry the `IF ...` entry of its own IF. A predicate read of an inner IF carries the branch path of the outer IF.
- [x] One predicate with two subqueries gives one operation.
- [x] The host visits the THEN body, the ELSE body, and the WHILE body as before, with the same branch paths.
- [x] A predicate read of a `#temp` table expands through the Temp Table Scope to the base tables behind the writers of that temp table.
- [x] An inline SQL text with `IF EXISTS (SELECT ... FROM T)` gives an Inline SQL Table Relation for `T` with the access type `SELECT` and the reason `inline_sql_parsed`.
- [x] A graph regression test with the real definition of `COMMON.CheckProgramAuth` (eFinance) shows a reads relationship to `COMMON.UserProgram`.
- [x] The graph format version stays at 12.
- [x] The whole suite shows no new failure.

## Notes

- Rule lives in `Visit` of `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: the `IfStatement` and `WhileStatement` branches call `AddPredicateRead` with the branch path outside the statement, then visit the bodies as before. It reuses `CreateNonDmlCandidate`, so the CTE rule, the table-variable rule, and the temp-table rule are the same as ticket 01.
- ScriptDom starts an `ExistsPredicate` at its parenthesis and leaves the `EXISTS` keyword out. So the location starts at the first token after `IF` or `WHILE` (`PredicateSpan`), and `SqlOperationCandidate` carries an optional `SqlSourceSpan` that `CreateLocation` uses in place of the fragment range.
- Not changed, as the ticket asks: the `IF ...` entry of the branch path of the THEN body still uses the same fragment text. For an EXISTS predicate that text also lacks the `EXISTS` keyword (`IF (SELECT ...)`). It is a separate, older defect.
- The graph version stays at 12 in this ticket. The working tree also holds an uncommitted change from another effort (database-qualified-call-target) that raises it to 13. This ticket did not touch it.
- Temp table and graph tests use the real host through `build_sql_execution_graph`. The inline SQL test uses the real host through `refresh_csharp_files`.
- Full suite: 1732 pass. `tests/test_search_roles.py` and `tests/test_sp_tables.py` stay out because no ODBC driver exists here.

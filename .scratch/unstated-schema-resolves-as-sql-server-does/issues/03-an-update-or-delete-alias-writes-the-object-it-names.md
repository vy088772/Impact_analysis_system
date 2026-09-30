# 03 — An UPDATE or DELETE alias writes the object it names

**What to build:** An analyst asks which programs write a table, and a writer that updates the table through an alias is found. The analyzer host replaces an `UPDATE` or `DELETE` target that names an alias of the `FROM` clause with the object behind that alias, and treats the statement as a direct write to that object. `update B1 ... from BSPL.BudgetBalanceSheet B1` writes `BSPL.BudgetBalanceSheet`.

See "The analyzer host" and user stories 28 to 34 in the spec.

**Blocked by:** 02 — A CTE name never becomes a table (an alias of a CTE needs that ticket's CTE names, and both change the same code).

**Status:** done

- [x] A failing analyzer host test comes first for an `UPDATE` alias and a `DELETE` alias of a real table.
- [x] An alias of a real table writes that table, with the parts the `FROM` clause writes.
- [x] An alias of a `#temp` table writes that temp table, and the temp table lineage still expands it.
- [x] An alias of an `@table` variable writes nothing, as a direct write to a variable does today.
- [x] An alias of a subquery or a CTE records an unresolved target and guesses no table.
- [x] The written object stops counting as a read.
- [x] A test uses the `BSPL.sp_BSprocess` statement, trimmed to the `update B1 ... from BSPL.BudgetBalanceSheet B1` statement, and finds a write to `BSPL.BudgetBalanceSheet`.
- [x] The graph format version does not change here.
- [x] The whole suite shows no new failure.

## Comments

Changed files (this ticket only):

- `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: new `AddWriteTarget` resolves the `UPDATE` or `DELETE` target. A bare target that matches an alias of the `FROM` clause (case-insensitive) becomes the object behind that alias, with the parts the `FROM` clause writes. `RemoveWrittenTables` then removes it from the reads. New `FindFromClauseAlias` and `IsBare` helpers. `AddObjectName` reuses `IsBare`. `SqlOperation` gains `UnresolvedWriteTargets` (JSON `unresolved_write_targets`, a list of alias names).
- `tests/test_static_analyzer_host.py`: new tests for an `UPDATE` alias and a `DELETE` alias of a real table, case and parts, `#temp`, `@table`, subquery and CTE aliases, a target that is no alias, and the trimmed `BSPL.sp_BSprocess` statement.

Decisions:

- An alias of a subquery or a CTE writes no table. The alias name goes to `unresolved_write_targets`.
- A bare target that names a CTE with no alias (`UPDATE C SET ...`) also goes to `unresolved_write_targets`, as the spec's Out of Scope section describes.
- An alias of an `@table` variable writes nothing and records nothing, as a direct write to a variable does today.
- The host contract version stays at 4, because the change only adds one field. The graph format version did not change. Ticket 09 raises it once.
- Not changed: a target with no alias that states a bare table name (`UPDATE Users ... FROM dbo.Users`) keeps the old result, a write to the bare name.
- Nothing reads `unresolved_write_targets` yet. It only travels on the operation node.

Verification: the analyzer host test file passes (38 tests). The whole suite gives 1226 passed and 16 failed. The 16 failures are the same set as ticket 02 recorded (wrapper and real checkout tests). `tests/test_search_roles.py` and `tests/test_sp_tables.py` need a live database, so the run skipped them.

**Whole-feature review, 2026-09-30** (`/code-review` from `b865587` to `154ad57`, then the fixes).

- Defect: the alias lookup walked every descendant of the `FROM` clause. An alias inside a derived table then answered first by position. `UPDATE t ... FROM (SELECT a FROM dbo.Other t) d JOIN dbo.Real t` wrote `dbo.Other`.
- Fix (commit `ec25045`): `FindFromClauseAlias()` reads the table references of the `FROM` clause only. It goes through a join and through a join in parentheses. It does not enter a derived table.
- 3 new tests in `tests/test_static_analyzer_host.py`. Two failed before the fix.
- The seven caches hold no such statement, so no graph needs a rebuild.

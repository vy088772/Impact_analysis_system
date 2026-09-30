# 03 — An UPDATE or DELETE alias writes the object it names

**What to build:** An analyst asks which programs write a table, and a writer that updates the table through an alias is found. The analyzer host replaces an `UPDATE` or `DELETE` target that names an alias of the `FROM` clause with the object behind that alias, and treats the statement as a direct write to that object. `update B1 ... from BSPL.BudgetBalanceSheet B1` writes `BSPL.BudgetBalanceSheet`.

See "The analyzer host" and user stories 28 to 34 in the spec.

**Blocked by:** 02 — A CTE name never becomes a table (an alias of a CTE needs that ticket's CTE names, and both change the same code).

**Status:** ready-for-agent

- [ ] A failing analyzer host test comes first for an `UPDATE` alias and a `DELETE` alias of a real table.
- [ ] An alias of a real table writes that table, with the parts the `FROM` clause writes.
- [ ] An alias of a `#temp` table writes that temp table, and the temp table lineage still expands it.
- [ ] An alias of an `@table` variable writes nothing, as a direct write to a variable does today.
- [ ] An alias of a subquery or a CTE records an unresolved target and guesses no table.
- [ ] The written object stops counting as a read.
- [ ] A test uses the `BSPL.sp_BSprocess` statement, trimmed to the `update B1 ... from BSPL.BudgetBalanceSheet B1` statement, and finds a write to `BSPL.BudgetBalanceSheet`.
- [ ] The graph format version does not change here.
- [ ] The whole suite shows no new failure.

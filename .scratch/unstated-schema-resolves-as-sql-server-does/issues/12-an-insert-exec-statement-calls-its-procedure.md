# 12 — An INSERT ... EXEC statement calls its procedure

**What to build:** An analyst follows a program into the procedures it reaches, and a procedure that an `INSERT ... EXEC` statement runs is on an Execution Path. Today the analyzer host records the `INSERT` of that statement and drops its `EXEC`. `INSERT INTO #t EXEC dbo.usp_X` writes `#t` and gives no call to `dbo.usp_X`. The call then gives no Execution Path, and the tables of `dbo.usp_X` are absent from the answer of that program.

The bug and gap review of 2026-10-01 found this defect. It is older than this feature, and no ticket of this feature changed it. It belongs here because user story 8 asks for one Execution Path for one call, and this call gives none.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A failing analyzer host test comes first: `INSERT INTO #t EXEC dbo.usp_X;` gives a `CALL` operation with the call target `dbo.usp_X`, and an `INSERT` operation that writes `#t`.
- [ ] The call target keeps every part it states, as a direct `EXEC` does. `INSERT INTO @t EXEC usp_X;` gives the bare target `usp_X`, and the graph builder resolves it by Schema Resolution (ticket 05).
- [ ] An `INSERT` into a table variable writes nothing, as today, and its `EXEC` still gives the `CALL` operation.
- [ ] `INSERT INTO @t EXEC sp_executesql @sql;` gives a `CALL` to `sp_executesql`, as a direct `EXEC sp_executesql` does. The graph builder resolves it to `sys` (ticket 05).
- [ ] `INSERT INTO #t EXEC (@sql);` gives the same `DYNAMIC_SQL` operation that a direct `EXEC (@sql)` gives. The seven caches hold no such statement.
- [ ] A graph builder test with a stub host shows one `calls` relationship from the module to the listed procedure, and one Execution Path through it.
- [ ] The golden `path_id` test stays unedited and passes.
- [ ] The graph format version rises, and its comment states why the earlier graph is rejected. The local caches rebuild in the order of ticket 09: back up, repair tool, then index backfill tool.
- [ ] A comparison of the graphs before and after the rebuild records the added `calls` relationships per cache. Expected: 27 in PUR and 26 in eFinance (see Comments). Any other change gets an explanation.
- [ ] The companion repository regenerates its routing expectations. Each change is a new program on a path through a called procedure, and an unexpected change becomes its own ticket.
- [ ] The whole suite shows no new failure.
- [ ] Another operator machine's step (repair tool, then index backfill tool) is written down as an open operator item.

## Comments

**Evidence, 2026-10-01.** The analyzer host at commit `4c3358d`, through `_analyze_sql_text()` of `tests/test_static_analyzer_host.py`:

| Statement | Operations today |
|---|---|
| `INSERT INTO #t EXEC dbo.usp_x;` | one `INSERT` that writes `#t`; no `CALL` |

**Cause.** `tools/StaticAnalyzerHost/SqlAnalyzer.cs`, `Visit()`. An `InsertStatement` is DML, so `Visit()` makes one candidate for it and returns. It does not walk into the `ExecuteInsertSource` of the statement, so the `ExecuteSpecification` inside it never reaches `CreateExecuteCandidate()`. The `INSERT` case of `CreateCandidate()` reads only the table references of the source.

**Scale in the seven local caches.** This count is a regex approximation over the module definitions, with comments removed. It finds 53 `INSERT ... EXEC` statements in 34 modules. All 53 are a static `EXEC`; none is `EXEC (@sql)`.

| Cache | Target | Called object | Statements |
|---|---|---|---|
| PUR | table variable | a user procedure | 23 |
| PUR | `#temp` table | a user procedure | 4 |
| eFinance | table variable | `sp_executesql` | 26 |

- In the v9 graphs, the module of 39 of the 53 statements has no `calls` relationship to the called object at all. The other 14 are eFinance modules that also run `sp_executesql` directly.
- All 27 PUR statements call a user procedure, and each one has no Execution Path today. Examples: `dbo.usp_Order_PUR_SOMaintain_Modify` and `dbo.usp_TaskSchedule` call `dbo.usp_Ship_ContainerEstimate_Calculate`. `dbo.usp_Financial_PUR_BillConfirm_Save` calls `usp_CheckProgramAuth`.

**Design notes for the implementer.**

- Give the `CALL` its own candidate, with the `ExecuteSpecification` as its fragment. The candidates sort by start offset, so the `CALL` comes after the `INSERT` of the same statement.
- One more operation in a module moves the sequence of each later operation of that module. The operation id holds the sequence, and the Path Identity holds the operation id. So the `path_id` of each later path in those 34 modules changes. This is expected, and the rise of the graph format version already invalidates every stored Derived Execution Evidence file. The golden `path_id` test must not change.
- Out of scope: the temp table lineage from the result set of the called procedure into `#t`. Today `#t` has no writer that reads a table, so a read of `#t` reaches no base table. The called procedure's own reads reach the answer through the new Execution Path. Record a separate ticket if the lineage is needed.

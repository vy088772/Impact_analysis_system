# 12 — An INSERT ... EXEC statement calls its procedure

**What to build:** An analyst follows a program into the procedures it reaches, and a procedure that an `INSERT ... EXEC` statement runs is on an Execution Path. Today the analyzer host records the `INSERT` of that statement and drops its `EXEC`. `INSERT INTO #t EXEC dbo.usp_X` writes `#t` and gives no call to `dbo.usp_X`. The call then gives no Execution Path, and the tables of `dbo.usp_X` are absent from the answer of that program.

The bug and gap review of 2026-10-01 found this defect. It is older than this feature, and no ticket of this feature changed it. It belongs here because user story 8 asks for one Execution Path for one call, and this call gives none.

**Blocked by:** None — can start immediately.

**Status:** done, except the rebuild of the shared local caches, which the landing script runs (see "Implementation notes")

- [x] A failing analyzer host test comes first: `INSERT INTO #t EXEC dbo.usp_X;` gives a `CALL` operation with the call target `dbo.usp_X`, and an `INSERT` operation that writes `#t`.
- [x] The call target keeps every part it states, as a direct `EXEC` does. `INSERT INTO @t EXEC usp_X;` gives the bare target `usp_X`, and the graph builder resolves it by Schema Resolution (ticket 05).
- [x] An `INSERT` into a table variable writes nothing, as today, and its `EXEC` still gives the `CALL` operation.
- [x] `INSERT INTO @t EXEC sp_executesql @sql;` gives a `CALL` to `sp_executesql`, as a direct `EXEC sp_executesql` does. The graph builder resolves it to `sys` (ticket 05).
- [x] `INSERT INTO #t EXEC (@sql);` gives the same `DYNAMIC_SQL` operation that a direct `EXEC (@sql)` gives. The seven caches hold no such statement.
- [x] A graph builder test with a stub host shows one `calls` relationship from the module to the listed procedure, and one Execution Path through it.
- [x] The golden `path_id` test stays unedited and passes.
- [ ] The graph format version rises, and its comment states why the earlier graph is rejected. The local caches rebuild in the order of ticket 09: back up, repair tool, then index backfill tool. (The version is 10. A copy of the caches is rebuilt. The shared `data/sql_cache` rebuilds when the landing script runs.)
- [x] A comparison of the graphs before and after the rebuild records the added `calls` relationships per cache. Expected: 27 in PUR and 26 in eFinance (see Comments). Any other change gets an explanation.
- [x] The companion repository regenerates its routing expectations. Each change is a new program on a path through a called procedure, and an unexpected change becomes its own ticket.
- [x] The whole suite shows no new failure.
- [x] Another operator machine's step (repair tool, then index backfill tool) is written down as an open operator item.

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

**Implementation notes, 2026-10-01.**

Files this ticket changed (other sessions work in parallel; these are the only ones):

- `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: `Visit()` adds a second candidate after an `InsertStatement` when its `InsertSource` has an `Execute` property (an `ExecuteInsertSource`). That candidate comes from `CreateExecuteCandidate()`, with the `ExecuteSpecification` as its fragment. `CreateExecuteCandidate()` now takes the location fragment and the `ExecuteSpecification` as two parameters, and it no longer takes the unused `module`. A direct `EXEC` keeps the whole statement as its fragment, so its source location does not change. CRLF kept.
- `tests/test_static_analyzer_host.py`: 5 host tests (the `#t` and `dbo.usp_X` case, the table variable and bare name case, `sp_executesql` beside a direct `EXEC sp_executesql`, `EXEC (@sql)` beside a direct `EXEC (@sql)`, and the branch path and sequence of the new operation). The first test failed first (red): the host gave one operation, not two.
- `tests/test_nested_sql_execution_paths.py`: one graph builder test with a stub host (`stubbed_procedures()`): one `calls` relationship from `dbo.usp_Fill` to `dbo.usp_X` (the bare call `usp_X` resolves to the module's schema), and one Execution Path through it.
- `service/sql_execution_graph.py`: `GRAPH_VERSION` 9 to 10, and its comment. `tests/test_sql_execution_graph.py` and `tests/cross_repository_agreement.json` follow.
- `docs/使用說明書.md` and `docs/進階手冊.md`: each names version 10 beside the repair tool.
- Companion repository `llamaindex-spec-rag`: `tests/_sql_cache_fixtures.py` (`GRAPH_VERSION = 10`). The routing expectations file does not change (see below).

The golden `path_id` test (`tests/test_execution_path_builder.py`) is unedited and passes.

**Why the shared caches rebuild in the landing script.** This work ran in a git worktree, and `data/` is shared with the main checkout. The main checkout code reads version 9 until this commit lands. A v10 cache in `data/sql_cache` before then is rejected by every other session. So this ticket rebuilt a copy, and the landing script rebuilds `data/sql_cache` after the commit lands, in the order of ticket 09: back up to `data/sql_cache_backup_v9_20261001/`, the repair tool, then the index backfill tool.

**Graph comparison, v9 copy against v10 copy** (repair tool 12 s, then index backfill tool). The comparison keys an operation node by its module and its source start offset, because the sequence of each later operation of a module moves (see Design notes). Each relationship is compared with all its fields except `id`.

| Cache | Relationships v9 | Relationships v10 | Added | Removed | Nodes changed |
|---|---|---|---|---|---|
| EFNETDB | 0 | 0 | 0 | 0 | 0 |
| ETON | 449 | 449 | 0 | 0 | 0 |
| PUR | 24340 | 24367 | 27 (`calls`) | 0 | 0 |
| Response | 429 | 429 | 0 | 0 | 0 |
| STC | 415 | 415 | 0 | 0 | 0 |
| SysErrorRecord | 25 | 25 | 0 | 0 | 0 |
| eFinance | 4916 | 4942 | 26 (`calls`) | 0 | 0 |
| **Total** | **30574** | **30627** | **53** | **0** | **0** |

The result is the same as the expected scale. No other change occurred.

- PUR: 27 statements in 23 modules, to 14 user procedures (24 module and procedure pairs, all new). 21 targets state `dbo` (`written`), and 6 resolve by `module_schema`. Examples: `dbo.usp_Order_PUR_SOMaintain_Modify` (line 199) and `dbo.usp_TaskSchedule` (lines 240 and 243) call `dbo.usp_Ship_ContainerEstimate_Calculate`. `dbo.usp_Financial_PUR_BillConfirm_Save` (line 16) calls `usp_CheckProgramAuth`, which resolves to `dbo.usp_CheckProgramAuth` (`module_schema`).
- eFinance: 26 statements in 11 modules, all to `sys.sp_executesql` (14 `written`, 12 `system`). 7 of the 11 module pairs are new. The other 4 modules already ran `sp_executesql` directly; they hold 14 of the 26 statements.
- So 27 + 12 = 39 statements had no `calls` relationship before, as the Comments say.

**What an analyst sees.** Two Impact services ran on the copies (v9 code on the v9 copy, v10 code on the v10 copy), and the companion repository's lookups asked both. The questions were the 14 PUR procedures that a new `calls` relationship reaches, and the 45 tables that those procedures read or write directly.

- `/find_by_table`: 19 of 45 tables gain programs (system `Y-Docs_TTPUR`). No table loses a program. Examples: `dbo.ContainerEstMaster` gains `program` and `pur_somaintain`. `dbo.VQM` gains `mtvdrquoaddchild` and `pur_quotationrespnew`. `dbo.Customers` and `dbo.Vendors` gain `usersignature`.
- `/find_by_sp`: the 14 procedures give the same answer. That endpoint lists the programs that call the procedure, and those did not change.

**Companion repository.** `routing_expectations.py --seeds-from` re-derived the 42 questions twice, with the same scan caches (version 43): one time against the v9 copy and one time against the v10 copy. The two drafts are equal, and both are equal to the reviewed file in each expectation and in `sql_cache_sources`. So the reviewed file does not change, and no new ticket is necessary. The cause: the three questions on `VQM` (`table-write-005`, `table-insert-004`, `table-delete-005`) ask for a write, and the new path only reads `VQM`. `sp-001` asks which programs call `usp_CheckProgramAuth`, and that answer did not change. No other question names one of the 19 tables or one of the 14 procedures. Both runs gave the same warnings for system `Y-DOCs_TTRDQ` (no `database` for `/find_by_sp`). Those warnings are older than this ticket.

**Whole suites.** Impact repository, worktree: 1445 passed, 2 failed (`test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog`, `test_wrapper_decompilation.py::test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end`). A worktree of the unchanged HEAD gives 1439 passed and the same 2 failures. These two depend on the checkout path, and they pass in the main checkout. `test_search_roles.py` and `test_sp_tables.py` are ignored (they need SQL Server). Companion repository, worktree: 1218 passed, 2 failed (`test_table_lookup_write_access_types`: it needs a sibling checkout path; ticket 11 recorded the same two).

**Open operator item (not run here):** another operator machine runs, in this order: `python tools/repair_sql_execution_graphs.py`, then `python tools/backfill_object_location_indexes.py`. Back up its `data/sql_cache` first.

**Out of scope, as the Design notes say:** the temp table lineage from the result set of the called procedure into `#t`. No ticket holds it yet.

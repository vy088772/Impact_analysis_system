# 11 — An UPDATE or DELETE reads the tables of its subqueries

**What to build:** An analyst asks which programs read a table, and a procedure that reads it only inside a subquery of an `UPDATE` or a `DELETE` is in the answer. Today the analyzer host reads the tables of the `FROM` clause and of the `WITH` clause of those two statements. It reads no table of a subquery in the `WHERE` clause, and no table of a subquery in a `SET` clause. A `SELECT` and an `INSERT` already read their subqueries.

The whole-feature review of 2026-09-30 found this defect. It is older than this feature: the code is the same at `b865587`. No ticket of this feature changed it.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failing analyzer host test comes first: `UPDATE dbo.T SET a = 1 WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = dbo.T.id);` reads `dbo.S` and writes `dbo.T`.
- [x] An `UPDATE` reads the tables of a subquery in its `WHERE` clause (`EXISTS` and `IN`) and in a `SET` clause (`SET a = (SELECT ...)`).
- [x] A `DELETE` reads the tables of a subquery in its `WHERE` clause (`EXISTS` and `IN`).
- [x] The same statements with a `FROM` clause and an alias target keep the write that ticket 03 gives, and gain the subquery read.
- [x] A CTE name inside the subquery is no table read, as ticket 02 decided.
- [x] A subquery that reads the written table gives no read of that table. The current read and write split stays.
- [x] The graph format version rises, and its comment states why the earlier graph is rejected. The local caches rebuild in the order of ticket 09: repair tool, then index backfill tool.
- [x] The rebuild adds reads and removes none. A comparison of the graphs before and after the rebuild proves it, and this ticket records the numbers.
- [x] The companion repository regenerates its routing expectations. Each change is a new reader of a table, and an unexpected change becomes its own ticket.
- [x] The whole suite shows no new failure.

## Comments

**Evidence, 2026-09-30.** Each line is the result of the analyzer host at commit `de113d6`, through `_write_test_statement()` of `tests/test_static_analyzer_host.py`.

| Statement | Reads today | Reads that are missing |
|---|---|---|
| `UPDATE dbo.T SET a = 1 WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = dbo.T.id);` | none | `dbo.S` |
| `UPDATE dbo.T SET a = 1 WHERE id IN (SELECT id FROM dbo.S);` | none | `dbo.S` |
| `UPDATE dbo.T SET a = (SELECT MAX(b) FROM dbo.S);` | none | `dbo.S` |
| `UPDATE t SET a = 1 FROM dbo.T t WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = t.id);` | none | `dbo.S` |
| `DELETE FROM dbo.T WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = dbo.T.id);` | none | `dbo.S` |
| `DELETE FROM dbo.T WHERE id IN (SELECT id FROM dbo.S);` | none | `dbo.S` |
| `DELETE t FROM dbo.T t WHERE EXISTS (SELECT 1 FROM dbo.S s WHERE s.id = t.id);` | none | `dbo.S` |

Statements that are correct today, for comparison:

- `UPDATE t SET a = 1 FROM dbo.T t JOIN dbo.J j ON j.id IN (SELECT id FROM dbo.S);` reads `dbo.J` and `dbo.S`. The subquery sits inside the `FROM` clause.
- `SELECT a FROM dbo.T WHERE EXISTS (SELECT 1 FROM dbo.S ...);` reads `dbo.T` and `dbo.S`.
- `INSERT INTO dbo.T (a) SELECT a FROM dbo.U WHERE EXISTS (SELECT 1 FROM dbo.S);` reads `dbo.U` and `dbo.S`.

**Cause.** `tools/StaticAnalyzerHost/SqlAnalyzer.cs`, the `UPDATE` case and the `DELETE` case of the operation builder. Each case calls `CollectReferences()` for the `FROM` clause and for the `WITH` clause only. For the `WHERE` clause it calls `CollectColumns()` and `CollectFunctionReferences()`, so the columns and the functions of the subquery are already in the answer. The `UPDATE` case does the same for `SetClauses`. One `CollectReferences()` call for each of those fragments, before `RemoveWrittenTables()`, is the probable fix.

**Scale in the seven local caches.** This count is a regex approximation, not a SQL parser. It reads the `where` field of each `UPDATE` and `DELETE` operation node. It does not count a subquery in a `SET` clause.

| Cache | `UPDATE` and `DELETE` operations | With a subquery in `WHERE` | With a table that the operation does not read |
|---|---|---|---|
| PUR | 1668 | 123 | 63 |
| eFinance | 499 | 15 | 1 |
| STC | 48 | 2 | 0 |
| ETON | 30 | 0 | 0 |
| Response | 18 | 0 | 0 |
| SysErrorRecord | 1 | 0 | 0 |
| EFNETDB | 0 | 0 | 0 |
| **Total** | **2264** | **140** | **64** |

The 64 operations miss 65 table reads. Temp tables and table variables are not in the count. Three cases from PUR: `dbo.PQFFormApproveCus_Reject` (operation 6) misses `PQRMaster`, `dbo.s_GOPorderRecive` (operations 8, 9, 10, and 15) misses `SOrder`, and `dbo.spDelEvaluate` (operation 4) misses `Quotation`.

**What the analyst sees today.** `/find_by_table` for a table such as `SOrder`, with read access, does not list a program that reaches `dbo.s_GOPorderRecive` only through those operations. The write answer is correct.

**Why the status is `needs-triage`.** The fix changes graph content, so it needs a new graph format version and one more rebuild on each operator machine. The operator decides when that rebuild runs, and whether it joins another change that also raises the version.

**Seen beside this defect, not in this ticket.** `UPDATE dbo.T SET a = 1 OUTPUT inserted.a INTO dbo.L WHERE id = 1;` writes `dbo.T` only. The write to `dbo.L` through `OUTPUT ... INTO` is missing. No count of the caches exists for it yet.

**Implementation notes, 2026-09-30.**

Files this ticket changed (other sessions leave uncommitted work in the same tree; these are the only ones):

- `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: the `UPDATE` case calls `CollectReferences()` for its `WHERE` clause and its `SetClauses`; the `DELETE` case calls it for its `WHERE` clause. Both calls come before `RemoveWrittenTables()`. `CollectReferences()` now walks `Fragments(value)`, because `SetClauses` is a list and the old `value is not TSqlFragment` test returned early for it.
- `tests/test_static_analyzer_host.py`: 7 parametrized statements from the evidence table, one CTE-name test, one test for a subquery that reads the written table. The 7 statements failed first (red); the other 3 already passed.
- `service/sql_execution_graph.py`: `GRAPH_VERSION` 8 to 9, and its comment. `tests/test_sql_execution_graph.py` and `tests/cross_repository_agreement.json` follow.
- `docs/使用說明書.md` and `docs/進階手冊.md`: each names version 9 beside the repair tool.
- Companion repository `llamaindex-spec-rag`: `tests/_sql_cache_fixtures.py` (`GRAPH_VERSION = 9`) and `evaluation/Impact_analysis/results/routing_expectations.json`.

Order of work: the backup `data/sql_cache_backup_v8_20260930/` (`cp -Rp`) came first; then the repair tool (seven caches 8 to 9), then the index backfill tool, then the comparison.

**Graph comparison, v8 backup against v9** (key of a relationship: type, source, target; compared per cache):

| Cache | Relationships v8 | Relationships v9 | Added | Removed | Nodes added or removed |
|---|---|---|---|---|---|
| EFNETDB | 0 | 0 | 0 | 0 | 0 |
| ETON | 449 | 449 | 0 | 0 | 0 |
| PUR | 24000 | 24340 | 340 (`reads` 336, `uses` 4) | 0 | 0 |
| Response | 429 | 429 | 0 | 0 | 0 |
| STC | 412 | 415 | 3 (`reads`) | 0 | 0 |
| SysErrorRecord | 25 | 25 | 0 | 0 | 0 |
| eFinance | 4913 | 4916 | 3 (`reads`) | 0 | 0 |
| **Total** | **30228** | **30574** | **346** | **0** | **0** |

The rebuild adds reads and removes none. The 336 PUR reads sit on 143 operations and 86 targets: 298 tables, 11 views, 4 functions. The `uses` relationships are 2 views (`view_selCustomer`, `view_YMMCPriceImport`). The three cases named above are present: operation 6 of `dbo.PQFFormApproveCus_Reject` reads `PQRMaster`; operations 8, 9, 10 of `dbo.s_GOPorderRecive` read `SOrder`; operation 4 of `dbo.spDelEvaluate` reads `Quotation`. The count is larger than the ticket's 65 because the ticket counted neither a temp table, a view, a function, nor a subquery in a `SET` clause, and it counted per operation only.

**Companion repository.** Regeneration needed the scan caches at version 42 (they were at 40, raised by another ticket, not this one), so the scan caches were backed up (`data/scan_cache_backup_v40_20260930/`) and rescanned on this machine. `routing_expectations.py --seeds-from` then re-derived the 42 questions. 41 rows keep their targets. No row gains a reader from the subquery fix. One row (`usp_CheckProgramAuth`) gains the unproven program `response.master`; it comes from scan cache version 42, not from this ticket, and no new ticket is needed for it because it follows an earlier decision. The file keeps its `reviewed` header, plus a sentence in `review_notice`.

**Whole suites.** Analyzer host tests: 51 pass. Companion repository: 1218 pass, 2 fail (`test_table_lookup_write_access_types`: the sibling checkout path is missing; they fail the same without this change). Impact repository: 1361 pass, 16 fail, 2 collection errors (`test_search_roles`, `test_sp_tables` need SQL Server). The same 16 fail when this ticket's two code files return to HEAD, so no failure is new.

**Not done.** Another operator machine must run the repair tool, then the index backfill tool. `OUTPUT ... INTO` still gives no write to its target table (beside this defect, not in this ticket).

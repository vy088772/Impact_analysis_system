# 13 — A MERGE writes its target, and an INSERT into a CTE guesses no table

**What to build:** An analyst asks which programs write a table, and a procedure that writes it through a `MERGE` statement is in the answer. Today the analyzer host reads no `MERGE` statement at all, so it gives no operation for it. In the same change, an `INSERT` into a common table expression (CTE) stops writing a table with the CTE's name. That second part closes the last statement kind of user story 25.

The bug and gap review of 2026-10-01 found both defects. The `MERGE` gap is older than this feature. The `INSERT` into a CTE is a gap of ticket 02 and ticket 03: the `UPDATE` and `DELETE` cases check the CTE names, and the `INSERT` case does not.

**Blocked by:** 12 — An INSERT ... EXEC statement calls its procedure (both change `Visit()` and `CreateCandidate()` in `tools/StaticAnalyzerHost/SqlAnalyzer.cs`).

**Status:** done

The `INSERT` into a CTE:

- [x] A failing analyzer host test comes first: `WITH c AS (SELECT a FROM dbo.T) INSERT INTO c (a) VALUES (1);` writes no table, records `c` in `unresolved_write_targets`, and reads `dbo.T`. This is the result that a bare `UPDATE c` gives today (ticket 03).
- [x] An `INSERT` into a schema-qualified name with the CTE's bare name (`INSERT INTO dbo.c ...`) still writes `dbo.c`, as ticket 02 decided for a read.

The `MERGE`:

- [x] A failing analyzer host test comes first: `MERGE dbo.T AS t USING dbo.S AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.a = s.a;` gives one operation of type `MERGE` that writes `dbo.T` and reads `dbo.S`.
- [x] The target writes the object it names. An alias of the target (`AS t`) does not change the write.
- [x] A `#temp` target writes that temp table. A table variable target writes nothing. A CTE target goes to `unresolved_write_targets`, as for the `INSERT` above.
- [x] The `USING` source reads its tables. A source subquery and a source CTE read the tables inside them, and a CTE name is no table read.
- [x] The `ON` condition and each `WHEN` clause read the tables of their subqueries.
- [x] The written columns hold the `UPDATE SET` columns and the `INSERT` columns of the `WHEN` clauses.
- [x] The written target stops counting as a read, as for `UPDATE` and `DELETE`.
- [x] `MERGE` counts as a write access type: `_WRITE_ACCESS_TYPES` in `service/table_match.py`, and in the companion repository `impact_orch/table_lookup.py` and `evaluation/Impact_analysis/routing_expectations.py`. A `write_only` question returns the `MERGE` writer.
- [x] A test uses the `dbo.usp_SOManagement_Save` statement of PUR, trimmed to its `MERGE`, and finds a write to `ShippingOrderD`.
- [x] The graph format version rises (11), and its comment states why the earlier graph is rejected. The local caches rebuild in the order of ticket 09 (backup, repair tool, index backfill tool, report; see the notes).
- [x] A comparison of the graphs before and after the rebuild records each change. Expected: 2 new `MERGE` operations in PUR, and no change from the `INSERT` part.
- [x] The companion repository regenerates its routing expectations. An unexpected change becomes its own ticket.
- [x] Both repositories' whole suites show no new failure.

## Comments

**Implementation notes, 2026-10-01.** Files this ticket changed (other tickets run in parallel; these are the only ones). Branch `ticket13-merge-target`, based on `YuHsien_20260630` at `f57d6cb`, which holds ticket 12.

- `tools/StaticAnalyzerHost/SqlAnalyzer.cs`: `IsDml()` knows `MergeStatement`; `CreateCandidate()` maps it to `MERGE` and has a new `MERGE` case (target through `AddWriteTarget()`, reads from `TableReference`, `SearchCondition`, `ActionClauses` and the `WITH` clause, written columns from each `UpdateMergeAction.SetClauses` and `InsertMergeAction.Columns`, then `RemoveWrittenTables()`). The `INSERT` case now calls `AddWriteTarget()` with no `FROM` clause, so a bare CTE name goes to `unresolved_write_targets`.
- `service/table_match.py`: `MERGE` joins `_WRITE_ACCESS_TYPES`.
- `service/sql_execution_graph.py`: `GRAPH_VERSION` 10 to 11, and its comment.
- `tests/test_static_analyzer_host.py`: 11 new tests (2 for the `INSERT`, 9 for the `MERGE`).
- `tests/test_table_match.py`: `is_write_access("MERGE")`, and a `write_only` question through `find_by_table` that returns the `MERGE` writer. (Added after the code review.)
- `tests/test_static_analyzer_host.py` also holds a `WHEN NOT MATCHED BY SOURCE` / `INSERT DEFAULT VALUES` case (after the code review). Not covered, and not asked: a subquery inside a `MERGE ... OUTPUT` clause or a `TOP` clause.
- `tests/test_sql_execution_graph.py`: the stale-version test asserts 11; a new test builds a graph from the trimmed `MERGE` of `usp_SOManagement_Save` and finds the write to `ShippingOrderD`.
- `tests/test_inline_sql_regex_fallback.py`: the host test that pinned "a `MERGE` text gives no operation" now expects one `MERGE` operation (that behaviour is what this ticket reverses).
- `tests/cross_repository_agreement.json`: the sample cache holds `graph_version` 11.
- `docs/使用說明書.md` and `docs/進階手冊.md`: each names version 11 beside the repair tool.

Two writes in the `MERGE` test of a CTE target read `T` and `S` in a different order than the statement text, because the `WITH` clause is read last. The test compares sets.

**Cache comparison, 2026-10-01 (a copy, not the real caches).** I copied `data/sql_cache` (graph version 10) twice, ran the repair tool on one copy (10 to 11, seven caches), and compared the two. The real `data/sql_cache` is not changed: the main checkout runs graph version 10 code, and a v11 cache would be rejected there until this branch lands.

- Six caches (EFNETDB, ETON, Response, STC, SysErrorRecord, eFinance): no change in operations or relationships. This agrees with "0 `INSERT` into a CTE, 0 `MERGE`".
- PUR: operations 7005 to 7007, two new `MERGE` operations, as expected.
  - `dbo.usp_SOManagement_Save` operation 8 writes `dbo.ShippingOrderD`. Before, the procedure had no relationship to that table.
  - `dbo.usp_SOManagement_getVendors` operation 5 writes the temp table `#VList` and reads `dbo.POrder` and `dbo.SOrder`.
  - The other 11 removed and about 13 added relationships in these two procedures are the same relationships under operation sequences that are one higher, after the new `MERGE` (the same effect as ticket 12). One real addition: `getVendors` operation 6 now also reads the tables that the `#VList` lineage carries.

Whole suite of this repository (worktree, `data/` absent): 1403 passed, 4 failed, 2 collection errors. All 6 depend on files under `data/` or on the companion path, which a worktree lacks (`test_search_roles.py`, `test_sp_tables.py`, `test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog`, two in `test_semantic_binding_availability.py`). No failure comes from this change. See also the path-dependent tests in the user's notes.

**Real cache rebuild and companion repository, 2026-10-01 (after this branch landed in the main checkout).**

- The real caches: backup `data/sql_cache_backup_v10_20261001` (21 files, `cp -Rp`); the repair tool (seven caches, 10 to 11); the index backfill tool (run by the operator, in the main checkout); then the report. All seven caches are `graph_version 11`. Totals: empty schema 2453, CTE reads 0, alias writes 0, unproven targets 659, by source `module_schema` 10674, `system` 72, `unresolved` 2453, `written` 6961. PUR: 2 `MERGE` operations, as in the copy comparison above. The other six caches show no change from the `MERGE` and `INSERT` parts.
- Whole suites after all changes: this repository, in the main checkout, 1466 passed, 0 failed (`tests/test_search_roles.py` and `tests/test_sp_tables.py` are left out: they connect to SQL Server at collection and the machine has no ODBC driver; they fail the same way before this change). The companion repository: 1221 passed.
- The companion repository changed these files (commit `b3069ff`, branch `spec_extend_20260701`): `impact_orch/table_lookup.py` and `evaluation/Impact_analysis/routing_expectations.py` (`MERGE` in the write set), `tests/_sql_cache_fixtures.py` (`GRAPH_VERSION = 11`), `tests/test_table_lookup_write_access_types.py` (a `MERGE` case, and the parity test now reads `_WRITE_ACCESS_TYPES` in `service/table_match.py`, because the old `write_types` in `analyze_service.find_by_table()` moved there before this ticket and the test already failed), and `evaluation/Impact_analysis/results/routing_expectations.json`.
- The regeneration of the routing expectations used `--seeds-from` the reviewed file, with no hand edit of any row: all 41 rows keep their targets. No seeded question names the two PUR `MERGE` statements. One number outside the rows changed: eFinance `unowned_call_targets` 21 to 47. The cause is ticket 12, not this ticket: the eFinance `calls` relationships are 92 at graph version 9, 118 at graph version 10, and 118 at graph version 11 (47 - 21 = 26 = 118 - 92). The previous regeneration ran at graph version 9. No row change, so no new ticket. `review_status` stays `reviewed` with the old reviewer fields, and the `review_notice` states this regeneration.
- A first run without `--seeds-from` overwrote the reviewed file with 30 new draft questions. The reviewed file was restored from `HEAD` as the seed file and regenerated. The stray `routing_expectations.draft.json` it left was not committed and was deleted.

Not covered, and not asked: a subquery inside a `MERGE ... OUTPUT` or `TOP` clause.

**Evidence, 2026-10-01.** The analyzer host at commit `4c3358d`, through `_analyze_sql_text()` of `tests/test_static_analyzer_host.py`:

| Statement | Result today |
|---|---|
| `WITH c AS (SELECT a FROM dbo.T) INSERT INTO c (a) VALUES (1);` | `INSERT`, writes `c`, reads `dbo.T` |
| `WITH c AS (SELECT a FROM dbo.T) UPDATE c SET a = 1;` | `UPDATE`, writes nothing, `unresolved_write_targets` `["c"]` (correct, for comparison) |
| `MERGE dbo.T AS t USING dbo.S AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.a = s.a;` | no operation |

**Cause.**

- The `INSERT` case of `CreateCandidate()` calls `AddObjectName()` for its target with no CTE names. The `UPDATE` and `DELETE` cases go through `AddWriteTarget()`, which checks them.
- `IsDml()` knows `SelectStatement`, `InsertStatement`, `UpdateStatement`, and `DeleteStatement` only. `Visit()` walks into a `MergeStatement` and finds no candidate.

**Scale in the seven local caches.** This count is a regex approximation over the module definitions, with comments removed.

- `INSERT` into a CTE: 0 statements. The `INSERT` part changes no cache.
- `MERGE`: 2 statements, both in PUR.
  - `dbo.usp_SOManagement_Save` merges into `dbo.ShippingOrderD`. In the v9 graph, that procedure has no relationship to `dbo.ShippingOrderD`. The only writer of the table today is `dbo.usp_SOManagement_Delete`. So every write question on `dbo.ShippingOrderD` misses `dbo.usp_SOManagement_Save`.
  - `dbo.usp_SOManagement_getVendors` merges into the temp table `#VList`.

**Why the write access type matters.** A `/find_by_table` record of a proven write takes the operation type of the path as its `access_type` (`service/graph_queries.py`, `_access_record()`). `is_write_access()` knows `INSERT`, `UPDATE`, `DELETE`, and `SELECT_INTO`, but not `MERGE`. Without the new value, a `write_only` question drops the `MERGE` record. The companion repository holds two more copies of that set.

**Out of scope.**

- `OUTPUT ... INTO` of a `MERGE`. Ticket 11 counts no real table as an `OUTPUT ... INTO` target in the seven caches.
- The regex extraction of inline C# SQL. It already keeps a statement that starts with `MERGE` (`code_analyzer/csharp_parser.py`). The `inline-sql-tables-come-from-the-parser` spec moves it to the analyzer host's parser.

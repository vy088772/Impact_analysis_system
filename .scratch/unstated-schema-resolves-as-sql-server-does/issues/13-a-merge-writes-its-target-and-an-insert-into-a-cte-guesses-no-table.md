# 13 — A MERGE writes its target, and an INSERT into a CTE guesses no table

**What to build:** An analyst asks which programs write a table, and a procedure that writes it through a `MERGE` statement is in the answer. Today the analyzer host reads no `MERGE` statement at all, so it gives no operation for it. In the same change, an `INSERT` into a common table expression (CTE) stops writing a table with the CTE's name. That second part closes the last statement kind of user story 25.

The bug and gap review of 2026-10-01 found both defects. The `MERGE` gap is older than this feature. The `INSERT` into a CTE is a gap of ticket 02 and ticket 03: the `UPDATE` and `DELETE` cases check the CTE names, and the `INSERT` case does not.

**Blocked by:** 12 — An INSERT ... EXEC statement calls its procedure (both change `Visit()` and `CreateCandidate()` in `tools/StaticAnalyzerHost/SqlAnalyzer.cs`).

**Status:** ready-for-agent

The `INSERT` into a CTE:

- [ ] A failing analyzer host test comes first: `WITH c AS (SELECT a FROM dbo.T) INSERT INTO c (a) VALUES (1);` writes no table, records `c` in `unresolved_write_targets`, and reads `dbo.T`. This is the result that a bare `UPDATE c` gives today (ticket 03).
- [ ] An `INSERT` into a schema-qualified name with the CTE's bare name (`INSERT INTO dbo.c ...`) still writes `dbo.c`, as ticket 02 decided for a read.

The `MERGE`:

- [ ] A failing analyzer host test comes first: `MERGE dbo.T AS t USING dbo.S AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.a = s.a;` gives one operation of type `MERGE` that writes `dbo.T` and reads `dbo.S`.
- [ ] The target writes the object it names. An alias of the target (`AS t`) does not change the write.
- [ ] A `#temp` target writes that temp table. A table variable target writes nothing. A CTE target goes to `unresolved_write_targets`, as for the `INSERT` above.
- [ ] The `USING` source reads its tables. A source subquery and a source CTE read the tables inside them, and a CTE name is no table read.
- [ ] The `ON` condition and each `WHEN` clause read the tables of their subqueries.
- [ ] The written columns hold the `UPDATE SET` columns and the `INSERT` columns of the `WHEN` clauses.
- [ ] The written target stops counting as a read, as for `UPDATE` and `DELETE`.
- [ ] `MERGE` counts as a write access type: `_WRITE_ACCESS_TYPES` in `service/table_match.py`, and in the companion repository `impact_orch/table_lookup.py` and `evaluation/Impact_analysis/routing_expectations.py`. A `write_only` question returns the `MERGE` writer.
- [ ] A test uses the `dbo.usp_SOManagement_Save` statement of PUR, trimmed to its `MERGE`, and finds a write to `ShippingOrderD`.
- [ ] The graph format version rises, and its comment states why the earlier graph is rejected. The local caches rebuild in the order of ticket 09.
- [ ] A comparison of the graphs before and after the rebuild records each change. Expected: 2 new `MERGE` operations in PUR, and no change from the `INSERT` part.
- [ ] The companion repository regenerates its routing expectations. An unexpected change becomes its own ticket.
- [ ] Both repositories' whole suites show no new failure.

## Comments

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

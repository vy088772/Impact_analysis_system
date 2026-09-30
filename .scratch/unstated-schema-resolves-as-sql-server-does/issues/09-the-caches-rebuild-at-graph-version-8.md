# 09 — The caches rebuild at graph version 8

**What to build:** An operator raises the graph format version to 8, rebuilds every local graph and index, and reads a report that shows what changed against the v7 baseline. The companion repository regenerates its routing expectations from the rebuilt caches. Every answer after this ticket comes from a v8 graph.

See "Rollout", "Testing Decisions" (the rebuild report), and user stories 35 to 40, 49, 50 in the spec.

**Blocked by:** 01, 02, 03, 04, 05, 06, 07.

**Status:** done, except one box (another machine) that stays an open operator item

- [x] The graph format version is 8. Its comment states why a v7 graph is rejected. The sample cache in the cross-repository agreement file follows, and the companion repository's fixture constant follows.
- [x] The SQL caches are backed up before the repair.
- [x] The repair tool rebuilds every local graph; the index backfill tool then rebuilds every index.
- [x] The rebuild report from ticket 01 runs on the rebuilt caches. This ticket's notes record the numbers beside the baseline and explain each difference from the expected scale.
- [x] Three spot checks are recorded: `COMMON.ModuleList_Update` writes `COMMON.UserProgram` with no mark; `EOR.AEBudgetLog_Summary_Qry` no longer reads a table named `Table1`; `BSPL.sp_BSprocess` writes `BSPL.BudgetBalanceSheet`.
- [x] A stored Derived Execution Evidence file from before the repair is not served: one `/find_by_table` question re-derives.
- [x] The companion repository regenerates its routing expectations. Each change is checked against the spec's predictions, and an unexpected change becomes its own ticket.
- [x] Both repositories' whole suites show no new failure.
- [x] Another operator machine's step (repair tool, then index backfill tool) is written down as an open operator item if it cannot run here.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/sql_execution_graph.py`: `GRAPH_VERSION` 7 to 8, and its comment (why a v7 graph is rejected). Line endings stay CRLF, as in HEAD.
- `tests/test_sql_execution_graph.py`: the stale-version test asserts 8 (CRLF kept).
- `tests/cross_repository_agreement.json`: the sample cache holds `graph_version` 8.
- `tools/repair_sql_execution_graphs.py`: the docstring names v8.
- Companion repository `llamaindex-spec-rag`: `tests/_sql_cache_fixtures.py` (`GRAPH_VERSION = 8`) and `evaluation/Impact_analysis/results/routing_expectations.json` (5 questions, see below).
- Data, not in git (`data/` is ignored): the seven SQL caches and their indexes, rebuilt.

Order of work: the v7 report ran first; the backup `data/sql_cache_backup_v7_20260930/` (21 files, copied with `cp -Rp`) came before the repair; then the repair tool (12 s, seven caches 7 to 8), then the index backfill tool, then the report again.

**v8 result, 2026-09-30** (same tool, all seven caches `graph_version 8`):

| Cache | empty schema (v7 to v8) | by source (v8) | CTE reads | alias writes | unproven targets (v7 to v8) |
|---|---|---|---|---|---|
| EFNETDB | 0 to 0 | (none) | 0 to 0 | 0 to 0 | 0 to 0 |
| ETON | 199 to 11 | module_schema 190, system 1, unresolved 11, written 78 | 0 | 0 | 36 to 3 |
| PUR | 12092 to 2161 | module_schema 9928, system 48, unresolved 2161, written 4155 | 199 to 0 | 184 to 0 | 937 to 593 |
| Response | 96 to 16 | module_schema 80, system 1, unresolved 16, written 155 | 0 | 0 | 14 to 6 |
| STC | 214 to 19 | module_schema 198, unresolved 19, written 29 | 0 | 1 to 0 | 26 to 5 |
| SysErrorRecord | 12 to 7 | module_schema 5, unresolved 7, written 6 | 0 | 0 | 3 to 2 |
| eFinance | 404 to 205 | module_schema 10, system 10, unresolved 205, written 2443 | 32 to 0 | 145 to 0 | 91 to 50 |
| **Total** | **13017 to 2419** | module_schema 10411, system 60, unresolved 2419, written 6866 | **231 to 0** | **330 to 0** | **1107 to 659** |

Differences from the expected scale:

- Resolved schemas: 10411 (`module_schema`) + 60 (`system`) = 10471. The spec says about 9800. The report counts relationships. The spec's 9845 counts listed references, and the CTE and alias removals change it. Same scale. `default_schema` is 0: every resolved target sits in its module's own schema in these caches (all `dbo` modules resolve as `module_schema`, as the rule allows).
- CTE reads 231 to 0 and alias writes 330 to 0: both match the spec exactly.
- `written` fell from 7612 to 6866 (-746). Cause: 675 `reads` and 18 `writes` relationships that v7 held for PUR, 64 `reads` and 115 `writes` for eFinance, and 1 in STC are gone. They are the removed CTE reads, the alias writes that became real-table writes (a write no longer also counts as a read), and alias-named targets. No relationship of type `contains`, `calls`, `uses`, or `unresolved` changed in count.
- The 1 `writes` and 616 `reads` that v7 stated with a schema are unchanged in their targets.
- Remaining unresolved: 2419 relationships (659 targets). They are the names the listing does not hold: `#temp` tables, `@table` variables, and other-Database objects. The spec counted 3107 unlisted names with a different unit (names, not relationships). No broken reference is left, since the CTE `Table1` is gone.
- `system`: 60 `calls` to an `sp_` or `xp_` name that no listing holds now name `sys`, as the spec says.

Spot checks (eFinance graph, v7 to v8):

- `COMMON.ModuleList_Update` writes `table:COMMON.UserProgram` (source `module_schema`), with no Unproven Schema mark. v7 held `table:.UserProgram`. It also writes `COMMON.RolePorgram` (`module_schema`). Its `#temp` tables stay `unresolved`, as the spec says.
- `EOR.AEBudgetLog_Summary_Qry` no longer reads a table named `Table1`. The v7 `table:.Table1` is gone. Its other reads stay `written`.
- `BSPL.sp_BSprocess` writes `table:BSPL.BudgetBalanceSheet` (`written`). The v7 `table:.B1` is gone. The v7 `table:.t` is gone too: `t` is an alias of the `@tab1` table variable, so the spec says the procedure writes nothing for it.

Stored Derived Execution Evidence: 2099 files existed before. One `/find_by_table` question (`dbo.CompanyApproval`, database `STC`) derived again and wrote 1 new file (2100 after). It did not reuse an old file. The answer carries `schema_source` `default_schema` on its match. The invalidation is the fix of commit `08dd048`.

Companion repository: `routing_expectations.py --seeds-from` regenerated a draft from the rebuilt caches (the Impact service ran on port 8800 for it, then stopped). 42 expectations; 5 changed, 37 equal. The `sql_cache_sources` stayed equal, because the repair keeps each scan time. All 5 changes match the spec's predictions (user story 34: a writer that an alias hid):

- `table-write-005`, `table-write-006`, `table-insert-004`, `table-insert-005` (VQM and CQM): `usp_Annual_PUR_RateChangeConfirm_Action` gains `UPDATE`. Its text is `Update P ... From dbo.ChangeExRate C inner join dbo.VQM as P`. The alias `P` now writes `dbo.VQM`. The procedure already wrote it with `INSERT`.
- `table-write-007` (SOrder): three writer procedures join, each with `Update SO ... From ... inner join SOrder`: `usp_Ship_ContainerEstimate_Save`, `usp_Ship_ContainerEstimate_Delete`, `usp_Ship_PUR_InvInput_Modify`. The programs `containerestimate` and `pur_invinput` join `required_programs` and `matched_programs` (system `Y-Docs_TTPUR`).
- No unexpected change, so no new ticket. I merged only those fields (`matched_programs`, `required_programs`, `evidence`) into the reviewed file. `review_status`, `reviewed_at`, and `reviewed_by` stay as they were. The reviewed file keeps its format (no trailing newline).

Whole suites: this repository 16 failed, 1246 passed, with `test_search_roles.py` and `test_sp_tables.py` ignored. The 16 are the same ones that ticket 01 recorded on a clean checkout (they need `dotnet` fixtures or a registry entry that this machine lacks). Companion repository: 1216 passed, 0 failed. Before the change there, 1 test failed (the fixture constant against the sample cache), and the new constant fixes it.

**Open operator item (not run here):** another operator machine runs, in this order: `python tools/repair_sql_execution_graphs.py`, then `python tools/backfill_object_location_indexes.py`. Back up its `data/sql_cache` first. Then that machine regenerates nothing else: the routing expectations file comes with the companion repository.

Also for the operator: ticket 10 changes the path builder only. It needs no new rebuild, but derived evidence files from before ticket 10 would hold paths without the new flag. Check the evidence stamp when ticket 10 lands.

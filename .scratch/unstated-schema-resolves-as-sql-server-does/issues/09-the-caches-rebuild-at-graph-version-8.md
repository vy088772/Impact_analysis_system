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

## Comments

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/sql_execution_graph.py`: `GRAPH_VERSION` 7 to 8, and its comment (why a v7 graph is rejected). Line endings stay CRLF, as in HEAD.
- `tests/test_sql_execution_graph.py`: the stale-version test asserts 8 (CRLF kept).
- `tests/cross_repository_agreement.json`: the sample cache holds `graph_version` 8.
- `tools/repair_sql_execution_graphs.py`: the docstring names v8.
- Companion repository `llamaindex-spec-rag`: `tests/_sql_cache_fixtures.py` (`GRAPH_VERSION = 8`) and `evaluation/Impact_analysis/results/routing_expectations.json` (5 questions, see below).
- Data, not in git (`data/` is ignored): the seven SQL caches and their indexes, rebuilt.
- After the code review (second commit): `docs/使用說明書.md` and `docs/進階手冊.md` (each names version 8 beside the repair tool), the `GRAPH_VERSION` comment, the docstring of the stale-version test, and these notes.

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

The code review of 2026-09-30 found four wrong explanations in the first version of this list. The list below replaces them. Each number comes from a count of the v7 backup and the v8 caches, by relationship type and target node type.

- CTE reads 231 to 0 and alias writes 330 to 0: both match the spec exactly.
- Resolved schemas: 10411 (`module_schema`) + 60 (`system`) = 10471. The spec says about 9800. The surplus has one cause, and it is a rule of the report, not a change in the graph:
  - 9754 `module_schema` references name a table (7677 `reads`, 2077 `writes`). With the 60 `system` calls, that is 9814. This is the spec's "about 9800".
  - 657 `module_schema` references name a procedure, a View, or a Function (80 `calls`, 552 View `reads`, 1 View `writes`, 24 Function `reads`). v7 already linked these no-schema references to a listed node. The report counts a v7 reference as `written` when its target node has a schema, so the v7 baseline put them in `written`.
- `default_schema` is 0: every resolved target sits in its module's own schema in these caches (all `dbo` modules resolve as `module_schema`, as the rule allows).
- `written` fell from 7612 to 6866 (-746). The parts:
  - -657: the procedure, View, and Function references above. They moved from `written` to `module_schema`. Their targets did not change.
  - +67 table `writes` (748 to 815): an alias write is now a write of the real table, and the procedure text states that table's schema.
  - -153 table `reads` (5398 to 5245): 234 left and 81 came, counted per statement. 232 of the 234 sit on a statement that held an alias write in v7. The statement now writes the real object and no longer reads it. When the real object is a temp table, the reads that its lineage carried leave too. One case was checked in full: `dbo.usp_ATV_Manifest_Qry` in PUR, two `Update L ... From #List as L` statements. These two numbers count per statement. The second review below counts per relationship, and its split replaces this one: 235 left, 78 came, and 4 changed their source.
  - The cause of the reads that came: a temp table now has the alias write as a writer, so a read of that temp table expands to more base tables. The second review below counts each one.
  - -4 Function `reads` and +1 View `reads`. All are lineage reads in PUR. The second review below gives their cause.
- All references: 20629 to 19756 (-873): `reads` 16096 to 15356 (-740), `writes` 4143 to 4010 (-133). This is a different number from the -746 above. The relationship types `contains` (9631), `calls` (390), `uses` (826), and `unresolved` (15) keep their counts.
- No-schema table `reads` fell by 584 (9562 to 8978). The 584 holds the CTE reads and the reads that the alias fix removed. The second review below splits the 584 by cause.
- No-schema table `writes` fell by 200 (3394 to 3194): 330 alias writes left, and 130 writes of the real object came (60 `module_schema`, 70 to a temp table).
- No module lost an answer. A check of each (module, object with a schema) pair shows no lost `writes` pair and no lost `calls` pair. 23 `reads` pairs are gone, and in each one the module now writes that table.
- Remaining unresolved: 2419 relationships (659 targets).
  - 2393 name a `#temp` table.
  - 24 `reads` name a plain table that the listing of its Database does not hold: `syscomments` (10, in PUR and Response), `FAQTable` (7) and `RoleFAQ` (6) in STC `dbo.spFAQQry_V2`, and `ETONLog` (1) in PUR `dbo.spSelETONPODLQry`. These are unlisted or broken references. They keep the Unproven Schema mark, as user story 6 says.
  - 2 name an object of another Database: `master..xp_cmdshell` (PUR) and `Common..Users` (Response).
  - No reference names a table variable.
- The spec's 3107 unlisted names use the same unit as this report. Its three numbers (9845 + 3107 + 3) give 12955, and the v7 baseline holds 13017. The gap is 62: the 61 no-schema calls of v7, and 1 table reference that states another Database (`Common..Users`). The second review below gives the count.
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

**Code review, 2026-09-30** (commits `a5ac2f3` here and `cce5493` in the companion repository). A second session did a read-only check first: the report, the three spot checks, the backup, and both whole suites gave the same results as above. It did not repeat the `/find_by_table` question.

What the review changed:

- The two operator documents stopped at version 7. Each now names version 8. The commit that raised the version to 7 (`acc0a7f`) changed the same two lines.
- The `GRAPH_VERSION` comment gave the tool's lookup order as the order of SQL Server. It now gives the order of SQL Server: `sys` for a system name, then the module's schema, then `dbo`. ADR-0037 says why the tool checks `sys` last and gets the same answer.
- The comment and the test docstring split the spec name across two lines. The name is now on one line, so a search finds it.
- Four explanations in "Differences from the expected scale" were wrong. The list above replaces them.

What the review found and did not change (each is an operator decision):

- `service/sql_execution_graph.py` ends with one CR byte that `a5ac2f3` added. The earlier commit ended with `"module"` and no line end. Python ignores the byte. Commit `d6af5e1` fixed the same kind of change in `sql_analyzer.py`.
- The routing expectations file keeps `reviewed_at` 2026-09-29 and `reviewed_by` `ticket-13-canonical-object-identity`. Each earlier regeneration stamped its own ticket. The review of the five changes is in these notes only.
- 14 `reads` name a plain table that no listing holds (`FAQTable`, `RoleFAQ`, `ETONLog`). They are correct by the rule. An operator can check whether each is a broken reference in the Database.

Also for the operator: ticket 10 changes the path builder only. It needs no new rebuild, but derived evidence files from before ticket 10 would hold paths without the new flag. Check the evidence stamp when ticket 10 lands. Done after the whole-feature review: `_STORE_VERSION` is 4 (commit `7be9368`), so a file from before ticket 10 is a miss.

**Second review, 2026-09-30: the four open differences.** A read-only comparison of the v7 backup and the v8 caches closes each one. It matches one read of v7 with one read of v8 by four parts: the operation, the target name, the stated Database, and the lineage chain.

All `reads` fell by 740 (16096 to 15356): 870 reads left, and 130 reads came.

The 870 reads that left:

- 234 direct reads of a CTE name. The report counted 231. The other 3 read `List2` in three PUR budget procedures (`usp_Budget_RMBudget_MT_Qry`, `usp_Budget_RMManaged_Qry`, `usp_Budget_RMMarketingPrice_Qry`). A comment sits between the comma and the CTE name there, so the regex of the report misses them. The analyzer host does not.
- 197 direct reads of an object that the statement now writes through its alias: 130 with no schema in v7, and 67 with a written schema.
- 274 lineage reads of a statement that now writes a temp table through its alias. The statement reads that temp table no longer, so its lineage reads leave: 265 table reads, 5 Function reads, and 4 View reads.
- 138 lineage reads behind a temp table whose writer lost a read. The writer read a CTE name, or it read an object that it now writes.
- 27 lineage reads that v7 held two times: one for the node with no schema, and one for the node with the written schema. The two nodes are one node in v8.

The 130 reads that came are all lineage reads. Each one goes through a temp table that gained a writer: an alias write that v7 gave to the alias name. They are 78 `written` table reads, 46 `module_schema` table reads, 5 View reads, and 1 Function read.

The four differences:

- The `written` table reads fell by 153. The parts:
  - -67: alias, direct.
  - -166: alias, lineage.
  - -2: a writer lost a read.
  - +78: the reads that came.
  - +4: reads of `IVWork` through `#List` in `dbo.usp_ATV_Manifest_Qry` (PUR). Two alias writes are new writers of `#List`, and they read `dbo.IVWork` with a written schema. The read keeps the strongest source.
- The Function `reads` fell by 4: 5 left, and 1 came. The View `reads` rose by 1: 4 left, and 5 came. All are lineage reads in PUR, with the causes above. One case of each: `dbo.usp_CDCU_RMCDDetail_Calculate` lost `dbo.fun_GetStatusForRMCD` through `#SourceData`, and `dbo.usp_SO_Publish_NoPriceV2` gained `dbo.view_GetPrice` through `#Data` and `#PriceOrder`.
- The no-schema table reads fell by 584. The parts:
  - -234: CTE names.
  - -130: alias, direct.
  - -99: alias, lineage.
  - -136: a writer lost a read.
  - -27: two nodes became one.
  - -4: the `IVWork` reads above, which are now `written`.
  - +46: the reads that came.
- The gap of 62. This review applied the rule to each v7 `reads` or `writes` reference with no schema. The listing is the four object lists of each v7 cache, and the module schema comes from the operation node. The count:
  - 9845 resolve: 7491 direct reads or writes, and 2354 lineage reads.
  - 3107 name an unlisted object: 2974 direct, and 133 lineage.
  - 3 name an object that neither schema holds: 1 direct, and 2 lineage.
  - Those three numbers are the spec's 12955.
  - The other 62 are the 61 calls with no schema and 1 table reference that states another Database (`Common..Users`).

Each sum agrees with the totals above. No difference stays open.

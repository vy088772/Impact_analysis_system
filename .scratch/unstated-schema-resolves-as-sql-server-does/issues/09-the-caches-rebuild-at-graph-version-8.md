# 09 — The caches rebuild at graph version 8

**What to build:** An operator raises the graph format version to 8, rebuilds every local graph and index, and reads a report that shows what changed against the v7 baseline. The companion repository regenerates its routing expectations from the rebuilt caches. Every answer after this ticket comes from a v8 graph.

See "Rollout", "Testing Decisions" (the rebuild report), and user stories 35 to 40, 49, 50 in the spec.

**Blocked by:** 01, 02, 03, 04, 05, 06, 07.

**Status:** ready-for-agent

- [ ] The graph format version is 8. Its comment states why a v7 graph is rejected. The sample cache in the cross-repository agreement file follows, and the companion repository's fixture constant follows.
- [ ] The SQL caches are backed up before the repair.
- [ ] The repair tool rebuilds every local graph; the index backfill tool then rebuilds every index.
- [ ] The rebuild report from ticket 01 runs on the rebuilt caches. This ticket's notes record the numbers beside the baseline and explain each difference from the expected scale.
- [ ] Three spot checks are recorded: `COMMON.ModuleList_Update` writes `COMMON.UserProgram` with no mark; `EOR.AEBudgetLog_Summary_Qry` no longer reads a table named `Table1`; `BSPL.sp_BSprocess` writes `BSPL.BudgetBalanceSheet`.
- [ ] A stored Derived Execution Evidence file from before the repair is not served: one `/find_by_table` question re-derives.
- [ ] The companion repository regenerates its routing expectations. Each change is checked against the spec's predictions, and an unexpected change becomes its own ticket.
- [ ] Both repositories' whole suites show no new failure.
- [ ] Another operator machine's step (repair tool, then index backfill tool) is written down as an open operator item if it cannot run here.

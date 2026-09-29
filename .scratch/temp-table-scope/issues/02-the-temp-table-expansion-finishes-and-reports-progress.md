# 02: The temp table expansion finishes and reports progress

**What to build:** An operator who refreshes a Database where many procedures
share a temp table name sees the refresh pass the graph stage. The refresh
command shows a labelled `lineage` progress stage after the graph stage reaches
100%. The temp table node stays shared in this ticket, so the lineage answers do
not change yet.

See "Expansion algorithm" in the spec, and test cases 1, 7, 11, and 12.

**Repositories:** this repository, and `llamaindex-spec-rag` for the stage label.

**Blocked by:** None (can start immediately).

**Status:** done (2026-09-29)

- [x] Write the tests first and watch them fail.
- [x] A worklist fixed point replaces the path enumeration. It needs no depth limit.
- [x] Test case 1 (cost): forty procedures that each run the chain `#t1` to `#t4` build in a few seconds. This ticket asserts only that the build ends.
- [x] Test case 7 (cycle): two builds of the same payload give the same relationships.
- [x] Test case 11 (progress): the progress callback receives the `lineage` stage after the last `graph` report and before the builder returns.
- [x] Test case 12 (label): the refresh command in `llamaindex-spec-rag` maps the `lineage` stage key to a readable label.
- [x] Each derived read keeps the server and database that its base read stated. The existing test for that passes with no edit.
- [x] The graph format version does not change. Do not refresh a cache after this ticket, because ticket 03 changes the graph again.
- [x] Tests build payloads from the shared test fixture module and read the graph version from its constant.
- [x] The whole suite of each repository passes. See the Notes for the failures that exist on HEAD without this change.

## Notes

What this ticket changed:

- `service/sql_execution_graph.py`: `_expand_temp_table_lineage()` builds one base table set for each temp node, then runs a worklist fixed point over the edges between temp nodes. `max_depth` is gone. The function takes `progress_callback`. It reports `lineage` 0/N before the fixed point, then one report for each temp read. N is the number of temp reads.
- `tests/sql_cache_fixtures.py`: new `StubAnalyzerHost` and `stubbed_procedures()`. The stub host reports fixed operations for each definition text, so a test does not start the analyzer host. Tickets 03 and 04 can use them.
- `tests/test_sql_execution_graph.py`: three new tests for test cases 1, 7, and 11.
- `llamaindex-spec-rag`: `impact_orch/refresh_sql_cli.py` gains `"lineage": "Temp table lineage 展開"`. `tests/test_refresh_sql_cli.py` gains the test for test case 12.

Evidence:

- Red: test case 1 did not end in 30 seconds on the old code. Test case 11 received no `lineage` report. Test case 12 showed the raw key `lineage`. Test case 7 passed on the old code, because it guards a behavior that must not change.
- The old and the new builder gave the same graph on 300 random payloads (a check script in the session scratchpad, not in the repository). The answers change only for a temp chain longer than 32 hops, which the old depth limit cut.
- Suites: the graph tests pass. The failures below exist on HEAD without this change. They read the local catalog, a live database, or real checkouts:
  - Impact: `test_search_roles.py` and `test_sp_tables.py` fail at collection (`KeyError: 'PUR'`). Sixteen more tests fail or skip on a clean HEAD worktree: the tests in `test_csharp_analysis_gateway`, `test_external_wrapper_discovery`, `test_formal_output_migration`, `test_graph_reverse_lookup` (wrapper projection), `test_program_refresh`, `test_raw_sql_execution_command_source`, and `test_sqldbcontext_real_calls_resolve`.
  - llamaindex-spec-rag: `test_path_evidence_wiring` (the cache route) and `test_source_resolver_databases` (the shipped catalog).

For ticket 03 and ticket 04:

- The worklist keys on the temp node id. Ticket 03 re-keys `base_tables`, `successors`, and `predecessors` to a pair of a scoped node and a direction.
- The base table sets hold no path. To make `lineage` hold the chain of scoped temp nodes, ticket 04 must keep one chain for each base table.
- The fixed point itself sends no progress report. If the direction states make it slow on PUR, add a report there.
- The code sends one progress report for each temp read, with no throttle. `refresh_progress.update_job` keeps its state in memory, so this was left as is.

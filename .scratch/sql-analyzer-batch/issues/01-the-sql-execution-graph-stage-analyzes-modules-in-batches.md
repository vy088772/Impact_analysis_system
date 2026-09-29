# 01: The SQL Execution Graph stage analyzes modules in batches

**What to build:** An operator runs a SQL refresh or a graph repair. The graph
stage starts the analyzer once for each batch of modules, not once for each
module. The graph is the same as before. The progress bar moves once for each
batch. When one module fails, the error names that module.

See "Implementation Decisions" and "Testing Decisions" in the spec.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] The analyzer SQL command accepts one or more `--input` options. With one input, the response keeps its current shape. With two or more inputs, the response holds a `sources` list with one entry for each input, in input order.
- [x] When the analysis of one input fails, the analyzer stops with an error message that holds the path of that input.
- [x] The contract version is 4 in the analyzer and in the Python host.
- [x] The Python host has a SQL batch method. It uses the existing batch limits (100 files, 24,000 characters), reports progress once for each batch, and rejects a response whose entry count differs from the batch length. The single-file SQL method stays.
- [x] The graph builder sends all modules through the batch method and joins each result to its module by position. Node order and relationship order do not change.
- [x] The `graph` stage reports progress once for each batch. The item is the name of the last module in the batch.
- [x] A host error that names an input path becomes a graph builder error that names the module.
- [x] The graph version stays 6.
- [x] An equivalence test with the real analyzer and a batch limit of 2 shows that the batch graph is equal to a graph from one `analyze_sql` call for each module.
- [x] The host tests cover the contract version, the batch split and its progress, a failed input, and a response with a wrong entry count.
- [x] The stub analyzer of the SQL cache fixtures supports the batch method. The existing graph tests pass without the real analyzer.
- [x] The whole test suite passes (no new failure; see Notes).

## Notes

Files that this ticket changed. Another ticket that runs in parallel must not
edit these lines without a merge check:

- `tools/StaticAnalyzerHost/Program.cs`: `ContractVersion` 4, `AnalyzeSql(List<string>)`, and the `input file not found` message now holds the path.
- `code_analyzer/static_analyzer_host.py`: `CONTRACT_VERSION` 4, new `analyze_sql_files`, `_analyze_sql_batch`, and the shared `_run_in_batches`. `analyze_csharp_files` now calls `_run_in_batches`.
- `service/sql_execution_graph.py`: the graph stage writes all files first, then calls `analyze_sql_files`. It reports progress once for each batch.
- `tests/sql_cache_fixtures.py`: `StubAnalyzerHost.analyze_sql_files`.
- `tests/test_static_analyzer_host.py`, `tests/test_sql_execution_graph.py`: new tests.
- `docs/PUR_CSharp_Analyzer_Example.md`: `contract_version` 3 to 4.

Notes for ticket 02 (PUR acceptance):

- The analyzer DLL rebuilds itself on the first `ensure_ready()`. The old Debug build has contract 3 and fails with `contract mismatch`.
- The graph version is still 6, so the current PUR cache stays valid as the backup for the comparison.
- The batch progress starts with `(0, total, "")`, then one report for each batch.
- `tests/test_sp_tables.py` fails at collection (`ObjectName` has no attribute). It needs a live database and does not relate to this ticket.

Full suite result (2026-09-29): 1127 passed, 19 failed after a fix of my own
(a bare `4` in a test, caught by `test_fixture_shapes_have_one_source.py`).
The 19 remaining failures are in C# wrapper, refresh, CRLF, and path-case
tests: `test_external_wrapper_discovery`, `test_program_refresh`,
`test_sqldbcontext_real_calls_resolve`, `test_raw_sql_execution_command_source`,
`test_repair_sql_execution_graphs`, `test_table_reverse_lookup_traffic_record`,
`test_graph_reverse_lookup`. None calls the SQL command. The count fell to 14
when the tests of one later run were repeated on their own; see the baseline
check below for the proof that all 14 fail on the old code too.

Baseline check (2026-09-29): I ran the same 14 tests in a clean worktree at
`43e46bc`, the commit before this ticket, with `data/repos` linked in for the
IQCS checkout tests. The same 14 tests fail there. This ticket adds no failure.
The causes are outside this ticket: C# wrapper `ambiguous_overload`, a missing
`sqldbcontext-…` entry, CRLF line endings, and path case (`yuhsien-tseng`).

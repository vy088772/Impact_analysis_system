# 06 — `/flow_chain` reads the table relations in both directions

**What to build:** An analyst asks `/flow_chain` forward and backward about one method, and both directions name the same inline SQL tables. Forward takes the tables of the reachable methods from the by-method query of the inline table relations module. The forward builder takes the C# Scan Result, as the backward builder does. It no longer extracts tables from the SQL strings of each method. The `inline_sql_tables` field stays and lists the table names of those relations. Backward takes its inline relations from the by-table query, so it resolves an unstated schema as `/find_by_table` does.

The helper that extracts tables from a definition text goes away. The code comment that claims the two paths use "the same rule" goes away with it, and the header text of the flow chain builder changes.

See "The consumers", "The inline table relations module", "Testing Decisions", and user stories 27, 34, and 46 in the spec.

**Blocked by:** 02 — The readers of the table relations read through the inline table relations module (both directions call the queries that ticket makes). Tickets 03 to 05 reach `/flow_chain` with no change here.

**Status:** done

- [x] A failing Seam 2 test comes first: a method whose SQL string names a function `dbo.fnList(1)` gives no `fnList` table in forward, as backward gives none.
- [x] A failing Seam 2 test: a relation that states no schema, and that resolves to `dbo`, does not answer a backward question that states another schema. `/find_by_table` gives the same result for the same relation.
- [x] Seam 2: forward and backward give the same inline SQL tables for one method.
- [x] Seam 2: a table relation of a method that is not reachable does not appear in forward.
- [x] The one forward test of inline tables gives its tables as table relations of a C# Scan Result. It no longer gives them as SQL strings of a method.
- [x] Forward and backward read the table relations only through the inline table relations module.
- [x] The helper that extracts tables from a definition text is gone. The regular expressions under it stay, and the complexity label of the quick single-procedure analyzer does not change.
- [x] The comment about "the same rule" is gone, and the header text of the flow chain builder names no removed extraction.
- [x] The list of SQL texts that the C# parser keeps for each method stays. The C# Scan Result format version does not change in this ticket.
- [x] The response shape of `/flow_chain` does not change.
- [x] The whole suite shows no new failure.

**Notes:**

Files this ticket changed (other tickets run in parallel; these are the only ones):

- `service/flow_chain_builder.py`: `build_forward_chain(scan, matched_files, ...)` takes the C# Scan Result as its first argument. `_inline_sql_tables` calls the by-method query with this test: the file is one of the matched files, and the method is reachable. `build_backward_chains` calls the by-table query with its rated invocations and its root, in place of its own loop over `scan.table_relations`. It reads `invocations` into a list once, because the graph query and the by-table query both read it. The module header and the `_inline_sql_tables` docstring changed. The import of `extract_tables_from_definition` and the "same rule" text are gone.
- `service/analyze_service.py`: only the call of `build_forward_chain` in `flow_chain()`. It now gives `scan`.
- `service/inline_table_relations.py`: the module docstring only. It names the callers of each query, and it no longer says that ticket 06 moves `/flow_chain` backward.
- `code_analyzer/sql_analyzer.py`: `extract_tables_from_definition` is gone. `_quick_extract_tables` and `estimate_complexity_from_definition` stay, so the complexity label does not change. `service/sp_fetcher.py` calls only `estimate_complexity_from_definition`.
- `tests/test_flow_chain_inline_tables.py` (new): 4 Seam 2 tests through `analyze_service.flow_chain` and `find_by_table`. All 4 failed before the change: forward gave `fnList`, backward answered `COMMON.AVM`, and forward read no relation.
- `tests/test_execution_path_integration.py`: a new `_scan_of` helper. The three forward tests give a C# Scan Result. The inline test gives `dbo.SOrder` as a table relation, not as a SQL string of a method.

Decisions:

- Forward compares the file of a relation with the matched files by exact string, as the shared component table list does. The C# parser writes `result.file_path` and `CodeLocation(self.current_file, ...)` from the same `file_path`, and `_merge_scans` keeps both lists. So the two strings are equal.
- Forward lists the bare name of each relation (`bare_name(relation.table)`), as before. A fallback relation with `UNRESOLVED` also appears in forward, because backward also answers it.
- Backward now takes the Database of a parsed relation from its rated invocation, as `/find_by_table` does since ticket 05. Before this ticket, backward took the connection Database.

Verification:

- `pytest tests/test_flow_chain_inline_tables.py tests/test_execution_path_integration.py tests/test_table_match.py tests/test_shared_component_contributions.py tests/test_sp_fetcher.py` gives 62 passed.
- The whole suite (in a worktree, with `--continue-on-collection-errors`) gives 2 failed, 1439 passed, and 2 errors. The 2 failures are `test_program_refresh.py::test_refresh_does_not_write_wrapper_registry_or_system_catalog` and `test_wrapper_decompilation.py::test_decompile_wrapper_classifies_sqlfunc_dll_end_to_end`. They depend on the checkout path, and they fail in a worktree with the HEAD code too. The 2 errors are `test_search_roles.py` and `test_sp_tables.py` at collection (`KeyError: 'PUR'`, they need a Database connection).
- mypy shows no error in the new test file and in `service/inline_table_relations.py`. The errors in the other changed files are old patterns (for example `response["..."]` on an `Optional[dict]`).

Review: the `code-review` skill is off for model calls in the settings, so the review ran inline. It found no defect. Open points, not done here: `CONTEXT.md` and the ADR (ticket 07).

Second review (`/code-review`, two axes, against `YuHsien_20260630`): no documented standard is broken, and the spec is complete. The Standards axis found five smells. A second commit fixes all five:

1. Data Clump: `build_forward_chain` took `scan` and `matched_files`, and `matched_files` is a part of `scan.csharp_results`. It now takes `build_forward_chain(scan, anchor_method, *, owns_file, ...)`, and it finds the files of the program in the scan. `flow_chain()` gives the same `owns_file` that it uses for its own `matched_files`. Forward now asks `owns_file(relation file)`, not "is the path one of the matched paths". Both use `_file_matches`, so the answer does not change.
2. Duplicated Code: the three callers of `by_method` each collected `bare_name(rel.table)`. `inline_table_relations.table_names_by_method(scan, passes)` now gives the bare names in relation order, each name once. Forward, the screen table list, and the shared component table list call it. The screen and the component keep their own tests: `owns_action` and `_same_name` ignore the case of the letters, and forward does not. Forward keeps the exact compare, because the relation's method name and `reachable_methods` both come from a C# method declaration, and C# names are case-sensitive. This is the same compare as before ticket 06 (`m.name in reachable_methods`).
3. Primitive Obsession: the test of `by_method` took two bare strings. It now takes one `MethodSite(file_path, method_name)`.
4. Test coupling: the new test file imported the private `_file` of `tests/test_graph_reverse_lookup.py`. A new fixture module `tests/scan_fixtures.py` gives `csharp_file` and `scan_of`.
5. Duplicated test code: `_scan_of` of `tests/test_execution_path_integration.py` and `_scan` of the new test file built the same scan. Both now call `scan_of`.

Files of the second commit: `service/flow_chain_builder.py`, `service/analyze_service.py` (the two table lists in `analyze()`, `owns_file` and the forward call in `flow_chain()`, and the import of `bare_name`, which has no other use there), `service/inline_table_relations.py`, `tests/scan_fixtures.py` (new), `tests/test_flow_chain_inline_tables.py`, and `tests/test_execution_path_integration.py`. `tests/test_table_match.py` still imports `_file` of `tests/test_graph_reverse_lookup.py`. That import is older than ticket 06, and this commit does not change it.

A side effect that the Spec axis found (not a defect): forward now credits a table to the `method_name` of its relation. For a fallback relation, the scanner finds that name by the line number (`_find_class_and_method`). That is an approximation: it can name the method before, or `unknown`. Before ticket 06, forward took the SQL strings of `MethodInfo.sql_queries`, and those strings belong to their method. So forward can now credit a fallback table to a neighbouring method. Backward always used the same `method_name`, so the two directions now agree (user story 27).

Verification of the second commit: the focused tests (the six files above, with `tests/test_shared_component_contributions.py`, `tests/test_sp_fetcher.py`, and `tests/test_fixture_shapes_have_one_source.py`) give 68 passed. The whole suite gives the same result as the first commit: 2 failed (the same two path-dependent ids), 1439 passed, and 2 collection errors. mypy shows no error in the lines that this commit changed.

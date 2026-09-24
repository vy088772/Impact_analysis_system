# 01 — The backward chain takes only live inputs, and the flow-chain descriptions match the graph

**What to build:** `flow_chain_builder` stops carrying code and inputs that no path uses, and its descriptions of column matching name the text that the code really searches. Delete the two private functions that read SP definition text and have no caller. Remove the unread `database_alias` parameter from the backward chain, and remove the argument that the `/flow_chain` backward branch passes into it. Move the design reason for approximate column matching to the function that does the graph column match. Rewrite the module docstring's column-matching limit so that it names the graph path metadata. The result of the backward chain does not change. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `flow_chain_builder` no longer contains `_table_referenced()` or `_column_referenced()`
- [x] `flow_chain_builder` still imports every name that its remaining functions use
- [x] `build_backward_chains()` no longer has a `database_alias` parameter
- [x] The backward branch of `analyze_service.flow_chain()` no longer passes `database_alias`, and no longer builds a local `database_alias` value if nothing else reads it
- [x] The docstring of `_graph_access_matches_column()` explains why the match is approximate whole-word text search and not SQL parsing, names the path metadata fields that it searches, and says that a caller must tell the user that a match is approximate
- [x] The docstring of `_graph_access_matches_column()` no longer refers to an "existing" filter
- [x] The module docstring's column-matching limit names the graph path metadata as the searched text, and still says that the match is approximate and can give a false match
- [x] A repo-wide search (excluding `.scratch/`) finds no reference to `_table_referenced` or `_column_referenced`
- [x] The backward flow-chain tests in the graph reverse-lookup test module pass without modification
- [x] No test file changed
- [x] mypy on the changed files has no new error compared to the commit before this ticket
- [x] The full test suite has no new failure compared to the commit before this ticket

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them. Tickets 02 and 03 run in parallel and touch no file that this ticket touches. Commit only this ticket's paths (`git commit --only`).

## Comments

**Implementation note (2026-09-24):**

- Changed files: `service/flow_chain_builder.py` and `service/analyze_service.py`. Both keep CRLF.
- `flow_chain_builder`: deleted `_table_referenced()` and `_column_referenced()`. Removed the `database_alias` parameter from `build_backward_chains()`. Replaced the docstring of `_graph_access_matches_column()`. Rewrote the column-matching entry in the module docstring. `re`, `extract_tables_from_definition` and `_normalize_name` still have users, so no import changed.
- `analyze_service.flow_chain()`: deleted the local `database_alias` and the argument that passed it.
- mypy on the two files: the error set is the same as before the change, after line numbers are removed.
- Full suite (`--ignore` on `test_search_roles.py` and `test_sp_tables.py`, which need a live SQL Server): no new failure. `test_graph_reverse_lookup.py::test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces` fails before and after the change. It fails in `analyze()` before it calls `flow_chain`. The other 15 tests in that module pass.
- Code review: Spec axis found no gap. Standards axis found no hard violation. It gave two judgement calls, and neither caused a change. (1) The docstrings repeat the metadata field list. The spec tells both docstrings to name the fields. (2) It said "Execution Path metadata" matches the glossary better than "graph path metadata". The spec uses "graph path metadata".

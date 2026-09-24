# 01 — Remove the dead SP-expansion code and the descriptions of it

**What to build:** The code and the docs stop claiming that the forward chain expands nested SP calls recursively, or that it looks up SQL objects live on a cache miss. Delete the private SP-expansion function in `flow_chain_builder`, which has no caller. Delete the `sp_call_fetcher` module, whose only caller is that function. Correct every description of this behavior: the `flow_chain_builder` module docstring, the advanced manual's file tree, and the `view_fetcher` module docstring (see ADR-0011). The result of the forward chain does not change. See `../spec.md` for the reason behind each step.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] `flow_chain_builder` no longer contains the SP-expansion function, its depth-cap constant, or the imports that only it used
- [x] `flow_chain_builder` still imports every name that its remaining functions use
- [x] The `sp_call_fetcher` module no longer exists
- [x] The `flow_chain_builder` module docstring no longer says that the forward chain expands nested SP calls, and no longer names `sp_call_fetcher`
- [x] The advanced manual's file tree no longer lists `sp_call_fetcher`
- [x] The `view_fetcher` module docstring says that the module skips a name that the cache does not hold, and no longer mentions a live SQL Server lookup
- [x] A repo-wide search (excluding `.scratch/`) finds no reference to `sp_call_fetcher` or to the deleted SP-expansion function
- [x] No test file changed
- [x] The full test suite has no new failure compared to the commit before this ticket

**Note:** the `.py` files in `service/` use CRLF line endings. Keep them.

## Comments

Implemented in commit `18737ff`. The ticket 02 commit `ddbafce` has `18737ff` as its parent, but its tree came from `cb0c50a`. Thus it reverted this ticket. Commit `383ebfe` applies the same changes again. At `383ebfe`, HEAD contains both tickets.

**Changes:**

- `service/flow_chain_builder.py`: deleted `_expand_sp_chain()`, `_MAX_SP_DEPTH_HARD_CAP`, and the imports of `fetch_sp_definitions` and `fetch_called_sp_names`. The module docstring now says that the forward chain lists SPs from the SQL Execution Graph `sp_chain`, nested calls included. The known-limit entry that named `sp_call_fetcher` is gone.
- `service/sp_call_fetcher.py`: deleted.
- `service/view_fetcher.py`: the module docstring now says that the module skips a name that the cache does not hold, with no live SQL Server lookup (ADR-0011).
- `docs/進階手冊.md`: removed the `sp_call_fetcher.py` line from the file tree.
- The `build_forward_chain()` signature is unchanged. Ticket 02 owns it.

**Known-limit entry:** the spec keeps the `extract_tables_from_definition` part only if it is still true. It is not. The forward chain takes SP tables from the `reads` and `writes` of each graph path. It does not read cached SP definitions. The whole entry is removed.

**Code review correction:** the first draft said "直接呼叫的 SP". The standards review found that the output still contains nested SPs from the graph `sp_chain`. The docstring now says this. The header list keeps "SP 內部巢狀呼叫" for the same reason.

**Parallel work:** ticket 02 edited the same file at the same time. The commit contains only the ticket 01 hunks. It came from a private index, so the working tree kept the ticket 02 edits.

**Verification:**

- mypy on the two changed `.py` files: 181 errors before, 179 after. The two removed errors were in the deleted code. The other errors only moved to new line numbers.
- Full suite: 16 failed, 1036 passed, 2 collection errors, the same set as `cb0c50a`.
- The committed tree alone (no ticket 02 edits): the flow-chain test files give 43 passed and 1 failed. The failure (`test_wrapper_projection_matches_analyze_and_reverse_lookup_surfaces`) is in the baseline set.
- A repo-wide search (excluding `.scratch/`) finds no `sp_call_fetcher`, `_expand_sp_chain`, `fetch_called_sp_names`, or `_MAX_SP_DEPTH_HARD_CAP`.

**Follow-up candidate (found in code review, out of scope):** `_table_referenced()` and `_column_referenced()` in `flow_chain_builder` have no caller. The known-limit entry about column matching by SP definition text is also stale. The backward chain filters columns on graph path metadata. The spec did not examine the backward direction.

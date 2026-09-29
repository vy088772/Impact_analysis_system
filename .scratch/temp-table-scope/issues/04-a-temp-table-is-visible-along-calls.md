# 04: A temp table is visible along calls, in one direction

**What to build:** An analyst keeps the lineage of a "parent creates, child
reads" pattern and of a "parent creates, child fills" pattern. Two procedures
that call one shared procedure stay separate.

See "Call visibility" and "Expansion algorithm" in the spec, and test cases 3,
4, 5, 6, and 9.

**Blocked by:** 01, 03.

**Status:** done (2026-09-29)

- [x] Write the tests first and watch them fail.
- [x] The expansion reads calls only through the helper from ticket 01.
- [x] A state is a pair of a scoped temp node and a direction: none, up, or down. Up then down, or down then up, is not allowed.
- [x] The expansion does not detect shadowing. It takes the union of the visible writers.
- [x] Test case 3 (caller to callee) passes.
- [x] Test case 4 (callee to caller) passes.
- [x] Test case 5 (siblings) passes.
- [x] Test case 6 (transitive chain) passes.
- [x] Test case 9 (undefined callee) passes.
- [x] Each derived read keeps `confidence: "proven"`. Its `lineage` holds the chain of scoped temp node identities from the read to the base read.
- [x] The graph format version does not rise again. No cache was refreshed between ticket 03 and this ticket.
- [x] Test cases 1, 2, 7, 8, 10, and 11 still pass.
- [x] The whole suite of this repository passes.

## Notes

What this ticket changed (only these three files; other tickets run in parallel):

- `service/sql_execution_graph.py`: `_add_operation()` takes a `call_edges` set and adds one `(caller module id, callee node id)` pair for each call that `_resolve_call_target()` resolves to a module node. A call that resolves to `None` adds no edge. `_expand_temp_table_lineage()` takes `call_edges` and reads calls only from it. The version comment now states the call visibility rule. `GRAPH_VERSION` stays 6.
- `tests/test_sql_execution_graph.py`: six new tests for test cases 3, 4, 5, 6, 9, and one for the direction of a temp read inside a writer. They sit before the `__main__` block.
- This file.

How the expansion works now:

- A state is `(scope module id, (schema, name) casefolded, direction)`. A global `##name` node is one state with no direction. A module that never names the temp table has no node, but its state still exists, so the chain passes through it (test case 6).
- A state in direction none goes up to callers and down to callees. A state in direction up goes only up. A state in direction down goes only down.
- Decision (the spec is silent): a temp read inside a visible writer keeps the direction of the state that reached the writer. Reason: a "down" resolution that turned "up" inside the callee would join two callers of one shared procedure again. Cost: if a callee's writer reads a temp table that only the caller created, and the reach was downward, the read is lost. The test `test_a_temp_read_inside_a_callee_writer_...` pins this choice. If ADR-0012's "over-report" is preferred here, the change is one line: pass `_NO_DIRECTION` instead of `direction` in `edges.add(state_of(read_id, direction))`.
- `lineage` holds the scoped temp node ids from the read to the base read. Each base table keeps its shortest chain, and a tie goes to the lower chain, so two builds give one result. A module with no node adds no element.

Suite: `pytest tests/ --ignore=tests/test_search_roles.py --ignore=tests/test_sp_tables.py`: 1124 passed, 16 failed. The 16 are the pre-existing failures that earlier tickets record.

Line endings: both Python files use CRLF and no final newline. Keep it when you edit them with a script.

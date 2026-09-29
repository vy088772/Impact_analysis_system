# 03: A temp table belongs to the procedure that uses it

**What to build:** An analyst who asks about a table reached through `#tmp` in
one procedure no longer receives the base tables of an unrelated procedure that
also uses `#tmp`. Each `#name` temp table becomes one node for each module that
uses it. A `##name` global temp table stays one node for the Database.

See "Temp Table Scope" in the spec, and test cases 1, 2, 8, and 10.

**Blocked by:** 02.

**Status:** done (2026-09-29)

- [x] Write the tests first and watch them fail.
- [x] The node identity of a `#name` temp table holds the plain table identity and the owning module identity. It comes from the node identity function that builds every other node.
- [x] A scoped node keeps `type: "table"`, keeps the written name in `name`, and gains `scope_module_id`.
- [x] The node lookup key of a scoped node contains the scope. One module that writes `#Tmp` and reads `#tmp` still produces one node.
- [x] Test case 1 (cost) now also asserts that each procedure's final read resolves only to its own base table.
- [x] Test case 2 (isolation) passes.
- [x] Test case 8 (global temp table) passes.
- [x] Test case 10 (node shape) passes, and every relationship resolves to a known node.
- [x] One test with the real analyzer host proves `SELECT ... INTO #name` then `SELECT ... FROM #name` in one procedure.
- [x] The Object Location Index still holds the same temp table names.
- [x] The graph format version rises by one. The version comment states the scoped node identity and the new expansion.
- [x] The whole suite of this repository passes.

## Notes

What this ticket changed:

- `service/sql_execution_graph.py`: `GRAPH_VERSION` is 6, with a version comment. `_node_id()` takes `scope_module_id` and adds `@<module id>` to the id. `_node_key()` returns a four-part key (`NodeKey`) that ends with the casefolded scope. `_ensure_referenced_node()` takes the owning `module_id` and builds a scoped node for a `#name` table (`_is_scoped_temp_table()`: starts with `#`, not `##`). A scoped node holds `type: "table"`, the written `name`, and `scope_module_id`. `_add_node()` reads `scope_module_id` for the key.
- The expansion (`_expand_temp_table_lineage`) has no edit. It keys on the node id, and each scoped node now has its own id, so the expansion stays inside one module. Ticket 04 adds the direction state.
- `tests/test_sql_execution_graph.py`: new tests for cases 2, 8, 10, the Object Location Index, and the real analyzer host. Case 1 now asserts each final read. The version test asserts 6.
- `tests/cross_repository_agreement.json`: `sample_cache` graph_version 5 to 6.

For ticket 04 and ticket 05:

- The node id of a scoped node is `table:dbo.#tmp@stored_procedure:dbo.usp_A`. No consumer parses the id.
- `llamaindex-spec-rag/tests/_sql_cache_fixtures.py` still has `GRAPH_VERSION = 5`. Its test compares key sets only, so it passes. No edit here.
- Failures that exist on HEAD without this change are the ones in the ticket 02 Notes.
